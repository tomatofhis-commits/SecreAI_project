import json
import os
import sys
import tkinter as tk
import requests

# Add root directory to path
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

# Add scripts directory to path
scripts_path = os.path.join(base_dir, "scripts")
if scripts_path not in sys.path:
    sys.path.insert(0, scripts_path)

import memory_viewer
import config_manager

class DummyParent(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()  # Hide dummy root window
        self.config_data = config_manager.load_config(os.path.join(base_dir, "data", "config.json"))
        self.lang = {}
        self.load_language()

    def load_language(self):
        lang_code = self.config_data.get("LANGUAGE", "ja")
        lang_path = os.path.join(base_dir, "data", "lang", f"{lang_code}.json")
        try:
            with open(lang_path, "r", encoding="utf-8") as f:
                self.lang = json.load(f)
        except Exception as e:
            print(f"Error loading language: {e}")
            self.lang = {}

if __name__ == "__main__":
    parent = DummyParent()
    config_path = os.path.join(base_dir, "data", "config.json")
    
    # memory_viewer.open_memory_viewer takes (parent, config)
    win_inst = memory_viewer.open_memory_viewer(parent, parent.config_data)
    
    # Configure cleanup
    def on_close():
        try:
            win_inst.root.destroy()
        except:
            pass
        try:
            parent.destroy()
        except:
            pass
        sys.exit(0)

    win_inst.root.protocol("WM_DELETE_WINDOW", on_close)
    parent.mainloop()
