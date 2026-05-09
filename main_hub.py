import sys
import os

# --- 1. 最優先で scripts へのパスを通す ---
if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(os.path.abspath(sys.executable))
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

scripts_path = os.path.join(base_dir, "scripts")
if os.path.exists(scripts_path) and scripts_path not in sys.path:
    sys.path.insert(0, scripts_path)

# --- 2. 標準・外部ライブラリのインポート ---
import time
import math
import threading
import subprocess
import json
import ctypes
import uuid  # Added for session ID
import queue # Added for thread-safe GUI updates
from flask import Flask, jsonify, request
import customtkinter as ctk
from PIL import Image, ImageTk
import pystray
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import messagebox, filedialog
import sounddevice as sd
import pygetwindow as gw 
import requests
import keyboard
import onnxruntime
import chromadb  # ビルド時にNuitkaへ存在を知らせるため

# --- 3. 自作モジュールのインポート ---
import settings_ui

try:
    import game_ai, fix_history, give_feedback, update_memory, clear_history
    import db_maintenance 
    import setup_wizard
    import error_handler
    import memory_viewer
    import config_manager
except ImportError:
    from scripts import game_ai, fix_history, give_feedback, update_memory, clear_history
    from scripts import db_maintenance
    from scripts import error_handler
    from scripts import memory_viewer
    from scripts import config_manager
    import setup_wizard

# ------------------------
# 🔹 GLOBAL CONFIGURATION 🔹
# ------------------------
VERSION = "1.1.2"
CONFIG_VERSION = "2.0"
APP_NAME = f"SecreAI - NextGen {VERSION}"

# --- グローバル変数とユーティリティ ---
settings_window_open = False
main_gui = None
APP_ROOT = base_dir # すでに取得済みの base_dir を使用
CONFIG_PATH = os.path.join(APP_ROOT, "data", "config.json")

def set_app_id():
    # Windows 7以降でタスクバーのアイコンを正しく表示させるためのID設定
    myappid = 'mycompany.myproduct.subproduct.version' # 任意
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except: pass

# --- Global Logic for Session Control ---
# These are managed by the MainApp instance but declared global for run_script access if needed,
# though cleaner design would move run_script inside MainApp. 
# For minimal refactor, we will access MainApp instance via 'main_gui'.

def get_current_session_id():
    if main_gui:
        return main_gui.active_session_id
    return None

def trigger_overlay(data):
    # data: (text, image_path, alpha, display_time)
    if main_gui:
        main_gui.overlay_queue.put(data)

def get_resource_path(relative_path):
    # exe化後と実行時でパスを出し分ける
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- 設定読み込み ---
def load_config_with_defaults():
    """config_manager を使用して設定を読み込みます"""
    return config_manager.load_config(CONFIG_PATH)

# --- アップデート確認 ---
def check_for_updates():
    """GitHub APIから最新リリースを確認し、更新があればログに表示します"""
    def task():
        time.sleep(3) # 起動直後の負荷を避けるため少し待機
        try:
            repo = "tomatofhis/SecreAI_project"
            api_url = f"https://api.github.com/repos/{repo}/releases/latest"
            headers = {"Accept": "application/vnd.github.v3+json"}
            
            response = requests.get(api_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                latest_v = data.get("tag_name", "").strip("v")
                html_url = data.get("html_url", "")
                
                if latest_v > VERSION:
                    msg = f"【UPDATE】最新バージョン v{latest_v} が利用可能です！\n詳細はGitHubを確認してください: {html_url}"
                    # 自身のAPIにポストしてログに表示
                    requests.post("http://127.0.0.1:5000/api/log", json={"message": msg, "is_error": False}, timeout=2)
        except Exception as e:
            print(f"Update check error: {e}")

    threading.Thread(target=task, daemon=True).start()

# --- Flaskサーバー ---
app = Flask(__name__)

@app.route('/api/log', methods=['POST'])
def receive_log():
    data = request.json
    if main_gui:
        main_gui.update_log_area(
            data.get("message", ""), 
            data.get("is_error", False),
            data.get("error_code")
        )
    return jsonify({"status": "ok"})

@app.route('/api/overlay', methods=['POST'])
def trigger_overlay_api():
    data = request.json
    if main_gui:
        text = data.get("text", "")
        image_path = data.get("image_path", "")
        alpha_val = data.get("alpha_val", 0.6)
        display_time = data.get("display_time", 60)
        status = data.get("status", "speaking")
        main_gui.overlay_queue.put((text, image_path, alpha_val, display_time, status))
    return jsonify({"status": "ok"})

@app.route('/api/translate', methods=['GET', 'POST'])
def remote_rtt_control():
    """StreamDeck等から Hub (5000) 経由で RTT をトグル制御する"""
    if main_gui:
        proc = getattr(main_gui, '_rtt_process', None)
        if proc and proc.poll() is None:
            main_gui.rtt_stop()
            return jsonify({"status": "ok", "action": "stop"})
        else:
            main_gui.rtt_start()
            return jsonify({"status": "ok", "action": "start"})
    return jsonify({"status": "error"}), 500

@app.route('/api/retrans', methods=['GET', 'POST'])
def remote_rtt_retrans():
    """Hub経由でRTTに再翻訳を依頼する"""
    try:
        # 127.0.0.1:5001 の RTT サーバーへ転送
        resp = requests.post("http://127.0.0.1:5001/api/retrans", timeout=2)
        return jsonify(resp.json()), resp.status_code
    except:
        return jsonify({"status": "error", "message": "RTT is not running or not responding"}), 504

@app.route('/api/status', methods=['GET'])
def remote_status():
    """HubとRTTの総合ステータスを返す"""
    proc = getattr(main_gui, '_rtt_process', None)
    rtt_running = proc and proc.poll() is None
    
    status_data = {
        "status": "ok",
        "version": VERSION,
        "rtt_process": "running" if rtt_running else "stopped"
    }
    
    if rtt_running:
        try:
            # 可能であれば RTT 内部の詳細ステータスも取得
            rtt_resp = requests.get("http://127.0.0.1:5001/api/status", timeout=0.5)
            if rtt_resp.status_code == 200:
                status_data["rtt_detail"] = rtt_resp.json()
        except:
            status_data["rtt_detail"] = "api_not_ready"
            
    return jsonify(status_data)

@app.route('/api/ecomode', methods=['GET', 'POST'])
def remote_rtt_ecomode():
    """Hub経由でRTTのエコモードをトグルする"""
    if main_gui:
        main_gui.toggle_rtt_eco_mode()
        status = "on" if main_gui.config_data.get("rtt_eco_mode", False) else "off"
        return jsonify({"status": "success", "ecomode": status})
    return jsonify({"status": "error"}), 500

@app.route('/api/<action>', methods=['GET'])
def remote_action(action):
    if action == "voice": run_script("game_ai.py", ["voice"])
    elif action == "vision": run_script("game_ai.py", ["vision"])
    elif action == "stop": stop_ai()
    elif action == "clear": run_script("clear_history.py")
    elif action == "fix": run_script("fix_history.py")
    elif action == "settings":
        if main_gui: main_gui.after(0, open_settings_guarded)
    elif action == "feedback_good": run_script("give_feedback.py", ["positive"])
    elif action == "feedback_bad": run_script("give_feedback.py", ["negative"])
    return jsonify({"status": "success", "action": action})

# --- 各種関数 ---
def run_script(script_name, args=[]):
    if not main_gui: return

    # 1. Stop previous session by generating a NEW ID
    new_id = str(uuid.uuid4())
    main_gui.active_session_id = new_id
    
    # Send stop signal log? (Optional, maybe not needed if seamless)
    # stop_ai() # No longer needed in the old sense
    
    if script_name == "game_ai.py":
        mode = args[0] if len(args) > 0 else "voice"
        chat_text = args[1] if len(args) > 1 else None
        
        # Pass the session ID control mechanisms
        # args for game_ai.main: (mode, chat_text, session_id, session_getter, overlay_queue)
        threading.Thread(
            target=game_ai.main, 
            args=(mode, chat_text, new_id, get_current_session_id, main_gui.overlay_queue), 
            daemon=True
        ).start()

    elif script_name == "clear_history.py":
        threading.Thread(target=clear_history.main, daemon=True).start()
    elif script_name == "fix_history.py":
        threading.Thread(target=fix_history.main, daemon=True).start()
    elif script_name == "give_feedback.py":
        fb_type = args[0] if len(args) > 0 else "positive"
        threading.Thread(target=give_feedback.main, args=(fb_type,), daemon=True).start()

def stop_ai():
    # Invalidate current session
    if main_gui:
        main_gui.active_session_id = str(uuid.uuid4()) # Changing ID stops the current runner
        main_gui.current_ai_status = 'idle'
        
        s = main_gui.lang.get("system", {})
        msg = s.get("ai_stop_signal", "AI Stop Signal Sent.")
        main_gui.update_log_area(msg)

def open_settings_guarded():
    global settings_window_open
    if settings_window_open: return
    settings_window_open = True
    try:
        main_gui.config_data = load_config_with_defaults()
        win = settings_ui.open_settings_window(main_gui, CONFIG_PATH, main_gui.config_data, main_gui.on_settings_saved)
        main_gui.wait_window(win)
    finally:
        settings_window_open = False

def setup_hotkeys():
    try:
        keyboard.unhook_all()
        keys = main_gui.config_data.get("HOTKEYS", {"voice_mode": "ctrl+alt+v", "vision_mode": "ctrl+alt+s", "stop_ai": "ctrl+alt+x"})
        keyboard.add_hotkey(keys["voice_mode"], lambda: run_script("game_ai.py", ["voice"]))
        keyboard.add_hotkey(keys["vision_mode"], lambda: run_script("game_ai.py", ["vision"]))
        keyboard.add_hotkey(keys["stop_ai"], stop_ai)
    except: pass

def check_single_instance(lang_data=None):
    app_id = "Global\\AI_Secretary_Hub_Unique_ID_12345"
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, app_id)
    if kernel32.GetLastError() == 183:
        root = tk.Tk()
        root.withdraw()
        title = lang_data.get("system", {}).get("single_instance_title", "二重起動") if lang_data else "二重起動"
        msg = lang_data.get("system", {}).get("single_instance_msg", "Already running.") if lang_data else "Already running."
        messagebox.showwarning(title, msg)
        root.destroy()
        sys.exit(0)
    return mutex

def check_and_start_voicevox(vv_path):
    if not vv_path or not os.path.exists(vv_path): return
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        is_running = s.connect_ex(('127.0.0.1', 50021)) == 0
    if not is_running:
        try:
            subprocess.Popen([vv_path], creationflags=0x08000000, cwd=os.path.dirname(vv_path))
        except: pass

# --- メインGUIクラス ---
class MainApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"SecreAI Hub v{VERSION} - Controller")
        try:
            icon_path = get_resource_path("SecreAI.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except: pass
        
        self.geometry("1000x800")
        self.log_theme_mode = "dark"
        self.themes = {
            "dark": {"bg": "#1a1a1a", "text": "#ffffff"},
            "green": {"bg": "#00ff00", "text": "#ffffff"}
        }
        
        self.grid_columnconfigure(0, weight=1, minsize=400)
        self.grid_columnconfigure(1, weight=0, minsize=320)
        self.grid_rowconfigure(0, weight=1)

        ctk.set_appearance_mode("dark")
        self.protocol('WM_DELETE_WINDOW', self.withdraw)
        self.config_data = load_config_with_defaults()
        self.load_language()

        # --- 設定画面高速化のためのキャッシュ用変数 ---
        self.cached_gpus = []
        self.cached_speakers = {"ずんだもん": 3, "四国めたん": 2, "春日部つむぎ": 8, "雨晴はう": 10}
        self.cached_ollama_models = self.config_data.get("CACHED_OLLAMA_MODELS", [])
        
        # バックグラウンドで重い情報の取得を開始
        threading.Thread(target=self._init_background_resources, daemon=True).start()

        # Session & Queue Management
        self.active_session_id = str(uuid.uuid4())
        self.overlay_queue = queue.Queue()
        self.current_overlay_window = None
        
        # Start polling for overlay requests
        self.after(100, self.poll_overlay_queue)
        
        # Start indicator animation
        self.after(100, self.update_indicator_animation)

        # 初回起動またはAPIキー未設定の場合にウィザードを表示
        if not self.config_data.get("GEMINI_API_KEY"):
            self.after(500, self.open_setup_wizard)

        # レイアウト配置
        self.left_frame = ctk.CTkFrame(self)
        self.left_frame.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="nsew")

        self.right_frame = ctk.CTkFrame(self, width=320)
        self.right_frame.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="ns")
        self.right_frame.pack_propagate(False)

        # UIパーツの作成
        self.label_log_header = ctk.CTkLabel(self.left_frame, text="", font=("MS Gothic", 16, "bold"))
        self.label_log_header.pack(pady=(5, 0))
        
        # --- Visual Indicator (Main UI) ---
        self.indicator_canvas = tk.Canvas(self.left_frame, height=12, bg='#1a1a1a', highlightthickness=0)
        self.indicator_canvas.pack(padx=10, pady=(2, 5), fill="x")
        self.current_ai_status = 'idle'
        
        self.log_box = ctk.CTkTextbox(
            self.left_frame, 
            font=("MS Gothic", self.config_data.get("LOG_FONT_SIZE", 13), "bold"),
            fg_color=self.themes[self.log_theme_mode]["bg"],
            text_color=self.themes[self.log_theme_mode]["text"]
        )
        self.log_box.pack(padx=10, pady=5, fill="both", expand=True)

        self.chat_frame = ctk.CTkFrame(self.left_frame)
        self.chat_frame.pack(padx=10, pady=10, fill="x")
        self.chat_entry = ctk.CTkEntry(self.chat_frame)
        self.chat_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.chat_entry.bind("<Return>", lambda e: self.send_chat())

        self.label_ops = ctk.CTkLabel(self.right_frame, text="", font=("MS Gothic", 14, "bold"))
        self.label_ops.pack(pady=5)

        self.btn_voice = ctk.CTkButton(self.right_frame, command=lambda: run_script("game_ai.py", ["voice"]))
        self.btn_voice.pack(pady=5, padx=20, fill="x")

        self.btn_vision = ctk.CTkButton(self.right_frame, command=lambda: run_script("game_ai.py", ["vision"]))
        self.btn_vision.pack(pady=5, padx=20, fill="x")

        self.btn_stop = ctk.CTkButton(self.right_frame, fg_color="#c0392b", command=stop_ai)
        self.btn_stop.pack(pady=5, padx=20, fill="x")

        fb_f = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        fb_f.pack(pady=5)
        self.btn_good = ctk.CTkButton(fb_f, text="", width=70, fg_color="#2ecc71", command=lambda: remote_action("feedback_good"))
        self.btn_good.pack(side="left", padx=2)
        self.btn_bad = ctk.CTkButton(fb_f, text="", width=70, fg_color="#e74c3c", command=lambda: remote_action("feedback_bad"))
        self.btn_bad.pack(side="left", padx=2)
        self.btn_fix = ctk.CTkButton(fb_f, text="", width=70, fg_color="#f39c12", command=lambda: remote_action("fix"))
        self.btn_fix.pack(side="left", padx=2)

        self.btn_clear = ctk.CTkButton(self.right_frame, fg_color="#7f8c8d", command=self.clear_log_display)
        self.btn_clear.pack(pady=5, padx=20, fill="x")

        self.label_display_settings = ctk.CTkLabel(self.right_frame, text="", font=("MS Gothic", 14, "bold"))
        self.label_display_settings.pack(pady=(10, 5))
        
        self.theme_toggle_btn = ctk.CTkButton(self.right_frame, fg_color="#27ae60", command=self.toggle_log_theme)
        self.theme_toggle_btn.pack(pady=5, padx=20, fill="x")

        self.label_target = ctk.CTkLabel(self.right_frame, text="")
        self.label_target.pack(anchor="w", padx=20)
        self.win_selector = ctk.CTkOptionMenu(self.right_frame, values=self.get_windows(), width=280)
        self.win_selector.set(self.config_data.get("TARGET_GAME_TITLE", ""))
        self.win_selector.pack(pady=5, padx=20)

        self.label_speed = ctk.CTkLabel(self.right_frame, text="")
        self.label_speed.pack(anchor="w", padx=20)
        self.speed_var = ctk.CTkSegmentedButton(self.right_frame, values=["1.0", "1.2", "1.5"])
        self.speed_var.set(str(self.config_data.get("VOICE_SPEED", "1.2")))
        self.speed_var.pack(pady=5, padx=20, fill="x")

        self.label_context = ctk.CTkLabel(self.right_frame, text="")
        self.label_context.pack(anchor="w", padx=20)
        self.context_box = ctk.CTkTextbox(self.right_frame, height=100, width=280)
        self.context_box.insert("1.0", self.config_data.get("TODAY_CONTEXT", ""))
        self.context_box.pack(pady=5, padx=20)

        self.btn_save = ctk.CTkButton(self.right_frame, fg_color="#3498db", command=self.quick_save)
        self.btn_save.pack(pady=10, padx=20, fill="x")
        
        self.btn_advanced = ctk.CTkButton(self.right_frame, fg_color="#7f8c8d", command=open_settings_guarded)
        self.btn_advanced.pack(side="bottom", pady=20, padx=20, fill="x")

        self.update_ui_text()
        self.create_menu_bar()
        self.create_tray_icon()

    def update_ui_text(self):
        g = self.lang.get("gui", {})
        self.label_log_header.configure(text="AI Transcript & System Log")
        self.chat_entry.configure(placeholder_text=g.get("placeholder_chat", "Type a message..."))
        self.label_ops.configure(text=g.get("op_operations", "-- Operations --"))
        self.btn_voice.configure(text=g.get("btn_voice_mode", "🎙 Voice Mode"))
        self.btn_vision.configure(text=g.get("btn_vision_mode", "👁 Vision Mode"))
        self.btn_stop.configure(text=g.get("btn_stop_ai", "🛑 Stop AI"))
        self.btn_good.configure(text=g.get("btn_good", "👍 Good"))
        self.btn_bad.configure(text=g.get("btn_bad", "👎 Bad"))
        self.btn_fix.configure(text=g.get("btn_fix", "⚠ Fix"))
        self.btn_clear.configure(text=g.get("btn_clear_log", "🧹 Clear Log"))
        self.label_display_settings.configure(text=g.get("op_display_settings", "-- Display Settings --"))
        self.theme_toggle_btn.configure(text=g.get("btn_toggle_theme", "Toggle Theme"))
        self.label_target.configure(text=g.get("label_target_window", "Target Window:"))
        self.label_speed.configure(text=g.get("label_voice_speed", "Voice Speed:"))
        self.label_context.configure(text=g.get("label_context", "Context:"))
        self.btn_save.configure(text=g.get("btn_quick_save", "Quick Save"))
        self.btn_advanced.configure(text=g.get("btn_open_settings", "Advanced Settings"))

    def _init_background_resources(self):
        """起動時に重いリソース（GPU, 音声合成話者, Ollamaモデル等）をバックグラウンドで取得する"""
        import subprocess as _sp
        
        # 1. GPU情報の取得 (PowerShell)
        try:
            r = _sp.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=8
            )
            lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
            if lines:
                self.cached_gpus = lines
        except: pass

        # 2. VOICEVOX 話者取得
        try:
            resp = requests.get("http://127.0.0.1:50021/speakers", timeout=2.0)
            if resp.status_code == 200:
                self.cached_speakers = {s['name']: s['styles'][0]['id'] for s in resp.json()}
        except: pass

        # 3. Ollama モデル取得 (URLが設定されている場合)
        url = self.config_data.get("OLLAMA_URL", "http://localhost:11434/v1")
        if url:
            try:
                base_url = url.split("/v1")[0].rstrip("/")
                resp = requests.get(f"{base_url}/api/tags", timeout=3.0)
                if resp.status_code == 200:
                    models = [m.get("name", "") for m in resp.json().get("models", [])]
                    if models:
                        self.cached_ollama_models = models
                        self.config_data["CACHED_OLLAMA_MODELS"] = models
            except: pass

    def create_menu_bar(self):
        self.menubar = tk.Menu(self)
        self.config(menu=self.menubar)
        m = self.lang.get("menu", {})

        # --- System メニュー ---
        system_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label=m.get("system_cascade", "System"), menu=system_menu)
        system_menu.add_command(label=m.get("refresh_windows", "Refresh Windows"), command=self.refresh_target_windows)
        system_menu.add_command(label=m.get("open_memory", "Memory Management"), command=self.open_memory_viewer)
        system_menu.add_command(label=m.get("reset_memory", "Reset Memory"), command=self.reset_short_term_memory_gui)
        system_menu.add_separator()
        system_menu.add_command(label=m.get("restart", "Restart Hub"), command=self.restart_hub)
        system_menu.add_separator()
        system_menu.add_command(label=m.get("exit", "Exit"), command=self.quit_app)

        # --- RTトランスレーター メニュー ---
        rtt_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label=m.get("rtt_cascade", "RTトランスレーター"), menu=rtt_menu)
        rtt_menu.add_command(
            label=m.get("rtt_start", "翻訳を開始"),
            command=self.rtt_start
        )
        rtt_menu.add_command(
            label=m.get("rtt_stop", "翻訳を停止"),
            command=self.rtt_stop
        )
        rtt_menu.add_separator()
        
        self.rtt_eco_var = tk.BooleanVar(value=self.config_data.get("rtt_eco_mode", False))
        rtt_menu.add_checkbutton(
            label=m.get("rtt_eco_mode", "エコモード"),
            variable=self.rtt_eco_var,
            command=self.toggle_rtt_eco_mode
        )
        
        self._rtt_menu = rtt_menu  # 状態更新用に保持

    def on_settings_saved(self, new_config):
        self.config_data = new_config
        self.load_language()
        self.update_ui_text()
        self.create_menu_bar()
        self.update_font_size(new_config.get("LOG_FONT_SIZE", 13))
        setup_hotkeys()
        self.sync_rtt_settings()  # RTTが起動中なら設定を同期
        self.update_log_area(self.lang.get("log_messages", {}).get("settings_applied", "Settings applied."))

    def load_language(self):
        lang_code = self.config_data.get("LANGUAGE", "ja")
        lang_path = get_resource_path(f"data/lang/{lang_code}.json")
        try:
            with open(lang_path, "r", encoding="utf-8") as f:
                self.lang = json.load(f)
        except:
            self.lang = {"system": {}, "gui": {}, "menu": {}, "log_messages": {}}

    def update_log_area(self, text, is_error=False, error_code=None):
        def _update():
            prefix = "[ERROR] " if is_error else ""
            self.log_box.insert("end", f"{prefix}{text}\n")
            self.log_box.see("end")
            
            if error_code:
                self.after(500, lambda: error_handler.notify_error(
                    self, 
                    error_code, 
                    self.lang
                ))
        
        # after(0) でメインスレッドでの実行を確約
        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            self.after(0, _update)

    def get_windows(self):
        titles = [w.title for w in gw.getAllWindows() if w.title.strip()]
        titles = sorted(list(set(titles)))
        default_label = self.lang.get("gui", {}).get("default_capture", "Default Window")
        return [default_label] + titles

    def quick_save(self):
        self.config_data["TARGET_GAME_TITLE"] = self.win_selector.get()
        self.config_data["VOICE_SPEED"] = float(self.speed_var.get())
        self.config_data["TODAY_CONTEXT"] = self.context_box.get("1.0", "end-1c").strip()
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, ensure_ascii=False, indent=4)
            self.update_log_area(self.lang.get("system", {}).get("save_success", "Saved."))
        except Exception as e:
            self.update_log_area(f"Save fail: {e}", True)

    def send_chat(self):
        msg = self.chat_entry.get()
        if msg:
            prefix = self.lang.get("system", {}).get("you_prefix", "You: ")
            self.update_log_area(f"{prefix}{msg}")
            run_script("game_ai.py", ["chat", msg])
            self.chat_entry.delete(0, 'end')

    def create_tray_icon(self):
        try:
            icon_path = get_resource_path("SecreAI.ico")
            img = Image.open(icon_path) if os.path.exists(icon_path) else Image.new('RGB', (64, 64), (40, 40, 40))
        except: img = Image.new('RGB', (64, 64), (40, 40, 40))
        m = self.lang.get("menu", {})
        menu = pystray.Menu(
            pystray.MenuItem(m.get("tray_show", "Show"), self.deiconify), 
            pystray.MenuItem(m.get("exit", "Exit"), self.quit_app)
        )
        self.tray_icon = pystray.Icon("AI_Secretary", img, "AI Secretary", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def restart_hub(self):
        stop_ai()
        if hasattr(self, 'tray_icon'): self.tray_icon.stop()
        executable = sys.executable
        args = sys.argv if not getattr(sys, 'frozen', False) else []
        subprocess.Popen([executable] + args)
        os._exit(0)

    def toggle_log_theme(self):
        self.log_theme_mode = "green" if self.log_theme_mode == "dark" else "dark"
        new_color = self.themes[self.log_theme_mode]
        self.log_box.configure(fg_color=new_color["bg"], text_color=new_color["text"])

    def update_font_size(self, size):
        self.log_box.configure(font=("MS Gothic", size, "bold"))

    def clear_log_display(self):
        self.log_box.delete("1.0", "end")

    def quit_app(self):
        try:
            stop_ai()
            # RTTを確実に停止（API経由 + taskkill）
            self.rtt_stop()
            if hasattr(self, 'tray_icon'): self.tray_icon.stop()
            
            # 親プロセス（自身）と子プロセスをすべて確実にキル
            import subprocess as _sp
            _sp.run(f"taskkill /F /PID {os.getpid()} /T", shell=True, capture_output=True)
        except: pass
        finally: os._exit(0)

    # --- RTtranslator プロセス管理 ---
    def rtt_start(self):
        """RTtranslator_core.exe をヘッドレスモードで起動する。
        EXE が存在しない場合は Python スクリプトで代替起動する（開発・テスト用）。
        """
        if getattr(self, '_rtt_process', None) and self._rtt_process.poll() is None:
            self.update_log_area("[RTT] 既に起動中です。")
            return

        # --- RTT 実行ファイルの探索 ---
        # 1. 同一ディレクトリ (製品版レイアウト)
        rtt_exe = os.path.join(base_dir, "RTtranslator_core.exe")
        
        # 2. 開発環境用の追加探索 (ビルド済み RTT が別フォルダにある場合など)
        if not os.path.exists(rtt_exe):
            potential_exe_paths = [
                os.path.join(os.path.dirname(base_dir), "Real_Time_Translate", "main.dist", "RTtranslator_core.exe"),
                os.path.join(os.path.dirname(os.path.dirname(base_dir)), "Real_Time_Translate", "main.dist", "RTtranslator_core.exe"),
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(base_dir))), "Real_Time_Translate", "main.dist", "RTtranslator_core.exe"),
            ]
            for p in potential_exe_paths:
                if os.path.exists(p):
                    rtt_exe = p
                    break

        # --- フォールバック: EXE がなければ Python スクリプトで起動 (開発用) ---
        rtt_script = None
        rtt_script_dir = None
        if not os.path.exists(rtt_exe):
            search_dirs = [
                os.path.join(base_dir, "RTtranslator"),
                os.path.join(os.path.dirname(base_dir), "RTtranslator"),
                os.path.join(os.path.dirname(os.path.dirname(base_dir)), "RTtranslator"),
            ]
            for d in search_dirs:
                p = os.path.join(d, "main.py")
                if os.path.exists(p):
                    rtt_script = p
                    rtt_script_dir = d
                    break
            
            if rtt_script:
                self.update_log_area("[RTT] EXEが見つかりません。Pythonスクリプトで代替起動します（開発モード）。")
                rtt_exe = None  # フォールバック実行フラグ
            else:
                self.update_log_area(
                    f"[RTT] 実行ファイルが見つかりません: {os.path.join(base_dir, 'RTtranslator_core.exe')}\n"
                    f"[RTT] 開発用スクリプトも見つかりませんでした。", is_error=True)
                return

        # SecreAI の config を rtt_ キーを除去した形で RTT 用設定ファイルに書き出す
        rtt_config_path = os.path.join(base_dir, "data", "rtt_config.json")
        rtt_cfg = self._build_rtt_config()
        try:
            os.makedirs(os.path.dirname(rtt_config_path), exist_ok=True)
            with open(rtt_config_path, "w", encoding="utf-8") as f:
                json.dump(rtt_cfg, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.update_log_area(f"[RTT] 設定ファイルの書き出しに失敗しました: {e}", is_error=True)
            return

        try:
            if rtt_exe:
                # 通常: ビルド済み EXE を起動
                cmd = [rtt_exe, "--headless", "--config", rtt_config_path]
            else:
                # フォールバック: Python スクリプトを直接起動
                cmd = [sys.executable, rtt_script, "--headless", "--config", rtt_config_path]

            self._rtt_process = subprocess.Popen(
                cmd,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                cwd=rtt_script_dir if not rtt_exe else base_dir
            )
            self.update_log_area("[RTT] リアルタイム翻訳を開始しました。")
        except Exception as e:
            self.update_log_area(f"[RTT] 起動に失敗しました: {e}", is_error=True)

    def sync_rtt_settings(self):
        """起動中の RTtranslator に対し、最新の設定を API 経由で送信して同期する。"""
        if not getattr(self, '_rtt_process', None) or self._rtt_process.poll() is not None:
            return
        
        def _sync():
            try:
                import requests as _req
                rtt_cfg = self._build_rtt_config()
                # ポート 5001 の RTT API へ設定を送信
                resp = _req.post("http://localhost:5001/api/update_config", json=rtt_cfg, timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    # RTT 側からの詳細なステータスチェックも兼ねる
                    status_resp = _req.get("http://localhost:5001/api/status", timeout=2)
                    if status_resp.status_code == 200:
                        s_data = status_resp.json()
                        err = s_data.get("error", "")
                        if err:
                            self.update_log_area(f"[RTT] Ollama接続エラー発生中: {err}", is_error=True)
                        else:
                            self.update_log_area("[RTT] 設定を同期しました。")
            except Exception as e:
                # 起動直後などでまだ API が立ち上がっていない場合は無視
                pass
        
        threading.Thread(target=_sync, daemon=True).start()

    def rtt_stop(self):
        """起動中の RTtranslator プロセスを停止する。"""
        proc = getattr(self, '_rtt_process', None)
        if proc is None or proc.poll() is not None:
            return  # 起動していない場合は何もしない
        try:
            # まず Flask API で停止を試みる（graceful shutdown）
            import requests as _req
            _req.post("http://localhost:5001/api/translate", timeout=2)
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._rtt_process = None
        self.update_log_area("[RTT] リアルタイム翻訳を停止しました。")

    def toggle_rtt_eco_mode(self):
        """エコモードのON/OFFを切り替え、RTTへ通知する"""
        current = self.config_data.get("rtt_eco_mode", False)
        new_state = not current
        self.config_data["rtt_eco_mode"] = new_state
        if hasattr(self, 'rtt_eco_var'):
            self.rtt_eco_var.set(new_state)
        
        # 設定保存
        self.quick_save()
        
        # RTTが起動中ならAPIで通知
        if hasattr(self, '_rtt_process') and self._rtt_process and self._rtt_process.poll() is None:
            try:
                # build_rtt_config を使って最新設定を送る
                requests.post("http://127.0.0.1:5001/api/update_config", 
                             json=self._build_rtt_config(), timeout=1)
            except: pass
        
        mode_str = "ON" if new_state else "OFF"
        self.update_log_area(f"[RTT] エコモードを {mode_str} にしました。")

    def _build_rtt_config(self) -> dict:
        """SecreAI の config_data から RTT 用設定を抽出・生成する。"""
        # 1. デフォルト値のセット
        rtt_cfg = {
            "target_window_title": self.config_data.get("TARGET_GAME_TITLE", ""),
            "target_language": self.config_data.get("rtt_target_language", "ja"),
            "ollama_url": self.config_data.get("OLLAMA_URL", "http://localhost:11434/v1"),
            "ollama_model": self.config_data.get("rtt_ollama_model", "translategemma:4b"),
            "ocr_engine_mode": "dual_scout_hybrid"
        }
        
        # 2. rtt_ プレフィックスの設定をマージ（キーは小文字化して統一）
        for k, v in self.config_data.items():
            if k.startswith("rtt_"):
                key = k[4:].lower()
                rtt_cfg[key] = v
        
        # 3. OLLAMA_URL は全般設定の値を強制的に優先させる（不整合防止）
        ollama_url = self.config_data.get("OLLAMA_URL", "http://localhost:11434/v1")
        rtt_cfg["ollama_url"] = ollama_url
        
        return rtt_cfg

    def refresh_target_windows(self):
        new_list = self.get_windows()
        self.win_selector.configure(values=new_list)
        self.update_log_area(self.lang.get("log_messages", {}).get("refresh_success", "Windows refreshed."))

    def open_setup_wizard(self):
        """セットアップウィザードを表示"""
        try:
            # 既に言語ファイルが読み込まれているか確認
            if not hasattr(self, "lang") or not self.lang:
                self.load_language()
            
            # ウィザードの表示
            setup_wizard.show_wizard(
                self, 
                CONFIG_PATH, 
                self.lang, 
                self.on_settings_saved # 保存後にUIを更新するコールバック
            )
        except Exception as e:
            print(f"Wizard Error: {e}")

    def open_memory_viewer(self):
        """記憶管理・表示ウィンドウを開く"""
        try:
            # MainHubの設定データと言語データを引き渡す
            memory_viewer.MemoryViewer(self, self.config_data)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open Memory Viewer: {e}")

    def reset_short_term_memory_gui(self):
        m = self.lang.get("log_messages", {})
        if messagebox.askyesno(m.get("reset_confirm_title", "Reset"), m.get("reset_confirm_msg", "Clear history?")):
            run_script("clear_history.py")
            self.update_log_area(m.get("reset_success", "Memory cleared."))

    # --- Overlay Polling ---
    def poll_overlay_queue(self):
        try:
            while True:
                data = self.overlay_queue.get_nowait()
                if len(data) == 4:
                    self.show_overlay_on_main_thread(data[0], data[1], data[2], data[3])
                else:
                    self.show_overlay_on_main_thread(*data)
        except queue.Empty:
            pass
        self.after(100, self.poll_overlay_queue)

    def update_indicator_animation(self):
        try:
            status = self.current_ai_status
            w = self.indicator_canvas.winfo_width()
            if w < 10: w = 400
            
            self.indicator_canvas.delete("all")
            if status == 'listening':
                # Cyan pulse - Keep it visible, avoid turning too dark
                val = int(140 + 115 * abs(math.sin(time.time() * 2)))
                color = f'#00{val:02x}{val:02x}'
                self.indicator_canvas.create_rectangle(0, 0, w, 12, fill=color, outline='')
            elif status == 'thinking':
                # Purple flowing
                x = (time.time() * 200) % w
                self.indicator_canvas.create_rectangle(x, 0, x + (w//3), 12, fill='#9b59b6', outline='')
                self.indicator_canvas.create_rectangle(x - w, 0, x - w + (w//3), 12, fill='#9b59b6', outline='')
            elif status == 'speaking':
                # Pale Pink (#f8a5c2) & Gold (#f1c40f) Smooth Fading
                # Use sine wave for smooth interpolation
                t = (math.sin(time.time() * 1.5) + 1) / 2 # 0 to 1
                
                # Interpolate R, G, B
                # Pink: (248, 165, 194), Pale Gold: (247, 225, 173)
                r = int(248 * (1 - t) + 247 * t)
                g = int(165 * (1 - t) + 225 * t)
                b = int(194 * (1 - t) + 173 * t)
                
                color = f'#{r:02x}{g:02x}{b:02x}'
                self.indicator_canvas.create_rectangle(0, 0, w, 12, fill=color, outline='')
            else: # idle
                self.indicator_canvas.create_rectangle(0, 0, w, 12, fill='#333333', outline='')
            
            self.after(50, self.update_indicator_animation)
        except:
            pass

    def show_overlay_on_main_thread(self, text, image_path, alpha_val, display_time, status='speaking'):
        self.current_ai_status = status
        
        # 既存のオーバーレイウィンドウを確実に閉じる
        if self.current_overlay_window and self.current_overlay_window.winfo_exists():
            try:
                self.current_overlay_window.destroy()
            except:
                pass
            self.current_overlay_window = None
        
        # alpha_val が "OFF" の場合はウィンドウを閉じるだけで終了（idle状態）
        if str(alpha_val).upper() == "OFF": 
            return

        try:
            top = tk.Toplevel(self)
            self.current_overlay_window = top
            top.overrideredirect(True)
            top.attributes("-topmost", True)
            top.attributes("-alpha", float(alpha_val))
            top.attributes("-topmost", True)
            top.configure(bg='black')
            
            w, sw, sh = 400, top.winfo_screenwidth(), top.winfo_screenheight()
            top.geometry(f"{w}x{sh}+{sw-w}+0")

            if image_path and os.path.exists(image_path):
                try:
                    pil_img = Image.open(image_path)
                    pil_img.thumbnail((380, 380))
                    photo = ImageTk.PhotoImage(pil_img, master=top)
                    lbl = tk.Label(top, image=photo, bg='black')
                    lbl.image = photo # keep ref
                    lbl.pack(pady=10)
                except: pass
            
            tk.Message(top, text=text, fg='white', bg='black', font=('MS Gothic', 12), width=w-20).pack(padx=10, pady=10)
            top.update() # 描画を強制確定
            
            # --- Win32 スタイル適用 (描画確定後に実行) ---
            def _apply_win32_style():
                try:
                    import ctypes
                    # winfo_id から始まり、真のトップレベル親ウィンドウまで遡る
                    hwnd = top.winfo_id()
                    while True:
                        parent = ctypes.windll.user32.GetParent(hwnd)
                        if not parent: break
                        hwnd = parent
                    
                    # 1. 画面キャプチャ除外設定
                    ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000011)

                    # 2. 拡張スタイルの強制設定 (RTTの成功フラグを再現)
                    # TRANSPARENT(20) | LAYERED(80000) | NOACTIVATE(08000000) | TOOLWINDOW(80) | TOPMOST(08)
                    GWL_EXSTYLE = -20
                    new_flags = 0x00000020 | 0x00080000 | 0x08000000 | 0x00000080 | 0x00000008
                    
                    current_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, current_style | new_flags)
                    
                    # 3. 最前面を保証しつつ反映
                    ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0013)
                except Exception as e:
                    print(f"[Overlay] Win32 Style Error: {e}")
            
            top.after(300, _apply_win32_style)
            
            # Auto close
            top.after(int(display_time * 1000), lambda: top.destroy() if top.winfo_exists() else None)
            
        except Exception as e:
            print(f"Overlay Error: {e}")

# --- サーバー・メイン実行 ---
def run_server():
    import time
    for _ in range(5):
        try:
            app.run(port=5000, debug=False, use_reloader=False)
            break
        except: time.sleep(1)

if __name__ == "__main__":
    set_app_id()
    temp_config = load_config_with_defaults()
    lang_code = temp_config.get("LANGUAGE", "ja")
    try:
        with open(get_resource_path(f"data/lang/{lang_code}.json"), "r", encoding="utf-8") as f:
            temp_lang = json.load(f)
    except: temp_lang = None
    
    # Need to register ImageTk for overlay usage if not already imported
    # "from PIL import Image" is there, but "ImageTk" is needed for overlay logic in MainApp now.
    from PIL import ImageTk 

    _keep_mutex = check_single_instance(temp_lang)
    main_gui = MainApp()
    threading.Thread(target=run_server, daemon=True).start()
    setup_hotkeys()
    check_and_start_voicevox(main_gui.config_data.get("VV_PATH"))
    
    # アップデート確認 (非同期)
    check_for_updates()
    
    main_gui.mainloop()