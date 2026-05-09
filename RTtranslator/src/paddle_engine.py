"""
paddle_engine.py
PaddleOCR (Serverモデル) をバックグラウンドワーカーとして提供するモジュール。
WinRTOCR の認識精度が低い場合（信頼度しきい値未満）にフォールバックとして呼び出す。
"""

from __future__ import annotations
import threading
from typing import Optional
from PIL import Image


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
                self._initialize()

        with self._lock:
            if self._ocr is None:
                return None

            return self._run_ocr(image, rec=rec)

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
            return f"[OK] PaddleOCR 有効 ({mode}, {self.gpu_mem_mb}MB)"
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
            gpu_id = self.gpu_index if use_gpu else 0

            new_ocr = PaddleOCR(
                use_angle_cls=True,
                lang=self.lang,
                use_gpu=use_gpu,
                gpu_id=gpu_id,
                gpu_mem=self.gpu_mem_mb,
                det_limit_side_len=3000,
                det_limit_type="max",
                det_model_dir=None,
                rec_model_dir=None,
                structure_version="PP-StructureV2",
                enable_mkldnn=not use_gpu,
                cpu_threads=self.cpu_threads if self.cpu_threads > 0 else 10,
                show_log=False,
            )
            
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
        except Exception as e:
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
