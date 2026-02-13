import customtkinter as ctk
import json
import os
import webbrowser
from tkinter import messagebox
from scripts import config_manager

class SetupWizard(ctk.CTkToplevel):
    def __init__(self, parent, config_path, lang_data, save_callback):
        super().__init__(parent)
        self.title(lang_data.get("setup_wizard", {}).get("title", "SecreAI Setup Wizard"))
        self.geometry("600x520")
        
        # モーダル化
        self.grab_set()
        self.focus_set()
        
        self.config_path = config_path
        self.lang_all = lang_data # すべての言語データ（更新用）
        self.current_lang = lang_data # 現在選択中の言語データ
        self.save_callback = save_callback
        
        # 仮の設定データ
        self.config_data = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                self.config_data = json.load(f)

        self.steps = [
            self.step_language,
            self.step_welcome,
            self.step_api_keys,
            self.step_ai_selection,
            self.step_ollama_info,
            self.step_voice_engine,
            self.step_finish
        ]
        self.current_step_index = 0
        
        # デフォルト設定の初期化
        if "search_switch" not in self.config_data:
            self.config_data["search_switch"] = False # デフォルトをOFFに
        if "AI_PROVIDER" not in self.config_data:
            self.config_data["AI_PROVIDER"] = "gemini"
        if "DB_PROVIDER" not in self.config_data:
            self.config_data["DB_PROVIDER"] = "gemini"

        self.main_frame = ctk.CTkFrame(self, corner_radius=10)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.content_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.content_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.nav_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.nav_frame.pack(fill="x", side="bottom", padx=10, pady=10)
        
        self.btn_back = ctk.CTkButton(self.nav_frame, text="Back", command=self.prev_step, width=100)
        self.btn_back.pack(side="left", padx=5)
        
        self.btn_next = ctk.CTkButton(self.nav_frame, text="Next", command=self.next_step, width=100)
        self.btn_next.pack(side="right", padx=5)
        
        self.show_step()

    def show_step(self):
        # 既存コンテンツの消去
        for child in self.content_frame.winfo_children():
            child.destroy()
            
        # ボタンのテキスト更新
        w = self.current_lang.get("setup_wizard", {})
        self.btn_back.configure(text=w.get("btn_back", "Back"))
        self.btn_next.configure(text=w.get("btn_next", "Next"))
        
        # 最初のステップでは「戻る」を非表示
        if self.current_step_index == 0:
            self.btn_back.configure(state="disabled")
        else:
            self.btn_back.configure(state="normal")
            
        # 最後のステップでは「完了」
        if self.current_step_index == len(self.steps) - 1:
            self.btn_next.configure(text=w.get("btn_finish", "Finish"))

        # カレントステップの描画
        self.steps[self.current_step_index]()

    def next_step(self):
        # バリデーション (APIキーのステップ)
        if self.current_step_index == self.steps.index(self.step_api_keys):
            gemini = self.config_data.get("GEMINI_API_KEY", "").strip()
            openai = self.config_data.get("OPENAI_API_KEY", "").strip()
            if not gemini and not openai:
                if not messagebox.askyesno("Confirm", self.current_lang.get("setup_wizard", {}).get("confirm_skip_api", "No API key is set. Would you like to set it later?")):
                    return
            
            # APIキーに基づいた自動選択（ユーザー要望）
            # モデル選択ステップに進む前にデフォルトを計算
            if gemini:
                self.config_data["AI_PROVIDER"] = "gemini"
                self.config_data["DB_PROVIDER"] = "gemini"
            elif openai:
                self.config_data["AI_PROVIDER"] = "openai"
                self.config_data["DB_PROVIDER"] = "openai"

        if self.current_step_index < len(self.steps) - 1:
            self.current_step_index += 1
            self.show_step()
        else:
            self.finish()

    def prev_step(self):
        if self.current_step_index > 0:
            self.current_step_index -= 1
            self.show_step()

    def step_language(self):
        w = self.current_lang.get("setup_wizard", {})
        title = ctk.CTkLabel(self.content_frame, text=w.get("step_lang_title", "Language Selection"), font=("Arial", 22, "bold"))
        title.pack(pady=20)
        
        # 内部管理用の変数
        current_val = self.config_data.get("LANGUAGE", "ja")
        radio_val = current_val if current_val in ["ja", "en"] else "other"
        radio_var = ctk.StringVar(value=radio_val)
        
        # その他の言語リスト (settings_ui.py の定義に準拠)
        lang_map_other = {
            "简体中文 (Chinese)": "zh-CN",
            "Español (Spanish)": "es",
            "한국어 (Korean)": "ko",
            "Français (French)": "fr",
            "Deutsch (German)": "de",
            "Italiano (Italian)": "it",
            "Português (Portuguese)": "pt",
            "Русский (Russian)": "ru"
        }
        inv_lang_map_other = {v: k for k, v in lang_map_other.items()}
        other_options = list(lang_map_other.keys())
        
        # 初期選択ラベル
        initial_other_label = inv_lang_map_other.get(current_val, other_options[0])
        other_var = ctk.StringVar(value=initial_other_label)

        def on_change():
            v = radio_var.get()
            if v == "other":
                selected_lang = lang_map_other[other_var.get()]
                self.other_dropdown.configure(state="normal")
            else:
                selected_lang = v
                self.other_dropdown.configure(state="disabled")
            
            self.config_data["LANGUAGE"] = selected_lang
            self.current_lang = self.lang_all.get(selected_lang, self.lang_all.get("en"))
            # 言語を即時反映するためにステップを再描画
            self.show_step()

        # 日本語
        ctk.CTkRadioButton(self.content_frame, text="日本語 (Japanese)", variable=radio_var, value="ja", command=on_change).pack(pady=5)
        
        # 英語
        ctk.CTkRadioButton(self.content_frame, text="English", variable=radio_var, value="en", command=on_change).pack(pady=5)
        
        # その他
        f_other = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        f_other.pack(pady=10)
        
        ctk.CTkRadioButton(f_other, text=w.get("other_languages", "Other..."), variable=radio_var, value="other", command=on_change).pack(side="left", padx=5)
        
        self.other_dropdown = ctk.CTkOptionMenu(f_other, variable=other_var, values=other_options, command=lambda v: on_change())
        self.other_dropdown.pack(side="left", padx=5)
        
        # 初期状態の設定
        if radio_val != "other":
            self.other_dropdown.configure(state="disabled")

    def step_welcome(self):
        w = self.current_lang.get("setup_wizard", {})
        title = ctk.CTkLabel(self.content_frame, text=w.get("welcome_title", "Welcome!"), font=("Arial", 26, "bold"))
        title.pack(pady=20)
        
        desc = ctk.CTkLabel(self.content_frame, text=w.get("welcome_desc", "This wizard will help you..."), wraplength=450, font=("Arial", 14))
        desc.pack(pady=10)

        # 告知メッセージの追加
        notice = ctk.CTkLabel(self.content_frame, text=w.get("welcome_notice", "You can change these later."), 
                              wraplength=450, font=("Arial", 12, "italic"), text_color="gray")
        notice.pack(pady=20)

    def step_api_keys(self):
        w = self.current_lang.get("setup_wizard", {})
        
        # スクロール可能なフレームにする（項目が増えるため）
        scroll_f = ctk.CTkScrollableFrame(self.content_frame, fg_color="transparent")
        scroll_f.pack(fill="both", expand=True)

        title = ctk.CTkLabel(scroll_f, text=w.get("step_api_title", "API Keys"), font=("Arial", 20, "bold"))
        title.pack(pady=10)
        
        desc = ctk.CTkLabel(scroll_f, text=w.get("step_api_desc", "Gemini or OpenAI API key is required."), wraplength=450)
        desc.pack(pady=5)
        
        # --- Gemini Section ---
        f_gemini = ctk.CTkFrame(scroll_f, fg_color="transparent")
        f_gemini.pack(fill="x", pady=10)
        
        ctk.CTkLabel(f_gemini, text=w.get("gemini_key_label", "Gemini API Key:")).pack(anchor="w", padx=10)
        gemini_entry = ctk.CTkEntry(f_gemini, width=400, placeholder_text="AIza...")
        gemini_entry.insert(0, self.config_data.get("GEMINI_API_KEY", ""))
        gemini_entry.pack(pady=5, padx=10)
        gemini_entry.bind("<KeyRelease>", lambda e: self.update_config("GEMINI_API_KEY", gemini_entry.get()))
        
        link = ctk.CTkLabel(f_gemini, text=w.get("get_key_link", "Get Key"), text_color="cyan", cursor="hand2")
        link.pack(anchor="w", padx=15)
        link.bind("<Button-1>", lambda e: webbrowser.open("https://ai.google.dev/gemini-api/docs/api-key"))

        # --- OpenAI Section ---
        f_openai = ctk.CTkFrame(scroll_f, fg_color="transparent")
        f_openai.pack(fill="x", pady=10)

        ctk.CTkLabel(f_openai, text=w.get("openai_key_label", "OpenAI API Key (GPT):")).pack(anchor="w", padx=10)
        openai_entry = ctk.CTkEntry(f_openai, width=400, placeholder_text="sk-...")
        openai_entry.insert(0, self.config_data.get("OPENAI_API_KEY", ""))
        openai_entry.pack(pady=5, padx=10)
        openai_entry.bind("<KeyRelease>", lambda e: self.update_config("OPENAI_API_KEY", openai_entry.get()))

        # --- Search Option (Tavily) ---
        f_search = ctk.CTkFrame(scroll_f, corner_radius=10)
        f_search.pack(fill="x", pady=20, padx=5)

        search_var = ctk.BooleanVar(value=self.config_data.get("search_switch", False))
        
        def toggle_search(v):
            self.config_data["search_switch"] = v
            if v:
                tavily_entry.configure(state="normal")
            else:
                tavily_entry.configure(state="disabled")

        sw = ctk.CTkSwitch(f_search, text=w.get("use_search_feature", "Use Search"), 
                           variable=search_var, command=lambda: toggle_search(search_var.get()))
        sw.pack(pady=10, padx=10, anchor="w")

        ctk.CTkLabel(f_search, text=w.get("tavily_key_label", "Tavily API Key:")).pack(anchor="w", padx=10)
        tavily_entry = ctk.CTkEntry(f_search, width=380, placeholder_text="tvly-...")
        tavily_entry.insert(0, self.config_data.get("TAVILY_API_KEY", ""))
        tavily_entry.pack(pady=5, padx=10)
        tavily_entry.bind("<KeyRelease>", lambda e: self.update_config("TAVILY_API_KEY", tavily_entry.get()))
        
        # 初期状態の設定
        if not search_var.get():
            tavily_entry.configure(state="disabled")

    def step_ai_selection(self):
        w = self.current_lang.get("setup_wizard", {})
        title = ctk.CTkLabel(self.content_frame, text=w.get("step_ai_selection_title", "AI Selection"), font=("Arial", 20, "bold"))
        title.pack(pady=10)
        
        desc = ctk.CTkLabel(self.content_frame, text=w.get("step_ai_selection_desc", "Select AI providers."), wraplength=450)
        desc.pack(pady=10)

        # --- Main AI Provider ---
        ctk.CTkLabel(self.content_frame, text=w.get("ai_provider_label", "Main AI:")).pack(pady=(10, 0))
        provider_var = ctk.StringVar(value=self.config_data.get("AI_PROVIDER", "gemini"))
        
        f_p = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        f_p.pack(pady=5)
        for p in ["gemini", "openai", "local"]:
            ctk.CTkRadioButton(f_p, text=p.capitalize(), variable=provider_var, value=p,
                               command=lambda p=p: self.update_config("AI_PROVIDER", p)).pack(side="left", padx=10)

        # --- DB AI Provider ---
        ctk.CTkLabel(self.content_frame, text=w.get("db_provider_label", "Memory AI:")).pack(pady=(20, 0))
        db_provider_var = ctk.StringVar(value=self.config_data.get("DB_PROVIDER", "gemini"))
        
        f_db = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        f_db.pack(pady=5)
        for p in ["gemini", "openai", "local"]:
            ctk.CTkRadioButton(f_db, text=p.capitalize(), variable=db_provider_var, value=p,
                               command=lambda p=p: self.update_config("DB_PROVIDER", p)).pack(side="left", padx=10)

    def step_ollama_info(self):
        w = self.current_lang.get("setup_wizard", {})
        title = ctk.CTkLabel(self.content_frame, text=w.get("step_ollama_title", "About Ollama"), font=("Arial", 20, "bold"))
        title.pack(pady=10)
        
        # アイコン的なダミー
        icon_lbl = ctk.CTkLabel(self.content_frame, text="💡", font=("Arial", 60))
        icon_lbl.pack(pady=10)

        desc = ctk.CTkLabel(self.content_frame, text=w.get("step_ollama_desc", "Local AI info..."), wraplength=450, font=("Arial", 14))
        desc.pack(pady=10)

        # おすすめ設定への誘導（もし local が選ばれていなければ）
        if self.config_data.get("DB_PROVIDER") != "local":
            btn_use_local = ctk.CTkButton(self.content_frame, text="Use Ollama for Memory (Recommended)", 
                                          command=lambda: (self.update_config("DB_PROVIDER", "local"), self.show_step()))
            btn_use_local.pack(pady=20)

    def step_voice_engine(self):
        w = self.current_lang.get("setup_wizard", {})
        title = ctk.CTkLabel(self.content_frame, text=w.get("step_voice_title", "Voice Engine"), font=("Arial", 20, "bold"))
        title.pack(pady=10)
        
        engine_var = ctk.StringVar(value="VOICEVOX" if self.config_data.get("VV_PATH") else "Edge-TTS")
        
        def toggle_vv_path(val):
            if val == "Edge-TTS":
                self.vv_path_entry.configure(state="disabled")
                self.config_data["SPEAKER_NAME"] = "en-US-AvaNeural" # Default edge-tts
            else:
                self.vv_path_entry.configure(state="normal")
                self.config_data["SPEAKER_NAME"] = "ずんだもん" # Default vv

        ctk.CTkRadioButton(self.content_frame, text=w.get("use_voicevox", "Use VOICEVOX"), 
                           variable=engine_var, value="VOICEVOX", command=lambda: toggle_vv_path("VOICEVOX")).pack(pady=10)
        
        self.vv_path_entry = ctk.CTkEntry(self.content_frame, width=400, placeholder_text="C:/path/to/voicevox/run.exe")
        self.vv_path_entry.insert(0, self.config_data.get("VV_PATH", ""))
        self.vv_path_entry.pack(pady=5)
        self.vv_path_entry.bind("<KeyRelease>", lambda e: self.update_config("VV_PATH", self.vv_path_entry.get()))

        ctk.CTkRadioButton(self.content_frame, text=w.get("use_edgetts", "Use Edge-TTS"), 
                           variable=engine_var, value="Edge-TTS", command=lambda: toggle_vv_path("Edge-TTS")).pack(pady=10)

    def step_finish(self):
        w = self.current_lang.get("setup_wizard", {})
        title = ctk.CTkLabel(self.content_frame, text=w.get("step_finish_title", "Done!"), font=("Arial", 24, "bold"))
        title.pack(pady=20)
        
        desc = ctk.CTkLabel(self.content_frame, text=w.get("step_finish_desc", "Everything is ready."), wraplength=450)
        desc.pack(pady=10)

    def update_config(self, key, value):
        self.config_data[key] = value

    def finish(self):
        # 保存して終了
        try:
            config_manager.save_config(self.config_path, self.config_data)
            self.save_callback(self.config_data) # 引数を渡すように修正
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save config: {e}")

def show_wizard(parent, config_path, lang_data, save_callback):
    wizard = SetupWizard(parent, config_path, lang_data, save_callback)
    return wizard
