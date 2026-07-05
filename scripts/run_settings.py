import os
import sys

# Add root directory and runtime path to prevent DLL conflicts (DLL Hell)
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
runtime_dir = os.path.join(base_dir, "python_runtime")
if os.path.exists(runtime_dir):
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(runtime_dir)
        except Exception:
            pass
    os.environ["PATH"] = runtime_dir + os.pathsep + os.environ.get("PATH", "")
    os.environ.pop("PYTHONPATH", None)
    os.environ.pop("PYTHONHOME", None)

import json
import tkinter as tk
import requests

if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

# Add scripts directory to path
scripts_path = os.path.join(base_dir, "scripts")
if scripts_path not in sys.path:
    sys.path.insert(0, scripts_path)

import settings_ui
import config_manager

class DummyParent(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()  # Hide dummy root window
        self.config_data = config_manager.load_config(os.path.join(base_dir, "data", "config.json"))
        self.lang = {}
        self.cached_speakers = {}
        self.cached_ollama_models = []
        self.active_session_id = "settings_test_session"
        self.load_language()
        self.load_speakers()
        self.load_ollama_models()

    def load_language(self):
        lang_code = self.config_data.get("LANGUAGE", "ja")
        lang_path = os.path.join(base_dir, "data", "lang", f"{lang_code}.json")
        try:
            with open(lang_path, "r", encoding="utf-8") as f:
                self.lang = json.load(f)
        except Exception as e:
            print(f"Error loading language: {e}")
            self.lang = {}

    def load_speakers(self):
        # 1. Try daemon server cache
        try:
            resp = requests.get("http://127.0.0.1:5003/api/cache", timeout=0.3)
            if resp.status_code == 200:
                data = resp.json()
                self.cached_speakers = data.get("speakers", {})
                if self.cached_speakers:
                    return
        except:
            pass

        # 2. Fallback to direct request
        try:
            resp = requests.get("http://127.0.0.1:50021/speakers", timeout=1.0)
            if resp.status_code == 200:
                self.cached_speakers = {s['name']: s['styles'][0]['id'] for s in resp.json()}
        except:
            self.cached_speakers = {"ずんだもん": 3, "四国めたん": 2, "春日部つむぎ": 8, "雨晴はう": 10}

    def load_ollama_models(self):
        self.cached_ollama_models = self.config_data.get("CACHED_OLLAMA_MODELS", [])
        if not self.cached_ollama_models:
            # 1. Try daemon server cache
            try:
                resp = requests.get("http://127.0.0.1:5003/api/cache", timeout=0.3)
                if resp.status_code == 200:
                    data = resp.json()
                    self.cached_ollama_models = data.get("ollama_models", [])
                    if self.cached_ollama_models:
                        return
            except:
                pass

            # 2. Fallback to direct request
            url = self.config_data.get("OLLAMA_URL", "http://localhost:11434/v1")
            try:
                base_url = url.split("/v1")[0].rstrip("/")
                resp = requests.get(f"{base_url}/api/tags", timeout=1.5)
                if resp.status_code == 200:
                    models = [m.get("name", "") for m in resp.json().get("models", [])]
                    if models:
                        self.cached_ollama_models = models
            except:
                self.cached_ollama_models = ["gemma3:4b", "gemma2:9b", "llama3.2:3b"]

    def update_log_area(self, text, is_error=False, error_code=None):
        print(f"[DummyParent Log] {text}")

    def on_settings_saved(self, new_config):
        self.config_data = new_config

if __name__ == "__main__":
    import traceback
    try:
        parent = DummyParent()
        config_path = os.path.join(base_dir, "data", "config.json")
        
        def save_callback(new_config):
            parent.on_settings_saved(new_config)
            # Notify WPF if running
            try:
                requests.post("http://127.0.0.1:5000/api/log", json={"message": "[Hub] 設定が変更され、保存されました。", "is_error": False})
            except:
                pass

        win = settings_ui.open_settings_window(parent, config_path, parent.config_data, save_callback)
        
        # Configure cleanup
        def on_close(event=None):
            if getattr(on_close, "_done", False):
                return
            on_close._done = True
            try:
                win.destroy()
            except:
                pass
            try:
                parent.destroy()
            except:
                pass
            sys.exit(0)

        win.protocol("WM_DELETE_WINDOW", on_close)
        win.bind("<Destroy>", lambda e: on_close() if str(e.widget) == str(win) else None)
        parent.mainloop()
    except Exception as e:
        log_path = os.path.join(base_dir, "settings_error.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("Settings UI Launch Error:\n")
            traceback.print_exc(file=f)
        sys.exit(1)
