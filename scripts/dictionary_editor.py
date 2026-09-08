"""
dictionary_editor.py - ユーザー辞書 添削・クリーンアップ画面

主な機能:
1. 辞書ファイル（USER_LEARNED.json 等）内の単語・エイリアス一覧表示とインクリメンタル検索
2. 会話の中で変に誤認識・学習されてしまった項目の丸ごと削除
3. 項目内の不要・不正なエイリアスの修正および削除
4. JSON保存時の自動フォーマットと .cache キャッシュファイルの確実な破棄・再生成
5. 実行中アプリ（game_ai / parent）の辞書エンジン即時再読み込み連携
"""

import os
import sys
import json
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Dict, List, Any

logger = logging.getLogger("DictionaryEditor")


def get_app_root():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(current_script_dir) == "scripts":
        return os.path.dirname(current_script_dir)
    return current_script_dir


class DictionaryEditor:
    """ユーザー辞書の添削・クリーンアップを行う専用ウィンドウ"""

    def __init__(self, parent_widget, config: dict, target_file: str = "USER_LEARNED.json"):
        self.parent_widget = parent_widget
        self.config = config
        self.base_dir = get_app_root()
        self.dict_dir = os.path.join(self.base_dir, "dictionary")
        self.cache_dir = os.path.join(self.dict_dir, ".cache")

        # 言語データの取得（フォールバック付き）
        self.l_set = {}
        if hasattr(parent_widget, "lang") and isinstance(parent_widget.lang, dict):
            self.l_set = parent_widget.lang.get("settings", {})
        elif hasattr(parent_widget, "master") and hasattr(parent_widget.master, "lang"):
            self.l_set = parent_widget.master.lang.get("settings", {})

        self.current_filename = target_file
        self.meta_data: Dict[str, Any] = {}
        self.raw_entries: List[Dict[str, Any]] = []
        self.displayed_indices: List[int] = []  # treeview row -> raw_entries index
        self.selected_raw_idx: Optional[int] = None
        self.has_unsaved_changes = False

        self._create_window()
        self._load_dictionary_file(self.current_filename)

    def _get_text(self, key: str, default: str) -> str:
        return self.l_set.get(key, default)

    def _create_window(self):
        self.window = tk.Toplevel(self.parent_widget)
        self.window.title(self._get_text("dict_editor_title", "ユーザー辞書 添削・クリーンアップ"))
        self.window.geometry("820x640")
        self.window.minsize(700, 500)
        
        try:
            top = self.parent_widget.winfo_toplevel()
            if top:
                self.window.transient(top)
        except Exception:
            pass

        # 確実に最前面に表示してフォーカスを当てる
        self.window.lift()
        self.window.focus_force()

        # メインコンテナ
        main_frame = ttk.Frame(self.window, padding=12)
        main_frame.pack(fill="both", expand=True)

        # 1. ヘッダー / ファイル選択・検索バー
        top_bar = ttk.Frame(main_frame)
        top_bar.pack(fill="x", pady=(0, 10))

        ttk.Label(top_bar, text=self._get_text("dict_select_file", "対象辞書:"), font=("", 9, "bold")).pack(side="left", padx=(0, 5))
        
        # 利用可能な辞書リストを取得
        json_files = []
        if os.path.exists(self.dict_dir):
            json_files = sorted([f for f in os.listdir(self.dict_dir) if f.endswith(".json") and not f.startswith(".")])
        if not json_files:
            json_files = [self.current_filename]

        self.file_var = tk.StringVar(value=self.current_filename if self.current_filename in json_files else json_files[0])
        file_menu = ttk.Combobox(top_bar, textvariable=self.file_var, values=json_files, state="readonly", width=24)
        file_menu.pack(side="left", padx=(0, 20))
        file_menu.bind("<<ComboboxSelected>>", self._on_file_changed)

        ttk.Label(top_bar, text=self._get_text("search_label", "検索:")).pack(side="left", padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._apply_filter())
        search_entry = ttk.Entry(top_bar, textvariable=self.search_var, width=25)
        search_entry.pack(side="left", fill="x", expand=True)

        btn_clear_search = ttk.Button(top_bar, text="✕", width=3, command=lambda: self.search_var.set(""))
        btn_clear_search.pack(side="left", padx=(4, 0))

        # 2. 一覧リスト (Treeview)
        list_frame = ttk.LabelFrame(main_frame, text=f" {self._get_text('dict_list_entries', '登録語一覧')} ", padding=6)
        list_frame.pack(fill="both", expand=True, pady=(0, 10))

        cols = ("name", "aliases", "category")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("name", text=self._get_text("dict_col_name", "正式名称 (Term)"))
        self.tree.heading("aliases", text=self._get_text("dict_col_aliases", "エイリアス / 誤認識語 (Aliases)"))
        self.tree.heading("category", text=self._get_text("dict_col_category", "カテゴリ (Category)"))

        self.tree.column("name", width=180, minwidth=120)
        self.tree.column("aliases", width=380, minwidth=200)
        self.tree.column("category", width=110, minwidth=80)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # 3. 添削フォームエリア
        edit_frame = ttk.LabelFrame(main_frame, text=f" {self._get_text('dict_edit_section', '選択項目の添削・修正')} ", padding=10)
        edit_frame.pack(fill="x", pady=(0, 10))

        # 1行目: 正式名称 & カテゴリ
        row1 = ttk.Frame(edit_frame)
        row1.pack(fill="x", pady=(0, 6))

        ttk.Label(row1, text=self._get_text("dict_col_name", "正式名称:")).pack(side="left", padx=(0, 5))
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(row1, textvariable=self.name_var, width=28)
        self.name_entry.pack(side="left", padx=(0, 15))

        ttk.Label(row1, text=self._get_text("dict_col_category", "カテゴリ:")).pack(side="left", padx=(0, 5))
        self.cat_var = tk.StringVar()
        self.cat_entry = ttk.Entry(row1, textvariable=self.cat_var, width=18)
        self.cat_entry.pack(side="left")

        # 2行目: エイリアス (編集・削除の中心)
        row2 = ttk.Frame(edit_frame)
        row2.pack(fill="x", pady=(0, 6))

        ttk.Label(row2, text=self._get_text("dict_col_aliases", "エイリアス:")).pack(side="left", padx=(0, 5))
        self.aliases_var = tk.StringVar()
        self.aliases_entry = ttk.Entry(row2, textvariable=self.aliases_var)
        self.aliases_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        # 補足ヒント
        lbl_hint = ttk.Label(
            edit_frame,
            text=self._get_text("dict_aliases_hint", "※誤認識パターンはカンマ「,」区切りです。不要なエイリアスを消すか書き直してください。"),
            foreground="#666666",
            font=("", 8)
        )
        lbl_hint.pack(anchor="w", pady=(0, 6))

        # 3行目: 詳細説明 (info)
        row3 = ttk.Frame(edit_frame)
        row3.pack(fill="x", pady=(0, 8))

        ttk.Label(row3, text=self._get_text("dict_col_info", "詳細情報:")).pack(side="left", padx=(0, 5))
        self.info_var = tk.StringVar()
        self.info_entry = ttk.Entry(row3, textvariable=self.info_var)
        self.info_entry.pack(side="left", fill="x", expand=True)

        # 4行目: 添削アクションボタン
        act_frame = ttk.Frame(edit_frame)
        act_frame.pack(fill="x", pady=(4, 0))

        self.btn_delete_entry = tk.Button(
            act_frame,
            text=self._get_text("dict_delete_entry", "この項目をまるごと削除 (Delete)"),
            command=self._delete_selected_entry,
            bg="#f44336",
            fg="white",
            relief="raised",
            padx=10,
            pady=4
        )
        self.btn_delete_entry.pack(side="left")

        self.btn_apply_edit = tk.Button(
            act_frame,
            text=self._get_text("dict_apply_edit", "添削内容を反映 (Apply)"),
            command=self._apply_current_edit,
            bg="#2196F3",
            fg="white",
            relief="raised",
            padx=14,
            pady=4
        )
        self.btn_apply_edit.pack(side="right")

        # 4. 最下部: 全体保存・完了バー
        bottom_bar = ttk.Frame(main_frame)
        bottom_bar.pack(fill="x", pady=(5, 0))

        self.btn_save_finish = tk.Button(
            bottom_bar,
            text=self._get_text("dict_save_changes", "変更をファイルに保存して完了"),
            command=self._save_to_file,
            bg="#4CAF50",
            fg="white",
            font=("", 10, "bold"),
            padx=16,
            pady=6
        )
        self.btn_save_finish.pack(side="left")

        btn_close = ttk.Button(bottom_bar, text=self._get_text("close", "閉じる"), command=self._on_close)
        btn_close.pack(side="right")

        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_dictionary_file(self, filename: str):
        self.current_filename = filename
        self.file_path = os.path.join(self.dict_dir, filename)
        self.raw_entries = []
        self.meta_data = {"title": os.path.splitext(filename)[0], "category": "General"}
        self.selected_raw_idx = None
        self._clear_form()

        if not os.path.exists(self.file_path):
            messagebox.showwarning("Warning", f"File not found: {filename}")
            return

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict) and "entries" in data and isinstance(data["entries"], list):
                self.meta_data = data.get("meta", self.meta_data)
                for item in data["entries"]:
                    if isinstance(item, dict):
                        self.raw_entries.append({
                            "name": str(item.get("name") or "").strip(),
                            "aliases": [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()],
                            "category": str(item.get("category") or "General").strip(),
                            "info": str(item.get("info") or "").strip()
                        })
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        self.raw_entries.append({
                            "name": str(item.get("name") or "").strip(),
                            "aliases": [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()],
                            "category": str(item.get("category") or "General").strip(),
                            "info": str(item.get("info") or "").strip()
                        })
                    elif isinstance(item, str) and item.strip():
                        self.raw_entries.append({
                            "name": item.strip(),
                            "aliases": [],
                            "category": "General",
                            "info": ""
                        })
            elif isinstance(data, dict):
                # key-value 形式
                for k, v in data.items():
                    if k == "meta":
                        continue
                    if isinstance(v, list):
                        self.raw_entries.append({
                            "name": str(k).strip(),
                            "aliases": [str(a).strip() for a in v if str(a).strip()],
                            "category": "Aliases",
                            "info": ""
                        })
                    elif isinstance(v, str):
                        self.raw_entries.append({
                            "name": str(k).strip(),
                            "aliases": [],
                            "category": "General",
                            "info": v.strip()
                        })

            self.has_unsaved_changes = False
            self._apply_filter()

        except Exception as e:
            logger.error(f"辞書読み込み失敗: {e}")
            messagebox.showerror("Error", f"Failed to load dictionary: {e}")

    def _apply_filter(self):
        query = self.search_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        self.displayed_indices = []

        for idx, entry in enumerate(self.raw_entries):
            name = entry["name"]
            aliases_str = ", ".join(entry["aliases"])
            cat = entry["category"]
            info = entry["info"]

            if not query or (query in name.lower()) or (query in aliases_str.lower()) or (query in cat.lower()) or (query in info.lower()):
                self.tree.insert("", "end", iid=str(idx), values=(name, aliases_str, cat))
                self.displayed_indices.append(idx)

    def _on_tree_select(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        raw_idx = int(selected[0])
        self.selected_raw_idx = raw_idx
        entry = self.raw_entries[raw_idx]

        self.name_var.set(entry["name"])
        self.aliases_var.set(", ".join(entry["aliases"]))
        self.cat_var.set(entry["category"])
        self.info_var.set(entry["info"])

    def _clear_form(self):
        self.name_var.set("")
        self.aliases_var.set("")
        self.cat_var.set("")
        self.info_var.set("")
        self.selected_raw_idx = None

    def _apply_current_edit(self):
        """フォーム内の添削内容を選択中の項目に反映"""
        if self.selected_raw_idx is None or self.selected_raw_idx >= len(self.raw_entries):
            messagebox.showinfo("Info", self._get_text("dict_msg_select_first", "一覧から添削する項目を選択してください。"))
            return

        new_name = self.name_var.get().strip()
        if not new_name:
            messagebox.showwarning("Warning", self._get_text("dict_msg_name_empty", "正式名称は必須です。"))
            return

        # カンマ区切りのエイリアスをパース・重複除外
        raw_alias_text = self.aliases_var.get()
        cleaned_aliases = []
        for part in raw_alias_text.replace("、", ",").split(","):
            s = part.strip()
            if s and s != new_name and s not in cleaned_aliases:
                cleaned_aliases.append(s)

        entry = self.raw_entries[self.selected_raw_idx]
        entry["name"] = new_name
        entry["aliases"] = cleaned_aliases
        entry["category"] = self.cat_var.get().strip() or "General"
        entry["info"] = self.info_var.get().strip()

        self.has_unsaved_changes = True

        # Treeviewの該当行を更新
        aliases_str = ", ".join(cleaned_aliases)
        self.tree.item(str(self.selected_raw_idx), values=(new_name, aliases_str, entry["category"]))
        messagebox.showinfo("Success", self._get_text("dict_msg_applied", "添削内容を反映しました。\n「変更をファイルに保存して完了」を押すと保存されます。"))

    def _delete_selected_entry(self):
        """選択中の項目を丸ごと削除"""
        if self.selected_raw_idx is None or self.selected_raw_idx >= len(self.raw_entries):
            messagebox.showinfo("Info", self._get_text("dict_msg_select_first", "一覧から削除する項目を選択してください。"))
            return

        term_name = self.raw_entries[self.selected_raw_idx]["name"]
        confirm_msg = self._get_text("dict_confirm_delete", f"『{term_name}』を辞書から削除しますか？")
        if not messagebox.askyesno("Confirm", confirm_msg):
            return

        del self.raw_entries[self.selected_raw_idx]
        self.has_unsaved_changes = True
        self._clear_form()
        self._apply_filter()

    def _save_to_file(self):
        """JSON ファイルへ整形書き込みし、.cache を安全に破棄"""
        out_data = {
            "meta": self.meta_data,
            "entries": self.raw_entries
        }

        try:
            # 1. JSON 書き込み
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(out_data, f, ensure_ascii=False, indent=2)

            # 2. ディスク上のバイナリキャッシュ（.cache）を破棄
            cache_name = f"{os.path.splitext(self.current_filename)[0]}.cache"
            cache_file = os.path.join(self.cache_dir, cache_name)
            if os.path.exists(cache_file):
                try:
                    os.remove(cache_file)
                    logger.info(f"キャッシュ破棄完了: {cache_file}")
                except Exception as ce:
                    logger.warning(f"キャッシュ削除失敗: {ce}")

            # 3. 実行中の辞書エンジン（メモリ上のTrie木）を即座に再読み込み
            self._notify_engine_reload()

            self.has_unsaved_changes = False
            messagebox.showinfo("Saved", self._get_text("dict_msg_save_success", "辞書を保存しました。反映を完了しました。"))

        except Exception as e:
            logger.error(f"辞書保存エラー: {e}")
            messagebox.showerror("Error", f"Failed to save dictionary: {e}")

    def _notify_engine_reload(self):
        """アプリ本体のメモリ上にある辞書エンジンを即時リロード"""
        try:
            # game_ai モジュールのシングルトンを再初期化
            import game_ai
            if hasattr(game_ai, "_dictionary_engine") and game_ai._dictionary_engine is not None:
                game_ai._dictionary_engine.initialize()
                logger.info("game_ai の辞書エンジンを即時再初期化しました。")
        except Exception:
            pass

        try:
            # scripts.game_ai 経由
            from scripts import game_ai
            if hasattr(game_ai, "_dictionary_engine") and game_ai._dictionary_engine is not None:
                game_ai._dictionary_engine.initialize()
                logger.info("scripts.game_ai の辞書エンジンを即時再初期化しました。")
        except Exception:
            pass

    def _on_file_changed(self, event=None):
        new_file = self.file_var.get()
        if new_file == self.current_filename:
            return

        if self.has_unsaved_changes:
            if not messagebox.askyesno("Confirm", self._get_text("dict_confirm_discard", "保存されていない変更があります。破棄して別の辞書を開きますか？")):
                self.file_var.set(self.current_filename)
                return

        self._load_dictionary_file(new_file)

    def _on_close(self):
        if self.has_unsaved_changes:
            if not messagebox.askyesno("Confirm", self._get_text("dict_confirm_discard", "保存されていない変更があります。破棄して閉じますか？")):
                return
        self.window.destroy()


def open_dictionary_editor(parent, config, target_file="USER_LEARNED.json"):
    """辞書エディタを開くヘルパー関数"""
    return DictionaryEditor(parent, config, target_file)
