import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox, filedialog
import json
import os
import requests
import sounddevice as sd
from datetime import datetime
import sys
import threading # 追加
import uuid

# --- Nuitka/ビルド環境および開発環境用の強力なパス解決 ---
def get_root_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        # settings_ui.py が scripts/ 内にある場合、その一つ上がルート
        current_file_path = os.path.dirname(os.path.abspath(__file__))
        if os.path.basename(current_file_path) == "scripts":
            return os.path.dirname(current_file_path)
        else:
            return current_file_path

base_dir = get_root_dir()

# --- 自作モジュールのインポート ---
get_db_stats = None
clean_up_database = None

try:
    # Nuitka ビルド時は scripts パッケージ配下としてインポート
    try:
        from scripts.db_maintenance import get_db_stats, clean_up_database
        from scripts import game_ai, config_manager
        print("DEBUG: db_maintenance, game_ai and config_manager loaded via scripts")
    except ImportError:
        # 開発時のフォールバック
        import game_ai
        from scripts import config_manager
        get_db_stats = db_maintenance.get_db_stats
        clean_up_database = db_maintenance.clean_up_database
        print("DEBUG: db_maintenance, game_ai and config_manager loaded via direct import")
except Exception as e:
    print(f"DEBUG: Import failed. Error: {e}")

# --- Helper: Fetch Ollama Models ---
def get_ollama_models(ollama_url):
    """Ollama API から利用可能なモデルの一覧を取得する"""
    default_models = ["llama4:scout", "llama3.2-vision", "llama3.1:8b", "gemma2:9b", "gemma3:1b", "gemma3:4b", "gemma3:12b"]
    try:
        # e.g. "http://localhost:11434/v1" -> "http://localhost:11434/api/tags"
        base_url = ollama_url.split("/v1")[0].rstrip("/")
        api_tags_url = f"{base_url}/api/tags"
        resp = requests.get(api_tags_url, timeout=2.0)
        if resp.status_code == 200:
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
            if models:
                # デフォルトの必須モデルが含まれていなければ追加（任意）するか、
                # 取得できたものだけを返す。ここでは実在するモデルのみを返す。
                return models
    except Exception as e:
        print(f"DEBUG: Failed to fetch Ollama models: {e}")
    # APIエラーや接続不可の場合はフォールバックを返す
    return default_models

def open_settings_window(parent, config_path, current_config, save_callback):
    config = current_config.copy()
    
    # 言語リソースの取得 (KeyError対策付き)
    l_set = parent.lang.get("settings", {})
    sys_lang = parent.lang.get("system", {})

    test_session_id = str(uuid.uuid4())

    root = tk.Toplevel(parent)
    root.title(l_set.get("win_title", "Settings"))
    root.geometry("600x850") 
    # root.attributes("-topmost", True) # Removed to allow normal window behavior

    # メインコンテナ（Notebook用）とフッター（保存ボタン用）
    main_container = tk.Frame(root)
    main_container.pack(expand=True, fill="both")

    footer_frame = tk.Frame(root)
    footer_frame.pack(side="bottom", fill="x")

    notebook = ttk.Notebook(main_container)
    notebook.pack(expand=True, fill="both", padx=10, pady=10)

    # --- タブの定義 ---
    tab_general = tk.Frame(notebook)
    tab_audio_view = tk.Frame(notebook)
    tab_hotkeys = tk.Frame(notebook)
    tab_search = tk.Frame(notebook)
    tab_database = tk.Frame(notebook)
    tab_extensions = tk.Frame(notebook)
    tab_rtt = tk.Frame(notebook)

    notebook.add(tab_general, text=l_set.get("tab_general", "General"))
    notebook.add(tab_audio_view, text=l_set.get("tab_audio_view", "View / Audio"))
    notebook.add(tab_hotkeys, text=l_set.get("tab_hotkey", "Hotkeys"))
    notebook.add(tab_search, text=l_set.get("tab_search", "Search"))
    notebook.add(tab_database, text=l_set.get("tab_database", "Database"))
    notebook.add(tab_extensions, text=l_set.get("tab_extensions", "Extensions"))
    notebook.add(tab_rtt, text=l_set.get("tab_rtt", "RTトランスレーター"))

    def add_label(parent_widget, text, pady=(10,0)):
        lbl = tk.Label(parent_widget, text=text)
        lbl.pack(pady=pady)
        return lbl

    # --- UIテキスト更新用関数 ---
    def refresh_ui_text():
        nonlocal l_set, sys_lang
        root.title(l_set.get("win_title", "Settings"))
        
        # タブタイトル
        notebook.tab(0, text=l_set.get("tab_general", "General"))
        notebook.tab(1, text=l_set.get("tab_audio_view", "View / Audio"))
        notebook.tab(2, text=l_set.get("tab_hotkey", "Hotkeys"))
        notebook.tab(3, text=l_set.get("tab_search", "Search"))
        notebook.tab(4, text=l_set.get("tab_database", "Database"))
        notebook.tab(5, text=l_set.get("tab_extensions", "Extensions"))
        notebook.tab(6, text=l_set.get("tab_rtt", "RTトランスレーター"))

        # 全般設定
        lbl_ai_provider.config(text=l_set.get("label_ai_provider", "AI Provider:"))
        lbl_model_normal.config(text=l_set.get("model_normal", "Normal Model:"))
        lbl_model_pro.config(text=l_set.get("model_pro", "Pro Model:"))
        lbl_lang.config(text=l_set.get("label_lang_restart", "Language:"))
        intersecting_ai_check.config(text=l_set.get("label_use_intersecting", "Simultaneously executes two AI and internet searches"))

        # View / Audio
        view_group.config(text=" " + l_set.get("tab_audio_view", "View & Window Settings") + " ")
        lbl_max_chars.config(text=l_set.get("max_chars", "Max Characters:"))
        lbl_window_alpha.config(text=l_set.get("window_alpha", "Window Alpha:"))
        lbl_font_size.config(text=l_set.get("font_size", "Font Size") + " (Log Window):")
        lbl_display_time.config(text=l_set.get("display_time", "Display Time") + " (Overlay):")
        
        audio_group.config(text=" " + l_set.get("tab_audio_view", "Audio Settings") + " ")
        lbl_voice_volume.config(text=l_set.get("label_voice_volume", "Voice Volume:"))
        lbl_output_device.config(text=l_set.get("audio_device", "Output Device:"))
        lbl_input_device.config(text=l_set.get("label_input_device", "Input Device:"))
        btn_test.config(text=l_set.get("btn_test_audio", "Test Sound"))
        btn_stop.config(text=l_set.get("btn_stop_test", "Stop"))
        btn_refresh.config(text=l_set.get("btn_refresh_devices", "Refresh Devices"))
        lbl_vv_path.config(text=l_set.get("label_vv_path", "VOICEVOX Path:"))
        btn_browse.config(text=l_set.get("browse", "Browse"))
        lbl_vv_speaker.config(text=l_set.get("voicevox_speaker", "Speaker:"))

        # Hotkeys
        lbl_hk_title.config(text=l_set.get("hotkey_title", "Hotkeys"))
        lbl_hk_voice.config(text=l_set.get("hotkey_voice", "Voice Mode:"))
        lbl_hk_vision.config(text=l_set.get("hotkey_vision", "Vision Mode:"))
        lbl_hk_stop.config(text=l_set.get("hotkey_stop", "Stop AI:"))

        # Search
        check_search.config(text=l_set.get("search_enable", "Enable Search"))
        lbl_sm.config(text=l_set.get("model_summary", "Summary Model (Local Ollama):"))
        refresh_search_usage_text()
        lbl_search_limit.config(text=l_set.get("search_limit_notice", "※無料枠の上限は月間1000回です。"))

        # Database
        lbl_db_t.config(text=l_set.get("db_title", "長期記憶設定 (ChromaDB)"))
        stats_group.config(text=" " + l_set.get('db_stats_group', '統計情報') + " ")
        btn_stats_ref.config(text=l_set.get("btn_refresh", "更新"))
        db_model_group.config(text=" " + l_set.get('db_model_settings', '記憶整理用AIモデル') + " ")
        lbl_db_p.config(text=l_set.get("label_db_provider", "プロバイダー:"))
        lbl_db_m.config(text=l_set.get("label_db_model", "記憶要約モデル:"))
        maintenance_group.config(text=" " + l_set.get('db_maintenance_group', 'メンテナンス') + " ")
        viewer_btn.config(text=l_set.get("btn_open_memory_viewer", "記憶の一覧・管理を表示"))

        # Extensions
        lbl_subtitle_ext.config(text=l_set.get("enable_subtitle", "Enable Local AI Subtitle System Integration\n(Sends text to ws://localhost:8765)"))
        
        if 'lbl_search_provider' in locals() or 'lbl_search_provider' in globals():
            lbl_search_provider.config(text=l_set.get("search_provider_label", "Search Engine:"))
        if 'lbl_grounding_notice' in locals() or 'lbl_grounding_notice' in globals():
            lbl_grounding_notice.config(text=l_set.get("search_provider_notice", "※Google Search選択時は「gemini-2.5-flash-lite」で固定されます。"))

        try:
            lbl_deprecation_notice.config(text=l_set.get("deprecation_notice", "⚠  Gemini 2.5 シリーズ 終了予定日       \nGemini 2.5 Flash: 2026年6月17日　／　Gemini 2.5 Flash-Lite: 2026年7月22日"))
            gemini_frame.config(text=l_set.get("setting_group_gemini", " Gemini Settings "))
            thinking_label.config(text=l_set.get("thinking_level_label", "思考レベル (3.1-flash-lite のみ):"))
            openai_frame.config(text=l_set.get("setting_group_openai", " OpenAI Settings "))
            llama_frame.config(text=l_set.get("setting_group_llama", " Llama (Local Ollama) Settings "))
            lbl_local_model_id.config(text=l_set.get("label_local_model_id", "Local Model ID:"))
            lbl_extensions_t.config(text=l_set.get("tab_extensions_title", "Extensions (Experimental)"))
            extensions_group.config(text=l_set.get("extensions_group_api", " API / WebSockets "))
            btn_fetch_ollama.config(text=l_set.get("btn_fetch_ollama", "Ollamaのモデルリストを取得・更新"))
        except NameError:
            pass

        # Footer
        btn_save.config(text=l_set.get("btn_save", "Save"))
        btn_save_close.config(text=l_set.get("btn_save_close", "Save & Close"))
        btn_cancel.config(text=l_set.get("btn_cancel", "Cancel"))

    def refresh_search_usage_text():
        now = datetime.now()
        g_count = config.get("GROUNDING_COUNT", 0)
        t_count = config.get("TAVILY_COUNT", 0)
        
        # 個別ラベルを取得しつつ、連結して表示
        g_tpl = l_set.get("search_usage_grounding_short", "Google (今日): {count}回")
        t_tpl = l_set.get("search_usage_tavily_short", "Tavily (今月): {count}回")
        
        g_text = g_tpl.format(count=g_count, date=now.strftime("%Y-%m-%d"))
        t_text = t_tpl.format(count=t_count, month=now.month)
        
        usage_label.config(text=f"{g_text}  /  {t_text}")

    # --- 1. 全般設定タブ ---
    # --- Gemini 2.5 廃止予定日 警告ラベル ---
    deprecation_frame = tk.Frame(tab_general, relief="ridge", bd=1, padx=8, pady=4)
    deprecation_frame.pack(fill="x", padx=10, pady=(8, 0))
    lbl_deprecation_notice = tk.Label(
        deprecation_frame,
        text=l_set.get("deprecation_notice", "⚠  Gemini 2.5 シリーズ 終了予定日       \nGemini 2.5 Flash: 2026年6月17日　／　Gemini 2.5 Flash-Lite: 2026年7月22日"),
        fg="#cc4400", font=("MS Gothic", 9, "bold"), justify="left"
    )
    lbl_deprecation_notice.pack(anchor="w")

    lbl_ai_provider = add_label(tab_general, l_set.get("label_ai_provider", "AI Provider:"), pady=(5,0))
    provider_var = tk.StringVar(tab_general, config.get("AI_PROVIDER", "gemini"))
    provider_frame = tk.Frame(tab_general)
    provider_frame.pack(pady=5)
    
    for p_val in ["gemini", "openai", "local"]:
        tk.Radiobutton(provider_frame, text=p_val.capitalize(), variable=provider_var, value=p_val).pack(side="left", padx=5)

    # Gemini Frame
    gemini_frame = tk.LabelFrame(tab_general, text=l_set.get("setting_group_gemini", " Gemini Settings "), padx=10, pady=5)
    gemini_frame.pack(pady=5, fill="x", padx=20)
    add_label(gemini_frame, "Gemini API Key:", pady=0)
    gemini_key_entry = tk.Entry(gemini_frame, width=50, show="*")
    gemini_key_entry.insert(0, config.get("GEMINI_API_KEY", ""))
    gemini_key_entry.pack(pady=2)

    lbl_model_normal = add_label(gemini_frame, l_set.get("model_normal", "Normal Model:"), pady=(5,0))
    # すべての候補を維持
    gemini_models = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-3.1-flash-lite-preview"]
    model_var = tk.StringVar(gemini_frame, config.get("MODEL_ID", "gemini-2.5-flash"))
    tk.OptionMenu(gemini_frame, model_var, *gemini_models).pack(pady=2)

    # 思考レベル (gemini-3.1-flash-lite-preview のみ)
    thinking_label = add_label(gemini_frame, l_set.get("thinking_level_label", "思考レベル (3.1-flash-lite のみ):"), pady=(5,0))
    THINKING_OPTIONS = {
        l_set.get("thinking_min", "最小"):     "minimal",
        l_set.get("thinking_low", "低"):       "low",
        l_set.get("thinking_mid", "中"):       "medium",
        l_set.get("thinking_high", "高"):       "high",
    }
    _budget_val = config.get("THINKING_BUDGET", "medium")
    # もし古い数値データや無効なデータが残っていた場合は medium にする
    if _budget_val not in THINKING_OPTIONS.values():
        _budget_val = "medium"
    _reverse_map = {v: k for k, v in THINKING_OPTIONS.items()}
    _initial_thinking = _reverse_map.get(_budget_val, l_set.get("thinking_mid", "中"))
    thinking_var = tk.StringVar(gemini_frame, _initial_thinking)
    thinking_menu = tk.OptionMenu(gemini_frame, thinking_var, *THINKING_OPTIONS.keys())
    thinking_menu.pack(pady=2)

    def update_thinking_state(*args):
        if model_var.get() == "gemini-3.1-flash-lite-preview":
            thinking_menu.configure(state="normal")
            thinking_label.configure(fg="black")
        else:
            thinking_menu.configure(state="disabled")
            thinking_label.configure(fg="gray")

    model_var.trace_add("write", update_thinking_state)
    update_thinking_state()

    lbl_model_pro = add_label(gemini_frame, l_set.get("model_pro", "Pro Model:"), pady=(5,0))
    pro_models = ["gemini-3-flash-preview", "gemini-3.1-pro-preview"]
    model_pro_var = tk.StringVar(gemini_frame, config.get("MODEL_ID_PRO", "gemini-3.1-pro-preview"))
    tk.OptionMenu(gemini_frame, model_pro_var, *pro_models).pack(pady=2)

    # OpenAI Frame
    openai_frame = tk.LabelFrame(tab_general, text=l_set.get("setting_group_openai", " OpenAI Settings "), padx=10, pady=5)
    openai_frame.pack(pady=5, fill="x", padx=20)
    add_label(openai_frame, "OpenAI API Key:", pady=0)
    openai_key_entry = tk.Entry(openai_frame, width=50, show="*")
    openai_key_entry.insert(0, config.get("OPENAI_API_KEY", ""))
    openai_key_entry.pack(pady=2)
    gpt_models = ["gpt-5.4-nano", "gpt-5.4-mini", "gpt-5", "gpt-5.4", "gpt-5.5-2026-04-23"]
    gpt_model_var = tk.StringVar(openai_frame, config.get("MODEL_ID_GPT", "gpt-5.4-mini"))
    tk.OptionMenu(openai_frame, gpt_model_var, *gpt_models).pack(pady=2)

    # Llama (Ollama) Frame
    llama_frame = tk.LabelFrame(tab_general, text=l_set.get("setting_group_llama", " Llama (Local Ollama) Settings "), padx=10, pady=5)
    llama_frame.pack(pady=5, fill="x", padx=20)
    lbl_local_model_id = add_label(llama_frame, l_set.get("label_local_model_id", "Local Model ID:"), pady=0)
    
    # 前回取得したキャッシュモデルを使用（なければデフォルト）
    ollama_url_current = config.get("OLLAMA_URL", "http://localhost:11434/v1")
    # 本体側で取得済みのキャッシュを優先
    ollama_dynamic_models = getattr(parent, "cached_ollama_models", [])
    if not ollama_dynamic_models:
        ollama_dynamic_models = config.get("CACHED_OLLAMA_MODELS", [])
    
    if not ollama_dynamic_models:
        ollama_dynamic_models = ["llama4:scout", "llama3.2-vision", "llama3.1:8b", "gemma2:9b", "gemma3:1b", "gemma3:4b", "gemma3:12b"]
    
    current_llama_val = config.get("MODEL_ID_LOCAL", ollama_dynamic_models[0] if ollama_dynamic_models else "")
    if current_llama_val not in ollama_dynamic_models and ollama_dynamic_models:
        ollama_dynamic_models.insert(0, current_llama_val)
        
    llama_model_var = tk.StringVar(llama_frame, current_llama_val)
    # tk.OptionMenu の再描画対応用コンテナ
    llama_model_menu_container = tk.Frame(llama_frame)
    llama_model_menu_container.pack(pady=2)
    tk.OptionMenu(llama_model_menu_container, llama_model_var, *ollama_dynamic_models).pack()
    
    add_label(llama_frame, "Ollama Endpoint:", pady=0)
    ollama_url_entry = tk.Entry(llama_frame, width=50)
    ollama_url_entry.insert(0, ollama_url_current)
    ollama_url_entry.pack(pady=2)

    # 言語設定（ここを1回だけにまとめます）
    lbl_lang = add_label(tab_general, l_set.get("label_lang_restart", "Language:"))
    lang_map = {
        "日本語 (Japanese)": "ja", 
        "English": "en",
        "简体中文 (Chinese)": "zh-CN",
        "Español (Spanish)": "es",
        "한국어 (Korean)": "ko",
        "Français (French)": "fr",
        "Deutsch (German)": "de",
        "Italiano (Italian)": "it",
        "Português (Portuguese)": "pt",
        "Русский (Russian)": "ru"
    }
    inv_lang_map = {v: k for k, v in lang_map.items()}
    current_lang_display = inv_lang_map.get(config.get("LANGUAGE", "ja"), "日本語 (Japanese)")
    lang_var = tk.StringVar(tab_general, current_lang_display)
    lang_options = sorted(lang_map.keys()) # アルファベット順などに並べ替えると見やすい
    tk.OptionMenu(tab_general, lang_var, *lang_options).pack(pady=5)

    # 複合AIモード (USE_INTERSECTING_AI) のスイッチを追加（言語設定の直後に配置）
    intersecting_ai_var = tk.BooleanVar(tab_general, value=config.get("USE_INTERSECTING_AI", False))
    intersecting_ai_check = tk.Checkbutton(
        tab_general, 
        text=l_set.get("label_use_intersecting", "Simultaneously executes two AI and internet searches"), 
        variable=intersecting_ai_var,
        font=("MS Gothic", 10, "bold"),
        fg="#1E88E5"
    )
    intersecting_ai_check.pack(pady=10)

    # --- 2. View / Audio 設定タブ ---
    view_group = tk.LabelFrame(tab_audio_view, text=" View & Window Settings ", padx=10, pady=10)
    view_group.pack(pady=10, fill="x", padx=20)

    # 文字数制限の動的読み込み
    lbl_max_chars = add_label(view_group, l_set.get("max_chars", "Max Characters:"), pady=0)
    
    # 言語ファイルから選択肢を取得 (存在しない場合のフォールバック)
    char_opts_data = l_set.get("max_chars_options", {
        "labels": ["300文字以内", "700文字以内", "1000文字以内"],
        "values": [300, 700, 1000]
    })
    char_labels = char_opts_data["labels"]
    char_values = char_opts_data["values"]
    val_to_label = dict(zip(char_values, char_labels))
    label_to_val = dict(zip(char_labels, char_values))

    # 現在の設定値を取得・変換
    raw_max_chars = config.get("MAX_CHARS", 700)
    # 古い形式（文字列）が保存されている場合の移行処理
    if isinstance(raw_max_chars, str):
        if "300" in raw_max_chars: raw_max_chars = 300
        elif "1000" in raw_max_chars: raw_max_chars = 1000
        else: raw_max_chars = 700
    
    # 現在のラベルを決定（リストにない場合はデフォルト値を使用）
    current_char_label = val_to_label.get(raw_max_chars, char_labels[1])
    char_limit_var = tk.StringVar(view_group, current_char_label)
    
    # 言語が変更されたときに選択肢を更新する関数
    def update_char_limit_options(*args):
        # 最新の言語ファイルからオプションを再取得
        # (save_all はまだ呼ばれていない可能性があるので、lang_var から直接読み込む必要はないか?)
        # 実際には OptionMenu を作り直すか、内容を更新する必要があるが、
        # 設定画面を開き直すのが一般的。今回は「言語切り替え」→「保存」→「反映」のフローなので
        # とりあえず現状の言語に基づいた初期化で十分。
        pass

    tk.OptionMenu(view_group, char_limit_var, *char_labels).pack(pady=5)

    lbl_window_alpha = add_label(view_group, l_set.get("window_alpha", "Window Alpha:"), pady=0)
    alpha_opts = ["OFF", "0.3", "0.6", "0.8"]
    alpha_var = tk.StringVar(view_group, str(config.get("WINDOW_ALPHA", 0.6)))
    tk.OptionMenu(view_group, alpha_var, *alpha_opts).pack(pady=5)

    lbl_font_size = add_label(view_group, l_set.get("font_size", "Font Size") + " (Log Window):")
    font_size_var = tk.StringVar(view_group, str(config.get("LOG_FONT_SIZE", "13")))
    tk.OptionMenu(view_group, font_size_var, "10", "12", "13", "15", "18", "20", "24").pack(pady=5)

    lbl_display_time = add_label(view_group, l_set.get("display_time", "Display Time") + " (Overlay):")
    display_time_var = tk.StringVar(view_group, str(config.get("DISPLAY_TIME", "60")))
    tk.OptionMenu(view_group, display_time_var, "30", "60", "90", "120").pack(pady=5)

    audio_group = tk.LabelFrame(tab_audio_view, text=" Audio Settings ", padx=10, pady=10)
    audio_group.pack(pady=10, fill="x", padx=20)

    # 1. 出力音量
    lbl_voice_volume = add_label(audio_group, l_set.get("label_voice_volume", "Voice Volume:"), pady=(5,0))
    volume_var = tk.DoubleVar(value=config.get("VOICE_VOLUME", 0.7) * 100)
    volume_scale = tk.Scale(audio_group, from_=0, to=150, orient="horizontal", variable=volume_var)
    volume_scale.pack(fill="x", padx=20, pady=2)

    # 2. 出力デバイス (MMEに限定)
    def get_mme_devices():
        try:
            apis = sd.query_hostapis()
            mme_idx = next((i for i, a in enumerate(apis) if a['name'] == 'MME'), None)
            devices = sd.query_devices()
            out_list = ["デフォルト"]
            in_list = ["デフォルト"]
            
            for d in devices:
                if d['hostapi'] == mme_idx:
                    if d['max_output_channels'] > 0:
                        out_list.append(d['name'])
                    if d['max_input_channels'] > 0:
                        in_list.append(d['name'])
            return sorted(list(set(out_list))), sorted(list(set(in_list)))
        except:
            return ["デフォルト"], ["デフォルト"]

    out_devices, in_devices = get_mme_devices()

    # デバイス選択用横並びフレーム
    device_row_frame = tk.Frame(audio_group)
    device_row_frame.pack(fill="x", pady=5)

    # 出力デバイス（左側）
    out_frame = tk.Frame(device_row_frame)
    out_frame.pack(side="left", expand=True, fill="x", padx=5)
    lbl_output_device = add_label(out_frame, l_set.get("audio_device", "Output Device:"), pady=0)
    device_var = tk.StringVar(out_frame, config.get("DEVICE_NAME", "デフォルト"))
    device_menu = tk.OptionMenu(out_frame, device_var, *out_devices)
    device_menu.pack(pady=2)

    # 入力デバイス（右側）
    in_frame = tk.Frame(device_row_frame)
    in_frame.pack(side="left", expand=True, fill="x", padx=5)
    lbl_input_device = add_label(in_frame, l_set.get("label_input_device", "Input Device:"), pady=0)
    input_device_var = tk.StringVar(in_frame, config.get("INPUT_DEVICE_NAME", "デフォルト"))
    input_device_menu = tk.OptionMenu(in_frame, input_device_var, *in_devices)
    input_device_menu.pack(pady=2)

    # テスト再生ボタン
    def test_audio():
        target = device_var.get()
        vol = volume_var.get() / 100.0
        test_config = config.copy()
        test_config["DEVICE_NAME"] = target
        test_config["VOICE_VOLUME"] = vol
        test_config["SPEAKER_NAME"] = speaker_var.get()
        test_config["SPEAKER_ID"] = speaker_map.get(speaker_var.get(), 3)
        # 現在の言語設定を反映させる（これがないと古い言語のままテストされる）
        test_config["LANGUAGE"] = lang_map.get(lang_var.get(), "ja")
        
        # 最新の翻訳データからテキストを取得
        current_l_set = parent.lang.get("settings", {})
        test_text = current_l_set.get("test_audio_text", l_set.get("test_audio_text", "読み上げテストを開始します。"))
        
        # 新しいセッションIDを発行して前の再生を無効化
        nonlocal test_session_id
        test_session_id = str(uuid.uuid4())
        
        # メイン画面のセッションIDも監視対象に含める（メインの停止ボタンでも止まるようにする）
        session_id_at_start = (test_session_id, parent.active_session_id)
        session_data = (session_id_at_start, lambda: (test_session_id, parent.active_session_id), None)

        try:
            threading.Thread(target=game_ai.speak_and_show, args=(test_text, None, test_config, base_dir, session_data, False), daemon=True).start()
        except Exception as e:
            messagebox.showerror("Error", f"Test failed: {e}")

    def stop_test_audio():
        nonlocal test_session_id
        test_session_id = str(uuid.uuid4())

    # デバイスリスト更新ボタン
    def refresh_device_lists(btn_ref=None):
        o, i = get_mme_devices()
        device_menu['menu'].delete(0, 'end')
        for dev in o:
            device_menu['menu'].add_command(label=dev, command=tk._setit(device_var, dev))
        input_device_menu['menu'].delete(0, 'end')
        for dev in i:
            input_device_menu['menu'].add_command(label=dev, command=tk._setit(input_device_var, dev))
        
        if btn_ref:
            orig = btn_ref.cget("text")
            btn_ref.config(text="✓ Updated!", state="disabled")
            root.after(1500, lambda: btn_ref.config(text=orig, state="normal"))

    # ボタン用フレーム
    btn_frame = tk.Frame(audio_group)
    btn_frame.pack(pady=10)

    btn_test = tk.Button(btn_frame, text=l_set.get("btn_test_audio", "Test Sound"), command=test_audio)
    btn_test.pack(side="left", padx=10)
    btn_stop = tk.Button(btn_frame, text=l_set.get("btn_stop_test", "Stop"), command=stop_test_audio, bg="#f44336", fg="white")
    btn_stop.pack(side="left", padx=10)
    
    btn_refresh = tk.Button(btn_frame, text=l_set.get("btn_refresh_devices", "Refresh Devices"))
    btn_refresh.config(command=lambda: refresh_device_lists(btn_refresh))
    btn_refresh.pack(side="left", padx=10)

    lbl_vv_path = add_label(audio_group, l_set.get("label_vv_path", "VOICEVOX Path:"), pady=(10,0))
    vv_frame = tk.Frame(audio_group)
    vv_frame.pack(pady=5)
    vv_entry = tk.Entry(vv_frame, width=40)
    vv_entry.insert(0, config.get("VV_PATH", ""))
    vv_entry.pack(side="left")
    
    def browse_vv():
        path = filedialog.askopenfilename(filetypes=[("EXE", "*.exe")])
        if path:
            vv_entry.delete(0, tk.END)
            vv_entry.insert(0, path)
    btn_browse = tk.Button(vv_frame, text=l_set.get("browse", "Browse"), command=browse_vv)
    btn_browse.pack(side="left", padx=5)

    lbl_vv_speaker = add_label(audio_group, l_set.get("voicevox_speaker", "Speaker:"), pady=0)
    # 本体側で取得済みのキャッシュを使用
    speaker_map = getattr(parent, "cached_speakers", {"ずんだもん": 3, "四国めたん": 2, "春日部つむぎ": 8, "雨晴はう": 10})
    
    # フォールバック取得（キャッシュが空の場合のみ）
    if len(speaker_map) <= 4:
        try:
            resp = requests.get("http://127.0.0.1:50021/speakers", timeout=0.5)
            if resp.status_code == 200:
                speaker_map = {s['name']: s['styles'][0]['id'] for s in resp.json()}
        except: pass
    speaker_var = tk.StringVar(audio_group, config.get("SPEAKER_NAME", "ずんだもん"))
    tk.OptionMenu(audio_group, speaker_var, *speaker_map.keys()).pack(pady=5)

    # --- 3. ホットキー設定タブ ---
    lbl_hk_title = tk.Label(tab_hotkeys, text=l_set.get("hotkey_title", "Hotkeys"), font=("MS Gothic", 12, "bold"))
    lbl_hk_title.pack(pady=10)
    hk_config = config.get("HOTKEYS", {"voice_mode": "ctrl+alt+v", "vision_mode": "ctrl+alt+s", "stop_ai": "ctrl+alt+x"})
    
    lbl_hk_voice = add_label(tab_hotkeys, l_set.get("hotkey_voice", "Voice Mode:"))
    hk_voice_entry = tk.Entry(tab_hotkeys, width=30, justify="center")
    hk_voice_entry.insert(0, hk_config.get("voice_mode", "ctrl+alt+v"))
    hk_voice_entry.pack(pady=5)
    
    lbl_hk_vision = add_label(tab_hotkeys, l_set.get("hotkey_vision", "Vision Mode:"))
    hk_vision_entry = tk.Entry(tab_hotkeys, width=30, justify="center")
    hk_vision_entry.insert(0, hk_config.get("vision_mode", "ctrl+alt+s"))
    hk_vision_entry.pack(pady=5)
    
    lbl_hk_stop = add_label(tab_hotkeys, l_set.get("hotkey_stop", "Stop AI:"))
    hk_stop_entry = tk.Entry(tab_hotkeys, width=30, justify="center")
    hk_stop_entry.insert(0, hk_config.get("stop_ai", "ctrl+alt+x"))
    hk_stop_entry.pack(pady=5)

    # --- プロバイダー連動制御 ---
    def on_provider_change(*args):
        p = provider_var.get()
        frames = {
            "gemini": (gemini_frame, "Gemini Models (Active)"),
            "openai": (openai_frame, "OpenAI Models (Active)"),
            "local": (llama_frame, "Llama Local (Active)")
        }
        for key, (frame, title) in frames.items():
            if key == p:
                frame.config(labelwidget=tk.Label(frame, text=title, fg="#4CAF50", font=("bold")))
            else:
                frame.config(labelwidget=tk.Label(frame, text=f"{key.capitalize()} (Inactive)", fg="gray"))

    provider_var.trace_add("write", on_provider_change)
    on_provider_change()

    # --- 4. Search機能タブ ---
    lbl_search_header = tk.Label(tab_search, text="Web Search Settings (Tavily)", font=("MS Gothic", 12, "bold"))
    lbl_search_header.pack(pady=10)
    search_switch_var = tk.BooleanVar(value=config.get("search_switch", False))
    check_search = tk.Checkbutton(tab_search, text=l_set.get("search_enable", "Enable Search"), variable=search_switch_var)
    check_search.pack(pady=10)

    search_frame = tk.LabelFrame(tab_search, text=" Search & Summary Configuration ", padx=10, pady=10)
    search_frame.pack(pady=10, fill="x", padx=20)
    
    # 検索プロバイダー選択
    lbl_search_provider = add_label(search_frame, l_set.get("search_provider_label", "Search Engine:"), pady=(5,0))
    search_provider_var = tk.StringVar(search_frame, config.get("SEARCH_PROVIDER", "tavily"))
    SEARCH_OPTIONS = {
        l_set.get("search_opt_grounding_2_5", "gemini-2.5-flash-liteのgrounding"):                        "grounding",
        l_set.get("search_opt_tavily", "tavilyで検索しollamaで要約"):                               "tavily",
        l_set.get("search_opt_integrated", "grounding + tavily をollamaで統合要約"):                    "integrated",
        l_set.get("search_opt_grounding_3_1", "gemini-3.1-flash-lite-previewのgrounding (思考最小)"):     "grounding_3_1",
    }
    _sp_reverse = {v: k for k, v in SEARCH_OPTIONS.items()}
    _initial_sp = _sp_reverse.get(config.get("SEARCH_PROVIDER", "tavily"), l_set.get("search_opt_tavily", "tavilyで検索しollamaで要約"))
    search_disp_var = tk.StringVar(search_frame, _initial_sp)
    search_provider_menu = tk.OptionMenu(search_frame, search_disp_var, *SEARCH_OPTIONS.keys(), command=lambda _: refresh_search_usage_text())
    search_provider_menu.pack(pady=5)

    lbl_grounding_notice = tk.Label(search_frame, text=l_set.get("search_provider_notice", "※Google Search選択時は該当モデルが使われます"), font=("MS Gothic", 9), fg="gray")
    lbl_grounding_notice.pack(pady=0)
    
    # 既存のTavily Key
    add_label(search_frame, "TAVILY_API_KEY:", pady=(10,0))
    tavily_key_entry = tk.Entry(search_frame, width=50, show="*")
    tavily_key_entry.insert(0, config.get("TAVILY_API_KEY", ""))
    tavily_key_entry.pack(pady=5)

    lbl_sm = add_label(search_frame, l_set.get("model_summary", "Summary Model (Local Ollama):"), pady=(10,0))
    # 動的に取得したOllamaモデルリストを流用
    current_summary_val = config.get("MODEL_ID_SUMMARY", ollama_dynamic_models[0] if ollama_dynamic_models else "gemma2:9b")
    if current_summary_val not in ollama_dynamic_models and ollama_dynamic_models:
        ollama_dynamic_models.insert(0, current_summary_val)
        
    summary_model_var = tk.StringVar(search_frame, current_summary_val)
    summary_model_menu_container = tk.Frame(search_frame)
    summary_model_menu_container.pack(pady=5)
    tk.OptionMenu(summary_model_menu_container, summary_model_var, *ollama_dynamic_models).pack()

    # 検索使用回数表示
    usage_label = tk.Label(tab_search, text="", font=("MS Gothic", 11, "bold"), fg="#2196F3")
    usage_label.pack(pady=15)
    refresh_search_usage_text()
    
    lbl_search_limit = add_label(tab_search, l_set.get("search_limit_notice", "※無料枠の上限は月間1000回です。"), pady=0)

    # --- 5. Databaseタブ ---
    lbl_db_t = tk.Label(tab_database, text=l_set.get("db_title", "長期記憶設定 (ChromaDB)"), font=("MS Gothic", 12, "bold"))
    lbl_db_t.pack(pady=10)

    # 1. 統計情報グループ
    stats_group = tk.LabelFrame(tab_database, text=f" {l_set.get('db_stats_group', '統計情報')} ", padx=10, pady=10)
    stats_group.pack(pady=10, fill="x", padx=20)

    stats_label = tk.Label(stats_group, text=l_set.get("db_stats_loading", "Loading..."), font=("MS Gothic", 11), justify="center")
    stats_label.pack(pady=5)

    def refresh_stats():
        if get_db_stats:
            try:
                # get_root_dir() で取得した base_dir (ルート) の直下にある memory_db を指定
                current_db_path = os.path.join(base_dir, "memory_db")
                
                c, s = get_db_stats(current_db_path)
                stats_tpl = l_set.get("db_stats_format", "合計記憶数： {count} 件\nDBサイズ： {size} MB")
                stats_label.config(text=stats_tpl.format(count=c, size=s), fg="black")
            except Exception as e:
                stats_label.config(text=f"Error: {str(e)}", fg="red")
        else:
            # get_db_stats が None の場合（インポート失敗時）
            stats_label.config(text=l_set.get("db_error_module", "Error: db_maintenance module missing."), fg="red")

    refresh_stats()
    btn_stats_ref = tk.Button(stats_group, text=l_set.get("btn_refresh", "更新"), command=refresh_stats)
    btn_stats_ref.pack()

    # 2. 記憶整理用AIモデルグループ (画像のデザインを再現し、動的更新に対応)
    db_model_group = tk.LabelFrame(tab_database, text=f" {l_set.get('db_model_settings', '記憶整理用AIモデル')} ", padx=10, pady=10)
    db_model_group.pack(pady=10, fill="x", padx=20)

    lbl_db_p = add_label(db_model_group, l_set.get("db_provider_label", "プロバイダー:"), pady=(5,0))
    db_provider_var = tk.StringVar(db_model_group, config.get("DB_PROVIDER", "local"))
    db_p_frame = tk.Frame(db_model_group)
    db_p_frame.pack(pady=5)

    lbl_db_m = add_label(db_model_group, l_set.get("label_db_model", "記憶要約モデル:"), pady=(5,0))
    db_model_var = tk.StringVar(db_model_group, config.get("DB_MODEL_ID", "gemma3:4b"))
    
    # オプションメニューを保持するためのコンテナ
    db_model_menu_container = tk.Frame(db_model_group)
    db_model_menu_container.pack(pady=5)

    def update_db_model_list(*args):
        # 現在のメニューを削除
        for widget in db_model_menu_container.winfo_children():
            widget.destroy()
        
        provider = db_provider_var.get()
        if provider == "gemini":
            # 最新の gemini-2.5-flash-lite を筆頭に配置
            models = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3-flash-preview", "gemini-3.1-flash-lite-preview（中）"]
        elif provider == "openai":
            # 2/13に終了する旧モデルを排除し、あなたが最適化した最新モデルのみを配置
            models = ["gpt-5.4-nano", "gpt-5.4-mini", "gpt-5", "gpt-5.4", "gpt-5.5-2026-04-23"]
        else: # local
            # APIから取得した最新のOllamaリストを使用
            models = ollama_dynamic_models.copy() if ollama_dynamic_models else ["gemma3:4b", "gemma3:1b", "gemma3:12b", "gemma2:9b", "llama3.2:3b"]
        
        # 既存の設定値がリストにない場合は先頭を選択
        if db_model_var.get() not in models and models:
            # 既に設定されている値があれば追加しつつ選択
            models.insert(0, db_model_var.get())
        elif not models:
            models = ["gemma3:4b"] # 究極のフォールバック
            db_model_var.set(models[0])
            
        tk.OptionMenu(db_model_menu_container, db_model_var, *models).pack()

    # ラジオボタン作成
    for dp in ["gemini", "openai", "local"]:
        tk.Radiobutton(db_p_frame, text=dp.capitalize(), variable=db_provider_var, value=dp).pack(side="left", padx=10)

    # 変更監視と初期実行
    db_provider_var.trace_add("write", update_db_model_list)
    update_db_model_list()

    # 3. メンテナンスグループ
    maintenance_group = tk.LabelFrame(tab_database, text=f" {l_set.get('db_maintenance_group', 'メンテナンス')} ", padx=10, pady=10)
    maintenance_group.pack(pady=10, fill="x", padx=20)

    def open_viewer():
        try:
            from scripts.memory_viewer import open_memory_viewer
            open_memory_viewer(parent, config)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open viewer: {e}")

    # 記憶一覧・管理ボタン (旧クリーンアップボタンの代わり)
    viewer_btn = tk.Button(maintenance_group, 
                          text=l_set.get("btn_open_memory_viewer", "記憶の一覧・管理を表示"), 
                          command=open_viewer, 
                          bg="#2196F3", 
                          fg="white", 
                          pady=10)
    viewer_btn.pack(pady=10, fill="x")

    # --- 6. 拡張機能 (Extensions) タブ ---
    lbl_extensions_t = tk.Label(tab_extensions, text=l_set.get("tab_extensions_title", "Extensions (Experimental)"), font=("MS Gothic", 12, "bold"))
    lbl_extensions_t.pack(pady=10)

    extensions_group = tk.LabelFrame(tab_extensions, text=l_set.get("extensions_group_api", " API / WebSockets "), padx=10, pady=10)
    extensions_group.pack(pady=10, fill="x", padx=20)
    
    # --- New Button for Ollama Model Fetch ---
    def fetch_ollama_models_async():
        original_text = btn_fetch_ollama.cget("text")
        btn_fetch_ollama.config(text=l_set.get("btn_fetching", "取得中..."), state="disabled")
        
        def _task():
            current_url = ollama_url_entry.get()
            fetched = get_ollama_models(current_url)
            
            def _update_ui():
                nonlocal fetched
                if not fetched:
                    fetched = ["llama4:scout", "llama3.2-vision", "llama3.1:8b", "gemma2:9b", "gemma3:1b", "gemma3:4b", "gemma3:12b"]
                
                # キャッシュも更新
                config["CACHED_OLLAMA_MODELS"] = fetched
                ollama_dynamic_models.clear()
                ollama_dynamic_models.extend(fetched)
                
                # Local Model 更新
                for widget in llama_model_menu_container.winfo_children():
                    widget.destroy()
                if llama_model_var.get() not in fetched:
                    llama_model_var.set(fetched[0] if fetched else "")
                tk.OptionMenu(llama_model_menu_container, llama_model_var, *fetched).pack()

                # Summary Model 更新
                for widget in summary_model_menu_container.winfo_children():
                    widget.destroy()
                if summary_model_var.get() not in fetched:
                    summary_model_var.set(fetched[0] if fetched else "")
                tk.OptionMenu(summary_model_menu_container, summary_model_var, *fetched).pack()
                
                # DB Model (Local) 更新
                update_db_model_list()

                btn_fetch_ollama.config(text=l_set.get("btn_fetch_success", "取得完了！"), state="disabled")
                root.after(2000, lambda: btn_fetch_ollama.config(text=original_text, state="normal"))
            
            root.after(0, _update_ui)
        
        threading.Thread(target=_task, daemon=True).start()

    btn_fetch_ollama = tk.Button(
        extensions_group,
        text=l_set.get("btn_fetch_ollama", "Ollamaのモデルリストを取得・更新"),
        command=fetch_ollama_models_async,
        bg="#4CAF50",
        fg="white"
    )
    btn_fetch_ollama.pack(pady=5, fill="x")

    subtitle_en_var = tk.BooleanVar(value=config.get("ENABLE_SUBTITLE", False))
    lbl_subtitle_ext = tk.Checkbutton(
        extensions_group, 
        text=l_set.get("enable_subtitle", "Enable Local AI Subtitle System Integration\n(Sends text to ws://localhost:8765)"), 
        variable=subtitle_en_var
    )
    lbl_subtitle_ext.pack(pady=10, anchor="w")

    # ================================================================
    # --- RTトランスレーター 設定タブ ---
    # ================================================================
    import os as _os

    rtt_canvas = tk.Canvas(tab_rtt, highlightthickness=0)
    rtt_vsb = tk.Scrollbar(tab_rtt, orient="vertical", command=rtt_canvas.yview)
    rtt_canvas.configure(yscrollcommand=rtt_vsb.set)
    rtt_vsb.pack(side="right", fill="y")
    rtt_canvas.pack(side="left", fill="both", expand=True)
    rtt_scroll_frame = tk.Frame(rtt_canvas)
    rtt_scroll_win = rtt_canvas.create_window((0, 0), window=rtt_scroll_frame, anchor="nw")
    rtt_scroll_frame.bind("<Configure>", lambda e: rtt_canvas.configure(scrollregion=rtt_canvas.bbox("all")))
    rtt_canvas.bind("<Configure>", lambda e: rtt_canvas.itemconfig(rtt_scroll_win, width=e.width))

    # ── Ollama 翻訳エンジン設定グループ ──
    rtt_ollama_group = tk.LabelFrame(rtt_scroll_frame, text=l_set.get("rtt_group_ollama", " Ollama 翻訳エンジン設定 "))
    rtt_ollama_group.pack(fill="x", padx=8, pady=5)

    tk.Label(rtt_ollama_group, text=l_set.get("rtt_label_model", "使用モデル:"), anchor="w").grid(row=0, column=0, sticky="w", padx=8, pady=4)
    rtt_ollama_models_default = config.get("CACHED_OLLAMA_MODELS", ["translategemma:4b"])
    rtt_model_var = tk.StringVar(value=config.get("rtt_ollama_model", "translategemma:4b"))
    rtt_model_menu = tk.OptionMenu(rtt_ollama_group, rtt_model_var, *rtt_ollama_models_default)
    rtt_model_menu.grid(row=0, column=1, sticky="ew", padx=8, pady=4)

    def fetch_rtt_ollama_models():
        ollama_url = config.get("OLLAMA_URL", "http://localhost:11434")
        models = get_ollama_models(ollama_url)
        menu = rtt_model_menu["menu"]
        menu.delete(0, "end")
        for m_name in models:
            menu.add_command(label=m_name, command=lambda v=m_name: rtt_model_var.set(v))
        if models:
            rtt_model_var.set(models[0] if rtt_model_var.get() not in models else rtt_model_var.get())

    tk.Button(rtt_ollama_group, text=l_set.get("btn_fetch_ollama", "モデルリストを取得"),
              command=lambda: threading.Thread(target=fetch_rtt_ollama_models, daemon=True).start()
              ).grid(row=0, column=2, padx=8, pady=4)

    tk.Label(rtt_ollama_group, text="※ OllamaのURLは「全般設定」タブで変更できます。", fg="gray",
             font=("", 9)).grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 6))
    rtt_ollama_group.columnconfigure(1, weight=1)

    # ── 翻訳先言語グループ ──
    rtt_lang_group = tk.LabelFrame(rtt_scroll_frame, text=l_set.get("rtt_group_lang", " 翻訳先言語 "))
    rtt_lang_group.pack(fill="x", padx=8, pady=5)

    rtt_lang_map = {
        "日本語": "ja", "English": "en", "Français": "fr", "Русский": "ru",
        "中文(简体)": "zh-CN", "한국어": "ko", "Español": "es",
        "Português": "pt", "Deutsch": "de", "Italiano": "it"
    }
    rtt_lang_map_rev = {v: k for k, v in rtt_lang_map.items()}
    saved_rtt_lang = config.get("rtt_target_language", "ja")
    rtt_lang_var = tk.StringVar(value=rtt_lang_map_rev.get(saved_rtt_lang, "日本語"))
    tk.OptionMenu(rtt_lang_group, rtt_lang_var, *rtt_lang_map.keys()).pack(side="left", padx=8, pady=6)

    # ── OCR読み取り言語グループ（2段レイアウト）──
    rtt_ocr_group = tk.LabelFrame(rtt_scroll_frame, text=l_set.get("rtt_group_ocr_lang", " OCR読み取り言語 (WinRT) "))
    rtt_ocr_group.pack(fill="x", padx=8, pady=5)

    # 1段目: 英語・日本語
    _OCR_ROW0 = [("英語 (en-US)", "en-US"), ("日本語 (ja-JP)", "ja-JP")]
    # 2段目: ロシア語・韓国語・中国語
    _OCR_ROW1 = [("ロシア語 (ru-RU)", "ru-RU"), ("韓国語 (ko-KR)", "ko-KR"), ("中国語 (zh-Hans)", "zh-Hans")]
    ALL_RTT_OCR_LANGS = _OCR_ROW0 + _OCR_ROW1

    saved_ocr_langs = set(config.get("rtt_ocr_languages", ["en-US", "ru-RU", "ko-KR", "zh-Hans"]))
    rtt_ocr_lang_cbs = {}
    for col_idx, (lbl_text, tag) in enumerate(_OCR_ROW0):
        var = tk.BooleanVar(value=tag in saved_ocr_langs)
        tk.Checkbutton(rtt_ocr_group, text=lbl_text, variable=var).grid(
            row=0, column=col_idx, sticky="w", padx=6, pady=(4, 0))
        rtt_ocr_lang_cbs[tag] = var
    for col_idx, (lbl_text, tag) in enumerate(_OCR_ROW1):
        var = tk.BooleanVar(value=tag in saved_ocr_langs)
        tk.Checkbutton(rtt_ocr_group, text=lbl_text, variable=var).grid(
            row=1, column=col_idx, sticky="w", padx=6, pady=(0, 4))
        rtt_ocr_lang_cbs[tag] = var

    # ── GPU / CPU設定グループ ──
    rtt_gpu_group = tk.LabelFrame(rtt_scroll_frame, text=l_set.get("rtt_group_gpu", " GPU / CPU 設定 "))
    rtt_gpu_group.pack(fill="x", padx=8, pady=5)

    # 実際のGPUをwmic/PowerShellで取得
    def _detect_gpus():
        """システムのGPU名一覧を取得する。wmic → PowerShell の順で試みる。"""
        # 本体が取得済みのキャッシュがあればそれを使用（高速化）
        if hasattr(parent, "cached_gpus") and parent.cached_gpus:
            return parent.cached_gpus

        import subprocess as _sp

        def _parse_names(text):
            return [l.strip() for l in text.splitlines()
                    if l.strip() and l.strip().lower() not in ("name", "")]

        # 方法1: wmic (Windows 10以前)
        try:
            r = _sp.run(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, timeout=5
            )
            names = _parse_names(r.stdout)
            if names:
                return names
        except Exception:
            pass

        # 方法2: PowerShell Get-CimInstance (Windows 11 / wmic非搭載環境)
        try:
            r = _sp.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=8
            )
            names = _parse_names(r.stdout)
            if names:
                return names
        except Exception:
            pass

        return []

    _detected_gpus = _detect_gpus()
    # GPU選択肢: 実GPUをインデックス付きで並べ、最後に「CPUのみ」を追加
    if _detected_gpus:
        _gpu_opts = [f"GPU {i}: {name}" for i, name in enumerate(_detected_gpus)] + ["CPU のみ (-1)"]
        _gpu_val_map = {f"GPU {i}: {name}": i for i, name in enumerate(_detected_gpus)}
        _gpu_val_map["CPU のみ (-1)"] = -1
    else:
        _gpu_opts = ["GPU 0 (デフォルト)", "CPU のみ (-1)"]
        _gpu_val_map = {"GPU 0 (デフォルト)": 0, "CPU のみ (-1)": -1}
    _gpu_val_map_rev = {v: k for k, v in _gpu_val_map.items()}

    # 使用GPU選択
    tk.Label(rtt_gpu_group, text=l_set.get("rtt_label_gpu", "使用GPU:"), anchor="w").grid(row=0, column=0, sticky="w", padx=8, pady=4)
    saved_gpu_idx = config.get("rtt_paddle_gpu_index", 0)
    rtt_gpu_var = tk.StringVar(value=_gpu_val_map_rev.get(saved_gpu_idx, _gpu_opts[0]))
    tk.OptionMenu(rtt_gpu_group, rtt_gpu_var, *_gpu_opts).grid(row=0, column=1, sticky="w", padx=8, pady=4)

    # VRAMリミット
    tk.Label(rtt_gpu_group, text=l_set.get("rtt_label_vram", "VRAMリミット (MB):"), anchor="w").grid(row=1, column=0, sticky="w", padx=8, pady=4)
    rtt_vram_var = tk.StringVar(value=str(config.get("rtt_paddle_gpu_mem_mb", 1024)))
    tk.Spinbox(rtt_gpu_group, from_=256, to=8192, increment=256, textvariable=rtt_vram_var, width=8).grid(row=1, column=1, sticky="w", padx=8, pady=4)

    # CPUスレッド制限 (RTT本体に合わせて％選択方式に変更)
    tk.Label(rtt_gpu_group, text=l_set.get("rtt_label_cpu", "CPU使用制限 (パーセント):"), anchor="w").grid(row=2, column=0, sticky="w", padx=8, pady=4)
    _cpu_pct_opts = ["25%", "50%", "75%", "100%"]
    saved_rtt_cpu_pct = config.get("rtt_ocr_thread_limit_percent", 100)
    # 値がリストにない場合のフォールバック
    if saved_rtt_cpu_pct not in [25, 50, 75, 100]:
        saved_rtt_cpu_pct = 100
    rtt_cpu_pct_var = tk.StringVar(value=f"{saved_rtt_cpu_pct}%")
    tk.OptionMenu(rtt_gpu_group, rtt_cpu_pct_var, *_cpu_pct_opts).grid(row=2, column=1, sticky="w", padx=8, pady=4)

    # Paddle専門言語
    tk.Label(rtt_gpu_group, text=l_set.get("rtt_label_paddle_lang", "Paddle専門言語:"), anchor="w").grid(row=3, column=0, sticky="w", padx=8, pady=4)
    rtt_paddle_lang_map = {
        "日本語 (JA/EN)": "japan", "英語 (EN)": "en", "韓国語 (KO)": "korean",
        "中国語 (ZH)": "ch", "ロシア語 (RU)": "cyrillic", "欧州諸語 (Latin)": "latin"
    }
    rtt_paddle_lang_map_rev = {v: k for k, v in rtt_paddle_lang_map.items()}
    saved_p_lang = config.get("rtt_paddle_language", "japan")
    rtt_paddle_lang_var = tk.StringVar(value=rtt_paddle_lang_map_rev.get(saved_p_lang, "日本語 (JA/EN)"))
    tk.OptionMenu(rtt_gpu_group, rtt_paddle_lang_var, *rtt_paddle_lang_map.keys()).grid(row=3, column=1, sticky="w", padx=8, pady=4)

    # ── キャプチャ / パフォーマンスグループ ──
    rtt_perf_group = tk.LabelFrame(rtt_scroll_frame, text=l_set.get("rtt_group_perf", " キャプチャ / パフォーマンス "))
    rtt_perf_group.pack(fill="x", padx=8, pady=5)

    # キャプチャモード
    tk.Label(rtt_perf_group, text=l_set.get("rtt_label_capture", "キャプチャモード:"), anchor="w").grid(row=0, column=0, sticky="w", padx=8, pady=4)
    rtt_capture_map = {"High (1秒・高反応)": "high", "Low (2.5秒・省電力)": "low"}
    rtt_capture_map_rev = {v: k for k, v in rtt_capture_map.items()}
    saved_capture = config.get("rtt_capture_mode", "high")
    rtt_capture_var = tk.StringVar(value=rtt_capture_map_rev.get(saved_capture, "High (1秒・高反応)"))
    tk.OptionMenu(rtt_perf_group, rtt_capture_var, *rtt_capture_map.keys()).grid(row=0, column=1, sticky="w", padx=8, pady=4)

    # 処理の反応感度スライダー（直感的なラベル）
    tk.Label(rtt_perf_group, text=l_set.get("rtt_label_sens", "処理の反応感度:"), anchor="w").grid(row=1, column=0, sticky="w", padx=8, pady=4)
    _SENS_LABELS = ["最低", "2", "3", "4", "5", "最大"]
    _SENS_VALUES = [1200, 1000, 800, 600, 400, 200]   # 内部値（数値が小さいほど高感度）
    saved_sens = config.get("rtt_ocr_skip_sensitivity", 800)
    saved_sens_idx = _SENS_VALUES.index(saved_sens) if saved_sens in _SENS_VALUES else 2

    rtt_sens_frame = tk.Frame(rtt_perf_group)
    rtt_sens_frame.grid(row=1, column=1, columnspan=2, sticky="w", padx=8)

    rtt_sens_slider = tk.Scale(rtt_sens_frame, from_=0, to=5, orient="horizontal",
                               resolution=1, showvalue=False, length=200)
    rtt_sens_slider.set(saved_sens_idx)
    rtt_sens_slider.pack(side="left")
    rtt_sens_lbl = tk.Label(rtt_sens_frame, text=_SENS_LABELS[saved_sens_idx], width=4, anchor="w")
    rtt_sens_lbl.pack(side="left", padx=4)
    rtt_sens_slider.config(command=lambda v: rtt_sens_lbl.config(text=_SENS_LABELS[int(v)]))

    # スライダー下にラベル目盛り表示
    rtt_tick_frame = tk.Frame(rtt_perf_group)
    rtt_tick_frame.grid(row=2, column=1, columnspan=2, sticky="w", padx=8)
    for tick_lbl in _SENS_LABELS:
        tk.Label(rtt_tick_frame, text=tick_lbl, font=("", 8), fg="gray", width=5).pack(side="left")


# --- 保存処理 ---
# （以下、save_all関数の内容およびSave & Closeボタンのコードは一切変更ありません。元のコードを維持してください）

    # --- 保存処理 ---

    def save_all(close_after=True, btn_ref=None):
        config["USE_INTERSECTING_AI"] = intersecting_ai_var.get() # これを追加
        config["search_switch"] = search_switch_var.get()
        config["ENABLE_SUBTITLE"] = subtitle_en_var.get()
        config["CACHED_OLLAMA_MODELS"] = ollama_dynamic_models
        config["TAVILY_API_KEY"] = tavily_key_entry.get().strip()
        config["MODEL_ID_SUMMARY"] = summary_model_var.get()
        
        # 思考レベル: gemini-3.1-flash-lite-preview 以外は "medium" 固定 (※API側での実質無効扱いは別途考慮するが、基本のフォールバック値)
        if config["MODEL_ID"] == "gemini-3.1-flash-lite-preview":
            config["THINKING_BUDGET"] = THINKING_OPTIONS.get(thinking_var.get(), "medium")
        else:
            config["THINKING_BUDGET"] = "medium"

        config["AI_PROVIDER"] = provider_var.get()
        config["GEMINI_API_KEY"] = gemini_key_entry.get()
        config["OPENAI_API_KEY"] = openai_key_entry.get()
        config["MODEL_ID"] = model_var.get()
        config["MODEL_ID_PRO"] = model_pro_var.get()
        config["MODEL_ID_GPT"] = gpt_model_var.get()
        config["MODEL_ID_LOCAL"] = llama_model_var.get()
        config["OLLAMA_URL"] = ollama_url_entry.get()
        
        # 文字数制限を数値として保存
        config["MAX_CHARS"] = label_to_val.get(char_limit_var.get(), 700)
        
        config["LANGUAGE"] = lang_map.get(lang_var.get(), "ja")
        config["VV_PATH"] = vv_entry.get()
        config["SPEAKER_NAME"] = speaker_var.get()
        config["SPEAKER_ID"] = speaker_map.get(speaker_var.get(), 3)
        config["DEVICE_NAME"] = device_var.get()
        config["INPUT_DEVICE_NAME"] = input_device_var.get()
        config["VOICE_VOLUME"] = volume_var.get() / 100.0
        config["LOG_FONT_SIZE"] = int(font_size_var.get())
        config["DISPLAY_TIME"] = int(display_time_var.get())
        config["DB_PROVIDER"] = db_provider_var.get()
        config["DB_MODEL_ID"] = db_model_var.get()
        config["search_switch"] = search_switch_var.get()
        config["SEARCH_PROVIDER"] = SEARCH_OPTIONS.get(search_disp_var.get(), "tavily")
        config["TAVILY_API_KEY"] = tavily_key_entry.get()
        config["MODEL_ID_SUMMARY"] = summary_model_var.get()

        # --- RTT 設定の保存 ---
        config["rtt_ollama_model"] = rtt_model_var.get()
        config["rtt_target_language"] = rtt_lang_map.get(rtt_lang_var.get(), "ja")
        config["rtt_ocr_languages"] = [tag for tag, cb in rtt_ocr_lang_cbs.items() if cb.get()]
        config["rtt_paddle_gpu_index"] = _gpu_val_map.get(rtt_gpu_var.get(), 0)
        config["rtt_paddle_gpu_mem_mb"] = int(rtt_vram_var.get())
        
        # CPUスレッド制限: ％選択方式の値を保存
        rtt_pct_val = int(rtt_cpu_pct_var.get().replace("%", ""))
        config["rtt_ocr_thread_limit_percent"] = rtt_pct_val
        config["rtt_cpu_threads"] = 0 # 判定強化ロジックにより、0なら％側が採用される
        config["rtt_paddle_language"] = rtt_paddle_lang_map.get(rtt_paddle_lang_var.get(), "japan")
        config["rtt_capture_mode"] = rtt_capture_map.get(rtt_capture_var.get(), "high")
        config["rtt_ocr_skip_sensitivity"] = _SENS_VALUES[rtt_sens_slider.get()]
        
        val = alpha_var.get()
        config["WINDOW_ALPHA"] = val if val == "OFF" else float(val)
        
        config["HOTKEYS"] = {
            "voice_mode": hk_voice_entry.get().strip().lower(),
            "vision_mode": hk_vision_entry.get().strip().lower(),
            "stop_ai": hk_stop_entry.get().strip().lower()
        }
        
        try:
            config_manager.save_config(config_path, config)
            save_callback(config)
            
            # 言語が変更された場合に、この設定ウィンドウ内の翻訳データも更新する
            nonlocal l_set, sys_lang
            l_set = parent.lang.get("settings", {})
            sys_lang = parent.lang.get("system", {})
            
            # 画面上のテキストを即座に更新
            refresh_ui_text()

            if close_after:
                root.destroy()
            elif btn_ref:
                # ダイアログの代わりにボタン文字列を一時変更
                old_txt = btn_ref.cget("text")
                btn_ref.config(text="✓ Saved!", state="disabled")
                root.after(1500, lambda: btn_ref.config(text=old_txt, state="normal"))
        except Exception as e:
            # 修正：e を変数に入れてから表示させる
            save_err = str(e)
            messagebox.showerror(sys_lang.get("error", "Error"), f"Save Error: {save_err}")

    # フッターボタン（横並び）
    btn_footer = tk.Frame(footer_frame)
    btn_footer.pack(pady=10)

    btn_save = tk.Button(btn_footer, text=l_set.get("btn_save", "Save"), command=lambda: save_all(False, btn_save), width=12)
    btn_save.pack(side="left", padx=5)

    btn_save_close = tk.Button(btn_footer, text=l_set.get("btn_save_close", "Save & Close"), command=lambda: save_all(True), bg="#2196F3", fg="white", width=18)
    btn_save_close.pack(side="left", padx=5)

    btn_cancel = tk.Button(btn_footer, text=l_set.get("btn_cancel", "Cancel"), command=root.destroy, width=12)
    btn_cancel.pack(side="left", padx=5)
    
    return root