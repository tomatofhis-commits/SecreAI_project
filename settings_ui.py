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
        from scripts import game_ai
        print("DEBUG: db_maintenance and game_ai loaded via scripts")
    except ImportError:
        # 開発時のフォールバック
        import db_maintenance
        import game_ai
        get_db_stats = db_maintenance.get_db_stats
        clean_up_database = db_maintenance.clean_up_database
        print("DEBUG: db_maintenance and game_ai loaded via direct import")
except Exception as e:
    print(f"DEBUG: Import failed. Error: {e}")

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

    notebook.add(tab_general, text=l_set.get("tab_general", "General"))
    notebook.add(tab_audio_view, text=l_set.get("tab_audio_view", "View / Audio"))
    notebook.add(tab_hotkeys, text=l_set.get("tab_hotkey", "Hotkeys"))
    notebook.add(tab_search, text=l_set.get("tab_search", "Search"))
    notebook.add(tab_database, text=l_set.get("tab_database", "Database"))

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

        # Footer
        btn_save.config(text=l_set.get("btn_save", "Save"))
        btn_save_close.config(text=l_set.get("btn_save_close", "Save & Close"))
        btn_cancel.config(text=l_set.get("btn_cancel", "Cancel"))

    def refresh_search_usage_text():
        now = datetime.now()
        usage_tpl = l_set.get("search_usage", "{month}月は {count} 回、検索をしました")
        usage_text = usage_tpl.format(month=now.month, count=config.get("TAVILY_COUNT", 0), year=now.year)
        usage_label.config(text=usage_text)

    # --- 1. 全般設定タブ ---
    lbl_ai_provider = add_label(tab_general, l_set.get("label_ai_provider", "AI Provider:"), pady=(5,0))
    provider_var = tk.StringVar(tab_general, config.get("AI_PROVIDER", "gemini"))
    provider_frame = tk.Frame(tab_general)
    provider_frame.pack(pady=5)
    
    for p_val in ["gemini", "openai", "local"]:
        tk.Radiobutton(provider_frame, text=p_val.capitalize(), variable=provider_var, value=p_val).pack(side="left", padx=5)

    # Gemini Frame
    gemini_frame = tk.LabelFrame(tab_general, text=" Gemini Settings ", padx=10, pady=5)
    gemini_frame.pack(pady=5, fill="x", padx=20)
    add_label(gemini_frame, "Gemini API Key:", pady=0)
    gemini_key_entry = tk.Entry(gemini_frame, width=50, show="*")
    gemini_key_entry.insert(0, config.get("GEMINI_API_KEY", ""))
    gemini_key_entry.pack(pady=2)

    lbl_model_normal = add_label(gemini_frame, l_set.get("model_normal", "Normal Model:"), pady=(5,0))
    # すべての候補を維持
    gemini_models = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3-flash-preview", "gemini-3-pro-preview"]
    model_var = tk.StringVar(gemini_frame, config.get("MODEL_ID", "gemini-2.5-flash"))
    tk.OptionMenu(gemini_frame, model_var, *gemini_models).pack(pady=2)

    lbl_model_pro = add_label(gemini_frame, l_set.get("model_pro", "Pro Model:"), pady=(5,0))
    pro_models = ["gemini-3-flash-preview", "gemini-3-pro-preview"]
    model_pro_var = tk.StringVar(gemini_frame, config.get("MODEL_ID_PRO", "gemini-3-pro-preview"))
    tk.OptionMenu(gemini_frame, model_pro_var, *pro_models).pack(pady=2)

    # OpenAI Frame
    openai_frame = tk.LabelFrame(tab_general, text=" OpenAI Settings ", padx=10, pady=5)
    openai_frame.pack(pady=5, fill="x", padx=20)
    openai_key_entry = tk.Entry(openai_frame, width=50, show="*")
    openai_key_entry.insert(0, config.get("OPENAI_API_KEY", ""))
    openai_key_entry.pack(pady=2)
    gpt_models = ["gpt-5", "gpt-5.2", "gpt-5-mini"]
    gpt_model_var = tk.StringVar(openai_frame, config.get("MODEL_ID_GPT", "gpt-5"))
    tk.OptionMenu(openai_frame, gpt_model_var, *gpt_models).pack(pady=2)

    # Llama (Ollama) Frame
    llama_frame = tk.LabelFrame(tab_general, text=" Llama (Local Ollama) Settings ", padx=10, pady=5)
    llama_frame.pack(pady=5, fill="x", padx=20)
    add_label(llama_frame, "Local Model ID:", pady=0)
    # すべての候補を維持
    llama_models = ["llama4:scout", "llama3.2-vision", "llama3.1:8b", "gemma2:9b", "gemma3:1b", "gemma3:4b", "gemma3:12b"]
    llama_model_var = tk.StringVar(llama_frame, config.get("MODEL_ID_LOCAL", "llama4:scout"))
    tk.OptionMenu(llama_frame, llama_model_var, *llama_models).pack(pady=2)
    add_label(llama_frame, "Ollama Endpoint:", pady=0)
    ollama_url_entry = tk.Entry(llama_frame, width=50)
    ollama_url_entry.insert(0, config.get("OLLAMA_URL", "http://localhost:11434/v1"))
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
    speaker_map = {"ずんだもん": 3, "四国めたん": 2, "春日部つむぎ": 8, "雨晴はう": 10}
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
    
    add_label(search_frame, "TAVILY_API_KEY:", pady=0)
    tavily_key_entry = tk.Entry(search_frame, width=50, show="*")
    tavily_key_entry.insert(0, config.get("TAVILY_API_KEY", ""))
    tavily_key_entry.pack(pady=5)

    lbl_sm = add_label(search_frame, l_set.get("model_summary", "Summary Model (Local Ollama):"), pady=(10,0))
    # すべての候補を維持
    summary_models = ["gemma2:9b", "gemma3:1b", "gemma3:4b", "gemma3:12b", "llama3.2:3b"]
    summary_model_var = tk.StringVar(search_frame, config.get("MODEL_ID_SUMMARY", "gemma2:9b"))
    tk.OptionMenu(search_frame, summary_model_var, *summary_models).pack(pady=5)

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

    lbl_db_m = add_label(db_model_group, l_set.get("db_model_label", "記憶要約モデル:"), pady=(5,0))
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
            models = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3-flash-preview"]
        elif provider == "openai":
            # 2/13に終了する旧モデルを排除し、あなたが最適化した最新モデルのみを配置
            models = ["gpt-5", "gpt-5.2", "gpt-5-mini"]
        else: # local
            # あなたの環境で勉強し、最適化された gemma3 シリーズ
            models = ["gemma3:4b", "gemma3:1b", "gemma3:12b", "gemma2:9b", "llama3.2:3b"]
        
        # 既存の設定値がリストにない場合は先頭を選択
        if db_model_var.get() not in models:
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

# --- 保存処理 ---
# （以下、save_all関数の内容およびSave & Closeボタンのコードは一切変更ありません。元のコードを維持してください）

    # --- 保存処理 ---
    def save_all(close_after=True, btn_ref=None):
        config["USE_INTERSECTING_AI"] = intersecting_ai_var.get() # これを追加
        config["search_switch"] = search_switch_var.get()
        config["TAVILY_API_KEY"] = tavily_key_entry.get().strip()
        config["MODEL_ID_SUMMARY"] = summary_model_var.get()
        
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
        
        val = alpha_var.get()
        config["WINDOW_ALPHA"] = val if val == "OFF" else float(val)
        
        config["HOTKEYS"] = {
            "voice_mode": hk_voice_entry.get().strip().lower(),
            "vision_mode": hk_vision_entry.get().strip().lower(),
            "stop_ai": hk_stop_entry.get().strip().lower()
        }
        
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
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