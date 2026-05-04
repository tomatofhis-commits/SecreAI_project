"""
Real Time Translate - メインエントリーポイント
Ollama (TranslateGemma) を使ってゲーム画面のテキストをリアルタイムに翻訳する
"""

import sys
import os
import psutil

import json
import re
import queue
from pathlib import Path
from difflib import SequenceMatcher
from collections import OrderedDict
import time
import threading

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QComboBox, QPushButton, QMessageBox, QCheckBox, QSpinBox, QGroupBox, QSlider
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from flask import Flask, jsonify, request
import threading

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
    # 記号の置換（文脈に影響しにくい記号をスペースへ）
    text = re.sub(r'[・•\*_\-\+\[\]\(\)\{\}|\\#@$]', ' ', text)
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
        return True
        
    return False


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
    "ocr_skip_sensitivity": 800,
    "ocr_thread_limit_percent": 100,
    "font_size": 16,
    "overlay_opacity": 0.85,
    "overlay_background_color": "#1a1a2e",
    "overlay_text_color": "#e0e0e0",
    "use_vision_translation": False,
    "eco_mode": False
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
        self.window_title = config.get("target_window_title", "")
        self.is_running = False
        
        # キャッシュマネージャーの設定
        self.cache_path = Path("translation_cache.json")
        self.translation_cache = OrderedDict()
        self._load_cache()
        self._cache_dirty = False
        self._last_cache_save = time.time()

        # === OCRスレッド分離用 ===
        # OCRワーカーに渡す画像キュー（サイズ1で、常に最新フレームだけ処理）
        self._ocr_input_queue: queue.Queue = queue.Queue(maxsize=1)
        # OCR結果をメインスレッドに返すキュー
        self._ocr_output_queue: queue.Queue = queue.Queue(maxsize=5)
        self._position_queue: queue.Queue = queue.Queue()
        # OCRワーカーが現在処理中かどうかのフラグ
        self._ocr_busy: bool = False
        self._current_frame_id = 0
        self._last_clear_id = 0
        self._stop_event = threading.Event()
        # 案A: 差分スキップ用の前フレーム情報
        self._prev_frame_hash: int = 0
        self._skip_counter: int = 0
        
        # 案A+案B 用の履歴保持
        self._prev_east_boxes: list = []
        self._prev_east_scores: list = []
        self._prev_paddle_boxes: list = []
        self._prev_paddle_scores: list = []
        self._last_raw_chunks: list = []  # スキップ時に流用する前回のOCR結果
        self._last_force_ocr_time: float = 0.0  # 5秒強制チェック用
        self._last_ocr_exec_time: float = 0.0   # エコモード用
        
        # デバッグ統計用カウンター
        self._stats_skip_count: int = 0
        self._stats_total_count: int = 0
        self._stats_last_time: float = time.time()
        
        self._last_winocr_time: float = time.time()  # 動的しきい値用
        
        # OCRワーカースレッドを起動
        self._ocr_thread = threading.Thread(target=self._ocr_worker, daemon=True)
        # 最初にCPU制限を適用してからワーカーを動かす
        self.apply_cpu_limit()
        self._ocr_thread.start()
        
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
        )

        # UI初期化 (まだ表示しない)
        self.overlay = TranslationOverlay(
            font_size=config.get("font_size", 16),
            opacity=config.get("overlay_opacity", 0.85),
            bg_color=config.get("overlay_background_color", "#1a1a2e"),
            text_color=config.get("overlay_text_color", "#e0e0e0"),
        )
        
        # 状態管理：翻訳完了、または翻訳依頼中のチャンクID
        self.active_translations = {}
        self.pending_texts = set()
        self.last_request_time = 0.0      # 全体の最終送信時刻
        self.last_short_word_time = 0.0   # 短文の最終送信時刻
        self._last_ocr_exec_time = 0.0    # エコモード用の最終OCR時刻
        
        # OBSブラウザオーバーレイ用の状態保持
        self.overlay_state = {}
        self.window_rect_data = {"x": 0, "y": 0, "w": 0, "h": 0}

        # 枠の存在確認・追従タイマー（約6FPSでメインループを駆動）
        self.timer = QTimer()
        self.timer.timeout.connect(self._on_tick)
        self.timer.setInterval(166) 
        
        # 解析結果ポーリング用タイマー（100ms間隔）
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll_ocr_result)
        
        # apply_cpu_limit は初期化の上方で行うように変更

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
            
        # 翻訳開始時にキャッシュの整理を実行
        self._auto_clean_cache()
        
        self.is_running = True
        self.overlay.set_status("🔍 Ollamaに接続中...")
        self.overlay.show()
        
        if self.translator.test_connection():
            self.overlay.set_status(f"✅ 接続OK | 対象: {self.window_title}")
        else:
            self.overlay.set_status("⚠️ Ollamaに接続できません")

        self.timer.start()
        self.poll_timer.start(100)
        # self.cache_save_timer.start() # 削除

    def stop(self):
        """翻訳ループを停止する。"""
        if not self.is_running:
            return
        
        self.is_running = False
        self.timer.stop()
        self.poll_timer.stop()
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
        
        # モデルとURLを更新
        new_model = new_config.get("ollama_model", "translategemma:4b")
        new_url = new_config.get("ollama_url", "http://localhost:11434")
        
        if self.translator.model != new_model:
            self.translator.model = new_model
        
        if hasattr(self.translator, "ollama_url"):
            # 末尾の / を除いて更新
            self.translator.ollama_url = new_url.rstrip("/")
        
        # CPU制限を再適用
        self.apply_cpu_limit()
        
        print(f"[RTtranslator] 設定を更新しました: Model={self.translator.model}, CPU_Limit={self.config.get('ocr_thread_limit_percent')}%")

    def force_retranslate(self):
        """現在画面上の翻訳結果のみをキャッシュから破棄し、再翻訳を強制する"""
        target_lang = self.config.get("target_language", "ja")
        
        # 画面に出ている文字列（または不可視として判定された文字列）のキャッシュだけを狙い撃ちで消す
        for cid in self.active_translations:
            if cid in self.history_chunks:
                text_clean = self.history_chunks[cid]['text'].strip()
                cache_key = f"{target_lang}::{text_clean}"
                if cache_key in self.translation_cache:
                    del self.translation_cache[cache_key]
                    
        # UI上のアクティブなラベルをすべて削除
        self.overlay.sync_active_ids(set())
        self.active_translations.clear()
        
        # テンポラリ履歴と処理中キューのクリア（全キャッシュは消さない）
        self.history_chunks.clear()
        self._history_grid.clear()
        self.pending_texts.clear()
        self._cache_dirty = True

        
    def _load_cache(self):
        """
        起動時は過去のキャッシュをロードせず、完全に白紙の状態からスタートする。
        前回の終了時に残されたファイルの内容は、起動したタイミングでクリアする。
        """
        print("[Cache] 起動時にキャッシュをリセットしました（ファイルも白紙からスタート）")
        self.translation_cache.clear()
        
        # ファイル自体も空の状態で上書き保存し、白紙化する
        self._save_cache()
        
        # 起動直後のオートクリーンは翻訳開始ボタン押下時に移動したためここでは実行しません

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
            
            if time_since_last >= 20.0: skip_thresh = 1.0
            elif time_since_last >= 10.0: skip_thresh = 0.9
            else: skip_thresh = 0.8
                
            if match_ratio >= skip_thresh: return True
            dynamic_thresh = min(1.0, 0.4 * time_since_last)
            return match_ratio >= dynamic_thresh
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
        while True:
            try:
                payload = self._ocr_input_queue.get()  # ブロッキング待機
                if payload is None:
                    break  # 終了シグナル
                
                # 6要素を展開 (image, rect, scale_x, scale_y, thread_limit_ratio, frame_id)
                image, rect, scale_x, scale_y, thread_limit_ratio, frame_id = payload
                
                # スキップ判定 (一本化されたロジック)
                skip_ocr = self._check_skip_ocr(image)
                
                if skip_ocr and hasattr(self, '_last_raw_chunks') and self._last_raw_chunks:
                    # スキップ判定 (前回結果を流用)
                    raw_chunks = self._last_raw_chunks
                else:
                    use_vision = self.config.get("use_vision_translation", False)
                    raw_chunks, _ = self.ocr.extract_text(
                        image,
                        window_title=self.window_title,
                        target_lang=self.config.get("target_language", "ja"),
                        attach_image=use_vision,
                        thread_limit_ratio=thread_limit_ratio,
                    )
                    self._last_raw_chunks = raw_chunks
                    self._last_winocr_time = time.time()
                
                # 5要素として返す (raw_chunks, rect, scale_x, scale_y, frame_id)
                self._ocr_output_queue.put((raw_chunks, rect, scale_x, scale_y, frame_id))
            except Exception as e:
                print(f"[OCR Worker] エラー: {e}")
            finally:
                if 'image' in locals() and image is not None:
                    if hasattr(image, 'close'):
                        image.close()
                    del image
                self._ocr_busy = False

    def _on_tick(self):
        """
        メインループ（約6FPS）。
        1回のキャプチャで、既存枠の監視(Monitor)と新規テキストの発見(Discovery)を行う。
        """
        if not self.is_running:
            return

        rect = get_client_rect_on_screen(self.window_title)
        if rect is None:
            self.overlay.set_status(f"⚠️ ウィンドウが見つかりません: {self.window_title}")
            return

        # UI をターゲットのクライアント領域（枠内）へ追従させる
        self.overlay.update_geometry(rect)

        # 1. 画面キャプチャ（1回のループで1回のみ）
        image = capture_window(self.window_title, rect=rect)
        if image is None:
            return

        # --- A. 既存枠の監視 (Monitor) ---
        if self.overlay_state and hasattr(self.ocr, 'paddle_engine') and self.ocr.paddle_engine:
            try:
                # 索敵 (rec=False) 実行
                found_blocks = self.ocr.paddle_engine.recognize(image, rec=False)
                new_rects = [b['rect'] for b in found_blocks if 'rect' in b]

                for cid, state in list(self.overlay_state.items()):
                    if state.get('text') in {"__IGNORE__", "__IGNORE_1__", "__IGNORE_2__"}:
                        continue
                    old_r = state['rect']
                    best_iou = 0.0
                    best_new_rect = None
                    for new_r in new_rects:
                        iou = self._calc_iou(old_r, new_r)
                        if iou > best_iou:
                            best_iou = iou
                            best_new_rect = new_r
                    
                    if best_iou < 0.02:
                        state['existence_strike'] = state.get('existence_strike', 0) + 1
                        if state['existence_strike'] >= 3:
                            if hasattr(self.overlay, 'active_labels') and cid in self.overlay.active_labels:
                                self.overlay.active_labels[cid].deleteLater()
                                del self.overlay.active_labels[cid]
                            del self.overlay_state[cid]
                            if cid in self.active_translations: del self.active_translations[cid]
                            if cid in self.history_chunks: del self.history_chunks[cid]
                    else:
                        state['existence_strike'] = 0
                        if best_iou >= 0.3:
                            if abs(old_r['x'] - best_new_rect['x']) > 2 or abs(old_r['y'] - best_new_rect['y']) > 2:
                                self.overlay.update_translation_position(cid, best_new_rect)
                                state['rect'] = best_new_rect
                                if cid in self.history_chunks: self.history_chunks[cid]['rect'] = best_new_rect
            except Exception as e:
                print(f"[Monitor Error] {e}")

        # --- B. 新規テキストの発見判定 (Discovery) ---
        import numpy as np
        thumb = image.resize((64, 36)).convert("L")
        thumb_arr = np.array(thumb, dtype=np.int16)
        frame_hash = int(np.sum(thumb_arr))
        pixel_diff = abs(frame_hash - self._prev_frame_hash)
        self._prev_frame_hash = frame_hash

        # 感度設定
        sensitivity = self.config.get("ocr_skip_sensitivity", 800)
        diff_threshold = sensitivity
        
        import time
        current_time = time.time()
        time_since_force = current_time - self._last_force_ocr_time
        
        # エコモード判定
        is_eco = self.config.get("eco_mode", False)
        time_since_last_exec = current_time - self._last_ocr_exec_time
        if is_eco and time_since_last_exec < 3.0:
            return

        # 変化が小さく、かつ前回の強制実行から5秒経っていないならサボる
        if pixel_diff < diff_threshold and time_since_force < 5.0:
            return
            
        # 【重要】実行頻度の制限 (最低 0.3秒 は空ける)
        # これにより 1秒/2.5秒 設定を消したことによる暴走と破棄サイクルを防ぐ
        if current_time - self._last_ocr_exec_time < 0.3:
            return
            
        # ここを通過＝OCR実行プロセスに入る
        if not self._ocr_busy:
            self.overlay.set_status(f"🔍 画面を解析中... | {self.window_title}")
            
        self._last_ocr_exec_time = current_time
        if time_since_force >= 5.0:
            self._last_force_ocr_time = current_time
            
        # 前回の OCR がまだ実行中なら古いものを破棄
        if self._ocr_busy:
            try:
                self._ocr_input_queue.get_nowait()
            except queue.Empty:
                pass

        logical_w, logical_h = rect[2], rect[3]
        physical_w, physical_h = image.width, image.height
        scale_x = physical_w / logical_w if logical_w > 0 else 1.0
        scale_y = physical_h / logical_h if logical_h > 0 else 1.0
        self.window_rect_data = {"x": rect[0], "y": rect[1], "w": logical_w, "h": logical_h}
        
        self._current_frame_id += 1
        current_id = self._current_frame_id

        if pixel_diff > diff_threshold * 100:
            self._last_clear_id = current_id
            self._ocr_output_queue.put(("CLEAR", None, 0, 0, current_id))

        self._ocr_busy = True
        thread_limit_ratio = self.config.get("ocr_thread_limit_percent", 100) / 100.0
        self._ocr_input_queue.put((image, rect, scale_x, scale_y, thread_limit_ratio, current_id))

    def _poll_ocr_result(self):
        """
        100ms ごとにメインスレッドから OCR 結果キューをポーリングし、
        UI 更新・翻訳依頼を実行する（旧 _on_tick の OCR 実行後の処理）。
        """
        if not self.is_running:
            return
            
        # 爆速追従：位置更新キューの処理
        while not self._position_queue.empty():
            try:
                cid, new_rect = self._position_queue.get_nowait()
                if hasattr(self, 'overlay'):
                    self.overlay.update_translation_position(cid, new_rect)
                    if cid in self.overlay_state:
                        self.overlay_state[cid]['rect'] = new_rect
                        
                        # 古い残骸を確実に消す：同じテキストの「別ID」があればUIから抹消
                        cur_txt = self.overlay_state[cid].get('text', '')
                        if cur_txt:
                            for other_cid, other_state in list(self.overlay_state.items()):
                                if other_cid == cid:
                                    continue
                                if other_state.get('text', '') == cur_txt:
                                    # 【改善】PyQt上のラベルも即時に破棄する
                                    if hasattr(self.overlay, 'active_labels') and other_cid in self.overlay.active_labels:
                                        self.overlay.active_labels[other_cid].deleteLater()
                                        del self.overlay.active_labels[other_cid]
                                        
                                    del self.overlay_state[other_cid]
                                    if other_cid in self.active_translations:
                                        del self.active_translations[other_cid]
            except queue.Empty:
                break
            except Exception as e:
                print(f"[Position Tracking] エラー: {e}")
                break

        while True:
            try:
                res = self._ocr_output_queue.get_nowait()
                # 常に5番目の要素が frame_id
                fid = res[4]
                
                # 【重要】届いた結果が「最後に画面をクリアした時」より古い場合のみ破棄する
                # これにより、背景が動いて ID が進んでいても、同じシーンなら結果を表示できます
                if fid < self._last_clear_id:
                    self._ocr_busy = False # フラグを落とさないと次の解析が始まらない
                    continue

                if res[0] == "CLEAR":
                    self.overlay.clear_labels()
                    continue

                # 通常のOCR結果
                raw_chunks, rect, scale_x, scale_y, _ = res
                self._ocr_busy = False
                
                # 結果が空（文字なし）の場合でもステータスを更新して「生存」を示す
                if not raw_chunks:
                    translated_count = len(self.overlay.active_labels)
                    perf_info = f" | ⚡ Latency: {self.translator.avg_latency:.1f}s"
                    self.overlay.set_status(f" 👀 監視中... (文字なし / 翻訳済: {translated_count}個){perf_info} | {self.window_title}")
                    return
                    
                break 
            except queue.Empty:
                return

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

            # --- 2. 空間トラッキング（IDの安定化） ---
            best_match_id = None
            best_iou = 0.2
            
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
                # 類似度が一定以上ならIDを継承する
                similarity = SequenceMatcher(None, chunk['text'], old_chunk['text']).ratio()
                if similarity > 0.4:
                    chunk['id'] = best_match_id
                    # 移動した古いテキストの残骸をUIから即時に抹消する処理も兼ねる
                    if hasattr(self, 'overlay') and best_match_id in self.overlay.active_labels:
                        # 過去のラベルの位置を新座標へテレポートさせる
                        self.overlay.update_translation_position(best_match_id, chunk['rect'])
                        
                    chunk['text'] = old_chunk['text']
            
            cid = chunk['id']
            new_history[cid] = chunk
            chunks.append(chunk)

            # --- 3. キャッシュチェックと表示ステートの更新 ---
            target_lang = self.config.get("target_language", "ja")
            cache_key = f"{target_lang}::{chunk['text'].strip()}"
            cached_trans = self.translation_cache.get(cache_key)
            
            if cached_trans:
                translated_count += 1
                # ソフトIGNOREも含め、全IGNORE系の値はオーバーレイに表示しない
                _all_ignores = {"__IGNORE__", "__IGNORE_1__", "__IGNORE_2__"}
                if cached_trans not in _all_ignores:
                    # デスクトップ用オーバーレイ（PyQt）の更新
                    self.overlay.show_translation(cid, chunk, cached_trans, target_lang)
                    # OBS API用ステートの更新（ブラウザ用）
                    self.overlay_state[cid] = {
                        "text": cached_trans,
                        "rect": chunk["rect"],
                        "bg_color": chunk.get("bg_color", "rgba(0,0,0,1.0)"),
                        "text_color": chunk.get("text_color", "#eeeeee"),
                        "lines_count": chunk.get("lines_count", 1)
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

        # 画面から消えたチャンクの処理（フリッカー対策：0.05秒は保持する）
        current_time = time.time()
        for cid in list(self.overlay_state.keys()):
            if cid not in current_ids:
                # 画面から消えたばかり（または非同期で追加されて画面にいない）場合、タイマー開始
                if 'last_seen' not in self.overlay_state[cid]:
                    self.overlay_state[cid]['last_seen'] = current_time
                    
                # 最後の確認からの経過時間で判定する
                if current_time - self.overlay_state[cid]['last_seen'] > 0.05:
                    if hasattr(self.overlay, 'active_labels') and cid in self.overlay.active_labels:
                        self.overlay.active_labels[cid].deleteLater()
                        del self.overlay.active_labels[cid]
                    del self.overlay_state[cid]
                    if cid in self.active_translations:
                        del self.active_translations[cid]
            else:
                self.overlay_state[cid]['last_seen'] = current_time # 寿命リセット(0.05秒保持)
                
        # ゴーストとして生き残っているIDも含めて同期するが、
        # 重複削除のあとで再度同期する必要がある
        
        # 同一フレーム内の重複・包含排除（同じタイミングで大小の枠が重なった場合、小さい方を捨てる）
        valid_chunks = []
        for c1 in chunks:
            is_noise = False
            for c2 in chunks:
                if c1['id'] == c2['id']: continue
                r1, r2 = c1['rect'], c2['rect']
                area1 = max(1, r1['w'] * r1['h'])
                area2 = max(1, r2['w'] * r2['h'])
                
                # c1がc2の半分のサイズ以下で、かつc1の領域の40%以上が重なっているならノイズとして捨てる
                if area1 < area2 * 0.5:
                    ix = max(0, min(r1['x']+r1['w'], r2['x']+r2['w']) - max(r1['x'], r2['x']))
                    iy = max(0, min(r1['y']+r1['h'], r2['y']+r2['h']) - max(r1['y'], r2['y']))
                    ioa = (ix * iy) / area1
                    if ioa > 0.4:
                        is_noise = True
                        break
            if not is_noise:
                valid_chunks.append(c1)
        chunks = valid_chunks
        
        # 空間的（座標）キャッシュ強化：既存の翻訳と強く重なる新規チャンクは品質比較を行う
        filtered_chunks = []
        for chunk in chunks:
            cid = chunk['id']
            if cid in self.active_translations:
                filtered_chunks.append(chunk)
                # 翻訳済みのチャンクが表示される際、下敷きになっている古いゴーストを掃除する
                for active_cid, state in list(self.overlay_state.items()):
                    if active_cid == cid: continue
                    if calculate_iou(chunk['rect'], state['rect']) > 0.6:
                        old_raw = state.get('raw_text', state['text'])
                        if _score_ocr_text(chunk['text']) > _score_ocr_text(old_raw) + 0.5:
                            if active_cid in self.overlay_state:
                                del self.overlay_state[active_cid]
                            if active_cid in self.active_translations:
                                del self.active_translations[active_cid]
                continue
                
            is_flicker = False
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
                
                iou = intersection_area / max(1, area1 + area2 - intersection_area)
                ioa = intersection_area / min(area1, area2)
                
                # 包含関係・部分的な強い重なり（小さな枠が大きな枠に40%以上重なっている）場合
                if ioa > 0.4:
                    if area1 < area2 * 0.5:
                        # 新しいチャンク(r1)が明らかに小さく、大半が重なっている → ノイズとして破棄
                        is_flicker = True
                        break
                    elif area2 < area1 * 0.5:
                        # 古いチャンク(r2)が明らかに小さく、大半が重なっている → 古いノイズを画面から削除
                        if active_cid in self.overlay_state:
                            del self.overlay_state[active_cid]
                        if active_cid in self.active_translations:
                            del self.active_translations[active_cid]
                        continue

                # 部分的な重複が大きい場合（IoU > 0.6）は品質で勝負
                if iou > 0.6: 
                    old_text = state.get('raw_text', state['text'])
                    new_text = chunk['text']
                    
                    # 内容が変わっている場合、古い表示を即時消去する
                    similarity = SequenceMatcher(None, old_text.strip(), new_text.strip()).ratio()
                    if similarity < 0.6:
                        if active_cid in self.overlay_state:
                            if hasattr(self.overlay, 'active_labels') and active_cid in self.overlay.active_labels:
                                self.overlay.active_labels[active_cid].deleteLater()
                                del self.overlay.active_labels[active_cid]
                            del self.overlay_state[active_cid]
                        if active_cid in self.active_translations:
                            del self.active_translations[active_cid]
                        continue
                        
                    # 新しい方が明らかに自然な文章なら、古い方を削除
                    if _score_ocr_text(new_text) > _score_ocr_text(old_text) + 0.5:
                        if active_cid in self.overlay_state:
                            del self.overlay_state[active_cid]
                        if active_cid in self.active_translations:
                            del self.active_translations[active_cid]
                    else:
                        # 既存の方が良い、あるいは同程度ならフリッカー（ノイズ）として新しい方を捨てる
                        is_flicker = True
                        # 古い表示がガタガタしないよう、位置だけは新しい矩形に追従させる
                        self.overlay.update_translation_position(active_cid, chunk['rect'])
                        state['rect'] = chunk['rect']
                        state['last_seen'] = time.time() # ノイズによって本来のテキストが押し出されて消えないよう寿命を回復
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
            if cid in self.active_translations:
                # 既に手配中、あるいは翻訳済みのテキストならUIへ位置の更新だけ伝える
                self.overlay.update_translation_position(cid, chunk['rect'])
                if cid in self.overlay_state:
                    self.overlay_state[cid]['rect'] = chunk['rect']
            else:
                # まだ手配していない新しいテキスト -> キャッシュを確認
                text_raw = chunk['text'].strip()
                text_lines = chunk.get('text_lines', [])
                
                if len(text_lines) > 1:
                    # ユーザー提案の「論理的結合パターン」を生成
                    ja_end_chars = tuple("。！？）」』…")
                    en_end_chars = tuple(".!?'\"")
                    
                    # 1. 日本語・中国語・ハングル向けパターン（句読点がなければスペース無しで結合）
                    ja_pattern = ""
                    for i, line in enumerate(text_lines):
                        if i == 0:
                            ja_pattern += line
                        else:
                            prev_line = text_lines[i-1]
                            if prev_line.endswith(ja_end_chars):
                                ja_pattern += "\n" + line
                            else:
                                ja_pattern += line
                                
                    # 2. 英語・ロシア語等のアルファベット向けパターン（句読点がなければスペース有りで結合）
                    en_pattern = ""
                    for i, line in enumerate(text_lines):
                        if i == 0:
                            en_pattern += line
                        else:
                            prev_line = text_lines[i-1]
                            if prev_line.endswith(en_end_chars):
                                en_pattern += "\n" + line
                            else:
                                en_pattern += " " + line
                                
                    # 3. OCRの生の出力（全て改行結合）
                    raw_pattern = "\n".join(text_lines)
                    
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
                    self.active_translations[cid] = True
                    continue
                
                # --- 単語辞書フィルター: 1〜2語の短文でどの辞書にも存在しない場合は即破棄 ---
                # プレイヤー名 (danger00, amachi等) やUIゴミ (I I I I等) をAPIに送る前に弾く
                if _word_filter_discard(text_raw):
                    target_lang_wf = self.config.get("target_language", "ja")
                    cache_key_wf = f"{target_lang_wf}::{text_raw}"
                    existing_wf = self.translation_cache.get(cache_key_wf, "")
                    if existing_wf not in ("__IGNORE__", "__IGNORE_1__", "__IGNORE_2__"):
                        _SOFT_IGNORE_MAP_WF = {"": "__IGNORE_1__", "__IGNORE_1__": "__IGNORE_2__", "__IGNORE_2__": "__IGNORE__"}
                        strike_wf = _SOFT_IGNORE_MAP_WF.get(existing_wf, "__IGNORE__")
                        self.translation_cache[cache_key_wf] = strike_wf
                        self._cache_dirty = True
                        print(f"[WordFilter] 辞書外: '{text_raw[:30]}' → {strike_wf}")
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
                            
                            # --- 段階2: 正規化後の完全一致 ---
                            if norm_ck == norm_target:
                                found_trans = cv
                                break
                            
                            # --- 段階3: 曖昧一致 (SequenceMatcher) ---
                            # 文字数が大幅に異なるものはスキップ（速度対策）
                            len_ratio = len(norm_target) / max(len(norm_ck), 1)
                            if not (0.5 <= len_ratio <= 2.0):
                                continue
                            ratio = SequenceMatcher(None, norm_target, norm_ck).ratio()
                            if ratio > best_ratio:
                                best_ratio = ratio
                                best_cv = cv
                        
                        # 段階3の結果: 閾値(85%)以上の場合のみ採用
                        if not found_trans and best_ratio >= 0.85:
                            found_trans = best_cv
                            print(f"[Cache] Fuzzy match: ratio={best_ratio:.2f}, text='{text_raw[:30]}'...")

                if found_trans:
                    # ソフトIGNOREはヒットとみなさずリトライ（Nストライク制）
                    if found_trans in ("__IGNORE_1__", "__IGNORE_2__"):
                        new_chunks.append(chunk)
                        continue
                    
                    # --- 永久IGNOREのfastText再評価 ---
                    # fastTextが明確に自然言語と認識できるなら、旧ロジックで誤記録された
                    # 可能性があるため __IGNORE_1__ に降格して再試行を許可する
                    if found_trans == "__IGNORE__":
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
                        # 信頼度低（真のゴミテキスト）→ 永久IGNOREを維持
                        self.active_translations[cid] = True
                        continue
                    
                    # --- 既存翻訳の品質チェック (事後リフレッシュ) ---
                    # 過去に保存された翻訳が、現在の基準（要約されていないか、前置きがないか等）
                    # を満たしていない場合は、キャッシュミスとして扱い再翻訳させる。
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
                    self.overlay.show_translation(cid, chunk, found_trans, target_lang)
                    self.overlay_state[cid] = {
                        "text": found_trans,
                        "raw_text": text_raw,
                        "rect": chunk["rect"],
                        "bg_color": chunk.get("bg_color", "rgba(0,0,0,1.0)"),
                        "text_color": "#ffffff",
                        "lines_count": chunk.get("lines_count", 1)
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
                    print(f"[DblCheck] 表示中の大きな枠に重なり({ioa:.0%})かつ小さい({area1:.0f}<{area2:.0f})ため翻訳スキップ: '{chunk['text'][:30]}'")
                    break
            if not is_shadowed:
                final_new_chunks.append(chunk)
        new_chunks = final_new_chunks


        # ステータス情報の更新準備
        translated_count = len(self.overlay.active_labels)
        backlog = self.translator.backlog_count
        latency = self.translator.avg_latency
        perf_info = f" | ⚡ Latency: {latency:.1f}s | 📥 Queue: {backlog}"

        if not new_chunks:
            self.overlay.set_status(f" 👀 監視中... (変更なし / 翻訳済: {translated_count}個){perf_info} | {self.window_title}")
            return
            
        # 【優先順位付け】新しく発見された長文・大きなフォントを優先
        new_chunks.sort(key=lambda c: (len(c['text']), c['rect']['h']), reverse=True)
        
        # 【動的スロットリング】バックログとLatencyに応じた送信制御
        current_time = time.time()
        
        # 1. 緊急停止ロジック: キューが溜まりすぎている場合は新規送信を完全に止める
        if backlog > 20:
            self.overlay.set_status(f"⚠️ 高負荷：キューを消化中... (残: {backlog}件 / 翻訳済: {translated_count}個){perf_info}")
            return

        # 2. Latencyに基づくグローバル送信間隔の計算 (2.0s〜Latencyの80%)
        # 例: Latencyが4sなら3.2s、2.5sなら2.0s待機
        global_interval = max(1.5, latency * 0.8)
        
        # 3. 前回のリクエストから十分な時間が経過しているか判定
        if current_time - self.last_request_time < global_interval:
            # まだ待機中。UIの位置更新などはパス1/2で完了しているので、ここでは何もしない
            return

        # ここまで来たら新規リクエストを送信可能
        # 送信可能枠 (バックログが溜まっている時は1件ずつ慎重に送る)
        if backlog > 10:
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
                if current_time - self.last_short_word_time < limit_sec:
                    continue
                else:
                    self.last_short_word_time = current_time
            chunks_to_send.append(chunk)

        if not chunks_to_send:
            return

        # ステータス更新 & 翻訳依頼の送信
        status_msg = f"🔄 翻訳中... (新規: {len(chunks_to_send)}個 / 翻訳済: {translated_count}個){perf_info} | 対象: {self.window_title}"
        self.overlay.set_status(status_msg)
        
        self.last_request_time = current_time # 送信時刻を更新
        
        for chunk in chunks_to_send:
            self.active_translations[chunk['id']] = True
            self.pending_texts.add(chunk['text'].strip())
            
            # fastText で発信元言語と信頼度を判定してチャンクに付与
            ocr_hint = chunk.get('lang', 'en').split('-')[0].lower()
            detected_lang, lang_conf = detect_source_language(
                chunk['text'],
                ocr_lang_hint=ocr_hint,
            )
            chunk['detected_source_lang'] = detected_lang
            
            # --- fastText 低信頼度チェック: OCRゴミを翻訳前に事前ストライク ---
            # 信頼度が極めて低い（fastTextが言語を特定できない）テキストは
            # 翻訳しても無意味なため、事前に IGNORE ストライクを与える
            if lang_conf < 0.2:
                text_raw_ps = chunk['text'].strip()
                # 1語、短文、または3語以上の明確なフレーズには事前ストライクを適用しない
                if len(text_raw_ps.split()) <= 1 or len(text_raw_ps) < 12 or len(text_raw_ps.split()) >= 3:
                    pass  # 事前ストライクをスキップして翻訳へ
                else:
                    target_lang_ps = self.config.get("target_language", "ja")
                    cache_key_ps = f"{target_lang_ps}::{text_raw_ps}"
                    _SOFT_IGNORE_MAP = {"": "__IGNORE_1__", "__IGNORE_1__": "__IGNORE_2__", "__IGNORE_2__": "__IGNORE__"}
                    existing_ps = self.translation_cache.get(cache_key_ps, "")
                    if existing_ps != "__IGNORE__":
                        strike = _SOFT_IGNORE_MAP.get(existing_ps, "__IGNORE__")
                        self.translation_cache[cache_key_ps] = strike
                        self._cache_dirty = True
                        print(f"[Cache] Pre-strike (low lang conf={lang_conf:.2f}): '{text_raw_ps[:30]}' -> {strike}")
                    self.pending_texts.discard(text_raw_ps)
                    continue  # 翻訳キューへは送らない
            
            check_active = lambda cid=chunk['id']: cid in getattr(self, "active_translations", {})
            self.translator.translate_single_async(chunk, self._on_single_translation_done, is_active_check=check_active)

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
            
        # 【最重要：画面に無い長文でも必ずキャッシュに記録する】
        # (次回表示時に正規化一致で救えるようにするため、原文のまま保存)
        self.translation_cache[cache_key] = final_translation
        self.translation_cache.move_to_end(cache_key)
        
        if len(self.translation_cache) > 2000:
            self.translation_cache.popitem(last=False)
            
        self._cache_dirty = True
        
        # コールバック時点での表示処理
        # 元のリクエストID(cid)が画面の揺れ等で消散し、同じテキストの新しいIDが画面にある場合（limbo状態）を救済するため、
        # 現在アクティブな全ラベルのうち、同じテキストを持つもの全てに対して翻訳結果を送信する
        if is_valid:
            text_clean = chunk['text'].strip()
            for active_cid in list(self.active_translations.keys()):
                # すでに画面から消えている（現在のフレームに存在しない）枠には絶対に描画しない（適当な位置にポップアップするのを防ぐ）
                if active_cid not in getattr(self, "current_ids", set()):
                    if active_cid in self.active_translations:
                        del self.active_translations[active_cid]
                    continue
                    
                ac_chunk = self.history_chunks.get(active_cid)
                if ac_chunk and ac_chunk['text'].strip() == text_clean:
                    # 【改善】翻訳中の座標移動に対応：最新の追従座標があるならそれに差し替える
                    if active_cid in self.overlay_state:
                        ac_chunk['rect'] = self.overlay_state[active_cid]['rect']
                        
                    self.overlay.show_translation(active_cid, ac_chunk, final_translation, target_lang)
                    
                    self.overlay_state[active_cid] = {
                        "text": final_translation,
                        "raw_text": text_clean,
                        "rect": ac_chunk["rect"],
                        "bg_color": ac_chunk.get("bg_color", "rgba(0,0,0,1.0)"),
                        "text_color": "#ffffff",
                        "lines_count": ac_chunk.get("lines_count", 1)
                    }


class ControlPanel(QMainWindow):
    """メインのコントロールパネル（設定画面）"""
    
    # Flaskスレッドからの操作用シグナル
    sig_toggle_translation = pyqtSignal()
    sig_force_retranslate = pyqtSignal()
    
    def __init__(self, config_path: str):
        super().__init__()
        self.config_path = config_path
        self.config = load_config(config_path)
        self.controller = None
        
        self.sig_toggle_translation.connect(self.toggle_translation)
        self.sig_force_retranslate.connect(self.force_retranslate)
        
        self._setup_window()
        self._setup_ui()
        self._init_controller()

        # ステータス表示の自動更新タイマー（2秒おきに最新の状態を確認）
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._refresh_status_labels)
        self.status_timer.start(2000)

        
    def _setup_window(self):
        self.setWindowTitle("Real Time Translate - Control Panel v1.1.1")
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
        models = Translator.get_available_models(ollama_url)
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

        self.sens_values = [2400, 1200, 800, 600, 400, 200]
        self.slider_sensitivity = QSlider(Qt.Orientation.Horizontal)
        self.slider_sensitivity.setRange(0, 5)
        self.slider_sensitivity.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_sensitivity.setTickInterval(1)
        
        curr_sens = self.config.get("ocr_skip_sensitivity", 800)
        if curr_sens not in self.sens_values: curr_sens = 800
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
            if hasattr(self, 'controller') and self.controller:
                self.controller.config["ocr_thread_limit_percent"] = val
                self.controller.apply_cpu_limit()
            save_config(self.config, self.config_path)

        self.slider_cpu_limit.valueChanged.connect(on_cpu_change)
        settings_vbox.addWidget(self.slider_cpu_limit)

        layout.addWidget(settings_group)

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
        self.controller.start()
        
        # UI状態更新
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

        # ステータス表示を最新に更新
        self._refresh_status_labels()

    def stop_translation(self):
        self.controller.stop()
        self.btn_start.setEnabled(True)
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

@app_flask.route('/api/translate', methods=['GET', 'POST'])
def api_translate():
    if global_panel_ref:
        # ControlPanel がある場合はシグナルを送信、ヘッドレスの場合は直接 controller を操作
        if hasattr(global_panel_ref, 'sig_toggle_translation'):
            global_panel_ref.sig_toggle_translation.emit()
        elif hasattr(global_panel_ref, 'controller'):
            ctrl = global_panel_ref.controller
            if ctrl.is_running: ctrl.stop()
            else: ctrl.start()
        return jsonify({"status": "success", "action": "toggle_translation"})
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
        return jsonify({
            "window": ctrl.window_rect_data,
            "translations": ctrl.overlay_state
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
    import argparse
    global global_panel_ref

    parser = argparse.ArgumentParser(description="RTtranslator")
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
        class _HeadlessPanelProxy:
            def __init__(self, controller, cfg_path):
                self.controller = controller
                self.config_path = str(cfg_path)

        global_panel_ref = _HeadlessPanelProxy(ctrl, config_path)
        ctrl.start()
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
