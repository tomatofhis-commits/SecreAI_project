"""
OCRモジュール
キャプチャ画像からテキストを抽出する
WinRTOCR（高速・第一段階）と PaddleOCR（高精度・第二段階）のハイブリッドエンジン。
"""

import hashlib
import winocr
import re
from PIL import Image
from concurrent.futures import ThreadPoolExecutor
import time
import numpy as np

try:
    from src.lang_check import is_same_as_target as _lang_check
except ImportError:
    from lang_check import is_same_as_target as _lang_check

try:
    from src.paddle_engine import PaddleOCREngine
except ImportError:
    from paddle_engine import PaddleOCREngine

def _calc_iou(r1: dict, r2: dict) -> float:
    """2つの矩形のIoU（重複面積率）を返す。"""
    x_l = max(r1['x'], r2['x'])
    y_t = max(r1['y'], r2['y'])
    x_r = min(r1['x'] + r1['w'], r2['x'] + r2['w'])
    y_b = min(r1['y'] + r1['h'], r2['y'] + r2['h'])
    if x_r < x_l or y_b < y_t:
        return 0.0
    i_a = (x_r - x_l) * (y_b - y_t)
    return i_a / float(max(1, r1['w'] * r1['h'] + r2['w'] * r2['h'] - i_a))


def get_script_ratio(text: str, lang: str) -> float:
    """テキストから言語特有の文字（スクリプト）の構成割合を出す。最も割合が高い言語結果を「正解」とする"""
    # 一般的な記号や数字などを除外した「純粋な文字群」を抽出する
    text_alpha_only = re.sub(r'[0-9\s\.,/\+\-xX{}:;!\?\'"()\[\]@#\$%\^&\*~_]+', '', text)
    if not text_alpha_only:
        # 完全な記号や数字のみのブロック（例: "123", "+1/+1"）
        return 1.0
        
    base_lang = lang.split("-")[0].lower()
    match_count = 0
    if base_lang in ['en', 'fr', 'it', 'es', 'de', 'pt']:
        match_count = len(re.findall(r'[A-Za-zÀ-ÿ]', text_alpha_only))
    elif base_lang == 'ru':
        match_count = len(re.findall(r'[А-Яа-яЁё]', text_alpha_only))
    elif base_lang == 'ko':
        match_count = len(re.findall(r'[가-힣]', text_alpha_only))
    elif base_lang == 'zh':
        match_count = len(re.findall(r'[一-龥]', text_alpha_only))
    elif base_lang == 'ja':
        match_count = len(re.findall(r'[ぁ-んァ-ン一-龥]', text_alpha_only))
    else:
        # 未知の言語はラテン系として扱う
        match_count = len(re.findall(r'[A-Za-z]', text_alpha_only))
        
    return match_count / len(text_alpha_only)


class OCREngine:
    """
    Windows Runtime OCR (winocr) + PaddleOCR のハイブリッドエンジン。

    モード:
      - winrt_only      : WinRT全言語で2パス処理（1パス目で枠決め、2パス目で精読）
      - hybrid          : WinRTで枠決め → PaddleOCRで精読・仕分け
      - dual_scout_hybrid : WinRT + PaddleOCR両方で枠を索敵 → PaddleOCRで精読・仕分け
    """

    def __init__(
        self,
        langs: list[str] = None,
        paddle_engine: PaddleOCREngine | None = None,
        paddle_threshold: float = 0.90,
        ocr_mode: str = "hybrid"
    ):
        """
        Args:
            langs: 読み込みたい言語タグの配列（例: ["en-US", "ja-JP", "ru-RU"]）
            paddle_engine: PaddleOCREngine インスタンス（None の場合は無効）
            paddle_threshold: 未使用（後方互換のために残存）
            ocr_mode: "winrt_only", "hybrid", "dual_scout_hybrid"
        """
        if not langs:
            langs = ["en-US"]

        self.ocr_mode = ocr_mode

        # 案A: OpenCV EASTモデルの初期化
        import cv2
        import os
        east_model_path = "frozen_east_text_detection.pb"
        self.east_net = None
        if os.path.exists(east_model_path):
            try:
                self.east_net = cv2.dnn.readNet(east_model_path)
                # CUDAサポートがOpenCVに組み込まれているか確認
                cuda_supported = False
                try:
                    if cv2.cuda.getCudaEnabledDeviceCount() > 0:
                        cuda_supported = True
                except Exception:
                    pass

                if cuda_supported:
                    # PaddleOCRと同じGPUインデックスを適用
                    if paddle_engine and hasattr(paddle_engine, 'gpu_index'):
                        gpu_id = paddle_engine.gpu_index
                        if gpu_id >= 0:
                            try:
                                cv2.cuda.setDevice(gpu_id)
                                print(f"[EAST] 使用GPUをデバイス {gpu_id} (PaddleOCRと共通) に設定しました。")
                            except Exception as e:
                                print(f"[EAST] GPUデバイスIDの設定エラー: {e}")

                    self.east_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                    self.east_net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA)
                    print("[EAST] GPU (CUDA) バックエンドを有効化しました。")
                else:
                    self.east_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                    self.east_net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                    print("[EAST Warning] OpenCVがCUDA非対応のため、CPUバックエンドを使用します。")
            except Exception as e:
                print(f"[EAST] 初期化エラー（CPUにフォールバックします）: {e}")
                try:
                    if self.east_net:
                        self.east_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                        self.east_net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                except:
                    pass
        else:
            print(f"[EAST Warning] モデルファイル '{east_model_path}' が見つかりません。文字枠検出は機能しません。")

        self.paddle_engine = paddle_engine
        self.paddle_threshold = paddle_threshold
            
        self.available_langs = []
        dummy_img = Image.new('RGB', (10, 10))
        for lang in langs:
            try:
                # テスト実行（モジュールが読み込めるか、言語パックが存在するか）
                winocr.recognize_pil_sync(dummy_img, lang=lang)
                self.available_langs.append(lang)
            except AssertionError as e:
                print(f"[OCR Warning] 言語パック '{lang}' がWindowsにインストールされていないためスキップします。")
                print(f"追加する場合はPowerShellで次のコマンドをお試しください: {e}")
            except Exception as e:
                print(f"[OCR Error] '{lang}' の初期化エラー: {e}")
                
        if not self.available_langs:
            print("[OCR CRITICAL] 有効なOCR言語が一つもありません。デフォルトの 'en' を強制使用します。")
            self.available_langs = ["en"]
            
        self.skip_cache = {}        # {text_hash: expiry_time}
        self.skip_cache_ttl = 5.0   # 5秒間は同じゴミを無視する
        
        # 部首ハルシネーションチェック用 (PaddleOCR特有の誤読)
        self.radical_chars = set('亻冫刂彐尸儿匕卩廾弋夂夊宀彑彡忄扌攵旡殳氵灬爿犭疒癶礻糹纟罒艹虍衤覀訁讠貝贝辶釒钅隹阝韋飠饣髟鬥麻黽齊齒龜龠卜丿乀乁丨亅丶亠')

    def _recognize_single(self, image: Image.Image, lang: str):
        try:
            from PIL import ImageEnhance
            # 前処理: コントラストとシャープネスを強化
            enhancer = ImageEnhance.Contrast(image)
            img_enhanced = enhancer.enhance(2.0)
            enhancer = ImageEnhance.Sharpness(img_enhanced)
            img_enhanced = enhancer.enhance(2.0)
            
            # 2倍拡大 (端の文字切れ対策)
            w, h = img_enhanced.width, img_enhanced.height
            img_enhanced = img_enhanced.resize((w * 2, h * 2), Image.Resampling.LANCZOS)
            
            # OCR実行
            res = winocr.recognize_pil_sync(img_enhanced, lang=lang)
            
            # 2倍拡大した座標系を元画像サイズに戻す
            if res and "lines" in res:
                for line in res["lines"]:
                    if "words" in line:
                        for word in line["words"]:
                            if "bounding_rect" in word:
                                br = word["bounding_rect"]
                                br["x"] = br["x"] / 2.0
                                br["y"] = br["y"] / 2.0
                                br["width"] = br["width"] / 2.0
                                br["height"] = br["height"] / 2.0
            return lang, res
        except Exception:
            return lang, None

    def _append_chunk(
        self,
        clean_chunks: list,
        image: Image.Image,
        t_text: str,
        t_rect: dict,
        t_lines: list,
        t_lang: str,
        target_lang: str,
        attach_image: bool = False,
        parent_rect: dict = None,
    ) -> None:
        """
        テキストチャンクを検証し、問題なければ clean_chunks に追加する。
        ループ外のクラスメソッドとして定義することで、毎イテレーションの
        クロージャ生成を防ぎメモリ効率を改善する。
        """
        if not t_text or len(t_text.strip()) <= 1:
            return
        if _lang_check(t_text, target_lang, threshold=0.7):
            # 既に翻訳先言語（日本語など）の場合はスキップ
            t_hash = hashlib.md5(t_text.encode('utf-8')).hexdigest()
            self.skip_cache[t_hash] = time.time() + self.skip_cache_ttl
            return

        t_hash = hashlib.md5(t_text.encode('utf-8')).hexdigest()
        # 既にスキップキャッシュにあるか確認
        if t_hash in self.skip_cache:
            if time.time() < self.skip_cache[t_hash]:
                return
            else:
                del self.skip_cache[t_hash]

        area_id = f"{t_rect['x'] // 20}_{t_rect['y'] // 20}"
        cid = f"{t_hash[:8]}_{area_id}"

        px, py, pw, ph = t_rect['x'], t_rect['y'], t_rect['w'], t_rect['h']

        def _get_px(dx, dy):
            return image.getpixel((max(0, min(image.width - 1, dx)), max(0, min(image.height - 1, dy))))

        c1 = _get_px(px, py)
        c2 = _get_px(px + pw - 1, py)
        c3 = _get_px(px, py + ph - 1)
        c4 = _get_px(px + pw - 1, py + ph - 1)

        r = (c1[0] + c2[0] + c3[0] + c4[0]) // 4
        g = (c1[1] + c2[1] + c3[1] + c4[1]) // 4
        b = (c1[2] + c2[2] + c3[2] + c4[2]) // 4

        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        text_color = "#111111" if luminance > 130 else "#eeeeee"

        img_b64 = None
        if attach_image:
            import base64
            import io
            mx = max(0, px - 10)
            my = max(0, py - 10)
            mw = min(image.width, px + pw + 10)
            mh = min(image.height, py + ph + 10)
            crop_img = image.crop((mx, my, mw, mh))
            buffered = io.BytesIO()
            crop_img.save(buffered, format="PNG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        # --- 【v1.1.2 追加】ブラケットペアチェック (短いテキストのみ) ---
        text_no_space = t_text.replace(" ", "").replace("\n", "")
        if len(text_no_space) <= 20:
            unpaired = False
            brackets = {'(': ')', '[': ']', '{': '}', '「': '」', '『': '』', '【': '】', '（': '）', '〈': '〉', '《': '》'}
            for op, cl in brackets.items():
                if (op in t_text) != (cl in t_text):
                    unpaired = True
                    break
            if unpaired:
                return

        # --- 【v1.1.2 統合】日本語特有の補正 ---
        if t_lang == 'ja' or (target_lang == 'ja' and re.search(r'[ぁ-んァ-ヶ一-龥]', t_text)):
            t_text = t_text.replace('<', 'く')
            t_text = re.sub(r'(?<=[ァ-ヶ])-(?=[ァ-ヶ])', 'ー', t_text)
            t_text = re.sub(r'(?<=\n)-(?=[ァ-ヶ])', 'ー', t_text)
            t_text = re.sub(r'^-(?=[ァ-ヶ])', 'ー', t_text)
            
            # 不要なスペースの除去
            new_chars = []
            for i, c in enumerate(t_text):
                if c == ' ':
                    if i > 0 and i < len(t_text) - 1:
                        if t_text[i-1].isascii() and t_text[i+1].isascii():
                            new_chars.append(c)
                            continue
                    continue
                new_chars.append(c)
            t_text = "".join(new_chars)

        # --- 【v1.1.2 強化】PaddleOCRが見た瞬間の画像でエッジ密度を確定させる ---
        base_density = self.calculate_edge_density(image, t_rect)
        
        # --- 【v1.1.2 追加】Step 3 の枠情報と追従用画像を保存 ---
        step3_crop_np = None
        p_rect_store = parent_rect if parent_rect else t_rect
        if p_rect_store:
            cx = max(0, p_rect_store['x'])
            cy = max(0, p_rect_store['y'])
            cw = max(1, min(image.width - cx, p_rect_store['w']))
            ch = max(1, min(image.height - cy, p_rect_store['h']))
            crop_img = image.crop((cx, cy, cx + cw, cy + ch)).convert("L")
            step3_crop_np = np.array(crop_img)

        clean_chunks.append({
            "text": t_text,
            "rect": t_rect,
            "id": cid,
            "lang": t_lang,
            "lines_count": len(t_lines),
            "bg_color": f"rgba({r}, {g}, {b}, 1.0)",
            "text_color": text_color,
            "text_lines": t_lines,
            "image_b64": img_b64,
            "base_density": base_density,
            "parent_rect": p_rect_store,
            "step3_crop": step3_crop_np
        })

    def _try_paddle_refine(
        self,
        image: Image.Image,
        rect: dict,
    ) -> list[tuple[str, dict, list[str], float]]:
        """
        PaddleOCRで指定矩形を適切なマージンで切り出して再認識する。
        統合された大きな枠を、内部の物理的な配置に基づいて適切に細分化(Subdivide)する。
        """
        if self.paddle_engine is None:
            return []
        try:
            x, y, w, h = int(rect['x']), int(rect['y']), int(rect['w']), int(rect['h'])

            # マージンの確保（文脈読み取りのため）
            # WinRTが上下の行を見落とした場合でもPaddleOCRが補完できるように、垂直マージンを少し広げる
            margin_v = min(max(int(h * 0.4), 20), 60)
            margin_h = min(max(int(w * 0.1), 10), 40)

            x0 = max(0, x - margin_h)
            y0 = max(0, y - margin_v)
            x1 = min(image.width,  x + w + margin_h)
            y1 = min(image.height, y + h + margin_v)
            crop = image.crop((x0, y0, x1, y1))
            
            # 【精度向上】1.5倍に拡大してOCRに渡す
            # 2倍よりもノイズが抑えられ、かつ小さな文字の認識率も維持できるバランスを狙います
            orig_w, orig_h = crop.size
            upscaled_crop = crop.resize((int(orig_w * 1.5), int(orig_h * 1.5)), Image.Resampling.LANCZOS)

            blocks = self.paddle_engine.recognize(upscaled_crop)
            if not blocks:
                return []
            
            # 座標を元のスケールに戻す
            for b in blocks:
                br = b['rect']
                br['x'] /= 1.5
                br['y'] /= 1.5
                br['w'] /= 1.5
                br['h'] /= 1.5

            good_blocks = [b for b in blocks if b['confidence'] >= 0.45]
            if not good_blocks:
                return []

            # 1. 各ブロックの「濃さ(Density)」を計算（太字判定用）
            for b in good_blocks:
                br = b['rect']
                # クロップ画像から該当ブロックをさらに切り出し
                try:
                    block_crop = crop.crop((br['x'], br['y'], br['x']+br['w'], br['y']+br['h'])).convert("L")
                    # 平均輝度を取得 (0:黒, 255:白)
                    avg_brightness = np.array(block_crop).mean()
                    # 濃さとして定義 (背景が明るい前提で 255 - 平均輝度)
                    # 背景が暗い場合も考慮し、コントラストの強さを指標にする
                    b['density'] = max(1.0, 255.0 - avg_brightness)
                except Exception:
                    b['density'] = 50.0 # フォールバック

            # 2. 座標ソート (Y座標優先、同程度ならX座標)
            avg_h = max(1, sum(b['rect']['h'] for b in good_blocks) / len(good_blocks))
            band_size = max(5, int(avg_h * 0.5))
            good_blocks.sort(key=lambda b: (int(b['rect']['y'] // band_size), b['rect']['x']))
            
            # 2. 段落(Paragraph)の細分化判定
            # 物理的に離れているものを別々のチャンクとして切り出す
            paragraphs = []
            if good_blocks:
                current_paragraph = [good_blocks[0]]
                for i in range(1, len(good_blocks)):
                    prev = good_blocks[i-1]
                    curr = good_blocks[i]
                    
                    # 垂直方向の隙間
                    v_gap = curr['rect']['y'] - (prev['rect']['y'] + prev['rect']['h'])
                    # 水平方向の隙間（同じ行内での判定）
                    h_gap = curr['rect']['x'] - (prev['rect']['x'] + prev['rect']['w'])
                    
                    # 共通指標
                    h_min = min(prev['rect']['h'], curr['rect']['h'])
                    x_diff = abs(prev['rect']['x'] - curr['rect']['x']) # 左端のズレ
                    
                    # テキストボックス全体の右端（能動的な判定用）
                    max_right = max(b['rect']['x'] + b['rect']['w'] for b in good_blocks)
                    prev_right = prev['rect']['x'] + prev['rect']['w']
                    
                    is_split = False
                    
                    # 句読点チェック (行末が 。 or . で終わっているか)
                    # ただし ... などの連続はノイズとして除外
                    clean_text = prev['text'].strip()
                    has_period_end = len(clean_text) >= 1 and clean_text[-1] in ('。', '.')
                    period_count = clean_text.count('。') + clean_text.count('.')
                    is_period_noise = period_count >= 3 # 1行に3つ以上はノイズの可能性大
                    
                    # A. 【能動的ルール】句読点による分割 (ノイズでない場合)
                    # ユーザー要望: 句読点の後に「十分な余白」または「明確な行間」がある場合に分割
                    if has_period_end and not is_period_noise:
                        # 行の右側に文字1.5個分以上の余白があるか、次の行との間に1.2倍以上の隙間がある場合のみ分割
                        if prev_right < max_right - (h_min * 1.5) or v_gap > h_min * 1.2:
                            is_split = True
                    
                    # B. 【能動的ルール】行末の大きな余白 (文字2.5個分以上の空きがある場合は強制分割)
                    elif prev_right < max_right - (h_min * 2.5):
                        is_split = True
                    
                    # C. フォントサイズの違い (1.5倍以上)
                    elif max(prev['rect']['h'], curr['rect']['h']) / max(1, h_min) > 1.5:
                        is_split = True
                    
                    # C. フォントの濃さ（太字）の違い (1.6倍以上)
                    elif max(prev['density'], curr['density']) / max(1, min(prev['density'], curr['density'])) > 1.6:
                        is_split = True
                    
                    # D. 垂直方向に離れている（能動的な行間判定）
                    # 基本は 1.5倍。ただし左端が揃っている場合は 2.0倍まで許容
                    elif v_gap > h_min * 1.5:
                        if x_diff > h_min * 0.4: 
                            is_split = True
                        elif v_gap > h_min * 2.0: # 明確な行間があれば分割
                            is_split = True
                            
                    # E. 水平方向に極端に離れている
                    elif h_gap > h_min * 3.0:
                        is_split = True
                        
                    if is_split:
                        paragraphs.append(current_paragraph)
                        current_paragraph = [curr]
                    else:
                        current_paragraph.append(curr)
                paragraphs.append(current_paragraph)
                
            results = []
            for para in paragraphs:
                assembled_text = ""
                paddle_lines = []
                current_line_text = ""
                last_b = None
                
                # 段落内での座標ソート
                para.sort(key=lambda b: (int(b['rect']['y'] // band_size), b['rect']['x']))
                
                for b in para:
                    txt = b['text'].strip()
                    if not txt: continue
                    
                    if last_b is None:
                        assembled_text = txt
                        current_line_text = txt
                    else:
                        y_diff = abs(b['rect']['y'] - last_b['rect']['y'])
                        h_min = min(b['rect']['h'], last_b['rect']['h'])
                        # 同じ行内かどうかの判定
                        if y_diff < h_min * 0.6:
                            # 日本語・中国語ならスペースなしで結合
                            if re.search(r'[ぁ-んァ-ヶ一-龥ー]', assembled_text[-1:]) and re.search(r'[ぁ-んァ-ヶ一-龥ー]', txt[:1]):
                                assembled_text += txt
                                current_line_text += txt
                            else:
                                assembled_text += " " + txt
                                current_line_text += " " + txt
                        else:
                            # 改行
                            paddle_lines.append(current_line_text)
                            assembled_text += "\n" + txt
                            current_line_text = txt
                    last_b = b
                
                if current_line_text:
                    paddle_lines.append(current_line_text)
                
                if not assembled_text.strip():
                    continue

                # 元画像全体の座標系に変換
                all_bx  = [b['rect']['x']              + x0 for b in para]
                all_by  = [b['rect']['y']              + y0 for b in para]
                all_bx2 = [b['rect']['x'] + b['rect']['w'] + x0 for b in para]
                all_by2 = [b['rect']['y'] + b['rect']['h'] + y0 for b in para]
                
                abs_rect = {
                    'x': min(all_bx),
                    'y': min(all_by),
                    'w': max(all_bx2) - min(all_bx),
                    'h': max(all_by2) - min(all_by),
                }

                avg_conf = sum(b['confidence'] for b in para) / len(para) if para else 0.0
                
                # 【精度向上】MTG特有の誤読補正を適用
                assembled_text = self._fix_mtg_misreads(assembled_text)
                paddle_lines = [self._fix_mtg_misreads(l) for l in paddle_lines]
                
                results.append((assembled_text, abs_rect, paddle_lines, avg_conf))

            return results

        except Exception as e:
            print(f"[OCR Paddle] 再認識・細分化エラー: {e}")
            return []


    def _tiled_paddle_detection(self, image: Image.Image) -> list[dict]:
        """画面を960x960のタイルに分割して高速索敵(rec=False)を行う"""
        if self.paddle_engine is None:
            return []
            
        TILE_SIZE = 960
        OVERLAP = 120  # タイル間の重なり（境界上の文字を拾うため）
        
        w, h = image.width, image.height
        all_blocks = []
        
        # タイルの座標リストを作成
        y_coords = []
        curr_y = 0
        while curr_y < h:
            y_coords.append(curr_y)
            if curr_y + TILE_SIZE >= h: break
            curr_y += (TILE_SIZE - OVERLAP)
            
        x_coords = []
        curr_x = 0
        while curr_x < w:
            x_coords.append(curr_x)
            if curr_x + TILE_SIZE >= w: break
            curr_x += (TILE_SIZE - OVERLAP)
            
        # 各タイルをスキャン
        for ty in y_coords:
            for tx in x_coords:
                # タイルの切り出し
                tw = min(TILE_SIZE, w - tx)
                th = min(TILE_SIZE, h - ty)
                tile = image.crop((tx, ty, tx + tw, ty + th))
                
                # 索敵(rec=False)実行
                blocks = self.paddle_engine.recognize(tile, rec=False)
                for b in blocks:
                    # 全体座標に変換
                    b['rect']['x'] += tx
                    b['rect']['y'] += ty
                    all_blocks.append(b)
                    
        # 重複・隣接する枠をグループ化して統合 (Union-Find的なアプローチ)
        if not all_blocks:
            return []
            
        def is_overlap_or_close(r1, r2):
            # IoUだけでなく、非常に近くにある枠も同じグループとみなす
            # 特にタイルの境界で分割された場合を考慮
            iou = _calc_iou(r1, r2)
            if iou > 0.1: return True # 重なりがあれば統合
            
            # 垂直方向に近く、水平方向に重なりがある場合（行の分割対策）
            dx = min(r1['x']+r1['w'], r2['x']+r2['w']) - max(r1['x'], r2['x'])
            dy = max(r1['y'], r2['y']) - min(r1['y']+r1['h'], r2['y']+r2['h'])
            if dx > 0 and abs(dy) < 15: return True
            
            return False

        # グループ化
        groups = []
        for b in all_blocks:
            found_group = False
            for group in groups:
                for member in group:
                    if is_overlap_or_close(b['rect'], member['rect']):
                        group.append(b)
                        found_group = True
                        break
                if found_group: break
            if not found_group:
                groups.append([b])
        
        # グループごとに最小包含矩形を計算
        merged_results = []
        for group in groups:
            xs = [b['rect']['x'] for b in group]
            ys = [b['rect']['y'] for b in group]
            rs = [b['rect']['x'] + b['rect']['w'] for b in group]
            bs = [b['rect']['y'] + b['rect']['h'] for b in group]
            
            union_rect = {
                'x': min(xs),
                'y': min(ys),
                'w': max(rs) - min(xs),
                'h': max(bs) - min(ys)
            }
            # 極端に小さいゴミを除去
            if union_rect['w'] < 10 or union_rect['h'] < 10:
                continue
            merged_results.append({'rect': union_rect})
                
        return merged_results

    def extract_text(self, image: Image.Image, force: bool = False, window_title: str = "", target_lang: str = "ja", attach_image: bool = False, thread_limit_ratio: float = 1.0) -> tuple[list[dict], bool]:
        import os
        try:
            results_by_lang = {}
            # CPU数に基づいた並列実行数の決定
            max_workers = max(1, int((os.cpu_count() or 1) * thread_limit_ratio))
            
            # --- Only Paddle モード (タイル分割索敵) ---
            if self.ocr_mode == "paddle_only" and self.paddle_engine is not None:
                # 1. タイル分割索敵
                scout_blocks = self._tiled_paddle_detection(image)
                # 2. 各枠を精読
                clean_chunks = []
                for b in scout_blocks:
                    refine_results = self._try_paddle_refine(image, b['rect'])
                    for text, r_rect, r_lines, r_conf in refine_results:
                        self._append_chunk(clean_chunks, image, text, r_rect, r_lines, "ja", target_lang, attach_image)
                return clean_chunks, True

            # --- 第1パス: 矩形群の獲得と統合 (Discovery OCR) ---
            # WinRT(全言語) と Paddle(索敵) を並列実行して「どこに文字があるか」を確定させる
            scout_rects = []
            
            with ThreadPoolExecutor(max_workers=max_workers + 1) as executor:
                # WinRT スキャン
                winrt_futures = [executor.submit(self._recognize_single, image, lang) for lang in self.available_langs]
                # Paddle 索敵スキャン (rec=False)
                paddle_scout_future = executor.submit(self.paddle_engine.recognize, image, rec=False) if self.paddle_engine else None
                
                # WinRT スキャン (Discovery: 枠の検出のみに使用し、テキストは破棄する)
                for future in winrt_futures:
                    lang, res = future.result()
                    if res and "lines" in res:
                        for line in res["lines"]:
                            if "words" in line:
                                # 座標のみを抽出し、WinRTが読み取ったテキスト内容は一切使用しない
                                xs = [w['bounding_rect']['x'] for w in line["words"]]
                                ys = [w['bounding_rect']['y'] for w in line["words"]]
                                rs = [w['bounding_rect']['x'] + w['bounding_rect']['width'] for w in line["words"]]
                                bs = [w['bounding_rect']['y'] + w['bounding_rect']['height'] for w in line["words"]]
                                scout_rects.append({"x": min(xs), "y": min(ys), "w": max(rs) - min(xs), "h": max(bs) - min(ys)})
                
                # Paddle の結果から矩形を抽出
                if paddle_scout_future:
                    p_blocks = paddle_scout_future.result()
                    if p_blocks:
                        for b in p_blocks:
                            scout_rects.append(b['rect'])

            # 矩形群を統合整理 (IoUでマージして重複を消す)
            if not scout_rects:
                return [], False
            
            # 矩形群を統合整理 (アグレッシブ・マージ)
            # 重複だけでなく、同一行にある近接した枠も一つの文章ブロックとして連結する
            master_rects = []
            scout_rects.sort(key=lambda r: r['w'] * r['h'], reverse=True)
            
            # [v1.1.2 Guard] 異常な数の矩形がある場合は制限（ノイズによるハング防止）
            if len(scout_rects) > 800:
                print(f"[OCR Guard] 警告: 検出された矩形が多すぎます ({len(scout_rects)}個)。上位400個に制限します。")
                scout_rects = scout_rects[:400]

            for r in scout_rects:
                is_merged = False
                for m in master_rects:
                    # A. 重複判定 (IoU > 0.1 または 内包)
                    iou = _calc_iou(r, m)
                    
                    # B. 近接判定（同一行または上下に並んでいる）
                    # Y軸の重なりがあるか、垂直方向に近い場合
                    y_overlap = max(0, min(r['y']+r['h'], m['y']+m['h']) - max(r['y'], m['y']))
                    min_h = min(r['h'], m['h'])
                    
                    # 垂直方向の隙間チェック
                    v_gap = 0
                    if r['y'] + r['h'] < m['y']:
                        v_gap = m['y'] - (r['y'] + r['h'])
                    elif m['y'] + m['h'] < r['y']:
                        v_gap = r['y'] - (m['y'] + m['h'])
                    
                    # 横方向の重なり具合 (50%以上重なっていれば縦に並んでいるとみなす)
                    x_overlap = max(0, min(r['x']+r['w'], m['x']+m['w']) - max(r['x'], m['x']))
                    is_v_aligned = (x_overlap > min(r['w'], m['w']) * 0.5)
                    
                    # 1. 同じ行にある
                    is_same_line = (y_overlap > min_h * 0.6)
                    # 2. 上下に並んでいる (隙間が文字高の2倍以内)
                    is_stacked = is_v_aligned and (v_gap < min_h * 2.5)
                    
                    # 左右の隙間が文字の高さの 1.5 倍以内なら「近接」
                    x_gap = 0
                    if r['x'] + r['w'] < m['x']:
                        x_gap = m['x'] - (r['x'] + r['w'])
                    elif m['x'] + m['w'] < r['x']:
                        x_gap = r['x'] - (m['x'] + m['w'])
                    is_h_close = (x_gap < min_h * 1.5)
                    
                    if iou > 0.1 or (is_same_line and is_h_close) or is_stacked:
                        # 統合（Union）してマスター領域を拡大
                        m_nx = min(m['x'], r['x'])
                        m_ny = min(m['y'], r['y'])
                        m_nw = max(m['x'] + m['w'], r['x'] + r['w']) - m_nx
                        m_nh = max(m['y'] + m['h'], r['y'] + r['h']) - m_ny
                        m['x'], m['y'], m['w'], m['h'] = m_nx, m_ny, m_nw, m_nh
                        is_merged = True
                        break
                if not is_merged:
                    master_rects.append(r)

            # --- 第2パス: 高精度読み取り (Recognition) ---
            # [v1.1.2 Guard] 最終的な読取対象が多すぎる場合も制限
            if len(master_rects) > 100:
                print(f"[OCR Guard] 読取対象が多すぎます ({len(master_rects)}個)。上位60個に制限します。")
                master_rects = master_rects[:60]

            clean_chunks = []
            for m_rect in master_rects:
                # PaddleOCR で精読
                refine_results = self._try_paddle_refine(image, m_rect)
                for p_text, p_rect, p_lines, p_conf in refine_results:
                    # 【v1.1.2 独立ガードレール】OCR直後のノイズを物理的に排除
                    text_no_space = p_text.replace(" ", "").replace("\n", "")
                    if not text_no_space: continue

                    # 1. 記号割合チェック (MTGの +1/+1 等を考慮して緩和)
                    # + や / は MTG では記号扱いにしない
                    meaningful_symbols = len(re.findall(r'[+/]', text_no_space))
                    symbol_count = len(re.findall(r'[^\wぁ-んァ-ン一-龥가-힣А-Яа-яЁёÀ-ÿ]', text_no_space)) - meaningful_symbols
                    symbol_ratio = symbol_count / max(1, len(text_no_space))
                    
                    # 判定を大幅に緩和 (0.25/0.35 -> 0.45/0.60)
                    if (len(text_no_space) <= 10 and symbol_ratio >= 0.45) or symbol_ratio >= 0.60:
                        if p_conf < 0.85: # 高い確信度がある場合はゴミではないと判断
                            # print(f"[OCRFilter] 記号過多スキップ ({symbol_ratio:.2f}): '{p_text[:20]}'")
                            t_hash = hashlib.md5(p_text.encode('utf-8')).hexdigest()
                            self.skip_cache[t_hash] = time.time() + 2.0
                            continue

                    # 2. 部首ハルシネーションチェック (PaddleOCR特有の誤読)
                    radical_count = sum(1 for c in text_no_space if c in self.radical_chars)
                    if radical_count >= 3 or (len(text_no_space) <= 15 and radical_count >= 2):
                        if p_conf < 0.90:
                            # print(f"[OCRFilter] 部首ハルシネーションスキップ: '{p_text[:20]}'")
                            # 2秒間のスキップキャッシュに登録
                            t_hash = hashlib.md5(str(p_text).encode('utf-8')).hexdigest()
                            self.skip_cache[t_hash] = time.time() + 2.0
                            continue

                    # 3. Unicodeブロック判定（有効な全言語を考慮）
                    # 基本の許可セット（英数字、スペース、基本記号、ラテン文字）
                    allowed_ranges = r'0-9A-Za-z\s\.,!\?\-\u0020-\u007F\u00A0-\u00FF'
                    
                    # 有効な言語に基づいて許可範囲を拡張
                    lang_tags = [l.split("-")[0].lower() for l in self.available_langs] if self.available_langs else ["en"]
                    src_lang = lang_tags[0]
                    if "ja" in lang_tags:
                        allowed_ranges += r'\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF'
                    if "ko" in lang_tags:
                        allowed_ranges += r'\uAC00-\uD7A3\u1100-\u11FF'
                    if "ru" in lang_tags:
                        allowed_ranges += r'\u0400-\u04FF'
                    
                    # 正規表現で不適合文字をカウント
                    pattern = f'[^{allowed_ranges}]'
                    invalid_chars = len(re.findall(pattern, text_no_space))
                    
                    if invalid_chars / len(text_no_space) > 0.4:
                        if p_conf < 0.85:
                            debug_lang = "/".join(lang_tags)
                            # print(f"[OCRFilter] Unicodeブロック不適合スキップ ({debug_lang}): '{p_text[:20]}'")
                            # 2秒間のスキップキャッシュに登録
                            t_hash = hashlib.md5(str(p_text).encode('utf-8')).hexdigest()
                            self.skip_cache[t_hash] = time.time() + 2.0
                            continue

                    # 4. 極端な短文排除
                    if len(text_no_space) <= 3 and not (p_rect['h'] > image.height * 0.1):
                        if p_conf < 0.80:
                            # print(f"[OCRFilter] 短文低確信度スキップ: '{p_text[:20]}' (conf: {p_conf:.2f})")
                            # 2秒間のスキップキャッシュに登録
                            t_hash = hashlib.md5(p_text.encode('utf-8')).hexdigest()
                            self.skip_cache[t_hash] = time.time() + 2.0
                            continue

                    # スキップキャッシュの最終チェック
                    t_hash = hashlib.md5(str(p_text).encode('utf-8')).hexdigest()
                    if t_hash in self.skip_cache:
                        if time.time() < self.skip_cache[t_hash]:
                            continue
                    
                    # ソース言語を推測して渡す
                    self._append_chunk(clean_chunks, image, p_text, p_rect, p_lines, src_lang, target_lang, attach_image, parent_rect=m_rect)
            
            return clean_chunks, True

            
            # 1. まず各言語ごとにクラスタリング（段落の組み立て）を行う
            for lang_key, result in results_by_lang.items():
                is_scout_pass = lang_key.startswith("paddle_")
                real_lang = lang_key.replace("paddle_", "")
                lines = result.get("lines", [])
                valid_lines = []
                for line in lines:
                    text = line.get("text", "").strip()
                    words = line.get("words", [])
                    # 索敵パス(paddle_)の場合はテキストが空でも枠があれば許可する
                    if (not text and not is_scout_pass) or not words:
                        continue
                    xs = [w['bounding_rect']['x'] for w in words]
                    ys = [w['bounding_rect']['y'] for w in words]
                    rs = [w['bounding_rect']['x'] + w['bounding_rect']['width'] for w in words]
                    bs = [w['bounding_rect']['y'] + w['bounding_rect']['height'] for w in words]
                    rect = {"x": min(xs), "y": min(ys), "w": max(rs) - min(xs), "h": max(bs) - min(ys)}
                    
                    if rect.get("h", 0) < 8:
                        continue
                        
                    valid_lines.append({"text": text, "rect": rect})
                    
                # Y座標である程度行を揃えてからX座標でソート（横方向の連続性を担保）
                valid_lines.sort(key=lambda l: (l['rect']['y'] // 15, l['rect']['x']))

                chunks = []
                for line in valid_lines:
                    added = False
                    for chunk in chunks:
                        last_line_rect = chunk['lines'][-1]['rect']
                        l_rect = line['rect']
                        
                        y_overlap = min(last_line_rect['y'] + last_line_rect['h'], l_rect['y'] + l_rect['h']) - max(last_line_rect['y'], l_rect['y'])
                        is_same_row = y_overlap > 0 or abs(l_rect['y'] - last_line_rect['y']) < min(last_line_rect['h'], l_rect['h']) * 0.5
                        y_diff = l_rect['y'] - (last_line_rect['y'] + last_line_rect['h'])
                        margin = max(last_line_rect['h'], l_rect['h']) * 2.0
                        left_diff = abs(l_rect['x'] - last_line_rect['x'])
                        center_diff = abs((l_rect['x'] + l_rect['w'] / 2) - (last_line_rect['x'] + last_line_rect['w'] / 2))
                        x_overlap = min(last_line_rect['x'] + last_line_rect['w'], l_rect['x'] + l_rect['w']) - max(last_line_rect['x'], l_rect['x'])
                        
                        # フォントサイズ判定：縦読み列（wが小さくhが大きい）に対応するため min(h, w) を使用
                        fs1 = min(last_line_rect['h'], last_line_rect['w'])
                        fs2 = min(l_rect['h'], l_rect['w'])
                        font_size_ratio = max(fs1, fs2) / max(1, min(fs1, fs2))
                        is_same_font_size = font_size_ratio < 2.5
                        
                        can_merge = False
                        if is_same_font_size:
                            if is_same_row:
                                # チャンク全体の矩形との横方向の重なり/ギャップを見る
                                c_rect = chunk['rect']
                                x_overlap_chunk = min(c_rect['x'] + c_rect['w'], l_rect['x'] + l_rect['w']) - max(c_rect['x'], l_rect['x'])
                                # 縦読み列同士の結合のため、ギャップ許容値を高さベース（最大0.8倍）まで広げる
                                gap_tolerance = max(10, min(last_line_rect['h'], l_rect['h']) * 0.8)
                                if x_overlap_chunk > -gap_tolerance: can_merge = True
                            else:
                                # 直前の行ではなく、現在組み立て中の段落の平均高さを基準にする（大文字小文字による判定ブレ解消）
                                avg_h = sum(l['rect']['h'] for l in chunk['lines']) / len(chunk['lines'])
                                # PaddleOCRは行間が密接していて枠が重なる（y_diffがマイナスになる）場合があるため、重なりも許容する
                                if -max(avg_h, l_rect['h']) * 0.5 <= y_diff <= max(avg_h, l_rect['h']) * 1.5:
                                    if left_diff <= margin or center_diff <= margin: can_merge = True

                        if can_merge:
                            chunk['lines'].append(line)
                            min_x = min(chunk['rect']['x'], l_rect['x'])
                            min_y = min(chunk['rect']['y'], l_rect['y'])
                            max_r = max(chunk['rect']['x'] + chunk['rect']['w'], l_rect['x'] + l_rect['w'])
                            max_b = max(chunk['rect']['y'] + chunk['rect']['h'], l_rect['y'] + l_rect['h'])
                            chunk['rect'] = {"x": min_x, "y": min_y, "w": max_r - min_x, "h": max_b - min_y}
                            added = True
                            break
                                
                    if not added:
                        chunks.append({"rect": dict(line['rect']), "lines": [line], "lang": real_lang})
                        
                all_raw_chunks.extend(chunks)

            # 2. 言語ごとのクラスタを大域的に統合する（同じ場所にあるものは比較判定グループにまとめる）
            grouped = []
            for raw in all_raw_chunks:
                best_group = None
                best_iou = 0.5
                for group in grouped:
                    iou = _calc_iou(raw['rect'], group['rect'])
                    if iou > best_iou:
                        best_iou = iou
                        best_group = group
                
                if best_group:
                    best_group['candidates'].append(raw)
                    gr = best_group['rect']
                    rr = raw['rect']
                    mx = min(gr['x'], rr['x'])
                    my = min(gr['y'], rr['y'])
                    mr = max(gr['x']+gr['w'], rr['x']+rr['w'])
                    mb = max(gr['y']+gr['h'], rr['y']+rr['h'])
                    best_group['rect'] = {"x": mx, "y": my, "w": mr-mx, "h": mb-my}
                else:
                    grouped.append({
                        "rect": dict(raw['rect']),
                        "candidates": [raw]
                    })
                    
            if not grouped:
                return [], False
                
            mean_height = sum(g['rect']['h'] for g in grouped) / len(grouped)

            clean_chunks = []
            # PaddleOCRが広範囲を再認識して吸収した矩形のリスト。
            # これに重なるWinRTチャンクは重複出力を防ぐためスキップする。
            paddle_absorbed_rects: list[dict] = []
            
            # 面積の大きい順に処理することで、広い枠（Paddle等）が先に処理され、
            # 小さいゴミ枠が確実に「吸収済み」として弾かれるようにする
            grouped.sort(key=lambda g: g['rect']['w'] * g['rect']['h'], reverse=True)
            
            # ===== winrt_only モード: 2パス目 WinRT 全言語再読み取り =====
            # 1パス目で決定した枠のみをクロップして全言語WinRTで再読み取りし、
            # 候補リストを更新する（この時、新たな枠は作らない）
            if self.ocr_mode == "winrt_only":
                for group in grouped:
                    gr = group['rect']
                    # マージンを小さく設けて切り出す（隣接テキストの混入を防ぐ）
                    margin = max(4, int(gr['h'] * 0.15))
                    x0 = max(0, gr['x'] - margin)
                    y0 = max(0, gr['y'] - margin)
                    x1 = min(image.width,  gr['x'] + gr['w'] + margin)
                    y1 = min(image.height, gr['y'] + gr['h'] + margin)
                    crop = image.crop((x0, y0, x1, y1))
                    
                    new_candidates = []
                    with ThreadPoolExecutor(max_workers=min(len(self.available_langs), max_workers)) as ex:
                        futs = [ex.submit(self._recognize_single, crop, lang) for lang in self.available_langs]
                        for fut in futs:
                            lang2, res2 = fut.result()
                            if not res2:
                                continue
                            lines = res2.get("lines", [])
                            valid_lines = []
                            for line in lines:
                                text2 = line.get("text", "").strip()
                                words2 = line.get("words", [])
                                if not text2 or not words2:
                                    continue
                                xs2 = [w['bounding_rect']['x'] + x0 for w in words2]
                                ys2 = [w['bounding_rect']['y'] + y0 for w in words2]
                                rs2 = [w['bounding_rect']['x'] + w['bounding_rect']['width'] + x0 for w in words2]
                                bs2 = [w['bounding_rect']['y'] + w['bounding_rect']['height'] + y0 for w in words2]
                                r2 = {"x": min(xs2), "y": min(ys2), "w": max(rs2) - min(xs2), "h": max(bs2) - min(ys2)}
                                if r2.get("h", 0) < 8:
                                    continue
                                valid_lines.append({"text": text2, "rect": r2})
                            if valid_lines:
                                new_candidates.append({
                                    "rect": gr,
                                    "lines": valid_lines,
                                    "lang": lang2,
                                    "source": "winrt_2nd",
                                    "joined_lines": [l["text"] for l in valid_lines],
                                })
                    
                    # 2パス目の候補が取れた場合のみ上書き（取れなければ1パス目の候補をそのまま使う）
                    if new_candidates:
                        group['candidates'] = new_candidates
                        print(f"[WinRT 2pass] 枠({gr['x']},{gr['y']}) {len(new_candidates)}言語で再読み取り完了")
            
            # 3. 最適なテキスト結果を選別
            for group in grouped:
                best_cand = None
                best_score = -1.0
                best_priority_score = -1.0
                
                tgt_family = target_lang.split("-")[0].lower()
                
                for cand in group['candidates']:
                    # cand_text を組み立てる際、同じ行とみなせるものは \n ではなくスペース等で繋ぐ
                    lines_sorted = sorted(cand['lines'], key=lambda x: (x['rect']['y'] // 15, x['rect']['x']))
                    assembled_text = ""
                    last_line = None
                    winrt_lines = []
                    current_line_text = ""
                    for l in lines_sorted:
                        txt = l['text'].strip()
                        if not txt: continue
                        if last_line is None:
                            assembled_text = txt
                            current_line_text = txt
                        else:
                            y_diff = abs(l['rect']['y'] - last_line['rect']['y'])
                            h_min = min(l['rect']['h'], last_line['rect']['h'])
                            if y_diff < h_min * 0.5:
                                # 同じ行の場合、日本語・中国語の間はスペースを入れない
                                if re.search(r'[ぁ-んァ-ヶ一-龥ー]', assembled_text[-1:]) and re.search(r'[ぁ-んァ-ヶ一-龥ー]', txt[:1]):
                                    assembled_text += txt
                                    current_line_text += txt
                                else:
                                    assembled_text += " " + txt
                                    current_line_text += " " + txt
                            else:
                                # 違う行
                                winrt_lines.append(current_line_text)
                                assembled_text += "\n" + txt
                                current_line_text = txt
                        last_line = l
                    if current_line_text:
                        winrt_lines.append(current_line_text)
                        
                    cand_text = assembled_text
                    cand['joined_lines'] = winrt_lines
                    score = get_script_ratio(cand_text, cand['lang'])

                    # --- 短いCJK断片へのペナルティ ---
                    # 「文すト」「呪消・」のような6文字以下の細切れCJKテキストは
                    # 誤認識の可能性が高い。スコアを下げてPaddleOCRフォールバックを
                    # 積極的に発動させ、より高精度な再認識を促す。
                    _text_compact = cand_text.replace('\n', '').replace(' ', '')
                    _has_cjk = bool(re.search(r'[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7a3]', _text_compact))
                    if _has_cjk and len(_text_compact) <= 6:
                        score -= 0.20

                    # 【多言語・文字種混在ノイズの段階的ペナルティ】
                    # アジア圏やロシア・アラビア圏の「固有文字」が複数混在するのはOCRのハルシネーション
                    _has_kana = bool(re.search(r'[ぁ-んァ-ン]', cand_text))
                    _has_hangul = bool(re.search(r'[가-힣]', cand_text))
                    _has_cyril = bool(re.search(r'[А-Яа-яЁё]', cand_text))
                    _has_arabic = bool(re.search(r'[\u0600-\u06ff]', cand_text))
                    
                    conflict_count = sum([_has_kana, _has_hangul, _has_cyril, _has_arabic])
                    if conflict_count == 2:
                        score -= 0.20
                    elif conflict_count == 3:
                        score -= 0.60
                    elif conflict_count >= 4:
                        score -= 1.00
                        
                    _has_kanji = bool(re.search(r'[一-龥]', cand_text))
                    # 現代の文章でハングルと漢字が混在することはほぼ無い
                    if _has_hangul and _has_kanji:
                        score -= 0.50

                    cand_family = cand['lang'].split("-")[0].lower()
                    _lines = [l['text'].strip() for l in cand['lines']]

                    # ============================================================
                    # 言語別 OCR 異常検知ペナルティ
                    # WinRTOCR が判定した言語ごとに固有の「誤読パターン」を検知して
                    # スコアを減点し、PaddleOCR フォールバックを積極的に発動させる。
                    # ※ 各チェックは該当言語の候補にのみ適用。他言語には一切影響しない。
                    # ============================================================

                    if cand_family == 'ja':
                        # 【日本語1】カタカナ・平仮名の不規則混在の検知
                        # 「つリ-チや-」のように1語内でカタカナと平仮名が交互出現するのは異常
                        _abnormal_mix = 0
                        for _word in re.split(r'[-\s。、・\n]', cand_text):
                            _word = _word.strip()
                            if len(_word) < 3:
                                continue
                            _kata_c = len(re.findall(r'[ァ-ヶ]', _word))
                            _hira_c = len(re.findall(r'[ぁ-ん]', _word))
                            if _kata_c >= 1 and _hira_c >= 1:
                                _abnormal_mix += 1
                        if _abnormal_mix >= 2:
                            score -= 0.20

                        # 【日本語2】常用外漢字（CJK拡張A: U+3400-U+4DBF）の検知
                        # 「鶩」「耨」等は通常のゲームUIに出現しないOCRのハルシネーション
                        _rare = len(re.findall(r'[\u3400-\u4dbf]', cand_text))
                        if _rare >= 1:
                            score -= 0.20
                        if _rare >= 3:
                            score -= 0.20  # 複数検出で追加ペナルティ（累積）

                    elif cand_family == 'ko':
                        # 【ハングル1】ハングルと漢字の不自然な混在の検知
                        # 現代韓国語ではハングルが圧倒的多数を占める
                        _han_c  = len(re.findall(r'[가-힣]', _text_compact))
                        _kanj_c = len(re.findall(r'[一-龥]', _text_compact))
                        if _han_c > 0 and _kanj_c > 0 and len(_text_compact) <= 15:
                            if min(_han_c, _kanj_c) / max(_han_c, _kanj_c) >= 0.3:
                                score -= 0.20

                        # 【ハングル2】常用外漢字の検知
                        _rare = len(re.findall(r'[\u3400-\u4dbf]', cand_text))
                        if _rare >= 2:
                            score -= 0.20

                    elif cand_family == 'zh':
                        # 【中国語1】簡体字・繁体字の不自然な混在の検知
                        # 同一テキストに簡体字特有の文字と繁体字特有の文字が共存するのは異常
                        _simp_c = len(re.findall(r'[们说这来时国际现实经济动话]', cand_text))
                        _trad_c = len(re.findall(r'[們說這來時國際現實經濟動話]', cand_text))
                        if _simp_c >= 1 and _trad_c >= 1:
                            score -= 0.20

                        # 【中国語2】常用外漢字の検知
                        _rare = len(re.findall(r'[\u3400-\u4dbf]', cand_text))
                        if _rare >= 2:
                            score -= 0.20


                    # ============================================================
                    # 言語性テキストの检出ブースト
                    # 「その言語に特有の文字」が含まれる場合、候補選びのための priority_score をブーストする。
                    # ============================================================
                    latin_count = len(re.findall(r'[a-zA-Z]', cand_text))
                    priority_score = score

                    if cand_family == 'ja':
                        kana_count  = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', cand_text))
                        kanji_count = len(re.findall(r'[\u4e00-\u9fff]', cand_text))
                        if kana_count > 0 and kana_count > latin_count * 0.2:
                            priority_score += 0.5
                        elif kanji_count > 0 and kanji_count >= latin_count:
                            priority_score += 0.3

                    elif cand_family == 'ko':
                        hangul_count = len(re.findall(r'[\uac00-\ud7a3]', cand_text))
                        if hangul_count > 0 and hangul_count > latin_count * 0.2:
                            priority_score += 0.5

                    elif cand_family == 'zh':
                        han_count = len(re.findall(r'[\u4e00-\u9fff]', cand_text))
                        if han_count > 0 and han_count > latin_count * 0.2:
                            priority_score += 0.3

                    elif cand_family == 'ru':
                        cyril_count = len(re.findall(r'[\u0400-\u04ff]', cand_text))
                        if cyril_count > 0 and cyril_count > latin_count * 0.2:
                            priority_score += 0.3


                    # 同スコアなら優先言語（配列の前の方）が来るようにする。
                    if priority_score > best_priority_score:
                        best_priority_score = priority_score
                        best_score = score
                        best_cand = cand
                        best_cand['full_text'] = cand_text
                        
                if not best_cand:
                    continue
                    
                chunk_text = best_cand['full_text']
                detected_lang = best_cand['lang']
                
                if window_title and chunk_text.strip().upper() == window_title.upper():
                    continue
                
                chunk_text = re.sub(r'[ \t]+', ' ', chunk_text).strip()
                
                # --- 日本語特有のOCR誤認識・レイアウト崩れの補正 ---
                if detected_lang.split('-')[0].lower() == 'ja':
                    # 「く」が「<」として誤認識されるケースへの対処
                    chunk_text = chunk_text.replace('<', 'く')
                    
                    # ハイフン「-」がカタカナの長音符「ー」として誤認識されるケースへの対処
                    # カタカナに挟まれた「-」を「ー」に置換する
                    chunk_text = re.sub(r'(?<=[ァ-ヶ])-(?=[ァ-ヶ])', 'ー', chunk_text)
                    # 行頭の「-」の直後がカタカナなら「ー」に置換（例: -ル → ール）
                    chunk_text = re.sub(r'(?<=\n)-(?=[ァ-ヶ])', 'ー', chunk_text)
                    chunk_text = re.sub(r'^-(?=[ァ-ヶ])', 'ー', chunk_text)
                    
                    # 文字間に不要な半角スペースが入る現象（例：「ア リ ー ナ」）を修正する
                    # 前後がASCII（英数字）である箇所のスペースだけを残し、それ以外（日本語の間など）のスペースは除去する
                    new_text = []
                    for i, c in enumerate(chunk_text):
                        if c == ' ':
                            if i > 0 and i < len(chunk_text) - 1:
                                prev_c = chunk_text[i-1]
                                next_c = chunk_text[i+1]
                                # 前後が両方ともASCII文字なら英語のスペースとして残す ("Level Up" など)
                                if prev_c.isascii() and next_c.isascii():
                                    new_text.append(c)
                                    continue
                            # 日本語文字に挟まれた空白は消す
                            continue
                        new_text.append(c)
                    chunk_text = "".join(new_text)
                
                if re.fullmatch(r'[\d\s\.,/\+\-xX]+', chunk_text):
                    continue
                    
                # 「＄128,168」「48min」「11h」「08：32」などの記号＋数字、数字＋略字を除外
                text_no_space = chunk_text.replace(" ", "").replace("：", ":")
                if re.fullmatch(r'^[\W\d]*[a-zA-Z]{0,4}[\W\d]*$', text_no_space) and any(c.isdigit() for c in text_no_space):
                    continue
                    
                is_large = group['rect']['h'] > mean_height * 1.4

                if len(chunk_text) <= 2 and not is_large:
                    continue

                text_no_space = chunk_text.replace(" ", "")
                
                # --- 強力な記号・特殊文字フィルター ---
                symbol_count = len(re.findall(r'[^\wぁ-んァ-ン一-龥가-힣А-Яа-яЁёÀ-ÿ]', text_no_space))
                if len(text_no_space) > 0:
                    symbol_ratio = symbol_count / len(text_no_space)
                    if len(text_no_space) <= 12 and symbol_ratio >= 0.25:
                        continue
                    elif symbol_ratio >= 0.35:
                        continue
                else:
                    symbol_ratio = 0
                
                # アルファベットと数字だらけなのに意味をなさない短い羅列
                alnum_count = sum(c.isalnum() for c in text_no_space)
                if len(text_no_space) <= 10 and alnum_count / max(1, len(text_no_space)) < 0.4:
                    continue

                # 「H e l l o」のように1文字ずつ分断された文字列の空白を除去
                words = [w for w in chunk_text.split() if w.isalnum()]
                if len(words) >= 3 and max((len(w) for w in words), default=0) <= 2:
                    chunk_text = chunk_text.replace(" ", "")
                    
                # 【丸数字・矢印だけの断片を排除】
                # ②を\n①きを のような意味のない断片
                stripped_for_check = re.sub(r'[\s\n①②③④⑤⑥⑦⑧⑨⑩◎○●▶▷►→←↑↓△▽☆★♦♢♣♠♥♤♧♡]', '', chunk_text)
                if len(stripped_for_check) <= 3:
                    continue
                    
                # 【CJK部首・偏旁文字の検出 → 文字化け判定】
                # 亻 冫 刂 彐 尸 儿 匕 卩 廾 弋 etc. は通常の日本語テキストに単独では出現しない
                # これらが複数含まれるテキストはOCRの部首誤認識（ハルシネーション）
                radical_chars = set('亻冫刂彐尸儿匕卩廾弋夂夊宀彑彡忄扌攵旡殳氵灬爿犭疒癶礻糹纟罒艹虍衤覀訁讠貝贝辶釒钅隹阝韋飠饣髟鬥麻黽齊齒龜龠卜丿乀乁丨亅丶亠')
                radical_count = sum(1 for c in text_no_space if c in radical_chars)
                if radical_count >= 3:
                    continue
                # 短いテキストで部首が2つ以上 → ほぼ確実にノイズ
                if len(text_no_space) <= 15 and radical_count >= 2:
                    continue
                    
                # 【ほとんどひらがなだけの短い断片 → 意味なし】
                # 「wなソ′亡の」「プロノイ」のような短い無意味断片
                if len(text_no_space) <= 5 and not is_large:
                    continue
                    
                # 【未ペアの括弧ノイズの徹底排除】
                if len(text_no_space) <= 20:
                    unpaired = False
                    brackets = {'(': ')', '[': ']', '{': '}', '「': '」', '『': '』', '【': '】', '（': '）', '〈': '〉', '《': '》'}
                    for op, cl in brackets.items():
                        if (op in chunk_text) != (cl in chunk_text):
                            unpaired = True
                            break
                    if unpaired:
                        continue
                    
                # （文字種の混在ペナルティは候補選択時のスコア減点に移行しました）
                
                # 【日本語OCRのハルシネーション対策】
                # ひらがな・カタカナが一切なく、漢字だけが不自然に並ぶケース（9文字以上なら稀なので破棄）
                if best_cand['lang'].split('-')[0].lower() == 'ja':
                    has_kana = bool(re.search(r'[ぁ-んァ-ン]', chunk_text))
                    has_kanji = bool(re.search(r'[一-龥]', chunk_text))
                    if not has_kana and has_kanji and len(text_no_space) >= 9:
                        continue
                    
                # 異常な文字化け記号
                if len(re.findall(r'[`§Ää€~_・\\]', chunk_text)) >= 2:
                    continue
                    
                # 【縦読みノイズ枠の完全排除】
                # 横書きのテキスト群を縦にスライスして誤読した中途半端な枠の生成を根絶する。
                # （MTGAは横書きメインであるため、極端に縦に長い枠はノイズ）
                if group['rect']['h'] > group['rect']['w'] * 1.5:
                    # 改行が複数ある、または極端に縦長な場合はノイズとして捨てる
                    if chunk_text.count('\n') >= 2 or group['rect']['h'] > group['rect']['w'] * 2.5:
                        continue                    
                # 【言語除外】
                # WinRTOCRのラベルではなく後段のfastTextに委譲するため
                # ここでは除外しない（仕様: fastTextが言語判定を担う）

                # --- 吸収済みチェック ---
                # 以前のPaddleOCRが広範囲を読んで吸収済みの矩形と重複していればスキップ
                gr = group['rect']
                is_absorbed = False
                for ar in paddle_absorbed_rects:
                    # IoU (面積重複率) で判定
                    ix = max(gr['x'], ar['x'])
                    iy = max(gr['y'], ar['y'])
                    ix2 = min(gr['x']+gr['w'], ar['x']+ar['w'])
                    iy2 = min(gr['y']+gr['h'], ar['y']+ar['h'])
                    if ix2 > ix and iy2 > iy:
                        inter = (ix2-ix)*(iy2-iy)
                        gr_area = max(1, gr['w']*gr['h'])
                        if inter / gr_area >= 0.5:  # 50%以上重複なら吸収済み
                            is_absorbed = True
                            break
                if is_absorbed:
                    continue

                # 【Step 3: PaddleOCRによる精査・文字起こし】
                # hybrid / dual_scout_hybrid モードではスコアに関わらず無条件でPaddleOCRに枠を渡し、精査・仕分けさせる
                needs_paddle = (self.ocr_mode in ["hybrid", "dual_scout_hybrid"])

                if needs_paddle:
                    paddle_results = self._try_paddle_refine(image, group['rect'])
                    print(f"  [Engine] PaddleOCR: Found {len(paddle_results) if paddle_results else 0} blocks")
                    if paddle_results:
                        for p_text, p_rect, p_lines, p_conf in paddle_results:
                            # Paddleの確信度に基づいた最終フィルタ
                            if p_conf < 0.5:
                                continue
                            if p_rect:
                                paddle_absorbed_rects.append(p_rect)
                            self._append_chunk(
                                clean_chunks, image, p_text, p_rect,
                                p_lines if p_lines else p_text.strip().split('\n'),
                                detected_lang, target_lang, attach_image
                            )
                        continue
                    else:
                        # PaddleOCRで検出できなかった = WinRT誤検出（ノイズ）→ 破棄
                        continue

                # winrt_only: WinRTOCRの行リストをそのまま使用
                raw_lines = best_cand.get('joined_lines', [])
                if not raw_lines:
                    raw_lines = [l['text'].strip() for l in best_cand['lines'] if l['text'].strip()]

                self._append_chunk(
                    clean_chunks, image, chunk_text, group['rect'],
                    raw_lines, detected_lang, target_lang, attach_image
                )

            if not clean_chunks:
                return [], False

            return clean_chunks, True
            
        except Exception as e:
            print(f"[OCR Error] {e}")
            import traceback
            traceback.print_exc()
            return [], False

    def detect_text_boxes_east(self, pil_image: Image.Image, min_confidence=0.5) -> list[dict]:
        """
        OpenCV EASTモデルを使って文字枠を検出する。
        """
        if not hasattr(self, 'east_net') or self.east_net is None:
            return []
            
        import cv2
        import numpy as np
        import time

        # PIL -> OpenCV
        image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        orig_h, orig_w = image.shape[:2]

        # EASTは32の倍数の画像サイズが必要 (CPU負荷軽減のため 640x640 に設定)
        new_w, new_h = 640, 640
        rW = orig_w / float(new_w)
        rH = orig_h / float(new_h)

        blob = cv2.dnn.blobFromImage(image, 1.0, (new_w, new_h),
                                     (123.68, 116.78, 103.94), swapRB=True, crop=False)
        
        layer_names = [
            "feature_fusion/Conv_7/Sigmoid",
            "feature_fusion/concat_3"
        ]
        
        start_time = time.time()
        try:
            self.east_net.setInput(blob)
            (scores, geometry) = self.east_net.forward(layer_names)
            self._last_east_time_ms = (time.time() - start_time) * 1000
        except Exception as e:
            print(f"[EAST] 推論エラー: {e}")
            if "DNN_BACKEND_CUDA" in str(e) or "Assertion failed" in str(e) or "No CUDA support" in str(e):
                print("[EAST] CUDAバックエンドが動作しないため、CPUへ自動フォールバックします。")
                try:
                    self.east_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                    self.east_net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                except:
                    pass
            return []

        rects = []
        confidences = []

        num_rows, num_cols = scores.shape[2:4]
        for y in range(0, num_rows):
            scores_data = scores[0, 0, y]
            x_data0 = geometry[0, 0, y]
            x_data1 = geometry[0, 1, y]
            x_data2 = geometry[0, 2, y]
            x_data3 = geometry[0, 3, y]
            angles_data = geometry[0, 4, y]

            for x in range(0, num_cols):
                score = scores_data[x]
                if score < min_confidence:
                    continue

                offset_x, offset_y = x * 4.0, y * 4.0
                angle = angles_data[x]
                cos = np.cos(angle)
                sin = np.sin(angle)

                h = x_data0[x] + x_data2[x]
                w = x_data1[x] + x_data3[x]

                end_x = offset_x + (cos * x_data1[x]) + (sin * x_data2[x])
                end_y = offset_y - (sin * x_data1[x]) + (cos * x_data2[x])
                start_x = end_x - w
                start_y = end_y - h

                rects.append([int(start_x), int(start_y), int(w), int(h)])
                confidences.append(float(score))

        boxes = []
        if rects:
            idxs = cv2.dnn.NMSBoxes(rects, confidences, min_confidence, 0.4)
            if len(idxs) > 0:
                for i in idxs.flatten():
                    box = rects[i]
                    x = int(box[0] * rW)
                    y = int(box[1] * rH)
                    w = int(box[2] * rW)
                    h = int(box[3] * rH)
                    x = max(0, x)
                    y = max(0, y)
                    boxes.append({"x": x, "y": y, "w": w, "h": h})

        return boxes

    def calculate_edge_density(self, pil_image: Image.Image, rect: dict) -> float:
        """
        指定された矩形内のエッジ密度（案B）を計算する。
        """
        import cv2
        import numpy as np

        x, y, w, h = int(rect['x']), int(rect['y']), int(rect['w']), int(rect['h'])
        if w <= 0 or h <= 0:
            return 0.0
            
        img_np = np.array(pil_image)
        h_img, w_img = img_np.shape[:2]
        
        x0 = max(0, min(x, w_img - 1))
        y0 = max(0, min(y, h_img - 1))
        x1 = max(0, min(x + w, w_img))
        y1 = max(0, min(y + h, h_img))
        
        if x1 <= x0 or y1 <= y0:
            return 0.0
            
        crop = img_np[y0:y1, x0:x1]
        if crop.size == 0:
            return 0.0
            
        try:
            gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            non_zero = cv2.countNonZero(edges)
            density = non_zero / float(crop.size)
            return density
        except Exception as e:
            print(f"[OCR] エッジ密度計算エラー: {e}")
            return 0.0

    def _fix_mtg_misreads(self, text: str) -> str:
        """
        MTG特有のOCR誤読パターンを修正する。
        """
        if not text: return text
        
        # 1. / を 1 と誤認するパターン (+11+1 -> +1/+1)
        text = re.sub(r'\+([1I])\s*([1I])\s*\+([1I])', r'+\1/\1', text)
        text = re.sub(r'\+([1I])\s*/\s*([1I])', r'+\1/\1', text) # 空白除去
        # 単純な 11+1 や +11+1 の修正
        text = text.replace("+11+1", "+1/+1").replace("+11+2", "+1/+2").replace("+21+2", "+2/+2")
        
        # 2. カタカナの「ト」と「卜」(ぼく)の誤認
        text = text.replace("卜ークン", "トークン").replace("アーテイファクト", "アーティファクト")
        
        # 3. ライブラリーの誤読 (ノラリー, ラリー等)
        if "ラリー" in text and "一番下" in text:
            text = text.replace("ノラリー", "ライブラリー").replace("ラリー", "ライブラリー")

        # 4. 句読点のゴミ取り (MTGでは .. や . . はあまり使われない)
        text = re.sub(r'\.{2,}', '.', text)
        
        return text
