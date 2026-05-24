import json
import os
import sys
import customtkinter as ctk
import requests

# Add root directory to path
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

# Add scripts directory to path
scripts_path = os.path.join(base_dir, "scripts")
if scripts_path not in sys.path:
    sys.path.insert(0, scripts_path)

import setup_wizard

class DummyParent(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.withdraw()  # Hide dummy root window
        self.config_data = {}
        config_path = os.path.join(base_dir, "data", "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    self.config_data = json.load(f)
            except:
                pass
        self.lang = {}
        self.load_languages()

    def load_languages(self):
        # We need ALL languages for setup wizard to support dynamic language changes
        self.lang = {}
        lang_dir = os.path.join(base_dir, "data", "lang")
        if os.path.exists(lang_dir):
            for file in os.listdir(lang_dir):
                if file.endswith(".json"):
                    code = file[:-5]
                    try:
                        with open(os.path.join(lang_dir, file), "r", encoding="utf-8") as f:
                            self.lang[code] = json.load(f)
                    except:
                        pass
        # Fallback default language
        lang_code = self.config_data.get("LANGUAGE", "ja")
        if lang_code not in self.lang:
            lang_path = os.path.join(base_dir, "data", "lang", f"{lang_code}.json")
            try:
                with open(lang_path, "r", encoding="utf-8") as f:
                    self.lang[lang_code] = json.load(f)
            except:
                self.lang[lang_code] = {}

if __name__ == "__main__":
    parent = DummyParent()
    config_path = os.path.join(base_dir, "data", "config.json")
    
    # Determine active language data dictionary
    lang_code = parent.config_data.get("LANGUAGE", "ja")
    active_lang_dict = parent.lang.get(lang_code, parent.lang.get("ja", {}))

    def save_callback(new_config):
        # Notify WPF if running
        try:
            requests.post("http://127.0.0.1:5000/api/log", json={"message": "[Hub] セットアップウィザードが完了しました。設定を反映します。", "is_error": False})
        except:
            pass

    # setup_wizard.show_wizard takes (parent, config_path, lang_data, save_callback)
    # Note: setup_wizard expects parent.lang_all or parent.lang, let's pass the language dictionary structure
    # setup_wizard has: self.lang_all = lang_data, self.current_lang = lang_data
    # In setup_wizard.py: self.lang_all.get(selected_lang, ...) is called.
    # Therefore, we MUST pass `parent.lang` (the full languages dictionary) as the third argument!
    win = setup_wizard.show_wizard(parent, config_path, parent.lang, save_callback)
    
    # Configure cleanup
    def on_close():
        win.destroy()
        parent.destroy()
        sys.exit(0)

    win.protocol("WM_DELETE_WINDOW", on_close)
    parent.wait_window(win)
