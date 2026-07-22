"""
Real Time Translate - メインエントリーポイント
Ollama (TranslateGemma) を使ってゲーム画面のテキストをリアルタイムに翻訳する
"""

import sys
import os
from PIL import Image, ImageDraw

# --- デバッグログ出力設定 ---
# 配布用に不要なディスク書き込みおよびログの肥大化を防ぐため、
# debug_rtt.log への stdout/stderr のリダイレクト設定は無効化されました。
#
# try:
#     app_data_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "SecreAI")
#     os.makedirs(app_data_dir, exist_ok=True)
#     log_file_path = os.path.join(app_data_dir, "debug_rtt.log")
#     
#     class Logger(object):
#         def __init__(self):
#             self.terminal = sys.stdout
#             # 追記モードで開き、ログ出力をバッファリングせず即時書き出します
#             self.log = open(log_file_path, "a", encoding="utf-8", buffering=1)
# 
#         def write(self, message):
#             self.terminal.write(message)
#             try:
#                 self.log.write(message)
#             except:
#                 pass
# 
#         def flush(self):
#             self.terminal.flush()
#             try:
#                 self.log.flush()
#             except:
#                 pass
# 
#     sys.stdout = Logger()
#     sys.stderr = sys.stdout
#     print("[RTtranslator] stdout/stderr を debug_rtt.log にリダイレクトしました。")
# except Exception as log_e:
#     print(f"[Logging Setup Error] {log_e}")


import psutil

import time
import json
import re
import traceback
import queue
import hashlib
import threading
from pathlib import Path
from difflib import SequenceMatcher
from collections import OrderedDict
import numpy as np
import cv2
from rapidfuzz import distance, fuzz

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QComboBox, QPushButton, QMessageBox, QCheckBox, QSpinBox, QGroupBox, QSlider
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont
from flask import Flask, jsonify, request

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)


from src.capture import capture_window, list_windows, get_client_rect_on_screen
from src.ocr import OCREngine
from src.translator import Translator
from src.ui import TranslationOverlay
from src.paddle_engine import PaddleOCREngine, get_available_gpus
from src.lang_check import get_model_status as lang_check_status, detect_source_language, is_valid_translation as _ft_validate_translation
from src.word_filter import should_discard as _word_filter_discard

def calculate_iou(r1, r2):
    x_left = max(r1['x'], r2['x'])
    y_top = max(r1['y'], r2['y'])
    x_right = min(r1['x'] + r1['w'], r2['x'] + r2['w'])
    y_bottom = min(r1['y'] + r1['h'], r2['y'] + r2['h'])

    if x_right < x_left or y_bottom < y_top:
        return 0.0

    intersection_area = (x_right - x_left) * (y_bottom - y_top)
    iou = intersection_area / float(max(1, r1['w'] * r1['h'] + r2['w'] * r2['h'] - intersection_area))
    return iou


def normalize_text(text):
    """
    比較用にテキストを正規化する。
    記号の除去、空白の集約、Unicode正規化、小文字化を行う。
    """
    import unicodedata
    if not text: return ""
    # Unicode正規化 (NFKC: 全角/半角、アクセント表現の統一)
    text = unicodedata.normalize('NFKC', text)
    # 小文字化
    text = text.lower()
    # 記号の置換（文脈に影響しにくい記号やOCRノイズになりやすい記号をスペースへ）
    text = re.sub(r'[•\*_\-\|\\#@$.,:;!\?\'\"`\^~～]', ' ', text)
    # 改行と余計な空白の整理
    text = " ".join(text.split())
    return text.strip()


def is_time_sensitive(text):
    """
    時間、カウントダウン、数値主体のテキストかどうかを判定する。
    """
    if not text: return False
    
    # 時間単位のパターン (OCR誤読対応: hou, miu, milt 等)
    time_units = r'(h|m|s|d|hr|min|sec|day|hour|hou|miu|milt|hours|minutes|seconds|days)'
    # 12h 25m や 12 hours 25 minutes など
    pattern = rf'\b\d+\s*{time_units}\b'
    # 12:34:56 などの形式
    hms_pattern = r'\b\d+[:：]\d+([:：]\d+)?\b'
    
    if re.search(pattern, text, re.IGNORECASE) or re.search(hms_pattern, text):
        return True
        
    # 数値比率チェック (数字と特定の記号が文字数の6割を超えたら時間/ID情報とみなす)
    clean_text = text.replace(" ", "")
    if not clean_text: return False
    
    num_chars = sum(c.isdigit() or c in ':/.-' for c in clean_text)
    if (num_chars / len(clean_text)) > 0.6:
        # print(f"[Discard:TimeSensitive] {text}") # デバッグ用に残す
        return True
        
def _score_ocr_text(text: str) -> float:
    """OCR結果の『もっともらしさ』をスコア化する。"""
    if not text: return 0.0
    score = 0.0
    # CJK文字が含まれれば加点
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7a3]", text):
        score += 1.0
    # 英単語として成立していれば加点
    words = text.split()
    if words and len(words) >= 2:
        score += 0.5
    # 文字種の多様性
    unique_chars = len(set(text))
    score += min(1.0, unique_chars / 10.0)
    return score


def cleanup_translation(translated_text, target_lang_code, source_text=""):
    """
    AIの回答に含まれる余計な前置き、言語ラベル、原文の繰り返しを除去する。
    """
    import re
    if not translated_text: return ""
    
    # ターゲット言語のラベル候補
    target_labels = ["日本語", "Japanese", "Translation", "翻訳", "結果", "Target"]
    # 除外したいラベル候補（ソース言語や説明など）
    exclude_labels = ["Source", "Original", "Text", "原文", "説明", "イタリア語", "Italian", "英語", "English", "フランス語", "French"]
    
    lines = translated_text.split('\n')
    cleaned_lines = []
    found_target_content = []
    
    for line in lines:
        line_strip = line.strip()
        if not line_strip: continue
        
        # --- 会話的な前置きやメタな発言の徹底排除 ---
        # プロンプトの指示文漏洩（「重要：出力は ONLY...」など）を削除
        if "重要：" in line_strip or "Important:" in line_strip:
            continue
            
        # 「はい、翻訳します」「以下に案を示します」等を削る
        line_strip = re.sub(r'^(はい、|もちろん、|承知いたしました[。、]|承知しました[。、]|以下に|翻訳[結果案は]*[：\s]*)', '', line_strip)
        line_strip = re.sub(r'(翻訳案\d*|を提示します[。、]|を示します[。、]|です[。、]|参照してください[。、])$', '', line_strip)
        line_strip = line_strip.strip()
        
        # 不要な記号（マークダウンの強調など）を削る
        line_strip = re.sub(r'^\*+\s*', '', line_strip)
        line_strip = re.sub(r'\s*\*+$', '', line_strip)
        
        if not line_strip or line_strip in ["翻訳", "結果", "案", "案1", "案2"]:
            continue
            
        # "Label: Content" 形式のチェック
        match = re.match(r'^([^:：]+)[:：]\s*(.*)$', line_strip)
        if match:
            label = match.group(1).strip()
            content = match.group(2).strip()
            if any(kw in label for kw in target_labels):
                if content: found_target_content.append(content)
                continue
            if any(kw in label for kw in exclude_labels):
                continue
        
        if source_text and line_strip == source_text.strip():
            continue
            
        cleaned_lines.append(line_strip)

    if found_target_content:
        result = "\n".join(found_target_content).strip()
    else:
        result = "\n".join(cleaned_lines).strip()
    
    if not result:
        result = translated_text.strip()
    
    # --- マークダウン記号（**）の除去 ---
    # LLMが "**クラス**" や "** クラス" のようなマークダウン記法で返すことがある
    result = re.sub(r'\*\*([^*]*)\*\*', r'\1', result)   # **text** → text
    result = re.sub(r'^\*+\s*', '', result, flags=re.MULTILINE)  # 行頭の * 除去
    result = re.sub(r'\s*\*+$', '', result, flags=re.MULTILINE)  # 行末の * 除去
    result = "\n".join(line for line in result.splitlines() if line.strip())  # 空行除去
    return result.strip() if result.strip() else translated_text.strip()



# 選択可能なWinRT OCR言語の全リスト
ALL_OCR_LANGUAGES = [
    ("英語 (en-US)",       "en-US"),
    ("日本語 (ja-JP)",     "ja-JP"),
    ("ロシア語 (ru-RU)",   "ru-RU"),
    ("韓国語 (ko-KR)",     "ko-KR"),
    ("中国語 (zh-Hans)",   "zh-Hans"),
]

DEFAULT_CONFIG = {
    "target_window_title": "",
    "target_language": "ja",
    "source_language": "auto",
    "ollama_model": "translategemma:4b",
    "ollama_url": "http://localhost:11434/v1",
    "ocr_engine_mode": "hybrid",
    "ocr_languages": ["en-US", "ja-JP", "ru-RU", "ko-KR", "zh-Hans"],
    "paddle_language": "japan",
    "paddle_gpu_index": 0,
    "paddle_gpu_mem_mb": 1024,
    "paddle_threshold": 0.90,
    "capture_interval_sec": 1.0,
    "ocr_skip_sensitivity": 2400,
    "ocr_thread_limit_percent": 100,
    "font_size": 16,
    "overlay_opacity": 0.85,
    "overlay_background_color": "#1a1a2e",
    "overlay_text_color": "#e0e0e0",
    "use_vision_translation": False,
    "eco_mode": False,
    "single_mode": False,
    "capture_mode": "wgc",
    "use_tensorrt": False,
    "use_gpu_preprocess": False,
    "use_csharp_overlay": True
}

def load_config(config_path: str = "config.json") -> dict:
    """設定ファイルを読み込む。存在しない場合はデフォルト値を返す。"""
    path = Path(config_path)
    if not path.exists():
        # 初回起動時はデフォルト設定を保存しておく
        save_config(DEFAULT_CONFIG, config_path)
        return DEFAULT_CONFIG.copy()
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
            # 既存の設定ファイルに足りないキーがあればデフォルト値で補完する
            merged_config = DEFAULT_CONFIG.copy()
            merged_config.update(config)
            return merged_config
    except Exception as e:
        print(f"Error loading config: {e}")
        return DEFAULT_CONFIG.copy()

def save_config(config: dict, config_path: str = "config.json"):
    """設定ファイルを保存する。"""
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

def _score_ocr_text(t: str) -> float:
    """
    OCRテキストが「自然な文章」としてどれだけ優れているかをスコア化する。
    フリッカー防止の品質比較に使用する。
    高いスコア = 意味のある文字が多い、配分行数が少ない。
    """
    t_clean = t.replace(' ', '').replace('\n', '')
    if not t_clean:
        return 0.0
    score = len(t_clean) * 0.1
    cjk = len(re.findall(r'[ぁ-んァ-ヶ一-龥]', t))
    alnum = len(re.findall(r'[a-zA-Z0-9]', t))
    valid_chars = cjk + alnum
    score += (valid_chars / len(t_clean)) * 5.0
    lines = [l for l in t.split('\n') if l.strip()]
    if len(lines) > 0:
        avg_line_len = len(t_clean) / len(lines)
        if avg_line_len < 4:
            score -= 2.0
    return score

class TranslationController:
    """
    キャプチャ → OCR → 翻訳 → UI表示 のサイクルを管理するコントローラー。
    """
    def __init__(self, config: dict):
        self.config = config
        
        # --- SecreAI本体の data/config.json から設定をフォールバックロード ---
        try:
            import json, os
            # RTtranslator/main.py の親の親が SecreAI ルート
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            secre_config_path = os.path.join(base_dir, "data", "config.json")
            if not os.path.exists(secre_config_path):
                # 旧パスフォールバック
                secre_config_path = os.path.join(base_dir, "config", "config.json")
            
            if os.path.exists(secre_config_path):
                with open(secre_config_path, "r", encoding="utf-8") as f:
                    s_cfg = json.load(f)
                
                # local_llm_provider / LOCAL_LLM_PROVIDER のマージ
                if "local_llm_provider" not in config:
                    prov = s_cfg.get("LOCAL_LLM_PROVIDER", s_cfg.get("local_llm_provider", "ollama")).lower()
                    config["local_llm_provider"] = prov
                
                # ollama_url (LM Studio または Ollama の適切なURLを選択)
                if "ollama_url" not in config or "localhost:11434" in config.get("ollama_url", ""):
                    prov = config.get("local_llm_provider", "ollama").lower()
                    if prov == "lmstudio":
                        url = s_cfg.get("LMSTUDIO_URL", "http://localhost:1234/v1")
                    else:
                        url = s_cfg.get("OLLAMA_URL", "http://localhost:11434/v1")
                    config["ollama_url"] = url
                    
                # ollama_model (LM Studio または Ollama の適切なモデル)
                if "ollama_model" not in config or config.get("ollama_model") == "translategemma:4b":
                    prov = config.get("local_llm_provider", "ollama").lower()
                    if prov == "lmstudio":
                        # LM Studio用のモデル名 (settings_ui.py 保存値またはキャッシュ)
                        model = s_cfg.get("rtt_ollama_model", s_cfg.get("MODEL_ID_LOCAL", "meta-llama-3-8b-instruct"))
                        config["ollama_model"] = model
                    else:
                        model = s_cfg.get("rtt_ollama_model", "translategemma:4b")
                        config["ollama_model"] = model
        except Exception as e:
            print(f"[RTtranslator Warning] Failed to merge main config.json: {e}")

        # --- [最優先] CPUリミットとアフィニティの適用 ---
        # 他の重いエンジンのロードが始まる前に制限をかける
        self.apply_cpu_limit()

        self.window_title = config.get("target_window_title", "")
        self.is_running = False
        
        # 辞書の先行ロード (OCRエンジンの初期化テスト等で走る前に完了させる)
        from src.word_filter import is_known_word as _wf_init
        _wf_init("--- INIT ---")

        # キャッシュマネージャーの設定
        self.cache_path = Path("translation_cache.json")
        self.translation_cache = OrderedDict()
        self._last_cache_save = time.time()
        self._cache_dirty = False
        
        # ステータス表示の統合用
        self._last_analysis_status = "👀 監視中"
        self._shadow_skip_cache = {}  # {chunk_id: expiry_time}
        # OCRワーカーに渡す画像キュー（サイズ1で、常に最新フレームだけ処理）
        self._ocr_input_queue: queue.Queue = queue.Queue(maxsize=1)
        # OCR結果をメインスレッドに返すキュー
        self._ocr_output_queue: queue.Queue = queue.Queue(maxsize=5)
        self._position_queue: queue.Queue = queue.Queue()
        # OCRワーカーが現在処理中かどうかのフラグ
        self._ocr_busy: bool = False
        self._current_frame_id = 0
        self._current_captured_by = "なし"
        self._last_clear_id = 0
        self._single_run_done = False
        self._single_run_done_candidate = False
        self._single_scan_backlog = []
        self._prev_frame_hash = 0
        self._prev_thumb_arr = None
        self._prev_gray = None
        self._prev_edge_count = 0
        self._last_ocr_exec_time = 0.0
        self._last_force_ocr_time = 0.0
        self._stop_event = threading.Event()
        self._skip_counter = 0
        
        # 案A+案B 用の履歴保持
        self._prev_east_boxes: list = []
        self._prev_east_scores: list = []
        self._prev_paddle_boxes: list = []
        self._prev_paddle_scores: list = []
        self._last_raw_chunks: list = []  # スキップ時に流用する前回のOCR結果
        
        # デバッグ統計用カウンター
        self._stats_skip_count: int = 0
        self._stats_total_count: int = 0
        self._stats_last_time: float = time.time()
        
        self._last_winocr_time: float = time.time()  # 動的しきい値用
        
        # OCRワーカースレッドの準備 (起動は初期化の最後)
        self._ocr_thread = threading.Thread(target=self._ocr_worker, daemon=True)
        
        # テンポラルトラッキング用（前回のチャンク状態）
        self.history_chunks = {}
        self._history_grid = {}  # 空間バケット: (gx, gy) -> [cid, ...]

        # OCRエンジン初期化（PaddleOCRハイブリッド対応）
        ocr_langs = config.get("ocr_languages", ["en-US", "ja-JP", "ru-RU", "ko-KR", "zh-Hans"])

        ocr_mode = config.get("ocr_engine_mode", "hybrid")
        paddle_enabled = (ocr_mode != "winrt_only")
        paddle_gpu_index = config.get("paddle_gpu_index", 0)
        paddle_gpu_mem = config.get("paddle_gpu_mem_mb", 1500)
        paddle_threshold = config.get("paddle_threshold", 0.90)
        target_lang_code = config.get("target_language", "ja")
        use_tensorrt = config.get("use_tensorrt", False)
        use_gpu_preprocess = config.get("use_gpu_preprocess", False)

        # PaddleOCRの言語モデルは全言語同時読み込みができないため、
        # 日本語と英語を両方高精度に読める 'japan' をデフォルトとする。
        # 翻訳先（target_language）に依存させるべきではない。
        paddle_lang = config.get("paddle_language", "japan")

        # --- CPUコア制限の算出 ---
        def resolve_limit(cfg):
            cpu_c = os.cpu_count() or 1
            # 1. cpu_threads (コア数 or 割合)
            val = cfg.get("cpu_threads", 0)
            if val > 0:
                if val <= 1.0: # 0.5 などの割合
                    return max(1, int(cpu_c * val))
                elif val > cpu_c: # コア数を超える数値はパーセント(1-100)とみなす
                    return max(1, int(cpu_c * (val / 100.0)))
                else: # 1以上の整数でコア数以下ならそのままコア数
                    return int(val)
            
            # 2. ocr_thread_limit_percent (パーセント 1-100)
            pct = cfg.get("ocr_thread_limit_percent", 100)
            return max(1, int(cpu_c * (pct / 100.0)))

        limit_count = resolve_limit(config)

        paddle_engine = PaddleOCREngine(
            gpu_index=paddle_gpu_index,
            gpu_mem_mb=paddle_gpu_mem,
            lang=paddle_lang,
            enabled=paddle_enabled,
            cpu_threads=limit_count, # Paddle側にも明示的に制限を伝える
            use_tensorrt=use_tensorrt,
            use_gpu_preprocess=use_gpu_preprocess,
        ) if paddle_enabled else None

        self.ocr = OCREngine(
            langs=ocr_langs,
            paddle_engine=paddle_engine,
            paddle_threshold=paddle_threshold,
            ocr_mode=ocr_mode
        )

        # 翻訳エンジン初期化
        self.translator = Translator(
            model=config.get("ollama_model", "translategemma:4b"),
            ollama_url=config.get("ollama_url", "http://localhost:11434"),
            target_lang=config.get("target_language", "ja"),
            source_lang=config.get("source_language", "auto"),
            local_llm_provider=config.get("local_llm_provider", "ollama"),
        )

        # UI初期化 (まだ表示しない)
        self.overlay = TranslationOverlay(
            font_size=config.get("font_size", 16),
            opacity=config.get("overlay_opacity", 0.85),
            bg_color=config.get("overlay_background_color", "#1a1a2e"),
            text_color=config.get("overlay_text_color", "#e0e0e0"),
            use_csharp=config.get("use_csharp_overlay", True),
        )
        self.overlay.font_size_calculated.connect(self._on_font_size_calculated)
        
        # 状態管理：翻訳完了、または翻訳依頼中のチャンクID
        self.active_translations = {}
        self.pending_texts = set()
        self.last_request_time = 0.0      # 全体の最終送信時刻
        self.last_short_word_time = 0.0   # 短文の最終送信時刻
        self._last_ocr_exec_time = 0.0    # エコモード用の最終OCR時刻
        self._single_run_done = False     # シングルモード：実行済みフラグ
        
        # OBSブラウザオーバーレイ用の状態保持
        self.overlay_state = {}
        self.window_rect_data = {"x": 0, "y": 0, "w": 0, "h": 0}

        self._last_analysis_status = "監視中"
        self._last_force_ocr_time = 0.0
        self._current_frame_id = 0
        
        # スレッド安全のためのロック（再入可能なRLockを使用）
        self._lock = threading.RLock()
        
        # 枠の存在確認・追従タイマー（約6FPSでメインループを駆動）
        self.timer = QTimer()
        self.timer.timeout.connect(self._on_tick)
        self.timer.setInterval(166) 
        
        # 解析結果ポーリング用タイマー（100ms間隔）
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll_ocr_result)
        
        # 起動時にキャッシュの白紙化を確実に行う
        self._load_cache()
        
        # すべてのエンジンの準備が整ってからスレッドを開始する
        self._ocr_thread.start()

    def apply_cpu_limit(self):
        """OSレベルでのCPUコア制限（Affinity）を現在の設定に基づいて適用する"""
        try:
            cpu_count = os.cpu_count() or 1
            
            # 強化された判定ロジック
            val = self.config.get("cpu_threads", 0)
            if val > 0:
                if val <= 1.0:
                    limit_count = max(1, int(cpu_count * val))
                elif val > cpu_count:
                    limit_count = max(1, int(cpu_count * (val / 100.0)))
                else:
                    limit_count = int(val)
            else:
                pct = self.config.get("ocr_thread_limit_percent", 100)
                limit_count = max(1, int(cpu_count * (pct / 100.0)))
            
            limit_count = min(limit_count, cpu_count)
            p = psutil.Process(os.getpid())
            
            # コア割り当て制限
            p.cpu_affinity(list(range(limit_count)))
            
            # OpenCV のスレッド制限
            import cv2
            cv2.setNumThreads(limit_count)
            
            print(f"[CPU Limit] 使用コア数を {limit_count} / {cpu_count} に制限しました。")
        except Exception as e:
            print(f"[CPU Limit Error] {e}")

    def start(self):
        """翻訳ループを開始する。"""
        if self.is_running:
            return
            
        with self._lock:
            # 翻訳開始時にキャッシュの整理を実行
            self._auto_clean_cache()
            
            self.is_running = True
            self.force_retranslate() # 開始時にキャッシュとUIを完全クリア
            self.overlay.set_status("🔍 Ollamaに接続中...")
            self.overlay.show()
            
            if self.translator.test_connection():
                self.overlay.set_status(f"✅ 接続OK | 対象: {self.window_title}")
            else:
                self.overlay.set_status("⚠️ Ollamaに接続できません")

            self.timer.start()

    def stop(self):
        """翻訳ループを停止する。"""
        if not self.is_running:
            return
        
        with self._lock:
            self.is_running = False
            self.force_retranslate() # 停止時に画面とキャッシュを完全クリア
            # self.timer.stop() # UIスレッド以外から呼ぶと落ちるため _on_tick 内で止めるように変更
        # self.poll_timer.stop()
        # self.cache_save_timer.stop()

        # 停止時に状態をリセット（Webオーバーレイを空白にする）
        self.overlay_state.clear()
        self.active_translations.clear()
        self.pending_texts.clear()
        self.window_rect_data = {"x": 0, "y": 0, "w": 0, "h": 0}
        self.overlay.sync_active_ids(set())
        
        # 停止時にキャッシュを保存
        if self._cache_dirty:
            self._save_cache()
            self._cache_dirty = False
        self.overlay.hide()

    def update_target_window(self, new_title: str):
        """ターゲットウィンドウを更新する。"""
        self.window_title = new_title

    def update_config(self, new_config: dict):
        """翻訳開始直前に最新の設定（翻訳先言語など）を反映する"""
        with self._lock:
            old_val = self.config.get("cpu_threads", 0)
            old_pct = self.config.get("ocr_thread_limit_percent", 100)
            
            self.config = new_config
            self.window_title = new_config.get("target_window_title", "")
            self.translator.target_lang = new_config.get("target_language", "ja")
            
            # PaddleOCR設定の更新
            new_ocr_mode = new_config.get("ocr_engine_mode", "hybrid")
            new_p_lang = new_config.get("paddle_language", "japan")
            
            # エンジンの再初期化が必要かチェック
            needs_reinit = False
            if self.ocr.ocr_mode != new_ocr_mode:
                needs_reinit = True
            
            if self.ocr.paddle_engine:
                if self.ocr.paddle_engine.lang != new_p_lang:
                    needs_reinit = True
            
            if needs_reinit:
                print(f"[Update] OCR設定変更を検知: Mode={new_ocr_mode}, Lang={new_p_lang}")
                self.ocr.ocr_mode = new_ocr_mode
                if self.ocr.paddle_engine:
                    # 既存エンジンの設定更新（言語が変わる場合は内部で再ロードされるようにする）
                    self.ocr.paddle_engine.enabled = (new_ocr_mode != "winrt_only")
                    if self.ocr.paddle_engine.lang != new_p_lang:
                        self.ocr.paddle_engine.reinit_with_lang(new_p_lang)
            
            if self.ocr.paddle_engine:
                self.ocr.paddle_engine.use_tensorrt = new_config.get("use_tensorrt", False)
                self.ocr.paddle_engine.use_gpu_preprocess = new_config.get("use_gpu_preprocess", False)
            
            # モデルとURLを更新
            new_model = new_config.get("ollama_model", "translategemma:4b")
            new_url = new_config.get("ollama_url", "http://localhost:11434")
            new_provider = new_config.get("local_llm_provider", "ollama")
            
            self.translator.local_llm_provider = new_provider
            
            if self.translator.model != new_model:
                self.translator.model = new_model
            
            # WinRT OCR 言語設定の動的反映（設定画面のチェック切り替えを反映！）
            new_ocr_langs = new_config.get("ocr_languages", [])
            if new_ocr_langs and hasattr(self, 'ocr'):
                validated_langs = []
                for lang in new_ocr_langs:
                    if lang in self.ocr.available_langs:
                        validated_langs.append(lang)
                    else:
                        try:
                            import winocr
                            dummy_img = Image.new('RGB', (10, 10))
                            winocr.recognize_pil_sync(dummy_img, lang=lang)
                            validated_langs.append(lang)
                        except:
                            pass
                if validated_langs:
                    self.ocr.available_langs = validated_langs
                    print(f"[Update] WinRT OCR 言語設定を更新しました: {self.ocr.available_langs}")
            
            if hasattr(self.translator, "ollama_url"):
                # 末尾の / を除いて更新
                self.translator.ollama_url = new_url.rstrip("/")
            if hasattr(self.translator, "local_llm_provider"):
                self.translator.local_llm_provider = self.config.get("local_llm_provider", "ollama").lower()
            
            # CPU制限を再適用（設定値に変更がある場合のみ）
            new_val = self.config.get("cpu_threads", 0)
            new_pct = self.config.get("ocr_thread_limit_percent", 100)
            if new_val != old_val or new_pct != old_pct:
                self.apply_cpu_limit()
            
            print(f"[RTtranslator] 設定を更新しました: Model={self.translator.model}, CPU_Limit={self.config.get('ocr_thread_limit_percent')}%")

    def _purge_cid(self, cid: str):
        """
        1つのIDに関するすべてのメモリ（UI・状態・履歴・空間バケット）を完全に削除する。
        ゴースト防止のための統一パージ関数。
        """
        # 1. UIラベルを削除（PyQt ラベルと C# overlays の両方を確実に消す）
        if hasattr(self.overlay, 'active_labels') and cid in self.overlay.active_labels:
            label = self.overlay.active_labels[cid]
            if hasattr(label, 'deleteLater'):
                label.deleteLater()
            del self.overlay.active_labels[cid]
        # C#モード時: csharp_overlays からも確実に削除しないとゴーストが残り続ける
        if hasattr(self.overlay, 'csharp_overlays') and cid in self.overlay.csharp_overlays:
            del self.overlay.csharp_overlays[cid]
        if hasattr(self.overlay, 'use_csharp') and self.overlay.use_csharp:
            if hasattr(self.overlay, '_push_csharp_update'):
                self.overlay._push_csharp_update()
        
        # 2. 各状態辞書から削除
        self.overlay_state.pop(cid, None)
        self.active_translations.pop(cid, None)
        self.history_chunks.pop(cid, None)
        
        # 3. 空間バケット (_history_grid) から該当CIDを除去
        for key, cids in list(self._history_grid.items()):
            if cid in cids:
                cids.remove(cid)
                if not cids:
                    del self._history_grid[key]
                break
        
        # 4. スキップ用バッファからも削除
        if hasattr(self, '_last_raw_chunks') and self._last_raw_chunks:
            self._last_raw_chunks = [c for c in self._last_raw_chunks if c.get('id') != cid]

    def force_retranslate(self):
        """現在画面上の表示と追跡状態をリセットし、再スキャンを強制する（翻訳済みキャッシュは保持する）"""
        print("[Controller] force_retranslate called: Resetting UI and tracking states.")
        
        # 1. UIと状態の完全クリア
        self.overlay.clear_labels()
        self.overlay_state.clear()
        self.active_translations.clear()
        self.history_chunks.clear()
        self._history_grid.clear()
        self.pending_texts.clear()
        if hasattr(self, 'translator') and self.translator:
            self.translator.clear_queue()
        self._shadow_skip_cache.clear()
        
        # 3. OCR強制再開フラグと「古い結果」の破棄
        with self._lock:
            # IDを大きく進めて、現在キューにある、または解析中のパケットをすべて「過去のもの」として無効化する
            self._current_frame_id += 10 
            self._last_clear_id = self._current_frame_id
            self._last_force_ocr_time = 0.0
            self._last_ocr_exec_time = 0.0
            self._single_run_done = False
            self._single_run_done_candidate = False
            self._single_scan_backlog = [] # シングルモード用の未送信キュー
            self._cache_dirty = True
            
            # 【重要】画像比較・スキップ判定用の基準値をすべてリセット
            self._last_ocr_image_hash = None
            self._prev_gray = None # 次のフレームで再取得させるために None にする
            self._prev_edge_count = 0
            self._last_raw_chunks = [] # 前回のOCR結果をクリア
            
            # 4. 未処理のキューを空にする (古い結果の混入を物理的に防ぐ)
            while not self._ocr_output_queue.empty():
                try: self._ocr_output_queue.get_nowait()
                except: break
        
        # Webオーバーレイ等へ空の状態を通知
        self.overlay.sync_active_ids(set())

        
    def _load_cache(self):
        """
        起動時にキャッシュを白紙化する。
        立ち上げ直し時はゲーム内容や状況が変更されている可能性があるため、
        常にクリーンな状態からスタートする。
        """
        from collections import OrderedDict
        self.translation_cache = OrderedDict()
        
        # ファイルも即座に白紙化（空の状態で保存）
        self._save_cache()
        print("[Cache] 起動時にキャッシュを白紙化しました（クリーンスタート）")

    def _auto_clean_cache(self):
        """起動時にキャッシュを最新フィルター基準で自動浄化する。"""
        if not self.translation_cache:
            return

        removed = 0
        reset_ignore = 0
        fuzzy_removed = 0
        # プロンプト漏洩のシグネチャ
        _LEAKAGE_SIGNALS = ["重要：", "Important:", "出力は ONLY", "ONLY 翻訳", "翻訳案1", "翻訳案2"]

        keys_to_delete = []
        keys_to_reset = []
        
        # Fuzzy match重複チェック用
        from difflib import SequenceMatcher
        norm_keys = {}

        for k, v in list(self.translation_cache.items()):
            if "::" not in k:
                continue
            text_part = k.split("::", 1)[1]

            # 【クリーン条件1】word_filter でゴミ原文と判定されるエントリーを削除
            # （プレイヤー名・UIゴミ等が過去に記録されてしまったもの）
            if _word_filter_discard(text_part):
                keys_to_delete.append(k)
                continue

            # 【クリーン条件2】翻訳結果にプロンプト漏洩が含まれるエントリーを削除
            # （「重要：出力は ONLY...」等が混入したもの）
            if isinstance(v, str) and v not in ("__IGNORE__", "__IGNORE_1__", "__IGNORE_2__"):
                if any(sig in v for sig in _LEAKAGE_SIGNALS):
                    keys_to_delete.append(k)
                    continue

            # 【クリーン条件3】一時IGNOREステータス(__IGNORE_1__, __IGNORE_2__)をリセット
            if v in ("__IGNORE_1__", "__IGNORE_2__"):
                keys_to_reset.append(k)
                
            # 【クリーン条件4】Fuzzy matchによる重複削除 (類似度85%以上)
            # 同じ言語設定の中で、過去に登録された類似テキストがあれば、後から見つかった方を消す
            norm = text_part.lower().replace(" ", "").replace("\n", "")
            if len(norm) > 2:
                lang_prefix = k.split("::", 1)[0]
                found_duplicate = False
                for nk, orig_k in norm_keys.items():
                    if orig_k.split("::", 1)[0] != lang_prefix:
                        continue
                    if 0.5 <= len(norm)/max(len(nk),1) <= 2.0:
                        if SequenceMatcher(None, norm, nk).ratio() >= 0.85:
                            found_duplicate = True
                            break
                if found_duplicate:
                    keys_to_delete.append(k)
                    fuzzy_removed += 1
                else:
                    norm_keys[norm] = k

        for k in keys_to_delete:
            if k in self.translation_cache:
                del self.translation_cache[k]
                removed += 1

        for k in keys_to_reset:
            if k in self.translation_cache:
                # word_filterで通過するものだけリセット（ゴミはそのままにしない）
                text_part = k.split("::", 1)[1]
                if not _word_filter_discard(text_part):
                    del self.translation_cache[k]
                    reset_ignore += 1

        if removed > 0 or reset_ignore > 0:
            print(f"[Cache] 起動時オートクリーン完了: 削除={removed}件 (うち重複整理={fuzzy_removed}件), IGNOREリセット={reset_ignore}件")
            self._cache_dirty = True  # 次の定期保存でファイルに反映


    def _save_cache(self):
        """現在の翻訳メモリをjsonに保存する"""
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.translation_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Cache save error: {e}")

    def _calc_iou(self, r1: dict, r2: dict) -> float:
        """2つの矩形のIoU（重複面積率）を返す。"""
        x_l = max(r1['x'], r2['x'])
        y_t = max(r1['y'], r2['y'])
        x_r = min(r1['x'] + r1['w'], r2['x'] + r2['w'])
        y_b = min(r1['y'] + r1['h'], r2['y'] + r2['h'])
        if x_r < x_l or y_b < y_t:
            return 0.0
        i_a = (x_r - x_l) * (y_b - y_t)
        union = float(max(1, r1['w'] * r1['h'] + r2['w'] * r2['h'] - i_a))
        return i_a / union

    def _check_skip_ocr(self, image) -> bool:
        """エッジ密度によるスキップ判定。"""
        try:
            if not hasattr(self.ocr, 'paddle_engine') or not self.ocr.paddle_engine:
                return False
            
            # PaddleOCRで枠のみ取得 (GPU活用・高速)
            blocks = self.ocr.paddle_engine.recognize(image, rec=False)
            current_boxes = [b['rect'] for b in blocks] if blocks else []
            current_scores = [self.ocr.calculate_edge_density(image, b) for b in current_boxes]
            
            if not self._prev_east_boxes:
                self._prev_east_boxes = current_boxes
                self._prev_east_scores = current_scores
                return False
                
            matched_count = 0
            total_count = max(len(current_boxes), len(self._prev_east_boxes))
            if total_count == 0: return True
                
            for i, c_box in enumerate(current_boxes):
                c_score = current_scores[i]
                best_iou = 0.0
                best_score_diff = 1.0
                for j, p_box in enumerate(self._prev_east_boxes):
                    iou = self._calc_iou(c_box, p_box)
                    if iou > best_iou:
                        best_iou = iou
                        best_score_diff = abs(c_score - self._prev_east_scores[j])
                
                if best_iou >= 0.8 and best_score_diff < 0.05:
                    matched_count += 1
                    
            match_ratio = matched_count / total_count
            self._prev_east_boxes = current_boxes
            self._prev_east_scores = current_scores
            
            import time
            current_time = time.time()
            time_since_last = current_time - getattr(self, '_last_ocr_exec_time', 0.0)
            
            # エコモード判定
            if self.config.get("eco_mode", False) and time_since_last < 3.0:
                return True

            # 時間経過による強制緩和
            # 3秒以上経過していれば、少しの変化でも読みに行くようにしきい値を下げる
            if time_since_last >= 3.0:
                skip_thresh = 0.6
            elif time_since_last >= 1.0:
                skip_thresh = 0.8
            else:
                skip_thresh = 0.95
                
            return match_ratio >= skip_thresh
        except Exception:
            return False

    # ------------------------------------------------------------------
    # OCR スレッド分離
    # ------------------------------------------------------------------

    def _ocr_worker(self):
        """
        バックグラウンドワーカー。
        _ocr_input_queue から (image, rect, scale_x, scale_y, thread_limit_ratio, frame_id) を受け取り、
        OCR を実行して結果を _ocr_output_queue に入れる。
        """
        # ワーカースレッド内でPaddleOCRを初期化（CUDAコンテキストを維持するため）
        if hasattr(self, 'ocr') and self.ocr.paddle_engine:
            self.ocr.paddle_engine.preload()

        while True:
            try:
                print("[OCR Worker] Waiting for payload...")
                payload = self._ocr_input_queue.get()  # ブロッキング待機
                if payload is None:
                    break  # 終了シグナル
                
                print("[OCR Worker] Received payload, checking skip...")
                image, rect, scale_x, scale_y, thread_limit_ratio, frame_id = payload
                
                skip_ocr = self._check_skip_ocr(image)
                print(f"[OCR Worker] skip_ocr={skip_ocr}")
                
                if skip_ocr and hasattr(self, '_last_raw_chunks') and self._last_raw_chunks:
                    raw_chunks = self._last_raw_chunks
                else:
                    use_vision = self.config.get("use_vision_translation", False)
                    ocr_mode = self.ocr.ocr_mode
                    
                    print("[OCR Worker] Starting extract_text...")
                    start_t = time.time()
                    raw_chunks, _ = self.ocr.extract_text(
                        image,
                        window_title=self.window_title,
                        target_lang=self.config.get("target_language", "ja"),
                        attach_image=use_vision,
                        thread_limit_ratio=thread_limit_ratio,
                    )
                    # self._last_raw_chunks = raw_chunks
                    
                    self._last_raw_chunks = raw_chunks
                    self._last_winocr_time = time.time()
                
                self._ocr_output_queue.put((raw_chunks, rect, scale_x, scale_y, frame_id))
                print("[OCR Worker] Result put in queue.")
            except Exception as e:
                print(f"[OCR Worker FATAL] エラー: {e}")
                import traceback
                traceback.print_exc()
            finally:
                if 'image' in locals() and image is not None:
                    if hasattr(image, 'close'):
                        image.close()
                    del image
                self._ocr_busy = False

    def _update_status(self, analysis_status=None):
        """
        ステータス行の表示を更新する。
        翻訳情報の統計（キュー数、レイテンシ、翻訳済み数）を常に含める。
        """
        if not hasattr(self, 'overlay') or not self.overlay:
            return

        if analysis_status:
            self._last_analysis_status = analysis_status
        
        # 統計情報の取得
        translated_count = len(self.overlay.active_labels)
        backlog = self.translator.backlog_count if hasattr(self, 'translator') else 0
        latency = self.translator.avg_latency if hasattr(self, 'translator') else 0.0
        
        perf_info = f" | Queue: {backlog} | Latency: {latency:.1f}s"
        status_prefix = self._last_analysis_status if hasattr(self, '_last_analysis_status') else "監視中"
        # 解析中、監視中のプレフィックスに実際のキャプチャ方式を付与する
        cap_name = getattr(self, "_current_captured_by", "なし")
        if status_prefix == "解析中":
            if cap_name != "なし":
                status_prefix = f"解析中 ({cap_name})"
        elif status_prefix in ("👀 監視中", "監視中"):
            if cap_name != "なし":
                status_prefix = f"監視中 ({cap_name})"
        
        # シングルモード実行済みならステータスを上書き
        if self.config.get("single_mode", False) and self._single_run_done:
            status_prefix = "シングルモード (待機)"
            
        full_status = f"{status_prefix} | 翻訳済: {translated_count}個{perf_info} | {self.window_title}"
        self.overlay.set_status(full_status)

    def _on_tick(self):
        """
        メインループ（約6FPS）。
        1回のキャプチャで、既存枠の監視(Monitor)と新規テキストの発見(Discovery)を行う。
        """
        if not self.is_running:
            self.timer.stop() # ここで止める（UIスレッド確定）
            return

        try:
            with self._lock:
                self._current_frame_id += 1 # 最初にIDを確定
                current_id = self._current_frame_id
            rect = get_client_rect_on_screen(self.window_title)
            if rect is None:
                self._update_status(f"窓消失: {self.window_title}")
                return

            # UI をターゲットのクライアント領域（枠内）へ追従させる
            self.overlay.update_geometry(rect)

            # --- 【CPU超省電力化】エコモード待機時間の超早期判定は後半のOCRトリガー制限に統合されました ---
            pass

            # 1. 画面キャプチャ（1回のループで1回のみ）
            capture_mode = self.config.get("capture_mode", "wgc")
            # C#字幕表示（WPF）はONのままで、キャプチャ処理はPython側の超高速・低負荷なネイティブキャプチャ（DXCAM等）をデフォルトにします。
            # 巨大な画像バイナリを毎秒HTTP転送するボトルネックを完全に回避し、Python時代の爆速パフォーマンスを復元します。
            use_cs_cap = self.config.get("use_csharp_capture", False)
            cs_api_url = getattr(self.overlay, "cs_api_url", "http://127.0.0.1:5002")
            image = capture_window(
                self.window_title,
                rect=rect,
                mode=capture_mode,
                use_csharp=use_cs_cap,
                cs_api_url=cs_api_url,
                dxcam_gpu_idx=self.config.get("paddle_gpu_index", 0)
            )

            if image:
                self._current_captured_by = image.info.get("captured_by", capture_mode).upper()
            else:
                self._current_captured_by = "なし"

            # 2. キューからの結果取得とUI反映
            self._poll_ocr_result(image)
            
            # 3. ステータス更新
            self._update_status()

            # シングルモード: 
            # 1. バックログが残っている場合は、スロットリングに従って小出しに送信する
            # 2. すべて送信済みで、かつ翻訳結果もすべて受け取り済みなら、表示を固定する
            is_single_mode = self.config.get("single_mode", False)
            if is_single_mode:
                if self._single_run_done:
                    return
                # まだ送信待ちがある場合は継続。
                # ただし、処理中でなくバックログもない時は、手動トリガー(0.0)がない限りスキップして節約する
                is_manual_trigger = (self._last_force_ocr_time == 0.0)
                if not self._ocr_busy and not self._single_scan_backlog and not is_manual_trigger:
                    self._poll_ocr_result(None)
                    return
                if is_manual_trigger:
                    print(f"[SingleMode] 手動トリガー検知、スキャンを開始します...")

            if image is None:
                if not self._ocr_busy:
                    self._update_status(f"警告: 対象ウィンドウが見つかりません: {self.window_title}")
                return

            new_rects = []  # 自動クリア判定用に初期化

            # --- A. 既存枠の監視 (Monitor) ---
            current_image_np = np.array(image.convert('L'))
            
            # DPIスケール係数の計算 (MonitorとScout両方で使用)
            logical_w, logical_h = rect[2], rect[3]
            physical_w, physical_h = image.width, image.height
            scale_x = physical_w / logical_w if logical_w > 0 else 1.0
            scale_y = physical_h / logical_h if logical_h > 0 else 1.0

            if self.overlay_state:
                try:
                    # [v1.1.2 Hotfix] PaddleOCRはスレッド固有のCUDAコンテキストを持つため、
                    # UIスレッド(_on_tick)からの直接呼び出しはクラッシュ(Unhandled Exception)の原因となります。
                    # そのため、Monitorフェーズでの索敵は一時的にスキップし、エッジ密度のみで生存判定を行います。
                    new_rects = [] 

                    for cid, state in list(self.overlay_state.items()):
                        if state.get('text') in {"__IGNORE__", "__IGNORE_1__", "__IGNORE_2__"}:
                            continue
                        old_r = state['rect']
                        parent_rect = state.get('parent_rect')
                        step3_crop = state.get('step3_crop')
                        
                        is_missed = True
                        
                        if parent_rect and step3_crop is not None:
                            # --- テンプレートマッチングによる追従 (DPIスケール考慮) ---
                            h, w = step3_crop.shape
                            px_phys = int(parent_rect['x'] * scale_x)
                            py_phys = int(parent_rect['y'] * scale_y)
                            
                            # 探索範囲 (±50px): テキストがスクロール・移動するゲームに対応
                            search_margin = 50
                            sx = max(0, px_phys - search_margin)
                            sy = max(0, py_phys - search_margin)
                            ex = min(current_image_np.shape[1], px_phys + w + search_margin)
                            ey = min(current_image_np.shape[0], py_phys + h + search_margin)
                            
                            search_region = current_image_np[sy:ey, sx:ex]
                            
                            if search_region.shape[0] >= h and search_region.shape[1] >= w:
                                res = cv2.matchTemplate(search_region, step3_crop, cv2.TM_CCOEFF_NORMED)
                                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                                
                                # 類似度しきい値を 0.72 に緩和 (背景誤認防止と検出率のバランス)
                                if max_val > 0.72:
                                    # 新しい位置 (物理ピクセル座標)
                                    nx = sx + max_loc[0]
                                    ny = sy + max_loc[1]
                                    
                                    dx_phys = nx - px_phys
                                    dy_phys = ny - py_phys
                                    
                                    # 移動量を論理座標に変換
                                    dx_logical = dx_phys / scale_x
                                    dy_logical = dy_phys / scale_y
                                    
                                    # 位置を更新 (論理座標)
                                    parent_rect['x'] += dx_logical
                                    parent_rect['y'] += dy_logical
                                    old_r['x'] += dx_logical
                                    old_r['y'] += dy_logical
                                    
                                    # crop更新
                                    new_px_phys = int(parent_rect['x'] * scale_x)
                                    new_py_phys = int(parent_rect['y'] * scale_y)
                                    new_crop = current_image_np[new_py_phys:new_py_phys+h, new_px_phys:new_px_phys+w]
                                    if new_crop.shape == step3_crop.shape:
                                        state['step3_crop'] = new_crop
                                        
                                    is_missed = False
                                    
                                    # 追従した場合はオーバーレイに位置を送信
                                    if dx_phys != 0 or dy_phys != 0:
                                        self._position_queue.put((cid, old_r.copy()))
                        
                        # --- WGCフレームを使った消失判定 ---
                        # calculate_edge_density は現フレーム(image)から直接クロップして Canny 処理する。
                        # 「前フレームとの相対変化量」ではなく、
                        # 「OCR時に確認したbase_densityと比べて今の密度が何割残っているか」で判定する。
                        check_rect = parent_rect if parent_rect else old_r
                        phys_rect = {
                            'x': check_rect['x'] * scale_x,
                            'y': check_rect['y'] * scale_y,
                            'w': check_rect['w'] * scale_x,
                            'h': check_rect['h'] * scale_y
                        }
                        density = self.ocr.calculate_edge_density(image, phys_rect)
                        base_density = state.get('base_density', 0.0)
                        
                        force_evict = False  # スライディングウィンドウをバイパスする即時削除フラグ
                        
                        if base_density > 0.005:
                            # OCR時のエッジ密度が残存しているかを絶対値で判定
                            retention_ratio = density / base_density
                            
                            # [v1.1.4仕様] 密度が15%未満に激減 → テキストが確実に消えた（即時削除）
                            if retention_ratio < 0.15:
                                is_missed = True
                                force_evict = True  # スライディングウィンドウを待たず即パージ
                            # [改善C] テンプレートマッチが失敗 かつ 密度35%未満 → 追加の即時パージ
                            # (テンプレートマッチ成功時は is_missed=False が既に確定しているためここには来ない)
                            elif is_missed and retention_ratio < 0.35:
                                force_evict = True  # スライディングウィンドウを待たず即パージ
                            # テンプレートマッチが成功した場合：密度が30%以上残っていれば生存
                            elif not is_missed and retention_ratio >= 0.30:
                                pass  # 生存確定
                            # [v1.1.4仕様] テンプレートマッチが失敗した場合：密度が75%以上残っていれば生存とみなす
                            # (density_diff < 25% に相当: メモ「エッジ救済閾値」準拠)
                            elif is_missed and retention_ratio >= 0.75:
                                is_missed = False  # エッジが極めて強く残っている場合のみ生存とみなす
                        else:
                            # base_density が未設定の場合は従来の絶対しきい値で判定
                            if density < 0.01:
                                is_missed = True
                                force_evict = True
                            elif is_missed and density > 0.02:
                                is_missed = False  # 密度がゼロではないので生存とみなす
                        
                        # --- スライディングウィンドウによる生存判定 (3回連続 or 6回中4回) ---
                        history = state.get('existence_history', [1, 1, 1, 1, 1, 1]) # 1=生存, 0=不在
                        history.pop(0)
                        history.append(0 if is_missed else 1)
                        state['existence_history'] = history
                        
                        # 判定条件
                        # [改善B] 連続不在判定を 3→2 フレームに短縮（6フレームウィンドウは維持）
                        consecutive_miss = all(h == 0 for h in history[-2:])
                        ratio_miss = (history.count(0) >= 4)
                        
                        # force_evict: 密度が激減した場合はウィンドウを待たず即パージ
                        if force_evict or consecutive_miss or ratio_miss:
                            evict_reason = "密度激減(即時)" if force_evict else ("2回連続不在" if consecutive_miss else "6回中4回不在")
                            self._purge_cid(cid)
                        else:
                            # 生存継続: last_seen を更新して長期カウンターをリセット
                            state['last_seen'] = time.time()
                            
                            # --- 【長期ゴースト対策】15秒以上表示中の翻訳をOCRで再検証 ---
                            # テンプレートマッチ・密度判定をすり抜けた「幽霊」を定期的に排除する
                            now_ts = time.time()
                            disp_time = now_ts - state.get('_display_start', now_ts)
                            last_deep = state.get('_last_deep_verify', 0)
                            
                            if disp_time > 15.0 and (now_ts - last_deep) > 15.0:
                                # PaddleOCR の検出のみ (rec=False) でその領域を高速チェック
                                if self.ocr.paddle_engine and self.ocr.paddle_engine._initialized:
                                    try:
                                        cr_x = max(0, int(phys_rect['x']))
                                        cr_y = max(0, int(phys_rect['y']))
                                        cr_w = max(1, int(phys_rect['w']))
                                        cr_h = max(1, int(phys_rect['h']))
                                        crop_img = image.crop((cr_x, cr_y, cr_x + cr_w, cr_y + cr_h))
                                        detections = self.ocr.paddle_engine.recognize(crop_img, rec=False)
                                        state['_last_deep_verify'] = now_ts
                                        
                                        if not detections:
                                            # テキストが検出されなかった → ゴースト確定、即時パージ
                                            print(f"[DeepVerify] {disp_time:.0f}秒超の表示を再検証: テキスト未検出 → パージ ID={cid}")
                                            self._purge_cid(cid)
                                        else:
                                            # テキスト存在確認 → カウンターをリセットして継続表示
                                            state['_display_start'] = now_ts
                                            print(f"[DeepVerify] {disp_time:.0f}秒超の表示を再検証: テキスト存在確認 ID={cid}")
                                    except Exception as e:
                                        state['_last_deep_verify'] = now_ts  # エラーでも次回まで待つ
                except Exception as e:
                    print(f"[Monitor Error] {e}")

            # --- 【CPU超軽量化】通常・エコモード時の頻度制限による重い全体Canny画像処理の早期バイパス ---
            # 既存の字幕のリアルタイム追従（追従）やエッジ消失判定は毎フレーム実行（上記）しつつ、
            # 新しいOCRをトリガーする処理は、エコモード時は10秒、通常時は0.3秒間は完全にスキップする。
            current_time = time.time()
            is_eco = self.config.get("eco_mode", False)
            limit_time = 10.0 if is_eco else 0.3
            if current_time - getattr(self, "_last_ocr_exec_time", 0.0) < limit_time:
                return

            # 128x72 に統一して判定 (ピクセルとエッジ両用)
            curr_gray_full = np.array(image.resize((128, 72)).convert("L"))
            
            if self._prev_gray is None:
                self._prev_gray = curr_gray_full.copy()
                return # 初回は比較対象がないためスキップ
            
            # --- 比較用のベースラインをバックアップし、即座に更新 (スキップ時も安全なように) ---
            prev_gray_baseline = self._prev_gray.copy()
            self._prev_gray = curr_gray_full.copy()

            # 【重要】現在のオーバーレイ状態に基づいたマスクを作成
            logical_w, logical_h = rect[2], rect[3]
            physical_w, physical_h = image.width, image.height
            scale_x = physical_w / logical_w if logical_w > 0 else 1.0
            scale_y = physical_h / logical_h if logical_h > 0 else 1.0
            
            mask_arr = np.ones((72, 128), dtype=np.uint8)
            if self.overlay_state:
                sx, sy = 128 / physical_w, 72 / physical_h
                for state in self.overlay_state.values():
                    r = state['rect']
                    x1 = int(r['x'] * scale_x * sx)
                    y1 = int(r['y'] * scale_y * sy)
                    x2 = int((r['x'] + r['w']) * scale_x * sx)
                    y2 = int((r['y'] + r['h']) * scale_y * sy)
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(128, x2), min(72, y2)
                    if x2 > x1 and y2 > y1:
                        mask_arr[y1:y2, x1:x2] = 0

            # 同一マスクを適用して比較 (マスク面積の変化による影響を相殺)
            curr_masked = curr_gray_full * mask_arr
            prev_masked = prev_gray_baseline * mask_arr

            # --- スキップ判定用のエッジ計算 (マスクあり) ---
            edges_curr = cv2.Canny(curr_masked, 50, 150)
            edges_prev = cv2.Canny(prev_masked, 50, 150)
            count_curr = np.count_nonzero(edges_curr)
            count_prev = np.count_nonzero(edges_prev)
            edge_diff_rate = abs(count_curr - count_prev) / max(1, count_prev)

            # 1. ピクセル差分 (L1ノルム)
            pixel_diff = np.sum(np.abs(curr_masked.astype(np.int16) - prev_masked.astype(np.int16)))

            # --- シーンチェンジ判定用のエッジ計算 (マスクなしの生画像を使用) ---
            edges_curr_raw = cv2.Canny(curr_gray_full, 50, 150)
            edges_prev_raw = cv2.Canny(prev_gray_baseline, 50, 150)
            count_curr_raw = np.count_nonzero(edges_curr_raw)
            count_prev_raw = np.count_nonzero(edges_prev_raw)
            
            raw_pixel_diff = np.sum(np.abs(curr_gray_full.astype(np.int16) - prev_gray_baseline.astype(np.int16)))
            raw_edge_diff_rate = abs(count_curr_raw - count_prev_raw) / max(1, count_prev_raw)
            
            # 【重要】シーンチェンジ検知 (エッジ50%変化、かつピクセルが閾値の30倍以上変化)
            is_huge_change = (raw_edge_diff_rate > 0.50 and raw_pixel_diff > (self.config.get("ocr_skip_sensitivity", 2400) * 30))
            last_clear_time = getattr(self, '_last_scene_clear_time', 0.0)
            now_time = time.time()
            
            if is_huge_change and (now_time - last_clear_time > 1.0):
                self._last_scene_clear_time = now_time
                self._last_clear_id = current_id
                print(f"[Queue] Scene change detected: Invalidating pending OCR tasks (FID <= {current_id})")
                
                # 「ID・翻訳・位置情報」に関連する表示系の一時キャッシュのみをクリア
                self.overlay_state.clear()
                if hasattr(self, 'overlay') and self.overlay:
                    self.overlay.clear_labels()
                self.active_translations.clear()
                self.history_chunks.clear()
                self.pending_texts.clear()
                self._last_raw_chunks = []
                self._history_grid.clear()
                if hasattr(self, 'translator') and self.translator:
                    self.translator.clear_queue()
                self.overlay.sync_active_ids(set())

            # 内部状態更新 (冒頭で実施済み)

            # 感度設定 (128x72=9216ピクセル。2400は全ピクセルの平均0.26変化に相当)
            # 安全装置: 閾値が低すぎると無限ループするため、最低 1000 以上を保証する
            sensitivity = self.config.get("ocr_skip_sensitivity", 2400)
            if not isinstance(sensitivity, (int, float)) or sensitivity < 1000:
                sensitivity = 2400
            diff_threshold = sensitivity
            
            current_time = now_time
            time_since_force = current_time - self._last_force_ocr_time
            
            # エコモード判定
            is_eco = self.config.get("eco_mode", False)
            time_since_last_exec = current_time - self._last_ocr_exec_time
            if is_eco and time_since_last_exec < 10.0:
                return

            # シングルモード判定
            is_single = self.config.get("single_mode", False)
            if is_single and self._single_run_done:
                # 実行済みなら OCR を一切走らせない（表示固定）
                return

            # (一旦ピクセル単体での return は削除し、後続のエッジ判定と統合して判断します)
                
            # 【重要】実行頻度の制限 (最低 0.3秒 は空ける)
            if current_time - self._last_ocr_exec_time < 0.3:
                # 頻度制限中はステータス更新をスキップ（負荷軽減）
                # ただし状態は更新済みなので安全
                return

            # --- C. スキップ判定 (第2フィルタ) ---
            # 比較対象を「直前フレーム」に戻す
            edge_count = count_curr
            is_single = self.config.get("single_mode", False)
            if is_single:
                # シングルモード：_last_force_ocr_time が 0.0（初期値）のときのみ実行を許可する。
                # エッジ変化・ピクセル変化による自動スキャンは一切行わない。
                is_forced = (self._last_force_ocr_time == 0.0)
                if not is_forced:
                    # 手動トリガー以外はすべてスキップ（シングルモードの安全ガード）
                    self._prev_edge_count = edge_count
                    return
            else:
                # 強制OCRの周期設定：通常モードなら5.0秒、エコモードなら10.0秒
                force_interval = 10.0 if is_eco else 5.0
                is_forced = (time_since_force >= force_interval)
            
            prev_edge_for_log = self._prev_edge_count
            
            # 判定フロー：
            # 1. 【最優先】強制実行（手動ボタン等）: 画面の状態に関わらず実行
            if is_forced:
                pass
            # 2. エッジ激変 (10%以上): 内容が変わったため実行（通常モードのみ）
            # ただし、エッジ数が極めて少ない（20未満）場合はノイズによる比率ブレを防ぐため激変判定を適用しない
            elif edge_diff_rate > 0.10 and max(edge_count, self._prev_edge_count) >= 20:
                pass 
            # 3. エッジ安定 (5%未満): 文字の形が変わっていないため、ピクセル変化を無視してスキップ
            # またはエッジ数が極めて少ない場合（20未満）も文字無し/ノイズとみなし、背景変化無視としてスキップ
            elif edge_diff_rate < 0.05 or max(edge_count, self._prev_edge_count) < 20:
                self._prev_edge_count = edge_count # 安定継続
                if not self._ocr_busy:
                    self._update_status("監視中 (背景変化無視)")
                return
            # 4. ピクセル安定: エッジ変化が中程度(5〜10%)でも、画素全体が静止していればスキップ
            elif pixel_diff < diff_threshold:
                self._prev_edge_count = edge_count
                if not self._ocr_busy:
                    self._update_status("監視中 (静止中)")
                return
            
            # いずれのスキップ条件も満たさない場合はOCRを実行
            
            self._prev_edge_count = edge_count
            
            # エッジ数が極端に少ない（15未満）場合は、文字が消えたと判断してクリアする
            if edge_count < 15:
                if self.overlay_state:
                    self.overlay.clear_labels()
                    self.overlay_state.clear()
                    self.active_translations.clear()
                    self.history_chunks.clear()
                    self._history_grid.clear()
                    self.pending_texts.clear()
                    if hasattr(self, 'translator') and self.translator:
                        self.translator.clear_queue()
                    print(f"[Monitor] Empty screen detected (Edges: {edge_count}): Cleared all states.")
                
                # 強制実行フラグが立っていた場合はタイマーをリセット（無限ループ防止）
                if is_forced:
                    self._last_force_ocr_time = current_time
                    
                self._update_status("監視中 (画面が空白)")
                return
                
            if not self._ocr_busy:
                # PaddleOCRの状態を反映
                if self.ocr.paddle_engine and not self.ocr.paddle_engine._initialized:
                    self._last_analysis_status = "準備中 (エンジン初期化)..."
                else:
                    self._last_analysis_status = "解析中"
                self._update_status()
                
            self._last_ocr_exec_time = current_time
            if time_since_force >= 10.0:
                self._last_force_ocr_time = current_time
                
            # --- 【v1.1.2 強化】OCR実行トリガーの詳細ログ ---
            trigger_reason = ""
            if is_forced: trigger_reason = "強制実行(10s)"
            elif edge_diff_rate > 0.10: trigger_reason = f"エッジ激変({edge_diff_rate:.1%})"
            else: trigger_reason = f"ピクセル変化(diff={pixel_diff} > threshold={diff_threshold}, edges={edge_diff_rate:.1%})"
            
            print(f"[OCR_Trigger] {trigger_reason} | Edges: {edge_count} (prev: {prev_edge_for_log})")
            
            self._prev_edge_count = edge_count

            if self._ocr_busy:
                try:
                    self._ocr_input_queue.get_nowait()
                except queue.Empty:
                    pass

            self.window_rect_data = {"x": rect[0], "y": rect[1], "w": logical_w, "h": logical_h}
            
            # 重複削除

            self._prev_edge_count = edge_count

            self._ocr_busy = True
            thread_limit_ratio = self.config.get("ocr_thread_limit_percent", 100) / 100.0
            self._ocr_input_queue.put((image, rect, scale_x, scale_y, thread_limit_ratio, current_id))

        except Exception as e:
            print(f"[Critical Error] _on_tick failed: {e}")
            traceback.print_exc()

    def _poll_ocr_result(self, image):
        """
        メインループから呼び出され、OCR結果の反映とUI更新を行う。
        """
        current_time = time.time()
        raw_chunks = []
        got_new_result = False
        new_chunks = []
        final_new_chunks = []
        is_single = self.config.get("single_mode", False)
        backlog = self.translator.backlog_count
        latency = self.translator.avg_latency
        try:
            if not self.is_running:
                return
            
            now = current_time
                
            # 爆速追従：位置更新キューの処理
            got_position_update = False
            while not self._position_queue.empty():
                try:
                    cid, new_rect = self._position_queue.get_nowait()
                    if hasattr(self, 'overlay'):
                        self.overlay.update_translation_position(cid, new_rect)
                        got_position_update = True
                        if cid in self.overlay_state:
                            self.overlay_state[cid]['rect'] = new_rect
                            
                            # 古い残骸を確実に消す：同じテキストの「別ID」があればUIから抹消
                            cur_txt = self.overlay_state[cid].get('text', '')
                            if cur_txt:
                                for other_cid, other_state in list(self.overlay_state.items()):
                                    if other_cid == cid:
                                        continue
                                    if other_state.get('text', '') == cur_txt:
                                        self._purge_cid(other_cid)
                except queue.Empty:
                    break
                except Exception as e:
                    print(f"[Position Tracking] エラー: {e}")
                    break

            if got_position_update and hasattr(self, 'overlay') and getattr(self.overlay, 'use_csharp', False):
                if hasattr(self.overlay, '_push_csharp_update'):
                    self.overlay._push_csharp_update()

            while True:
                try:
                    res = self._ocr_output_queue.get_nowait()
                    fid = res[4]
                    if fid < self._last_clear_id:
                        self._ocr_busy = False
                        print(f"[Queue] Discarded stale result: FID={fid} < ClearID={self._last_clear_id}")
                        continue

                    if res[0] in ["CLEAR", "CLEAR_PIXEL"]:
                        # 「ID・翻訳・位置情報」に関連する表示系の一時キャッシュのみをクリア
                        if hasattr(self, 'overlay'):
                            self.overlay.clear_labels()
                        self.overlay_state.clear()
                        self.active_translations.clear()
                        self.history_chunks.clear()
                        self.pending_texts.clear()
                        self._last_raw_chunks = []
                        self._history_grid.clear()
                        self._shadow_skip_cache.clear()
                        if hasattr(self, 'translator') and self.translator:
                            self.translator.clear_queue()
                        self.overlay.sync_active_ids(set())
                        continue

                    raw_chunks, rect, scale_x, scale_y, _ = res
                    self._ocr_busy = False
                    got_new_result = True
                    # シングルモード: フラグはこのメソッドの最後でセットする（途中の早期リターンでの消失を防ぐ）
                    is_single = self.config.get("single_mode", False)
                    
                    if not raw_chunks:
                        translated_count = len(self.overlay.active_labels)
                        perf_info = f" | Latency: {self.translator.avg_latency:.1f}s"
                        status_prefix = "初期化中" if (self.ocr.paddle_engine and not self.ocr.paddle_engine._initialized) else "監視中"
                        self._update_status(f"{status_prefix} (文字なし)")
                        # 文字なしの場合は履歴更新フェーズに進む（画面上の枠を消すため）
                        
                    break 
                except queue.Empty:
                    break

            if got_new_result:
                # ---- 以下は旧 _on_tick の OCR 実行後の処理をそのまま移植 ----
                translated_count = 0
                chunks = []
                new_history = {}
                
                for chunk in raw_chunks:
                    # --- 1. 座標を物理ピクセルから論理座標に変換（DPIスケーリング補正） ---
                    chunk['rect']['x'] /= scale_x
                    chunk['rect']['y'] /= scale_y
                    chunk['rect']['w'] /= scale_x
                    chunk['rect']['h'] /= scale_y
                    
                    if 'parent_rect' in chunk and chunk['parent_rect']:
                        chunk['parent_rect']['x'] /= scale_x
                        chunk['parent_rect']['y'] /= scale_y
                        chunk['parent_rect']['w'] /= scale_x
                        chunk['parent_rect']['h'] /= scale_y
    
                    # --- 【v1.1.2 強化】OCR実行時のエッジ密度（base_density）をそのまま採用する ---
                    # 以前はここで再計算していたが、タイムラグによる不一致を防ぐため、OCR時点の値を優先する
                    cur_density = chunk.get('base_density', 0.0)
                    
                    if cur_density < 0.005: # 密度が極端に低い（ほぼ空白）場合は無視
                        if cur_density > 0:
                            print(f"[Queue] Skip low-density chunk: '{chunk['text'][:20]}' (density: {cur_density:.4f})")
                        continue
    
                    # --- 2. 空間トラッキング（IDの安定化） ---
                    best_match_id = None
                    best_iou = 0.1
                    
                    cr = chunk['rect']
                    gx = int(cr['x'] // 40)
                    gy = int(cr['y'] // 40)
                    neighbor_cids = set()
                    for dx in range(-1, 2):
                        for dy in range(-1, 2):
                            for cid in self._history_grid.get((gx + dx, gy + dy), []):
                                neighbor_cids.add(cid)
                    
                    for old_cid in neighbor_cids:
                        old_chunk = self.history_chunks.get(old_cid)
                        if not old_chunk:
                            continue
                        iou = calculate_iou(cr, old_chunk['rect'])
                        if iou > best_iou:
                            best_iou = iou
                            best_match_id = old_cid
                            
                    if best_match_id:
                        old_chunk = self.history_chunks[best_match_id]
                        # 類似度の判定: エッジ情報の比較対象を「前回のOCR時点の値」に固定する
                        # overlay_state にあればそこから、なければ履歴(old_chunk)から取得
                        old_density = self.overlay_state.get(best_match_id, {}).get('base_density')
                        if old_density is None:
                            old_density = old_chunk.get('base_density', cur_density)
                        
                        density_diff_ratio = abs(cur_density - old_density) / max(0.01, old_density)
                        
                        text_sim = SequenceMatcher(None, chunk['text'], old_chunk['text']).ratio()
                        
                        # 【調整】「同じ」判定基準を大幅に緩和（細分化対応）
                        is_same_item = False
                        if density_diff_ratio < 0.45: # エッジ一致を 45% まで大幅に許容
                            if text_sim > 0.25: # テキスト一致も 25% まで緩和
                                is_same_item = True
                                
                        if is_same_item:
                            chunk['id'] = best_match_id
                            # 過去のラベルの位置を新座標へテレポートさせる
                            if hasattr(self, 'overlay') and best_match_id in self.overlay.active_labels:
                                self.overlay.update_translation_position(best_match_id, chunk['rect'])
                    
                    # IDが固定されなかった場合、新規IDを生成
                    if chunk['id'].startswith("new_"):
                        # 密度ステップを除去し、座標とテキストのみで安定化させる
                        area_id = f"{gx}_{gy}"
                        t_hash = hashlib.md5(chunk['text'].encode('utf-8')).hexdigest()
                        chunk['id'] = f"{t_hash[:8]}_{area_id}"
    
                    cid = chunk['id']
                    
                    # --- 追加バリデーション：既存IDの場合、内容の激変をチェック ---
                    # (この判定は後段の空間パージ/不一致判定に統合されたため、ここではスルーする)
    
                    # --- 【復活・強化】空間的な重複排除：新しい枠が古い枠を上書きする場合、古い方を即座に消す ---
                    for old_cid in list(self.overlay_state.keys()):
                        if old_cid == cid: continue
                        old_rect = self.overlay_state[old_cid]['rect']
                        # 新しい枠と古い枠が20%以上重なっているなら、古い方は「残骸」とみなして即座に削除（重複防止）
                        if calculate_iou(chunk['rect'], old_rect) > 0.20:
                            self._purge_cid(old_cid)
    
                    new_history[cid] = chunk
                    chunks.append(chunk)
    
                    # --- 3. キャッシュチェックと表示ステートの更新 ---
                    target_lang = self.config.get("target_language", "ja")
                    text_raw = chunk['text'].strip()
                    norm_text = normalize_text(text_raw)
                    
                    # 直前に消去されたばかりのテキスト（ブラックリスト）は、5秒間キャッシュ復活を阻止
                    if hasattr(self, "_recent_cleared_texts"):
                        expiry = self._recent_cleared_texts.get(norm_text, 0)
                        if time.time() < expiry:
                            # ブラックリスト期間中
                            new_history[cid] = chunk
                            chunks.append(chunk)
                            continue
    
                    cache_key = f"{target_lang}::{text_raw}"
                    cached_trans = self.translation_cache.get(cache_key)
                    
                    if cached_trans:
                        translated_count += 1
                        # ソフトIGNOREも含め、全IGNORE系の値はオーバーレイに表示しない
                        _all_ignores = {"__IGNORE__", "__IGNORE_1__", "__IGNORE_2__"}
                        if cached_trans not in _all_ignores:
                            # デスクトップ用オーバーレイ（PyQt）の更新
                            # 保存されたフォントサイズがあれば渡す
                            stored_fs = self.overlay_state.get(cid, {}).get('font_size')
                            self.overlay.show_translation(cid, chunk, cached_trans, target_lang, font_size=stored_fs)
                            # OBS API用ステートの更新（ブラウザ用）
                            # font_size ・ 追従テンプレートを引き継いで上書き消失・ゴースト消え残りを防ぐ
                            existing_state = self.overlay_state.get(cid, {})
                            self.overlay_state[cid] = {
                                "text": cached_trans,
                                "text_raw": text_raw,
                                "rect": chunk["rect"],
                                "bg_color": chunk.get("bg_color", "rgba(0,0,0,1.0)"),
                                "text_color": chunk.get("text_color", "#eeeeee"),
                                "lines_count": chunk.get("lines_count", 1),
                                "base_density": chunk.get("base_density", 0.0),
                                "font_size": stored_fs,
                                "mismatch_strikes": existing_state.get("mismatch_strikes", 0),
                                "change_strikes": existing_state.get("change_strikes", 0),
                                # 追従用テンプレート: Numpy配列のor評価バグを防ぐため is not None で確認
                                "parent_rect": chunk.get("parent_rect") if chunk.get("parent_rect") is not None else existing_state.get("parent_rect"),
                                "step3_crop": chunk.get("step3_crop") if chunk.get("step3_crop") is not None else existing_state.get("step3_crop"),
                                # 初回表示時刻: 既に表示中なら引き継ぐ（長期ゴースト検証用）
                                "_display_start": existing_state.get("_display_start", time.time()),
                            }
    
                # 空間バケットを再構築
                new_grid = {}
                for cid, c in new_history.items():
                    gx = int(c['rect']['x'] // 40)
                    gy = int(c['rect']['y'] // 40)
                    if (gx, gy) not in new_grid:
                        new_grid[(gx, gy)] = []
                    new_grid[(gx, gy)].append(cid)
                self._history_grid = new_grid
                self.history_chunks = new_history
    
                # 【パス1】まずcurrent_idsを完成させる（全チャンクのIDを収集）
                current_ids = set(chunk['id'] for chunk in chunks)
                self.current_ids = current_ids
    
                # 画面から消えたチャンクの生存確認:
                # 時間ベースの Grace Period は廃止し、_on_tick 側の不在ストライク制(3回)に一本化しました。
                # ここでは last_seen の更新のみ行い、削除判断はストライク側に任せます。
                for cid in list(self.overlay_state.keys()):
                    if cid in current_ids:
                        self.overlay_state[cid]['last_seen'] = current_time
                
                # --- 【改善A】OCR差分フィードバック (ocr_miss_count) ---
                # OCRスキャン結果と overlay_state を突合し、2回連続で見つからなかったIDを即時パージする。
                # スライディングウィンドウ（Monitor フェーズ）と独立して動作するため、
                # 他テキストが画面に残っている場合でも迅速に個別消去できる。
                for cid in list(self.overlay_state.keys()):
                    state = self.overlay_state.get(cid)
                    if state is None:
                        continue
                    # __IGNORE__ 系はスキップ（表示対象外のID）
                    if state.get('text') in {"__IGNORE__", "__IGNORE_1__", "__IGNORE_2__"}:
                        continue

                    if cid in current_ids:
                        # OCRで発見された → 不在カウンタをリセット
                        state['ocr_miss_count'] = 0
                    else:
                        # OCRで見つからなかった → 不在カウンタをインクリメント
                        miss_cnt = state.get('ocr_miss_count', 0) + 1
                        state['ocr_miss_count'] = miss_cnt

                        # 2回連続でOCRに見つからなければ即時パージ
                        # （スライディングウィンドウを待たないため追加の遅延はゼロ）
                        if miss_cnt >= 2:
                            print(f"[OCR-Miss] 2連続OCR不在 → 即時パージ: ID={cid}")
                            self._purge_cid(cid)
                
                # ゴーストとして生き残っているIDも含めて同期するが、
                # 重複削除のあとで再度同期する必要がある
                
                # 同一フレーム内の重複・包含排除 ＆ テキストの統合 (v1.1.2 強化)
                # 以前は重なりがある場合に小さい方を破棄していましたが、
                # それだと「+1/+1」等の記号行が大きな枠に飲まれて消えるため、
                # 重なっている場合は文章をマージするように変更します。
                merged_results = []
                
                # 処理を安定させるため、まずは Y 座標順（上から下）にソート
                chunks.sort(key=lambda c: (c['rect']['y'], c['rect']['x']))
                
                for c in chunks:
                    is_merged = False
                    cr = c['rect']
                    c_text = c['text'].strip()
                    
                    for mc in merged_results:
                        mcr = mc['rect']
                        # 重なり判定
                        area_c = max(1, cr['w'] * cr['h'])
                        area_mc = max(1, mcr['w'] * mcr['h'])
                        
                        ix = max(0, min(cr['x']+cr['w'], mcr['x']+mcr['w']) - max(cr['x'], mcr['x']))
                        iy = max(0, min(cr['y']+cr['h'], mcr['y']+mcr['h']) - max(cr['y'], mcr['y']))
                        intersection = ix * iy
                        
                        # 包含関係が強い (70%以上) ならマージ
                        if intersection / area_c > 0.7 or intersection / area_mc > 0.7:
                            # テキストがすでに含まれていないかチェック
                            mc_text = mc['text'].strip()
                            if c_text and c_text not in mc_text:
                                if mc_text not in c_text:
                                    # 両方のテキストを統合 (Y座標順に結合)
                                    if cr['y'] < mcr['y']:
                                        mc['text'] = c_text + "\n" + mc_text
                                    else:
                                        mc['text'] = mc_text + "\n" + c_text
                                else:
                                    # c の方が情報量が多い場合は置換
                                    mc['text'] = c_text
                            
                            # 矩形を外接矩形に拡張
                            x0 = min(cr['x'], mcr['x'])
                            y0 = min(cr['y'], mcr['y'])
                            x1 = max(cr['x']+cr['w'], mcr['x']+mcr['w'])
                            y1 = max(cr['y']+cr['h'], mcr['y']+mcr['h'])
                            mc['rect'] = {'x': x0, 'y': y0, 'w': x1-x0, 'h': y1-y0}
                            
                            # IDの継承: すでに active_translations にある方を優先
                            if c['id'] in self.active_translations and mc['id'] not in self.active_translations:
                                mc['id'] = c['id']
                                
                            is_merged = True
                            break
                    
                    if not is_merged:
                        merged_results.append(c)
                chunks = merged_results
                
                # 空間的（座標）キャッシュ強化：既存の翻訳と強く重なる新規チャンクは品質比較を行う
                filtered_chunks = []
                for chunk in chunks:
                    cid = chunk['id']
                    is_flicker = False
                    if cid in self.active_translations:
                        filtered_chunks.append(chunk)
                        # 翻訳済みのチャンクが表示される際、下敷きになっている古いゴーストを掃除する
                        for active_cid, state in list(self.overlay_state.items()):
                            if active_cid == cid: continue
                            # 重なり判定を甘く (0.3) して、近傍の古いゴミを積極的に消す
                            if calculate_iou(chunk['rect'], state['rect']) > 0.3:
                                old_raw = state.get('text_raw', state['text'])
                                if _score_ocr_text(chunk['text']) > _score_ocr_text(old_raw) + 0.4:
                                    print(f"[Evict] ID={active_cid} | Reason: 高品質な上書き")
                                    self._purge_cid(active_cid)
                        continue
                        
                    # ディクショナリ変更エラーを避けるため list() でラップ
                    for active_cid, state in list(self.overlay_state.items()):
                        if active_cid == cid: continue
                        
                        r1 = chunk['rect']
                        r2 = state['rect']
                        
                        area1 = max(1, r1['w'] * r1['h'])
                        area2 = max(1, r2['w'] * r2['h'])
                        ix = max(0, min(r1['x']+r1['w'], r2['x']+r2['w']) - max(r1['x'], r2['x']))
                        iy = max(0, min(r1['y']+r1['h'], r2['y']+r2['h']) - max(r1['y'], r2['y']))
                        intersection_area = ix * iy
                        
                        ioa = intersection_area / min(area1, area2)
                        
                        # 包含関係・部分的な重なり判定を甘く (0.3)
                        if ioa > 0.3:
                            old_text = state.get('text_raw', state['text'])
                            new_text = chunk['text']
                            similarity = SequenceMatcher(None, old_text.strip(), new_text.strip()).ratio()
                            
                            # --- 同一性判定: まず物理的形状(エッジ)の一致を確認するが、「同じ」判定には慎重に使う ---
                            old_density = state.get('base_density', 0)
                            density_diff_ratio = abs(cur_density - old_density) / max(0.01, old_density)
                            
                            # 同一性の定義: 
                            # 1. エッジが安定(40%以内) かつ テキストも20%以上(0.2)一致している場合
                            # 2. または、テキストが 0.55 以上一致している場合
                            is_same_item = (density_diff_ratio < 0.40 and similarity > 0.20) or (similarity > 0.55)
                            
                            # --- ケースA: 同一性が認められる場合 (表示維持) ---
                            if is_same_item:
                                # 座標の揺れを吸収しつつ寿命を延ばす
                                if area1 < area2 * 0.7:
                                    is_flicker = True
                                    self.overlay.update_translation_position(active_cid, chunk['rect'])
                                    state['rect'] = chunk['rect']
                                    state['last_seen'] = time.time()
                                    state['mismatch_strikes'] = 0 
                                    break
                                elif area2 < area1 * 0.7:
                                    # 古い方が明らかに小さい残骸ならパージ
                                    print(f"[Evict] ID={active_cid} | Reason: サイズ不一致(残骸排除)")
                                    self._purge_cid(active_cid)
                                    continue
    
                            # --- ケースB: 内容が変化している場合 (不一致判定) ---
                            # 細分化ロジック導入に伴い、類似度の判定を緩和
                            if similarity < 0.35:
                                # --- 【v1.1.2 強化】キャッシュ・ファストパス & 即時パージ ---
                                # キャッシュに既にある場合や、完全に別物（sim<0.25）の場合はストライクを待たずに即時更新する。
                                target_lang = self.config.get("target_language", "ja")
                                cache_key = f"{target_lang}::{new_text}"
                                cached_trans = self.translation_cache.get(cache_key)
                                is_cached = cached_trans and cached_trans not in ("__IGNORE__", "__IGNORE_1__", "__IGNORE_2__")
                                
                                mismatch_strikes = state.get('mismatch_strikes', 0) + 1
                                
                                if is_cached or similarity < 0.25:
                                    mismatch_strikes = 2
                                
                                # エッジもテキストも両方違うなら、即座に2ストライク（即パージ確定）
                                # 判定を緩和 (0.20 -> 0.50)
                                if density_diff_ratio > 0.50:
                                    mismatch_strikes = 2
                                
                                # スコアによる強制更新判定
                                new_score = _score_ocr_text(new_text)
                                old_score = _score_ocr_text(old_text)
                                if new_score > old_score + 0.5:
                                    mismatch_strikes = 2
                                
                                state['mismatch_strikes'] = mismatch_strikes
                                if mismatch_strikes >= 3:
                                    print(f"[Evict] ID={active_cid} | Reason: 内容変化(Sim:{similarity:.2f}, Strikes:{mismatch_strikes}) | New: '{new_text[:30]}'")
                                    # 消去された原文をブラックリストに登録（5秒間はキャッシュ復活を阻止）
                                    if not hasattr(self, "_recent_cleared_texts"): self._recent_cleared_texts = OrderedDict()
                                    norm_cleared = normalize_text(old_text)
                                    self._recent_cleared_texts[norm_cleared] = time.time() + 5.0
                                    # LRU的に古いものを消す
                                    if len(self._recent_cleared_texts) > 50:
                                        self._recent_cleared_texts.popitem(last=False)
    
                                    self._purge_cid(active_cid)
                                    # ここでは break せず、他の重なりもチェックする
                                    continue
                                else:
                                    is_flicker = True
                                    break
                            elif similarity > 0.95:
                                state['mismatch_strikes'] = 0
    
                            # 新しい方が明らかに高品質な文章なら、古い方を削除(細分化・改善のケース)
                            if _score_ocr_text(new_text) > _score_ocr_text(old_text) + 0.4:
                                self._purge_cid(active_cid)
                                # 新しい方を表示させるため continue
                                continue
                            
                            # どちらでもない、または同程度ならフリッカーとして新しい方を捨てる
                            is_flicker = True
                            break
                    if not is_flicker:
                        filtered_chunks.append(chunk)
                    
                chunks = filtered_chunks
                
                # 不要なチャンクを削除し終えた後で最終的な active_ids を UI と同期
                active_ids = set(self.overlay_state.keys())
                self.overlay.sync_active_ids(active_ids)
    
                # 【パス2】キャッシュ照会と新規チャンクの仕分け
                new_chunks = []
                target_lang = self.config.get("target_language", "ja")
    
                for chunk in chunks:
                    cid = chunk['id']
                    text_raw = chunk['text'].strip()
                    norm_text = normalize_text(text_raw)
                    
                    # ブラックリストチェック
                    if hasattr(self, "_recent_cleared_texts"):
                        expiry = self._recent_cleared_texts.get(norm_text, 0)
                        if time.time() < expiry:
                            continue
    
                    text_lines = chunk.get('text_lines', [])
    
                    if cid in self.active_translations:
                        # ステートがある場合は位置更新のみ行う（生存・密度変化の監視は _on_tick に集約）
                        if cid in self.overlay_state:
                            self.overlay.update_translation_position(cid, chunk['rect'])
                            self.overlay_state[cid]['rect'] = chunk['rect']
                            self.overlay_state[cid]['last_seen'] = time.time()
                        continue
    
    
                    
                    # --- 新規または変化したテキストの処理 ---
                    if True: # elseブロックの代わり（30%ルールで抜けてきた場合も通るように）
                        if len(text_lines) > 1:
                            # ユーザー提案の「論理的結合パターン」を生成
                            ja_end_chars = tuple("。！？）」』…")
                            en_end_chars = tuple(".!?'\"")
                            
                            # 1. 日本語・中国語・ハングル向けパターン（句読点がなければスペース無しで結合）
                            ja_pattern = ""
                            for i, line_obj in enumerate(text_lines):
                                line = line_obj['text'] if isinstance(line_obj, dict) else line_obj
                                if i == 0:
                                    ja_pattern += line
                                else:
                                    prev_line_obj = text_lines[i-1]
                                    prev_line = prev_line_obj['text'] if isinstance(prev_line_obj, dict) else prev_line_obj
                                    if prev_line.endswith(ja_end_chars):
                                        ja_pattern += "\n" + line
                                    else:
                                        ja_pattern += line
                                        
                            # 2. 英語・ロシア語等のアルファベット向けパターン（句読点がなければスペース有りで結合）
                            en_pattern = ""
                            for i, line_obj in enumerate(text_lines):
                                line = line_obj['text'] if isinstance(line_obj, dict) else line_obj
                                if i == 0:
                                    en_pattern += line
                                else:
                                    prev_line_obj = text_lines[i-1]
                                    prev_line = prev_line_obj['text'] if isinstance(prev_line_obj, dict) else prev_line_obj
                                    if prev_line.endswith(en_end_chars):
                                        en_pattern += "\n" + line
                                    else:
                                        en_pattern += " " + line
                                        
                            # 3. OCRの生の出力（全て改行結合）
                            raw_pattern = "\n".join([l['text'] if isinstance(l, dict) else l for l in text_lines])
                        
                            # fasttextで評価し、最も適したものを選択
                            candidates = list(set([ja_pattern, en_pattern, raw_pattern]))
                            best_text = raw_pattern
                            best_score = -1.0
                            
                            for cand in candidates:
                                if len(cand) < 2: continue
                                eval_text = cand.replace('\n', ' ')
                                lang, score = detect_source_language(eval_text)
                                
                                # アジア系言語ならja_patternを優遇
                                if lang in ['ja', 'zh', 'ko'] and cand == ja_pattern:
                                    score += 0.05
                                # アルファベット系言語ならen_patternを優遇
                                elif lang in ['en', 'ru', 'fr', 'de', 'es', 'it', 'pt'] and cand == en_pattern:
                                    score += 0.05
                                    
                                if score > best_score:
                                    best_score = score
                                    best_text = cand
                                    
                            text_raw = best_text
                    
                        # --- 時間・数値主体のテキストは翻訳をスキップ ---
                        if is_time_sensitive(text_raw):
                            # print(f"[Discard:TimeSensitive] {text_raw}")
                            self.active_translations[cid] = True
                            continue
                        
                        # --- 単語辞書フィルター: 1〜2語の短文でどの辞書にも存在しない場合は即破棄 ---
                        # プレイヤー名 (danger00, amachi等) やUIゴミ (I I I I等) をAPIに送る前に弾く
                        if _word_filter_discard(text_raw):
                            print(f"[Discard:WordFilter] {text_raw}")
                            target_lang_wf = self.config.get("target_language", "ja")
                            cache_key_wf = f"{target_lang_wf}::{text_raw}"
                            existing_wf = self.translation_cache.get(cache_key_wf, "")
                            if existing_wf not in ("__IGNORE__", "__IGNORE_1__", "__IGNORE_2__"):
                                _SOFT_IGNORE_MAP_WF = {"": "__IGNORE_1__", "__IGNORE_1__": "__IGNORE_2__", "__IGNORE_2__": "__IGNORE__"}
                                strike_wf = _SOFT_IGNORE_MAP_WF.get(existing_wf, "__IGNORE__")
                                self.translation_cache[cache_key_wf] = strike_wf
                                self._cache_dirty = True
                                # print(f"[WordFilter] 辞書外: '{text_raw[:30]}' → {strike_wf}")
                            self.active_translations[cid] = True
                            continue
                        
                        if text_raw in self.pending_texts:
                            self.active_translations[cid] = True
                            self.overlay.update_translation_position(cid, chunk['rect'])
                            continue
                        
                        # キャッシュ検索 (1. 完全一致, 2. 正規化完全一致, 3. 曖昧一致)
                        target_lang = self.config.get("target_language", "ja")
                        cache_key = f"{target_lang}::{text_raw}"
                        
                        found_trans = self.translation_cache.get(cache_key)
                            
                        if not found_trans:
                            norm_target = normalize_text(text_raw)
                            if len(norm_target) > 2:
                                best_ratio = 0.0
                                best_cv = None
                                for ck, cv in list(self.translation_cache.items()):
                                    if not ck.startswith(f"{target_lang}::"): continue
                                    ck_text = ck.split("::", 1)[1]
                                    norm_ck = normalize_text(ck_text)
                                    
                                    # --- 段階2: 正規化後の完全一致 (全長のテキストで許可) ---
                                    if norm_ck == norm_target:
                                        found_trans = cv
                                        break
                                    
                                    # --- 2秒間スキップガード（重複計算防止） ---
                                    # text_raw が確実に文字列であることを担保してハッシュ化
                                    t_hash = hashlib.md5(str(text_raw).encode('utf-8')).hexdigest()
                                    if time.time() < getattr(self, "_skip_2s_cache", {}).get(t_hash, 0):
                                        break
    
                                    # 文字数が大幅に異なるものはスキップ（速度対策）
                                    len_ratio = len(norm_target) / max(len(norm_ck), 1)
                                    if not (0.5 <= len_ratio <= 2.0):
                                        continue
                                    ratio = SequenceMatcher(None, norm_target, norm_ck).ratio()
                                    if ratio > best_ratio:
                                        best_ratio = ratio
                                        best_cv = cv
                                
                                # 段階3の結果: 曖昧検索をさらに厳格化（20文字以上の長文かつ99%以上のみ）
                                if not found_trans and len(norm_target) >= 20 and best_ratio >= 0.99:
                                    found_trans = best_cv
                                    print(f"[Cache] Fuzzy match: ratio={best_ratio:.2f}, text='{text_raw[:30]}'...")
                                    # 2秒間はこのテキストのFuzzy判定をスキップ
                                    if not hasattr(self, "_skip_2s_cache"): self._skip_2s_cache = {}
                                    t_hash = hashlib.md5(str(text_raw).encode('utf-8')).hexdigest()
                                    self._skip_2s_cache[t_hash] = time.time() + 2.0
    
                        if found_trans:
                            # ソフトIGNOREはヒットとみなさずリトライ（Nストライク制）
                            if found_trans in ("__IGNORE_1__", "__IGNORE_2__"):
                                new_chunks.append(chunk)
                                continue
                            
                            # --- 永久IGNOREのfastText再評価 ---
                            # 毎フレーム判定すると重いため、前回の判定から一定時間空ける
                            if found_trans == "__IGNORE__":
                                cache_time_key = f"last_eval_{cache_key}"
                                last_eval = getattr(self, "_last_eval_times", {}).get(cache_time_key, 0)
                                
                                if now - last_eval > 10.0:
                                    if not hasattr(self, "_last_eval_times"): self._last_eval_times = {}
                                    self._last_eval_times[cache_time_key] = now
                                    
                                    ocr_hint = chunk.get('lang', 'en').split('-')[0].lower()
                                    _, lang_conf = detect_source_language(text_raw, ocr_lang_hint=ocr_hint)
                                    if lang_conf >= 0.70:
                                        # 明確に自然言語として高信頼(0.7以上)の場合のみ再試行を許可
                                        if cache_key in self.translation_cache:
                                            self.translation_cache[cache_key] = "__IGNORE_1__"
                                            self._cache_dirty = True
                                            print(f"[Cache] IGNORE→IGNORE_1 降格（fastText再評価 conf={lang_conf:.2f}）: '{text_raw[:30]}'")
                                        new_chunks.append(chunk)
                                        continue
                                
                                # 信頼度低（真のゴミテキスト）または待機時間中 → 永久IGNOREを維持
                                self.active_translations[cid] = True
                                continue
                            
                            # --- 既存翻訳の品質チェック (事後リフレッシュ) ---
                            is_valid_cached = True
                            _ref_reason = ""
                            
                            # 判定A: 要約チェック (原文 > 60文字 かつ 翻訳 < 25%)
                            if len(text_raw) > 60:
                                if len(found_trans) < len(text_raw) * 0.25:
                                    is_valid_cached = False
                                    _ref_reason = "要約の疑い"
                            
                            # 判定B: 前置き混入チェック
                            if is_valid_cached:
                                preambles = ["はい、", "もちろん、", "翻訳案", "翻訳結果"]
                                if any(p in found_trans[:15] for p in preambles):
                                    is_valid_cached = False
                                    _ref_reason = "前置きの混入"
                                    
                            if not is_valid_cached:
                                print(f"[Cache] 既存キャッシュを破棄し再翻訳（{_ref_reason}）: '{text_raw[:30]}'")
                                new_chunks.append(chunk)
                                continue
                            
                            # キャッシュヒット時の順序更新
                            if cache_key in self.translation_cache:
                                self.translation_cache.move_to_end(cache_key)
                            
                            self.active_translations[cid] = True
                            # 保存されたフォントサイズがあれば渡す
                            stored_fs = self.overlay_state.get(cid, {}).get('font_size')
                            self.overlay.show_translation(cid, chunk, found_trans, target_lang, font_size=stored_fs)
                            # font_size ・ 追従テンプレートを引き継いで上書き消失・ゴースト消え残りを防ぐ
                            existing_state = self.overlay_state.get(cid, {})
                            self.overlay_state[cid] = {
                                "text": found_trans,
                                "raw_text": text_raw,
                                "rect": chunk["rect"],
                                "bg_color": chunk.get("bg_color", "rgba(0,0,0,1.0)"),
                                "text_color": "#ffffff",
                                "lines_count": chunk.get("lines_count", 1),
                                # image=None（エコモード早期リターン等）の場合は再計算せず既存値を引き継ぐ
                                "base_density": self.ocr.calculate_edge_density(image, chunk['rect']) if image is not None else existing_state.get("base_density", chunk.get("base_density", 0.0)),
                                "font_size": stored_fs,
                                "mismatch_strikes": existing_state.get("mismatch_strikes", 0),
                                "change_strikes": existing_state.get("change_strikes", 0),
                                # 追従用テンプレート: Numpy配列のor評価バグを防ぐため is not None で確認
                                "parent_rect": chunk.get("parent_rect") if chunk.get("parent_rect") is not None else existing_state.get("parent_rect"),
                                "step3_crop": chunk.get("step3_crop") if chunk.get("step3_crop") is not None else existing_state.get("step3_crop"),
                                # 初回表示時刻: 既に表示中なら引き継ぐ（長期ゴースト検証用）
                                "_display_start": existing_state.get("_display_start", time.time()),
                            }
                        else:
                            new_chunks.append(chunk)
    
                # ──────────────────────────────────────────────────────
                # 【ダブルチェック】翻訳送信直前の座標重複フィルター
                # 現在 overlay_state に表示中の矩形と比較して
                # 「重なっており、かつ自分が小さい」ならば翻訳に送らない。
                # OCR→吸収チェック→フリッカーチェックをすり抜けたゴミの最終防衛ライン。
                # ──────────────────────────────────────────────────────
                final_new_chunks = []
                for chunk in new_chunks:
                    r1 = chunk['rect']
                    area1 = max(1, r1['w'] * r1['h'])
                    is_shadowed = False
                    for state in self.overlay_state.values():
                        r2 = state['rect']
                        area2 = max(1, r2['w'] * r2['h'])
                        # ① まず重なりを計算
                        ix = max(0, min(r1['x'] + r1['w'], r2['x'] + r2['w']) - max(r1['x'], r2['x']))
                        iy = max(0, min(r1['y'] + r1['h'], r2['y'] + r2['h']) - max(r1['y'], r2['y']))
                        ioa = (ix * iy) / area1  # 自分の面積に対する重複率
                        if ioa < 0.4:
                            continue  # 重なっていなければ大きさ比較不要
                        # ② 重なっている → 自分が小さい場合のみスキップ
                        if area1 < area2 * 0.7:
                            is_shadowed = True
                            # ログの氾濫を防ぐためのスキップキャッシュ
                            shadow_key = f"shadow_{chunk['text']}"
                            if current_time - self._shadow_skip_cache.get(shadow_key, 0) > 2.0:
                                self._shadow_skip_cache[shadow_key] = current_time
                                print(f"[DblCheck] 表示中の大きな枠に重なり({ioa:.0%})かつ小さい({area1:.0f}<{area2:.0f})ため翻訳スキップ: '{chunk['text'][:30]}'")
                            break
                    if not is_shadowed:
                        final_new_chunks.append(chunk)
                # ステータス情報の更新準備
                backlog = self.translator.backlog_count
                latency = self.translator.avg_latency
    
                # ワンショット翻訳モード：新しく見つかったものをバックログに追加
                if is_single and new_chunks:
                    for c in new_chunks:
                        # Translator が「有効なチャンク」と認識できるように登録
                        self.active_translations[c['id']] = c
                    
                    self._single_scan_backlog.extend(new_chunks)
                    # 長文優先でソート
                    self._single_scan_backlog.sort(key=lambda c: len(c.get('text', '')), reverse=True)
                    print(f"[OneShot] バックログに追加: {len(new_chunks)}件 (合計: {len(self._single_scan_backlog)}件)")
                    new_chunks = []
                
                new_chunks = final_new_chunks if not is_single else []
    
    
                # ステータス表示の一括統合
                self._update_status()
    
                # 【ノイズフィルタ & 重複排除】
                # ゴミデータを早期に捨て、同じ内容のテキストが複数回翻訳に回るのを防ぐ
                filtered = []
                seen_in_this_batch = set()
                now = time.time()
                
                # 短寿命キャッシュ（2秒間）でループをブロック
                if not hasattr(self, "_recent_texts"):
                    self._recent_texts = {}
                # 古い履歴を掃除
                self._recent_texts = {k: v for k, v in self._recent_texts.items() if now - v < 2.0}
    
                for c in new_chunks:
                    text = c.get('text', '').strip()
                    if not text:
                        continue
                    
                    # 1. ゴミ排除（1文字の記号のみ、または極小チャンク）
                    if len(text) == 1 and not text.isalnum():
                        continue
                    if c['rect']['w'] < 8 or c['rect']['h'] < 8:
                        continue
                        
                    # 2. バッチ内（今回のOCR結果）での重複排除
                    if text in seen_in_this_batch:
                        continue
                    seen_in_this_batch.add(text)
                    
                    # 3. 翻訳待ち（pending）との重複排除
                    if text in self.pending_texts:
                        continue
                        
                    # 4. 直近2秒間に処理したテキストとの重複排除
                    if text in self._recent_texts:
                        continue
                        
                    # 生き残ったテキストを登録して追加
                    self._recent_texts[text] = now
                    filtered.append(c)
                    
                new_chunks = filtered
    
                # チャンク数制限 (新規追加がある場合のみ)
                if new_chunks and len(new_chunks) > 30:
                    print(f"[Queue] Too many chunks ({len(new_chunks)}), limiting to top 30.")
                    new_chunks.sort(key=lambda c: (len(c['text']), c['rect']['w']*c['rect']['h']), reverse=True)
                    new_chunks = new_chunks[:30]
                
                if new_chunks:
                    # 【優先順位付け】新しく発見された長文・大きなフォントを優先
                    new_chunks.sort(key=lambda c: (len(c['text']), c['rect']['h']), reverse=True)
                    
                    # 【動的スロットリング】バックログとLatencyに応じた送信制御
                    current_time = time.time()
                    
                    # 1. 緊急停止ロジック: キューが溜まりすぎている場合は新規送信を完全に止める
                    if not is_single and backlog > 20:
                        self._update_status("高負荷：キューを消化中...")
                        return
    
                    # 送信可能枠の計算
                    if is_single:
                        MAX_TO_SEND = 100
                    elif backlog > 10:
                        MAX_TO_SEND = 1
                    elif backlog > 3:
                        MAX_TO_SEND = 2
                    else:
                        MAX_TO_SEND = 3
                        
                    chunks_to_send_raw = new_chunks[:MAX_TO_SEND]
                
                    # 【短文の流量制限】負荷時はさらに厳しく
                    chunks_to_send = []
                    for chunk in chunks_to_send_raw:
                        text = chunk['text'].strip()
                        is_short = len(text) <= 15 or len(text.split()) <= 2
                        if is_short:
                            limit_sec = max(5.0, latency * 1.5) if backlog > 5 else 3.0
                            if current_time - getattr(self, 'last_short_word_time', 0) < limit_sec:
                                continue
                            else:
                                self.last_short_word_time = current_time
                        chunks_to_send.append(chunk)
    
                    if chunks_to_send:
                        # ステータス更新 & 翻訳依頼の送信
                        self._update_status(f"翻訳中... (新規: {len(chunks_to_send)}個)")
                        self.last_request_time = time.time()
                        
                        # --- スマート・テキスト・フィルター (v1.1.4) ---
                        final_chunks_to_send = []
                        for chunk in chunks_to_send:
                            cid = chunk['id']
                            text_raw = chunk['text'].strip()
                            
                            # すでに表示中のテキスト（原文）と比較
                            if cid in self.overlay_state:
                                old_text_raw = self.overlay_state[cid].get('text_raw', '')
                                if old_text_raw:
                                    # 類似度計算（0.0 〜 1.0）
                                    sim = fuzz.ratio(text_raw, old_text_raw) / 100.0
                                    
                                    # 判定しきい値（短い文は厳しめに）
                                    threshold = 0.95 if len(text_raw) < 10 else 0.90
                                    
                                    if sim >= threshold:
                                        # 類似度が高い場合は翻訳リクエストをスキップ
                                        # ただしID追跡のために active_translations には残しておく
                                        # print(f"[SmartFilter] Skip: '{text_raw[:20]}...' (Sim: {sim:.2f} >= {threshold})")
                                        self.active_translations[cid] = chunk
                                        continue
                            
                            final_chunks_to_send.append(chunk)
                        
                        for chunk in final_chunks_to_send:
                            self.active_translations[chunk['id']] = chunk
                            self.pending_texts.add(chunk['text'].strip())
                            
                            ocr_hint = chunk.get('lang', 'en').split('-')[0].lower()
                            detected_lang, lang_conf = detect_source_language(chunk['text'], ocr_lang_hint=ocr_hint)
                            chunk['detected_source_lang'] = detected_lang
                            
                            # --- 低信頼度チェック ---
                            if lang_conf < 0.35:
                                # (略：キャッシュへの pre-strike 処理)
                                pass
                            
                            check_active = lambda cid=chunk['id']: cid in getattr(self, "active_translations", {})
                            self.translator.translate_single_async(chunk, self._on_single_translation_done, is_active_check=check_active)

        except Exception as e:
            print(f"[Queue Error] _poll_ocr_result failed: {e}")
            traceback.print_exc()

        # ────── 以下、OCRの結果がなくても毎フレーム実行すべき補充と状態管理 ──────
        is_single = self.config.get("single_mode", False)
        if is_single and not getattr(self, "_single_scan_backlog", []):
            if not getattr(self, "_ocr_busy", True) and getattr(self, "_last_ocr_exec_time", 0) > 0:
                self._single_run_done_candidate = True

        try:
            if self.config.get("single_mode", False):
                # 送信情報の再取得
                backlog = self.translator.backlog_count
                
                # 補充が必要かチェック
                if backlog < 3 and self._single_scan_backlog:
                    # 長文優先でソート
                    self._single_scan_backlog.sort(key=lambda c: len(c.get('text', '')), reverse=True)
                    
                    batch_size = 3 - backlog
                    to_send = self._single_scan_backlog[:batch_size]
                    self._single_scan_backlog = self._single_scan_backlog[batch_size:]
                    
                    print(f"[OneShot] パイプライン補充: {len(to_send)}件 (現在実行中: {backlog + len(to_send)}件, 残り: {len(self._single_scan_backlog)}件)")
                    
                    for chunk in to_send:
                        check_active = lambda cid=chunk['id']: cid in getattr(self, "active_translations", {})
                        self.translator.translate_single_async(chunk, self._on_single_translation_done, is_active_check=check_active)
                
                elif not self._single_scan_backlog and backlog == 0 and getattr(self, "_single_run_done_candidate", False):
                    if not self._single_run_done:
                        self._single_run_done = True
                        print("[OneShot] 全件の翻訳が完了しました。")

        except Exception as e:
            print(f"[Queue Maintenance Error] {e}")

    def _on_font_size_calculated(self, cid, font_size):
        """UI側で計算されたフォントサイズを保存する"""
        with self._lock:
            if cid in self.overlay_state:
                self.overlay_state[cid]['font_size'] = font_size

    def _on_single_translation_done(self, chunk, translated_text):
        # 処理が完了したのでpendingから削除
        text_raw = chunk['text'].strip()
        self.pending_texts.discard(text_raw)
        
        if not self.is_running:
            return
            
        target_lang = self.config.get("target_language", "ja")
        
        # --- デバッグ: クリーンアップ前の翻訳結果を記録 ---
        _raw_translated = translated_text
        
        # --- 翻訳結果のクリーンアップ (余計なラベルや解説の除去) ---
        translated_text = cleanup_translation(translated_text, target_lang, source_text=text_raw)
        
        # クリーンアップで変化があった場合はログ出力
        if _raw_translated != translated_text:
            print(f"[Cleanup] '{text_raw[:25]}' → 変換前: '{_raw_translated[:50]}' / 変換後: '{translated_text[:50]}'")
        
        base_tgt = target_lang.split("-")[0].lower()
        
        # --- 翻訳結果のフィルタリング ---
        is_valid = True
        _fail_reason = ""  # デバッグ用失敗理由

        # 初間チェック: 原文とまったく同じなら未翻訳
        if translated_text.strip() == chunk['text'].strip():
            is_valid = False
            _fail_reason = "原文と同一"

        if is_valid:
            if base_tgt == 'ja':
                if not re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', translated_text):
                    # 日本語文字が全くない場合は fastText で補助判定
                    if not _ft_validate_translation(translated_text, target_lang):
                        is_valid = False
                        _fail_reason = f"日本語文字なし+fastText失敗"
            elif base_tgt == 'zh':
                if not re.search(r'[\u4e00-\u9fff]', translated_text):
                    if not _ft_validate_translation(translated_text, target_lang):
                        is_valid = False
                        _fail_reason = "中国語文字なし+fastText失敗"
            elif base_tgt == 'ko':
                if not re.search(r'[\uac00-\ud7a3]', translated_text):
                    if not _ft_validate_translation(translated_text, target_lang):
                        is_valid = False
                        _fail_reason = "ハングルなし+fastText失敗"
            elif base_tgt == 'ru':
                if not re.search(r'[\u0410-\u044f\u0401\u0451]', translated_text):
                    if not _ft_validate_translation(translated_text, target_lang):
                        is_valid = False
                        _fail_reason = "キリル文字なし+fastText失敗"
            else:
                if not _ft_validate_translation(translated_text, target_lang):
                    is_valid = False
                    _fail_reason = "fastText失敗（ラテン系ターゲット）"
        
        # winrt_only モードの追加バリデーション:
        # PaddleOCRによる精査がない分、誤認識テキストの翻訳結果が混入しやすいため、
        # fastText で翻訳結果が明確にターゲット言語であることを確認し、そうでなければスキップする
        if is_valid and self.config.get("ocr_engine_mode", "hybrid") == "winrt_only":
            if not _ft_validate_translation(translated_text, target_lang):
                is_valid = False
                _fail_reason = "winrt_only: fastText厳格バリデーション失敗"
                print(f"[WinRT-Validator] ❌ スキップ: '{translated_text[:50]}'... ({_fail_reason})")
                
        # AIの翻訳拒否・誤動作メッセージ
        refusal_keywords = [
            "意味不明", "翻訳する必要がある", "翻訳できません", "正確な翻訳はできません",
            "数字や記号の組み合わせ", "翻訳する内容", "該当する言葉", "不明な文字列",
            "英語\n", "\n日本語\n", "English\n", "\nJapanese",
        ]
        for kw in refusal_keywords:
            if kw in translated_text:
                is_valid = False
                _fail_reason = f"拒否キーワード検出: '{kw}'"
                break
        
        # 言語名のみの返答チェック
        _lang_name_only = re.fullmatch(
            r'\s*(英語|日本語|イタリア語|フランス語|スペイン語|ドイツ語|中国語|韓国語|'
            r'English|Japanese|Italian|French|Spanish|German|Chinese|Korean)'
            r'(\s*[\n,/]\s*(英語|日本語|イタリア語|フランス語|スペイン語|ドイツ語|中国語|韓国語|'
            r'English|Japanese|Italian|French|Spanish|German|Chinese|Korean))*\s*',
            translated_text
        )
        if _lang_name_only:
            is_valid = False
            _fail_reason = "言語名のみの返答"

        # ハルシネーション（無駄な前置きや長文暴走）
        original_len = len(chunk['text'])
        translated_len = len(translated_text)
        source_lang = chunk.get("lang", "en-US")
        base_src = source_lang.split("-")[0].lower()
        
        is_src_logo = base_src in ["ja", "zh"]
        is_tgt_logo = base_tgt in ["ja", "zh"]
        
        if is_src_logo and not is_tgt_logo:
            max_allowed_len = original_len * 5.5 + 20
        elif not is_src_logo and is_tgt_logo:
            max_allowed_len = original_len * 2.8 + 20
        elif is_src_logo and is_tgt_logo:
            max_allowed_len = original_len * 3.2 + 20
        else:
            max_allowed_len = original_len * 4.0 + 30

        if translated_len > max_allowed_len:
            is_valid = False
            _fail_reason = f"長すぎる（{translated_len} > max={max_allowed_len:.0f}, src={original_len}）"
            
        # --- 最小長チェック (要約・手抜き翻訳の検出) ---
        if is_valid and original_len > 60:
            # 日本語ターゲットの場合、イタリア語等のラテン文字に対して文字数は少なめになるが
            # 25%未満は明らかに情報が欠落している（要約されている）可能性が高い
            min_allowed_len = original_len * 0.25
            if translated_len < min_allowed_len:
                is_valid = False
                _fail_reason = f"短すぎる（{translated_len} < min={min_allowed_len:.0f}, src={original_len}）"

        
        # 最終的な空チェック
        if is_valid and not translated_text.strip():
            is_valid = False
            _fail_reason = "翻訳結果が空（クリーンアップ後）"
        
        # 失敗時は詳細ログ出力
        if not is_valid:
            print(f"[Validator] ❌ 失敗理由='{_fail_reason}' | src='{text_raw[:40]}' | result='{translated_text[:60]}'")

            
        # Nストライク制: 失敗のたびにストライク数を増やし、3回で永久IGNORE
        # __IGNORE_1__ / __IGNORE_2__ は「仮IGNORE（リトライ許可）」、__IGNORE__ は「永久IGNORE」
        _SOFT_IGNORE_MAP = {
            "": "__IGNORE_1__",
            "__IGNORE_1__": "__IGNORE_2__",
            "__IGNORE_2__": "__IGNORE__",
        }
        
        cache_key = f"{target_lang}::{chunk['text'].strip()}"
        if is_valid:
            final_translation = translated_text
        else:
            # 既存のストライク状態を確認してカウントアップ
            existing = self.translation_cache.get(cache_key, "")

            # 既に永久IGNOREなら据え置き
            if existing == "__IGNORE__":
                final_translation = "__IGNORE__"
            else:
                # 空（初回）または仮IGNORE → 次のストライクへ
                final_translation = _SOFT_IGNORE_MAP.get(existing, "__IGNORE__")
            print(f"[Cache] Strike recorded: '{chunk['text'][:30]}' → {final_translation}")
            
        with self._lock:
            # 【最重要：画面に無い長文でも必ずキャッシュに記録する】
            # (次回表示時に正規化一致で救えるようにするため、原文のまま保存)
            self.translation_cache[cache_key] = final_translation
            self.translation_cache.move_to_end(cache_key)
            
            if len(self.translation_cache) > 2000:
                self.translation_cache.popitem(last=False)
                
            self._cache_dirty = True
            
            # コールバック時点での表示処理
            if is_valid:
                text_clean = chunk['text'].strip()
                norm_clean = normalize_text(text_clean)
                
                # ブラックリストチェック
                if hasattr(self, "_recent_cleared_texts"):
                    expiry = self._recent_cleared_texts.get(norm_clean, 0)
                    if time.time() < expiry:
                        print(f"[Broadcast] ❌ スキップ: 消去されたばかりのテキストです: '{text_clean[:30]}'")
                        return

                is_single = self.config.get("single_mode", False)
                for active_cid in list(self.active_translations.keys()):
                    # 通常モードでは、すでに画面から消えている（現在のフレームに存在しない）枠には描画しない
                    # シングルモードでは、監視を止めているため current_ids 判定をスキップする
                    if not is_single and active_cid not in getattr(self, "current_ids", set()):
                        if active_cid in self.active_translations:
                            print(f"[Broadcast] ❌ 破棄: 描画前に枠が消失しました ID={active_cid}")
                            del self.active_translations[active_cid]
                        continue
                        
                    ac_chunk = self.history_chunks.get(active_cid)
                    if ac_chunk and ac_chunk['text'].strip() == text_clean:
                        # 【位置の解決】翻訳リクエスト後に追従した最新座標を優先して使う
                        # 優先順位: overlay_state（テンプレート追従）> history_chunks（最終OCR）> ac_chunk（リクエスト時点）
                        latest_rect = None
                        if active_cid in self.overlay_state:
                            latest_rect = self.overlay_state[active_cid].get('rect')
                        if latest_rect is None and active_cid in self.history_chunks:
                            latest_rect = self.history_chunks[active_cid].get('rect')
                        if latest_rect is not None:
                            ac_chunk = dict(ac_chunk)  # 元のchunkを書き換えないようにコピー
                            ac_chunk['rect'] = latest_rect
                        
                        # 保存されたフォントサイズがあれば渡す
                        stored_fs = self.overlay_state.get(active_cid, {}).get('font_size')
                        self.overlay.show_translation(active_cid, ac_chunk, final_translation, target_lang, font_size=stored_fs)
                        
                        # font_size・追従テンプレートを引き継いで上書き消失を防ぐ
                        # step3_crop と parent_rect を必ず保持することで、翻訳後もテンプレートマッチ追従が機能する
                        existing_state = self.overlay_state.get(active_cid, {})
                        self.overlay_state[active_cid] = {
                            "text": final_translation,
                            "text_raw": text_clean,
                            "rect": ac_chunk["rect"],
                            "bg_color": ac_chunk.get("bg_color", "rgba(0,0,0,1.0)"),
                            "text_color": ac_chunk.get("text_color", "#eeeeee"),
                            "lines_count": ac_chunk.get("lines_count", 1),
                            "base_density": ac_chunk.get("base_density", 0.0),
                            "last_seen": time.time(),
                            "existence_history": [1, 1, 1, 1, 1, 1],
                            "mismatch_strikes": 0,
                            "change_strikes": 0,
                            "font_size": stored_fs,
                            # 追従用テンプレート: チャンクから取得し、なければ既存ステートから引き継ぐ
                            "step3_crop": ac_chunk.get("step3_crop") if ac_chunk.get("step3_crop") is not None else existing_state.get("step3_crop"),
                            "parent_rect": ac_chunk.get("parent_rect") if ac_chunk.get("parent_rect") is not None else existing_state.get("parent_rect"),
                            # 初回表示時刻: 既に表示中なら引き継ぐ（長期ゴースト検証用）
                            "_display_start": existing_state.get("_display_start", time.time()),
                        }


class ControlPanel(QMainWindow):
    """メインのコントロールパネル（設定画面）"""
    
    # API 経由での制御用シグナル
    sig_start_translation = pyqtSignal()
    sig_stop_translation = pyqtSignal()
    sig_force_retranslate = pyqtSignal()
    sig_toggle_translation = pyqtSignal()
    
    def __init__(self, config_path: str):
        super().__init__()
        self.config_path = config_path
        self.config = load_config(config_path)
        self.controller = None
        
        # self.init_ui()  # <- これがエラーの原因だったので削除
        
        # APIシグナルの接続
        self.sig_start_translation.connect(self.start_translation)
        self.sig_stop_translation.connect(self.stop_translation)
        self.sig_force_retranslate.connect(self.force_retranslate)
        self.sig_toggle_translation.connect(self.toggle_translation)
        
        self._initializing = True  # UI構築中の重複イベントを抑制
        self._setup_window()
        self._setup_ui()
        self._init_controller()
        self._initializing = False

        # ステータス表示の自動更新タイマー（2秒おきに最新の状態を確認）
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._refresh_status_labels)
        self.status_timer.start(2000)

        
    def _setup_window(self):
        self.setWindowTitle("Real Time Translate - Control Panel v1.3.1")
        self.setFixedSize(560, 640)
        
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        # 0. モデル設定エリア
        model_layout = QHBoxLayout()
        model_label = QLabel("使用モデル:")
        model_label.setFont(QFont("Yu Gothic UI", 10, QFont.Weight.Bold))
        model_layout.addWidget(model_label)
        
        self.model_combo = QComboBox()
        self.model_combo.setFont(QFont("Yu Gothic UI", 10))
        self.model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        
        # モデルリスト取得して追加
        ollama_url = self.config.get("ollama_url", "http://localhost:11434")
        provider = self.config.get("local_llm_provider", "ollama")
        models = Translator.get_available_models(ollama_url, provider=provider)
        if not models:
            models = ["translategemma:4b"] # 取得失敗時のフォールバック
            
        for m in models:
            self.model_combo.addItem(m)
            
        saved_model = self.config.get("ollama_model", "translategemma:4b")
        if saved_model in models:
            self.model_combo.setCurrentText(saved_model)
        else:
            self.model_combo.addItem(saved_model)
            self.model_combo.setCurrentText(saved_model)
            
        model_layout.addWidget(self.model_combo, stretch=1)
        layout.addLayout(model_layout)


        # 0.5 PaddleOCR & GPU 設定エリア
        paddle_group = QGroupBox("高精度OCR設定 (PaddleOCR)")
        paddle_group.setFont(QFont("Yu Gothic UI", 9))
        paddle_group.setStyleSheet("""
            QGroupBox {
                color: #aaaaaa;
                border: 1px solid #555;
                border-radius: 4px;
                margin-top: 6px;
                padding: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
        """)
        paddle_layout = QVBoxLayout(paddle_group)
        paddle_layout.setSpacing(4)
        paddle_layout.setContentsMargins(8, 8, 8, 6)

        # OCRエンジンモード選択 (内部的に dual_scout_hybrid に固定)
        paddle_top = QHBoxLayout()
        ocr_mode_label = QLabel("OCRモード: ハイブリッド (WinRT+Paddle)")
        ocr_mode_label.setFont(QFont("Yu Gothic UI", 9, QFont.Weight.Bold))
        ocr_mode_label.setStyleSheet("color: #00ffcc;")
        paddle_top.addWidget(ocr_mode_label)
        
        # UIパーツは参照だけ残す（エラー防止）
        self.combo_ocr_mode = QComboBox()
        self.combo_ocr_mode.addItem("統合索敵ハイブリッド", "dual_scout_hybrid")
        self.combo_ocr_mode.setCurrentIndex(0)
        self.config["ocr_engine_mode"] = "dual_scout_hybrid"

        # fastText ガードレール状態表示
        self.lbl_langcheck = QLabel(lang_check_status())
        self.lbl_langcheck.setFont(QFont("Yu Gothic UI", 8))
        self.lbl_langcheck.setStyleSheet("color: #aaaaaa;")
        paddle_top.addWidget(self.lbl_langcheck)
        paddle_layout.addLayout(paddle_top)

        # GPU選択 & メモリ設定
        gpu_row = QHBoxLayout()
        gpu_label = QLabel("使用GPU:")
        gpu_label.setFont(QFont("Yu Gothic UI", 9))
        gpu_row.addWidget(gpu_label)

        self.gpu_combo = QComboBox()
        self.gpu_combo.setFont(QFont("Yu Gothic UI", 9))
        self._gpu_list = get_available_gpus()
        for gpu in self._gpu_list:
            vram_str = f" ({gpu['vram_mb']}MB)" if gpu['vram_mb'] > 0 else ""
            self.gpu_combo.addItem(f"{gpu['name']}{vram_str}")
        saved_gpu_idx = self.config.get("paddle_gpu_index", 0)
        if 0 <= saved_gpu_idx < self.gpu_combo.count():
            self.gpu_combo.setCurrentIndex(saved_gpu_idx)
        gpu_row.addWidget(self.gpu_combo, stretch=1)

        mem_label = QLabel("VRAMlimit:")
        mem_label.setFont(QFont("Yu Gothic UI", 9))
        gpu_row.addWidget(mem_label)

        self.spin_gpu_mem = QSpinBox()
        self.spin_gpu_mem.setFont(QFont("Yu Gothic UI", 9))
        self.spin_gpu_mem.setRange(256, 8192)
        self.spin_gpu_mem.setSingleStep(256)
        self.spin_gpu_mem.setValue(self.config.get("paddle_gpu_mem_mb", 1500))
        self.spin_gpu_mem.setSuffix(" MB")
        self.spin_gpu_mem.setFixedWidth(100)
        gpu_row.addWidget(self.spin_gpu_mem)
        paddle_layout.addLayout(gpu_row)

        # PaddleOCR 専門言語設定
        paddle_lang_row = QHBoxLayout()
        paddle_lang_label = QLabel("Paddle専門言語:")
        paddle_lang_label.setFont(QFont("Yu Gothic UI", 9))
        paddle_lang_row.addWidget(paddle_lang_label)

        self.paddle_lang_combo = QComboBox()
        self.paddle_lang_combo.setFont(QFont("Yu Gothic UI", 9))
        self.paddle_langs = {
            "日本語 (JA/EN)": "japan",
            "英語 (EN)": "en",
            "韓国語 (KO)": "korean",
            "中国語 (ZH)": "ch",
            "ロシア語 (RU)": "cyrillic",
            "欧州諸語 (Latin)": "latin"
        }
        for label in self.paddle_langs.keys():
            self.paddle_lang_combo.addItem(label)
        
        saved_p_lang = self.config.get("paddle_language", "japan")
        for label, val in self.paddle_langs.items():
            if val == saved_p_lang:
                self.paddle_lang_combo.setCurrentText(label)
                break
        paddle_lang_row.addWidget(self.paddle_lang_combo, stretch=1)
        
        self.lbl_paddle_status = QLabel("PaddleOCR 待機中")
        self.lbl_paddle_status.setFont(QFont("Yu Gothic UI", 8))
        self.lbl_paddle_status.setStyleSheet("color: #00ff00;")
        paddle_lang_row.addWidget(self.lbl_paddle_status)
        paddle_layout.addLayout(paddle_lang_row)

        # PaddleOCR の動作ステータス表示
        self.lbl_paddle_status = QLabel("待機中...")
        self.lbl_paddle_status.setFont(QFont("Yu Gothic UI", 8))
        self.lbl_paddle_status.setStyleSheet("color: #aaaaaa;")
        paddle_layout.addWidget(self.lbl_paddle_status)

        # TensorRT 有効化設定
        self.chk_tensorrt = QCheckBox("NVIDIA TensorRT を有効にする (高速化)")
        self.chk_tensorrt.setFont(QFont("Yu Gothic UI", 9))
        self.chk_tensorrt.setStyleSheet("color: #00ffcc;")
        self.chk_tensorrt.setChecked(self.config.get("use_tensorrt", False))
        def on_trt_changed(state):
            self.config["use_tensorrt"] = (state == 2)
            save_config(self.config, self.config_path)
        self.chk_tensorrt.stateChanged.connect(on_trt_changed)
        paddle_layout.addWidget(self.chk_tensorrt)

        # GPU 前処理設定
        self.chk_gpu_pre = QCheckBox("GPU 前処理を有効にする (Cupyが必要)")
        self.chk_gpu_pre.setFont(QFont("Yu Gothic UI", 9))
        self.chk_gpu_pre.setStyleSheet("color: #00ffcc;")
        self.chk_gpu_pre.setChecked(self.config.get("use_gpu_preprocess", False))
        def on_gpu_pre_changed(state):
            self.config["use_gpu_preprocess"] = (state == 2)
            save_config(self.config, self.config_path)
        self.chk_gpu_pre.stateChanged.connect(on_gpu_pre_changed)
        paddle_layout.addWidget(self.chk_gpu_pre)

        layout.addWidget(paddle_group)

        # モードに合わせてGPU設定の有効/無効を初期化
        self._on_ocr_mode_changed(self.combo_ocr_mode.currentIndex())

        # ステータス表示の初期化
        self._refresh_status_labels()

        # ===== 案B: WinRT OCR 言語選択チェックボックス =====
        lang_ocr_group = QGroupBox("OCR読み取り言語 (WinRT)")
        lang_ocr_group.setFont(QFont("Yu Gothic UI", 9))
        lang_ocr_group.setStyleSheet("""
            QGroupBox {
                color: #aaaaaa;
                border: 1px solid #555;
                border-radius: 4px;
                margin-top: 6px;
                padding: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
        """)
        lang_ocr_layout = QHBoxLayout(lang_ocr_group)
        lang_ocr_layout.setContentsMargins(8, 8, 8, 6)
        lang_ocr_layout.setSpacing(10)
        
        saved_ocr_langs = set(self.config.get("ocr_languages", [lang for _, lang in ALL_OCR_LANGUAGES]))
        self._ocr_lang_checkboxes = {}  # tag -> QCheckBox
        for label, tag in ALL_OCR_LANGUAGES:
            cb = QCheckBox(label)
            cb.setFont(QFont("Yu Gothic UI", 8))
            cb.setChecked(tag in saved_ocr_langs)
            lang_ocr_layout.addWidget(cb)
            self._ocr_lang_checkboxes[tag] = cb
        
        self.lang_ocr_group = lang_ocr_group
        # 初期状態の有効/無効を設定
        is_paddle_only = (self.config.get("ocr_engine_mode", "dual_scout_hybrid") == "paddle_only")
        self.lang_ocr_group.setEnabled(not is_paddle_only)

        layout.addWidget(lang_ocr_group)


        # 差分スキップのステータス表示
        skip_status_layout = QHBoxLayout()
        diff_skip_label = QLabel("差分スキップ: 有効 (自動インテリジェント制御)")
        diff_skip_label.setFont(QFont("Yu Gothic UI", 8))
        diff_skip_label.setStyleSheet("color: #88cc88;")
        skip_status_layout.addStretch()
        skip_status_layout.addWidget(diff_skip_label)
        layout.addLayout(skip_status_layout)

        # ===== 感度設定とCPU制限のグループ =====
        settings_group = QGroupBox("パフォーマンス設定")
        settings_group.setFont(QFont("Yu Gothic UI", 9))
        settings_group.setStyleSheet("""
            QGroupBox {
                color: #aaaaaa;
                border: 1px solid #555;
                border-radius: 4px;
                margin-top: 5px;
                padding: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
        """)
        settings_vbox = QVBoxLayout(settings_group)
        settings_vbox.setSpacing(2)
        settings_vbox.setContentsMargins(8, 12, 8, 4)

        # --- スキップ感度 (2400, 1200, 800, 600, 400, 200) ---
        sens_label_box = QHBoxLayout()
        sens_title = QLabel("しきい値 (高いほど変化を無視/低負荷):")
        self.sens_val_label = QLabel("")
        self.sens_val_label.setStyleSheet("color: #00ffcc; font-weight: bold;")
        sens_label_box.addWidget(sens_title)
        sens_label_box.addStretch()
        sens_label_box.addWidget(self.sens_val_label)
        settings_vbox.addLayout(sens_label_box)

        self.sens_values = [6000, 4800, 2400, 1200, 600, 400]
        self.slider_sensitivity = QSlider(Qt.Orientation.Horizontal)
        self.slider_sensitivity.setRange(0, 5)
        self.slider_sensitivity.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_sensitivity.setTickInterval(1)
        
        curr_sens = self.config.get("ocr_skip_sensitivity", 2400)
        if curr_sens not in self.sens_values: curr_sens = 2400
        self.slider_sensitivity.setValue(self.sens_values.index(curr_sens))
        self.sens_val_label.setText(str(curr_sens))

        def on_sens_change(v):
            val = self.sens_values[v]
            self.sens_val_label.setText(str(val))
            self.config["ocr_skip_sensitivity"] = val
            # TranslationController側へも即座に通知
            if hasattr(self, 'controller') and self.controller:
                self.controller.config["ocr_skip_sensitivity"] = val

        self.slider_sensitivity.valueChanged.connect(on_sens_change)
        settings_vbox.addWidget(self.slider_sensitivity)

        # --- CPUスレッド使用制限 (25%, 50%, 75%, 100%) ---
        cpu_label_box = QHBoxLayout()
        cpu_title = QLabel("CPU使用制限 (WinRT OCR):")
        self.cpu_val_label = QLabel("")
        self.cpu_val_label.setStyleSheet("color: #ffcc00; font-weight: bold;")
        cpu_label_box.addWidget(cpu_title)
        cpu_label_box.addStretch()
        cpu_label_box.addWidget(self.cpu_val_label)
        settings_vbox.addLayout(cpu_label_box)

        self.cpu_percents = [25, 50, 75, 100]
        self.slider_cpu_limit = QSlider(Qt.Orientation.Horizontal)
        self.slider_cpu_limit.setRange(0, 3)
        self.slider_cpu_limit.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_cpu_limit.setTickInterval(1)

        curr_cpu = self.config.get("ocr_thread_limit_percent", 100)
        if curr_cpu not in self.cpu_percents: curr_cpu = 100
        self.slider_cpu_limit.setValue(self.cpu_percents.index(curr_cpu))
        self.cpu_val_label.setText(f"{curr_cpu}%")

        def on_cpu_change(v):
            val = self.cpu_percents[v]
            self.cpu_val_label.setText(f"{val}%")
            self.config["ocr_thread_limit_percent"] = val
            if hasattr(self, '_initializing') and self._initializing:
                return
            if hasattr(self, 'controller') and self.controller:
                self.controller.config["ocr_thread_limit_percent"] = val
                self.controller.apply_cpu_limit()
            save_config(self.config, self.config_path)

        self.slider_cpu_limit.valueChanged.connect(on_cpu_change)
        settings_vbox.addWidget(self.slider_cpu_limit)

        layout.addWidget(settings_group)

        # ===== 動作モード設定グループ =====
        mode_group = QGroupBox("動作モード")
        mode_group.setFont(QFont("Yu Gothic UI", 9))
        mode_group.setStyleSheet("""
            QGroupBox {
                color: #aaaaaa;
                border: 1px solid #555;
                border-radius: 4px;
                margin-top: 5px;
                padding: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
        """)
        mode_vbox = QVBoxLayout(mode_group)
        mode_vbox.setSpacing(4)

        self.chk_eco    = QCheckBox("エコモード (10秒間隔)")
        self.chk_single = QCheckBox("ワンショット翻訳モード")

        for cb in (self.chk_eco, self.chk_single):
            cb.setFont(QFont("Yu Gothic UI", 9))
            cb.setStyleSheet("color: #cccccc;")
            mode_vbox.addWidget(cb)

        mode_hint = QLabel("ワンショット: 開始ボタンで1回読み取り→停止まで表示を固定\n※エコとワンショットは同時選択できません。")
        mode_hint.setFont(QFont("Yu Gothic UI", 8))
        mode_hint.setStyleSheet("color: #888888; padding-left: 4px;")
        mode_vbox.addWidget(mode_hint)

        # 保存済み設定を反映
        self.chk_eco.setChecked(self.config.get("eco_mode", False))
        self.chk_single.setChecked(self.config.get("single_mode", False))

        def on_mode_changed():
            is_eco    = self.chk_eco.isChecked()
            is_single = self.chk_single.isChecked()
            
            # 排他制御（グレーアウト）
            self.chk_eco.setEnabled(not is_single)
            self.chk_single.setEnabled(not is_eco)
            
            self.config["eco_mode"]    = is_eco
            self.config["single_mode"] = is_single
            if hasattr(self, 'controller') and self.controller:
                self.controller.config["eco_mode"]    = is_eco
                self.controller.config["single_mode"] = is_single
            save_config(self.config, self.config_path)

        self.chk_eco.stateChanged.connect(on_mode_changed)
        self.chk_single.stateChanged.connect(on_mode_changed)
        
        # 初期状態のグレーアウト反映
        on_mode_changed()

        layout.addWidget(mode_group)

        # --- キャプチャ設定エリア ---
        capture_group = QGroupBox("キャプチャ設定")
        capture_group.setFont(QFont("Yu Gothic UI", 9))
        capture_group.setStyleSheet("QGroupBox { color: #aaaaaa; border: 1px solid #555; margin-top: 10px; padding-top: 10px; }")
        capture_vbox = QVBoxLayout(capture_group)

        cap_mode_layout = QHBoxLayout()
        cap_mode_label = QLabel("取得方式:")
        cap_mode_label.setFont(QFont("Yu Gothic UI", 10, QFont.Weight.Bold))
        cap_mode_layout.addWidget(cap_mode_label)

        self.capture_combo = QComboBox()
        self.capture_combo.setFont(QFont("Yu Gothic UI", 10))
        self.capture_combo.addItem("レイヤードウィンドウ除外 (BitBlt)", "bitblt")
        self.capture_combo.addItem("レイヤードウィンドウ除外 (PrintWindow)", "printwindow")
        self.capture_combo.addItem("互換モード (mss)", "mss")
        self.capture_combo.addItem("高速キャプチャ (WGC / DXCAM)", "wgc")
        
        # 保存設定を反映
        saved_mode = self.config.get("capture_mode", "wgc")
        idx = self.capture_combo.findData(saved_mode)
        if idx >= 0: self.capture_combo.setCurrentIndex(idx)

        def on_capture_mode_change(idx):
            mode = self.capture_combo.itemData(idx)
            self.config["capture_mode"] = mode
            if hasattr(self, 'controller') and self.controller:
                self.controller.config["capture_mode"] = mode
            save_config(self.config, self.config_path)

        self.capture_combo.currentIndexChanged.connect(on_capture_mode_change)
        cap_mode_layout.addWidget(self.capture_combo, stretch=1)
        capture_vbox.addLayout(cap_mode_layout)
        
        cap_hint = QLabel("※通常は高速・低負荷なWGC推奨。画面が真っ黒な場合はPrintWindowまたはmssに変更。")
        cap_hint.setFont(QFont("Yu Gothic UI", 8))
        cap_hint.setStyleSheet("color: #888;")
        capture_vbox.addWidget(cap_hint)
        
        layout.addWidget(capture_group)

        # 1. ターゲットウィンドウ設定エリア
        window_layout = QHBoxLayout()
        
        window_label = QLabel("ターゲットウィンドウ:")
        window_label.setFont(QFont("Yu Gothic UI", 10, QFont.Weight.Bold))
        window_layout.addWidget(window_label)
        
        # ウィンドウを選択するコンボボックス
        self.window_combo = QComboBox()
        self.window_combo.setFont(QFont("Yu Gothic UI", 10))
        self.window_combo.setMinimumWidth(200)
        window_layout.addWidget(self.window_combo, stretch=1)
        
        # リスト更新ボタン
        refresh_btn = QPushButton("更新")
        refresh_btn.setFont(QFont("Yu Gothic UI", 9))
        refresh_btn.setFixedSize(60, 30)
        refresh_btn.clicked.connect(self.refresh_window_list)
        window_layout.addWidget(refresh_btn)
        
        layout.addLayout(window_layout)

        # 1.5 翻訳先言語設定エリア
        lang_layout = QHBoxLayout()
        lang_label = QLabel("翻訳先言語:")
        lang_label.setFont(QFont("Yu Gothic UI", 10, QFont.Weight.Bold))
        lang_layout.addWidget(lang_label)
        
        self.lang_combo = QComboBox()
        self.lang_combo.setFont(QFont("Yu Gothic UI", 10))
        
        self.supported_langs = {
            "日本語 (Japanese)": "ja",
            "英語 (English)": "en",
            "フランス語 (French)": "fr",
            "ロシア語 (Russian)": "ru",
            "簡体字中国語 (Chinese)": "zh-CN",
            "韓国語 (Korean)": "ko",
            "スペイン語 (Spanish)": "es",
            "ポルトガル語 (Portuguese)": "pt",
            "ドイツ語 (German)": "de",
            "イタリア語 (Italian)": "it"
        }
        
        for name in self.supported_langs.keys():
            self.lang_combo.addItem(name)
            
        # configから読み込んだ設定を選択
        saved_lang = self.config.get("target_language", "ja")
        for name, code in self.supported_langs.items():
            if code == saved_lang:
                self.lang_combo.setCurrentText(name)
                break
                
        lang_layout.addWidget(self.lang_combo, stretch=1)
        layout.addLayout(lang_layout)

        # 初回のウィンドウリスト読み込み
        self.refresh_window_list()
        
        # 保存されていたウィンドウタイトルを初期選択
        saved_title = self.config.get("target_window_title", "")
        if saved_title:
            index = self.window_combo.findText(saved_title)
            if index >= 0:
                self.window_combo.setCurrentIndex(index)
            else:
                # リストに見つからない場合でも追加しておく
                self.window_combo.insertItem(0, saved_title)
                self.window_combo.setCurrentIndex(0)

        # 2. 開始・停止ボタンエリア
        btn_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("翻訳を開始")
        self.btn_start.setFont(QFont("Yu Gothic UI", 11, QFont.Weight.Bold))
        self.btn_start.setMinimumHeight(45)
        self.btn_start.setStyleSheet("background-color: #2e7d32; color: white;")
        self.btn_start.clicked.connect(self.start_translation)
        btn_layout.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("翻訳を停止")
        self.btn_stop.setFont(QFont("Yu Gothic UI", 11, QFont.Weight.Bold))
        self.btn_stop.setMinimumHeight(45)
        self.btn_stop.setStyleSheet("background-color: #c62828; color: white;")
        self.btn_stop.clicked.connect(self.stop_translation)
        self.btn_stop.setEnabled(False) 
        btn_layout.addWidget(self.btn_stop)
        
        layout.addLayout(btn_layout)

    def _init_controller(self):
        self.controller = TranslationController(self.config)

    def refresh_window_list(self):
        """現在開いているウィンドウのリストを取得してコンボボックスを更新する"""
        current_selection = self.window_combo.currentText()
        self.window_combo.clear()
        windows = list_windows()
        for title in windows:
            if "Real Time Translate" not in title:
                self.window_combo.addItem(title)
        if current_selection:
            index = self.window_combo.findText(current_selection)
            if index >= 0:
                self.window_combo.setCurrentIndex(index)

    def start_translation(self):
        selected_window = self.window_combo.currentText()
        if not selected_window:
            QMessageBox.warning(self, "エラー", "ターゲットウィンドウを選択してください。")
            return
        self.config["target_window_title"] = selected_window
        selected_lang_name = self.lang_combo.currentText()
        self.config["target_language"] = self.supported_langs.get(selected_lang_name, "ja")
        self.config["ollama_model"] = self.model_combo.currentText()
        # PaddleOCR / GPU 設定を保存
        self.config["ocr_engine_mode"] = self.combo_ocr_mode.currentData()
        gpu_real_index = self._gpu_list[self.gpu_combo.currentIndex()]["index"] if self._gpu_list else 0
        self.config["paddle_gpu_index"] = gpu_real_index
        self.config["paddle_gpu_mem_mb"] = self.spin_gpu_mem.value()
        self.config["paddle_language"] = self.paddle_langs[self.paddle_lang_combo.currentText()]
        # 案B: 選択されたOCR言語リストを保存
        selected_ocr_langs = [tag for tag, cb in self._ocr_lang_checkboxes.items() if cb.isChecked()]
        if not selected_ocr_langs:
            selected_ocr_langs = ["en-US"]  # 最低1言語を保証
        self.config["ocr_languages"] = selected_ocr_langs
        # 感度を保存
        # 案A拡張: スキップ感度を保存
        self.config["ocr_skip_sensitivity"] = self.slider_sensitivity.value()
        save_config(self.config, self.config_path)
        
        # コントローラーを開始
        self.controller.update_config(self.config)

        is_single = self.config.get("single_mode", False)
        
        # キュー上限の調整 (シングルモードは全翻訳のため上限を100へ、通常は30)
        if hasattr(self.controller, "translator") and self.controller.translator:
            q_limit = 100 if is_single else 30
            self.controller.translator.set_queue_limit(q_limit)

        if is_single:
            # シングルモード: すでに実行中なら「強制再読み取り」を実行（UIクリア含む）
            if self.controller.is_running:
                self.controller.force_retranslate()
                self._update_single_btn_label()
                return
            else:
                self.controller.start()
        else:
            self.controller.start()
        
        # UI状態更新
        is_single = self.config.get("single_mode", False)
        if not is_single:
            # 通常/エコモードのみ開始中に無効化する（シングルは繰り返し押せる）
            self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.window_combo.setEnabled(False)
        self.lang_combo.setEnabled(False)
        self.model_combo.setEnabled(False)
        self.combo_ocr_mode.setEnabled(False)
        self.gpu_combo.setEnabled(False)
        self.spin_gpu_mem.setEnabled(False)
        for cb in self._ocr_lang_checkboxes.values():
            cb.setEnabled(False)
        self.slider_sensitivity.setEnabled(False)
        self.capture_combo.setEnabled(False)

        if is_single:
            self.btn_start.setText("再読み取り")
            self.btn_start.setEnabled(True)
            self.btn_start.setStyleSheet("background-color: #1565c0; color: white;")

        # ステータス表示を最新に更新
        self._refresh_status_labels()

    def _update_single_btn_label(self):
        """シングルモード時のボタンテキストを状態に応じて更新"""
        is_single = self.config.get("single_mode", False)
        if is_single and self.controller and self.controller.is_running:
            self.btn_start.setText("再読み取り")
            self.btn_start.setStyleSheet("background-color: #1565c0; color: white;")
            self.btn_start.setEnabled(True)

    def stop_translation(self):
        self.controller.stop()
        self.btn_start.setEnabled(True)
        self.btn_start.setText("翻訳を開始")
        self.btn_start.setStyleSheet("background-color: #2e7d32; color: white;")
        self.btn_stop.setEnabled(False)
        self.window_combo.setEnabled(True)
        self.lang_combo.setEnabled(True)
        self.model_combo.setEnabled(True)
        self.combo_ocr_mode.setEnabled(True)
        paddle_on = (self.combo_ocr_mode.currentData() != "winrt_only")
        self.gpu_combo.setEnabled(paddle_on)
        self.spin_gpu_mem.setEnabled(paddle_on)
        for cb in self._ocr_lang_checkboxes.values():
            cb.setEnabled(True)
        self.slider_sensitivity.setEnabled(True)
        self.capture_combo.setEnabled(True)

        # ステータス表示を最新に更新
        self._refresh_status_labels()

    def _refresh_status_labels(self):
        """fastText や PaddleOCR の現在の状態をUIに反映する"""
        self.lbl_langcheck.setText(lang_check_status())
        
        # PaddleOCR の状態を表示 (Noneチェックを厳密に行う)
        if getattr(self, 'controller', None) is not None and self.controller.ocr and self.controller.ocr.paddle_engine:
            status = self.controller.ocr.paddle_engine.get_status()
            self.lbl_paddle_status.setText(status)
        else:
            self.lbl_paddle_status.setText("PaddleOCR 設定待ち")
        
    def toggle_translation(self):
        if self.controller and self.controller.is_running:
            self.stop_translation()
        else:
            self.start_translation()
            
    def force_retranslate(self):
        if self.controller and self.controller.is_running:
            self.controller.force_retranslate()

    def _on_ocr_mode_changed(self, index):
        """OCRモードは固定のため処理なし"""
        pass
        
    def closeEvent(self, event):
        if self.controller:
            self.controller.stop()
        event.accept()


# --- Flask API Server ---
app_flask = Flask(__name__)
global_panel_ref = None

@app_flask.route('/api/start', methods=['GET', 'POST'])
def api_start():
    if global_panel_ref:
        if hasattr(global_panel_ref, 'sig_start_translation'):
            global_panel_ref.sig_start_translation.emit()
        return jsonify({"status": "success", "action": "start_translation"})
    return jsonify({"status": "error", "message": "Panel not found"}), 500

@app_flask.route('/api/stop', methods=['GET', 'POST'])
def api_stop():
    if global_panel_ref:
        if hasattr(global_panel_ref, 'sig_stop_translation'):
            global_panel_ref.sig_stop_translation.emit()
        return jsonify({"status": "success", "action": "stop_translation"})
    return jsonify({"status": "error", "message": "Panel not found"}), 500

@app_flask.route('/api/retrans', methods=['GET', 'POST'])
def api_retrans():
    if global_panel_ref:
        if hasattr(global_panel_ref, 'sig_force_retranslate'):
            global_panel_ref.sig_force_retranslate.emit()
        elif hasattr(global_panel_ref, 'controller'):
            global_panel_ref.controller.force_retranslate()
        return jsonify({"status": "success", "action": "force_retranslate"})
    return jsonify({"status": "error", "message": "Panel not found"}), 500

@app_flask.route('/api/update_config', methods=['POST'])
def api_update_config():
    """
    SecreAI から設定変更を受け取り、稼働中のコントローラーに即時反映する。
    受け取った設定は config.json にも書き込み、次回起動時に引き継がれる。
    """
    try:
        new_settings = request.json
        if not new_settings or not isinstance(new_settings, dict):
            return jsonify({"status": "error", "message": "Invalid JSON body"}), 400

        if global_panel_ref and global_panel_ref.controller:
            ctrl = global_panel_ref.controller
            # 既存の設定にマージ（rtt_ プレフィックスのキーは除去して渡す）
            clean = {k.removeprefix("rtt_"): v for k, v in new_settings.items()}
            merged = {**ctrl.config, **clean}
            ctrl.update_config(merged)
            save_config(merged, global_panel_ref.config_path)
            return jsonify({"status": "success", "applied": list(clean.keys())})

        return jsonify({"status": "error", "message": "Controller not running"}), 503
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app_flask.route('/api/status', methods=['GET'])
def api_status():
    """RTtranslator の稼働状態を返す（SecreAI がポーリングで確認するために使用）。"""
    if global_panel_ref and global_panel_ref.controller:
        ctrl = global_panel_ref.controller
        return jsonify({
            "status": "ok",
            "is_running": ctrl.is_running,
            "model": ctrl.translator.model,
            "target_lang": ctrl.translator.target_lang,
            "error": getattr(ctrl.translator, "last_error", "")
        })
    return jsonify({"status": "ok", "is_running": False})

@app_flask.route('/api/overlay_data')
def api_overlay_data():
    if global_panel_ref and global_panel_ref.controller:
        ctrl = global_panel_ref.controller
        # ndarray (step3_crop) は JSON に変換できないため除外して送信する
        sanitized_state = {
            cid: {k: v for k, v in state.items() if k != "step3_crop"}
            for cid, state in ctrl.overlay_state.items()
        }
        return jsonify({
            "window": ctrl.window_rect_data,
            "translations": sanitized_state,
            "config": {
                "font_size_ratio": ctrl.config.get("font_size_ratio", 1.0)
            }
        })
    return jsonify({"translations": {}, "window": {"x":0,"y":0,"w":0,"h":0}})

@app_flask.route('/overlay')
def api_overlay_page():
    try:
        script_dir = Path(__file__).parent
        file_path = script_dir / "overlay.html"
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"overlay.html not found at {file_path}. Error: {e}"

def run_server():
    import time
    for _ in range(5):
        try:
            app_flask.run(port=5001, debug=False, use_reloader=False)
            break
        except:
            time.sleep(1)

def main():
    # クラッシュの詳細な原因を特定するため、PyQtのスロット内で発生した例外を強制的にキャッチして表示する
    import traceback
    def global_exception_handler(exc_type, exc_value, exc_traceback):
        print(f"[FATAL CRASH] Unhandled Exception: {exc_type.__name__}: {exc_value}")
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        sys.exit(1)
    sys.excepthook = global_exception_handler

    import argparse
    global global_panel_ref

    parser = argparse.ArgumentParser(description="Real-Time Translator (Worker)")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="設定画面を表示せず、すぐに翻訳を開始するモード（SecreAI統合用）"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="使用する config.json のフルパス（省略時は自身のディレクトリ内を参照）"
    )
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    if args.config:
        config_path = Path(args.config)
    else:
        config_path = script_dir / "config.json"

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # ヘッドレス時にオーバーレイを閉じてもアプリが終了しないよう設定
    app.setStyleSheet("""
        QMainWindow { background-color: #2b2b2b; }
        QLabel { color: #ffffff; }
        QComboBox { 
            background-color: #3b3b3b; 
            color: #ffffff; 
            border: 1px solid #555;
            padding: 4px;
            border-radius: 4px;
        }
        QPushButton { 
            border-radius: 4px;
            border: none;
            padding: 5px;
            color: white;
            background-color: #555;
        }
        QPushButton:hover { background-color: #666; }
        QPushButton:disabled { background-color: #444; color: #888; }
    """)

    if args.headless:
        # ===== ヘッドレスモード =====
        # 設定画面を表示せず、コントローラーを直接起動して翻訳を開始する。
        # SecreAI から subprocess で呼び出された際に使用されるモード。
        print(f"[RTtranslator] ヘッドレスモードで起動します。config: {config_path}")
        config = load_config(str(config_path))

        # ControlPanel を使わず、TranslationController を直接生成して起動
        ctrl = TranslationController(config)

        # Flask API から ctrl を参照できるようにするためのダミーパネルオブジェクトを設定
        class _HeadlessPanelProxy(QObject):
            sig_start_translation = pyqtSignal()
            sig_stop_translation = pyqtSignal()
            sig_force_retranslate = pyqtSignal()

            def __init__(self, controller, cfg_path):
                super().__init__()
                self.controller = controller
                self.config_path = str(cfg_path)
                
                # シグナルをメインスレッド上のスロットに接続
                self.sig_start_translation.connect(self._on_start)
                self.sig_stop_translation.connect(self._on_stop)
                self.sig_force_retranslate.connect(self._on_force)
                
            def _on_start(self):
                if not self.controller.is_running:
                    self.controller.start()

            def _on_stop(self):
                if self.controller.is_running:
                    self.controller.stop()
                    
            def _on_force(self):
                if self.controller.is_running:
                    self.controller.force_retranslate()

        global_panel_ref = _HeadlessPanelProxy(ctrl, config_path)
        # 起動直後に翻訳を開始せず、API経由の開始指示を待機する (待機状態で起動)
        # ctrl.start() を削除
    else:
        # ===== 通常モード（設定画面あり）=====
        app.setQuitOnLastWindowClosed(True)
        panel = ControlPanel(str(config_path))
        global_panel_ref = panel
        panel.show()

    threading.Thread(target=run_server, daemon=True).start()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
