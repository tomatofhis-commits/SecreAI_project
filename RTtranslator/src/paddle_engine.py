"""
paddle_engine.py
PaddleOCR (Serverモデル) をバックグラウンドワーカーとして提供するモジュール。
WinRTOCR の認識精度が低い場合（信頼度しきい値未満）にフォールバックとして呼び出す。
"""

from __future__ import annotations
import os
import sys
import threading
from typing import Optional
from PIL import Image
from pathlib import Path

# Python 3.8+ on Windows で cuDNN DLL等の追加DLLを正しくロードできるよう、想定される配置パスを登録
dll_dirs = set()
# paddle_engine.py の2階層上の親 (例: D:\SecreAI_Build)
try:
    src_parent = Path(__file__).resolve().parent.parent.parent
    dll_dirs.add(str(src_parent))
except Exception:
    pass
# sys.executable の配置先 (例: D:\SecreAI_Build)
try:
    exe_dir = Path(sys.executable).parent
    dll_dirs.add(str(exe_dir))
except Exception:
    pass
# カレントディレクトリ
dll_dirs.add(os.getcwd())

for d in dll_dirs:
    if os.path.exists(d):
        # フォルダ内に cudnn*.dll が存在する場合のみ登録を実行
        if any(Path(d).glob("cudnn*.dll")):
            # OSのDLL Directory登録と合わせて、依存DLLの芋づる式ロードを可能にするため PATH 環境変数の先頭に追加
            os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(d)
                except Exception:
                    pass
            print(f"[DLL Path] PATH環境変数とDLL検索パスに cuDNN ディレクトリを追加しました: {d}")


def get_available_gpus() -> list[dict]:
    """
    システムに搭載されている GPU の一覧を返す。
    WMI 経由で取得し、VRAM などの情報も含める。

    Returns:
        [{"index": 0, "name": "NVIDIA GeForce RTX 3080", "vram_mb": 10240}, ...]
        取得失敗時は [{"index": -1, "name": "CPU（GPUなし）", "vram_mb": 0}]
    """
    gpus = []
    try:
        import wmi
        w = wmi.WMI()
        for i, gpu in enumerate(w.Win32_VideoController()):
            name = gpu.Name or f"GPU {i}"
            vram_mb = 0
            try:
                # AdapterRAM は bytes 単位（None の場合あり）
                if gpu.AdapterRAM:
                    vram_mb = int(gpu.AdapterRAM) // (1024 * 1024)
            except Exception:
                pass
            gpus.append({
                "index": i,
                "name": name,
                "vram_mb": vram_mb,
            })
    except Exception as e:
        print(f"[PaddleEngine] GPU 一覧の取得に失敗しました: {e}")

    if not gpus:
        gpus.append({"index": -1, "name": "CPU（GPUなし）", "vram_mb": 0})

    return gpus


class PaddleOCREngine:
    """
    PaddleOCR Serverモデルのラッパー。
    - スレッドセーフ（内部ロックで保護）
    - 遅延初期化（最初の認識要求が来た時点でモデルをロード）
    - GPU インデックスとメモリ上限を受け取る
    """

    def __init__(
        self,
        gpu_index: int = 0,
        gpu_mem_mb: int = 1500,
        lang: str = "japan",
        enabled: bool = True,
        cpu_threads: int = 0,
        use_tensorrt: bool = False,
        use_gpu_preprocess: bool = False,
    ):
        """
        Args:
            gpu_index: 使用するGPUのインデックス（-1 でCPUモード）
            gpu_mem_mb: GPUメモリ使用上限（MB）
            lang: PaddleOCR の言語設定。 "japan", "korean", "chinese_cht" など
            enabled: False の場合は常に None を返す（無効化）
        """
        self.gpu_index = gpu_index
        self.gpu_mem_mb = gpu_mem_mb
        self.lang = lang
        self.enabled = enabled
        self.cpu_threads = cpu_threads
        self.use_tensorrt = use_tensorrt
        self.use_gpu_preprocess = use_gpu_preprocess

        self._ocr = None           # PaddleOCR インスタンス
        self._lock = threading.Lock()
        self._initialized = False
        self._is_loading = False   # 読み込み中フラグ
        self._init_error: Optional[str] = None

    # ------------------------------------------------------------------
    # パブリックAPI
    # ------------------------------------------------------------------

    def preload(self):
        """ワーカー・スレッドなどから呼び出し、初期化を同期的に済ませる"""
        if not self.enabled:
            return
        if not self._initialized:
            self._initialize()

    def recognize(self, image: Image.Image, rec: bool = True) -> Optional[list[dict]]:
        """
        PIL画像を受け取り、認識されたテキストブロックのリストを返す。
        rec=False の場合はテキスト認識を行わず、矩形検出のみを行う。

        Returns:
            [{"text": "...", "rect": {"x":..., "y":..., "w":..., "h":...}, "confidence": 0.95}, ...]
            失敗 / 無効時は None
        """
        if not self.enabled:
            return None

        # 未初期化の場合のハンドリング
        if not self._initialized:
            # UIのフリーズを防ぐため、メインスレッドからの呼び出し時は待たずに None を返す
            if threading.current_thread() == threading.main_thread():
                return None
            else:
                # バックグラウンドスレッド（_ocr_worker等）なら初期化を実行
                try:
                    self._initialize()
                except BaseException as init_err:
                    print(f"[PaddleEngine] 初期化例外による強制CPUフォールバック: {init_err}")
                    self.gpu_index = -1
                    self._ocr = None
                    self._initialized = False
                    try:
                        self._initialize()
                    except BaseException as reinit_err:
                        print(f"[PaddleEngine] フォールバック初期化失敗: {reinit_err}")
                        self._init_error = str(reinit_err)
                        return None

        with self._lock:
            if self._ocr is None:
                return None

            try:
                return self._run_ocr(image, rec=rec)
            except BaseException as run_err:
                print(f"[PaddleEngine] 推論実行時エラー（自動フォールバックを試みます）: {run_err}")
                # GPUモードでエラーになった場合はCPUモードへ強制切り替えして再試行
                if self.gpu_index >= 0:
                    print("[PaddleEngine] GPU推論に失敗したため、CPUモードへ強制フォールバックします。")
                    self.gpu_index = -1
                    self._ocr = None
                    self._initialized = False
                    try:
                        self._initialize()
                        if self._ocr is not None:
                            return self._run_ocr(image, rec=rec)
                    except BaseException as reinit_err:
                        print(f"[PaddleEngine] フォールバック初期化・実行エラー: {reinit_err}")
                        self._init_error = str(reinit_err)
                
                self._init_error = str(run_err)
                return None

    def reinit_with_lang(self, new_lang: str):
        """言語設定を更新し、次回使用時に再初期化を強制する。"""
        with self._lock:
            if self.lang == new_lang and self._ocr is not None:
                return
            
            print(f"[PaddleEngine] 言語変更を検知: {self.lang} -> {new_lang}. 再初期化を準備します。")
            self.lang = new_lang
            self._ocr = None  # 古いモデルを破棄（メモリ解放）
            self._initialized = False
            self._is_loading = False
            self._init_error = None

    def get_status(self) -> str:
        """設定画面などで表示するステータス文字列を返す。"""
        if not self.enabled:
            return "[OFF] PaddleOCR 無効"
        if self._init_error:
            return f"[ERROR] PaddleOCR: {self._init_error}"
        if self._is_loading:
            return "PaddleOCR 初期化中... (バックグラウンド)"
        if self._ocr:
            mode = "GPU" if self.gpu_index >= 0 else "CPU"
            trt_str = " + TensorRT" if self.use_tensorrt else ""
            return f"[OK] PaddleOCR 有効 ({mode}{trt_str}, {self.gpu_mem_mb}MB)"
        return "PaddleOCR 準備完了 (開始時に起動)"

    # ------------------------------------------------------------------
    # 内部実装
    # ------------------------------------------------------------------

    def _initialize(self):
        """PaddleOCR を初期化する。"""
        with self._lock:
            if self._initialized:
                return
            self._is_loading = True
            
        try:
            # 重いインポートとインスタンス生成
            from paddleocr import PaddleOCR

            use_gpu = self.gpu_index >= 0

            # 共通の引数
            ocr_args = {
                "use_angle_cls": True,
                "lang": self.lang,
                "use_gpu": use_gpu,
                "det_limit_side_len": 1280,
                "det_limit_type": "max",
                "det_db_unclip_ratio": 1.6,
                "det_model_dir": None,
                "rec_model_dir": None,
                "structure_version": "PP-StructureV2",
                "show_log": False,
            }

            if use_gpu:
                ocr_args["gpu_id"] = self.gpu_index
                ocr_args["gpu_mem"] = self.gpu_mem_mb
                ocr_args["use_tensorrt"] = self.use_tensorrt if hasattr(self, 'use_tensorrt') else False
                ocr_args["enable_mkldnn"] = False
                ocr_args["cpu_threads"] = self.cpu_threads if self.cpu_threads > 0 else 10
            else:
                ocr_args["enable_mkldnn"] = True
                ocr_args["cpu_threads"] = max(1, min(self.cpu_threads if self.cpu_threads > 0 else 4, 4))
                ocr_args["use_tensorrt"] = False

            try:
                new_ocr = PaddleOCR(**ocr_args)
            except BaseException as gpu_err:
                if use_gpu:
                    print(f"[PaddleEngine] GPU初期化に失敗しました。CPUモードに自動フォールバックします。エラー: {gpu_err}")
                    use_gpu = False
                    ocr_args["use_gpu"] = False
                    ocr_args["enable_mkldnn"] = True
                    ocr_args["cpu_threads"] = max(1, min(self.cpu_threads if self.cpu_threads > 0 else 4, 4))
                    ocr_args.pop("gpu_id", None)
                    ocr_args.pop("gpu_mem", None)
                    ocr_args.pop("use_tensorrt", None)
                    
                    try:
                        new_ocr = PaddleOCR(**ocr_args)
                    except BaseException as cpu_err:
                        raise cpu_err
                else:
                    raise gpu_err
            
            with self._lock:
                self._ocr = new_ocr
                self._initialized = True
                self._init_error = None

            mode = f"GPU:{self.gpu_index}" if use_gpu else "CPU"
            print(f"[PaddleEngine] PaddleOCR 初期化完了 ({mode}, {self.gpu_mem_mb}MB, lang={self.lang})")

        except ImportError:
            with self._lock:
                self._init_error = "paddleocr がインストールされていません"
            print(f"[PaddleEngine] {self._init_error}")
        except BaseException as e:
            with self._lock:
                self._init_error = str(e)
                self._ocr = None
            print(f"[PaddleEngine] 初期化エラー: {e}")
        finally:
            with self._lock:
                self._is_loading = False

    def _run_ocr(self, image: Image.Image, rec: bool = True) -> Optional[list[dict]]:
        """実際の認識処理を行い、正規化された結果リストを返す。"""
        try:
            import numpy as np
            
            # GPU 前処理の適用
            if self.use_gpu_preprocess:
                try:
                    import cupy as cp
                    # PIL -> Numpy -> Cupy
                    img_np = np.array(image.convert("RGB"))
                    gpu_img = cp.asarray(img_np)
                    
                    # 1. グレースケール化 (GPU)
                    gray_gpu = (0.299 * gpu_img[:,:,0] + 0.587 * gpu_img[:,:,1] + 0.114 * gpu_img[:,:,2]).astype(cp.uint8)
                    
                    # 2. コントラスト強調 (Linear Stretch)
                    min_val = cp.min(gray_gpu)
                    max_val = cp.max(gray_gpu)
                    if max_val > min_val:
                        gray_gpu = ((gray_gpu - min_val) * (255.0 / (max_val - min_val))).astype(cp.uint8)
                    
                    # 3. PaddleOCR用にRGB(3ch)に戻してホストメモリへ
                    img_array = cp.asnumpy(cp.stack([gray_gpu]*3, axis=-1))
                except Exception as e:
                    print(f"[PaddleEngine] GPU 前処理失敗: {e}")
                    img_array = np.array(image.convert("RGB"))
            else:
                img_array = np.array(image.convert("RGB"))

            # rec=False の場合は検出のみ。rec=True(デフォルト)は認識まで行う。
            result = self._ocr.ocr(img_array, cls=True, rec=rec)

            if not result or not result[0]:
                return []

            blocks = []
            for line in result[0]:
                if not line:
                    continue

                if rec:
                    # 認識あり: [ [[x1,y1],...], ("text", confidence) ]
                    if len(line) < 2: continue
                    box, (text, confidence) = line[0], line[1]
                else:
                    # 認識なし: [ [[x1,y1],...] ]
                    box = line
                    text = ""
                    confidence = 1.0  # 検出された時点で1.0とする（後のフィルタ用）

                # box は4点の座標 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                xs = [pt[0] for pt in box]
                ys = [pt[1] for pt in box]
                x = int(min(xs))
                y = int(min(ys))
                w = int(max(xs)) - x
                h = int(max(ys)) - y

                if w <= 0 or h < 6:
                    continue

                blocks.append({
                    "text": text.strip(),
                    "rect": {"x": x, "y": y, "w": w, "h": h},
                    "confidence": float(confidence),
                })

            return blocks

        except Exception as e:
            print(f"[PaddleEngine] 認識エラー: {e}")
            return None
