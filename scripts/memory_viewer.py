import tkinter as tk
from tkinter import ttk, messagebox
import chromadb
from .chromadb_pool import get_chroma_collection
import os
import json
import threading
from datetime import datetime
import time
import re

# --- 1. パス解決 ---
def get_app_root():
    import sys
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(current_script_dir) == "scripts":
        return os.path.dirname(current_script_dir)
    return current_script_dir

class MemoryViewer:
    def __init__(self, parent, config):
        self.root = tk.Toplevel(parent)
        self.root.title("Memory Management")
        self.root.geometry("800x600")
        self.root.minsize(600, 400)
        
        self.parent = parent
        self.config = config
        self.base_dir = get_app_root()
        self.db_path = os.path.join(self.base_dir, "memory_db")
        self.config_path = os.path.join(self.base_dir, "config", "config.json")
        
        # 言語データ取得
        self.l_set = parent.lang.get("settings", {})
        self.sys_lang = parent.lang.get("system", {})
        
        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        # メインフレーム
        main_f = ttk.Frame(self.root, padding="10")
        main_f.pack(fill="both", expand=True)
        
        # タブコントロール (Notebook) の導入
        self.notebook = ttk.Notebook(main_f)
        self.notebook.pack(fill="both", expand=True)
        
        # --- タブ1: 記憶一覧 ---
        self.mem_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(self.mem_tab, text="  記憶管理 (Memory)  ")
        
        # 検索エリア
        search_f = ttk.Frame(self.mem_tab)
        search_f.pack(fill="x", pady=(0, 10))
        
        ttk.Label(search_f, text=self.l_set.get("search_label", "Search:")).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.filter_data())
        ttk.Entry(search_f, textvariable=self.search_var).pack(side="left", fill="x", expand=True, padx=5)
        
        # リスト表示 (TreeView)
        tree_f = ttk.Frame(self.mem_tab)
        tree_f.pack(fill="both", expand=True)
        
        self.tree = ttk.Treeview(tree_f, columns=("ID", "Timestamp", "Length", "Content"), show="headings")
        self.tree.heading("ID", text="ID")
        self.tree.heading("Timestamp", text=self.l_set.get("col_time", "Time"))
        self.tree.heading("Length", text=self.l_set.get("col_len", "Len"))
        self.tree.heading("Content", text=self.l_set.get("col_content", "Content"))
        
        self.tree.column("ID", width=100, minwidth=80)
        self.tree.column("Timestamp", width=150, minwidth=120)
        self.tree.column("Length", width=80, minwidth=60, anchor="center")
        self.tree.column("Content", width=350, minwidth=200)
        
        scrollbar = ttk.Scrollbar(tree_f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # プレビューエリア (詳細表示)
        preview_f = ttk.LabelFrame(self.mem_tab, text=" " + self.l_set.get("col_content", "Details") + " ")
        preview_f.pack(fill="x", pady=5)
        
        self.preview_text = tk.Text(preview_f, height=5, font=("MS Gothic", 10))
        self.preview_text.pack(fill="x", padx=5, pady=5)
        self.preview_text.config(state="disabled")
        
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        
        # 操作エリア (下部)
        btn_f = ttk.Frame(self.mem_tab)
        btn_f.pack(fill="x", pady=(10, 0))
        
        self.btn_del = ttk.Button(btn_f, text=self.l_set.get("btn_delete", "Delete Selected"), command=self.delete_selected)
        self.btn_del.pack(side="left", padx=5)
        
        self.btn_summarize = ttk.Button(btn_f, text=self.l_set.get("btn_summarize", "Summarize Selected"), command=self.summarize_selected)
        self.btn_summarize.pack(side="left", padx=5)
        
        self.btn_cleanup = ttk.Button(btn_f, text=self.l_set.get("btn_db_cleanup", "Cleanup DB"), command=self.run_cleanup)
        self.btn_cleanup.pack(side="left", padx=5)
        
        self.btn_bulk = ttk.Button(btn_f, text=self.l_set.get("btn_bulk_summarize", "Bulk Summarize"), command=self.run_bulk_summarize)
        self.btn_bulk.pack(side="left", padx=5)
        
        ttk.Button(btn_f, text=self.l_set.get("btn_refresh", "Refresh"), command=self.load_data).pack(side="right", padx=5)

        # --- タブ2: パフォーマンスダッシュボード ---
        self.perf_tab = ttk.Frame(self.notebook, padding="15")
        self.notebook.add(self.perf_tab, text="  パフォーマンス (Performance)  ")
        self.create_performance_tab()

    def create_performance_tab(self):
        """パフォーマンス統計画面の構築"""
        p = self.parent.lang.get("performance", {})
        
        # タイトル
        ttk.Label(self.perf_tab, text=p.get("title", "Performance Dashboard"), font=("Arial", 16, "bold")).pack(pady=(0, 20))
        
        # グリッドレイアウト
        stats_f = ttk.Frame(self.perf_tab)
        stats_f.pack(fill="both", expand=True)
        
        # 1. APIキャッシュ統計
        cache_f = ttk.LabelFrame(stats_f, text=f" {p.get('cache_stats', 'API Cache Stats')} ", padding=10)
        cache_f.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        self.lbl_cache_total = ttk.Label(cache_f, text=p.get("total_requests", "Total Requests: --").replace("{count}", "--"))
        self.lbl_cache_total.pack(anchor="w")
        self.lbl_cache_hits = ttk.Label(cache_f, text=p.get("hits", "Hits: --").replace("{count}", "--").replace("{miss}", "--"))
        self.lbl_cache_hits.pack(anchor="w")
        self.lbl_cache_rate = ttk.Label(cache_f, text=p.get("hit_rate", "Hit Rate: --%").replace("{rate}", "--"), font=("Arial", 12, "bold"), foreground="green")
        self.lbl_cache_rate.pack(anchor="w", pady=5)
        
        # 2. Tavily検索利用状況
        tavily_f = ttk.LabelFrame(stats_f, text=f" {p.get('tavily_usage', 'Tavily Search Usage')} ", padding=10)
        tavily_f.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        
        self.lbl_tavily_count = ttk.Label(tavily_f, text=p.get("tavily_monthly", "Used: -- / 1000").replace("{count}", "--"))
        self.lbl_tavily_count.pack(anchor="w")
        self.lbl_tavily_cost = ttk.Label(tavily_f, text=p.get("savings", "Savings: $--").replace("{amount}", "--"))
        self.lbl_tavily_cost.pack(anchor="w")

        # 3. Grounding検索利用状況
        grounding_f = ttk.LabelFrame(stats_f, text=f" {p.get('grounding_usage', 'Google Search Usage')} ", padding=10)
        grounding_f.grid(row=0, column=2, sticky="nsew", padx=10, pady=10)
        
        self.lbl_grounding_count = ttk.Label(grounding_f, text=p.get("search_usage_grounding", "Used: -- / 1000").replace("{count}", "--").replace("{month}", "--"))
        self.lbl_grounding_count.pack(anchor="w")
        
        # 3. リソース・データベース
        db_f = ttk.LabelFrame(stats_f, text=f" {p.get('db_resources', 'Database & Resources')} ", padding=10)
        db_f.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        
        self.lbl_db_size = ttk.Label(db_f, text=p.get("db_size", "DB Size: -- MB").replace("{size}", "--"))
        self.lbl_db_size.pack(anchor="w")
        self.lbl_mem_count = ttk.Label(db_f, text=p.get("total_entries", "Total Entries: --").replace("{count}", "--"))
        self.lbl_mem_count.pack(anchor="w")
        
        # 4. モデル別統計リスト
        model_f = ttk.LabelFrame(stats_f, text=f" {p.get('model_stats_title', 'Model Statistics')} ", padding=10)
        model_f.grid(row=1, column=1, sticky="nsew", padx=10, pady=10)
        
        # Treeviewの作成
        cols = ("model", "req", "hits", "rate")
        self.tree_models = ttk.Treeview(model_f, columns=cols, show="headings", height=4)
        self.tree_models.heading("model", text=p.get("model_header", "Model"))
        self.tree_models.heading("req", text=p.get("requests_header", "Req"))
        self.tree_models.heading("hits", text=p.get("hits_header", "Hits"))
        self.tree_models.heading("rate", text="Rate")
        
        self.tree_models.column("model", width=120)
        self.tree_models.column("req", width=50, anchor="center")
        self.tree_models.column("hits", width=50, anchor="center")
        self.tree_models.column("rate", width=50, anchor="center")
        self.tree_models.pack(fill="both", expand=True)
        
        # グリッドの重み設定
        stats_f.columnconfigure(0, weight=1)
        stats_f.columnconfigure(1, weight=1)
        stats_f.rowconfigure(0, weight=0)
        stats_f.rowconfigure(1, weight=1)
        
        # 更新ボタン
        ttk.Button(self.perf_tab, text=p.get("btn_update", "Update"), command=self.update_dashboard).pack(pady=20)
        
    def update_dashboard(self):
        """統計情報を更新表示"""
        p = self.parent.lang.get("performance", {})
        try:
            from .api_cache_system import APICache
            cache_dir = os.path.join(self.base_dir, "data", "api_cache")
            ttl_hours = self.config.get("API_CACHE_TTL_HOURS", 24)
            cache = APICache(cache_dir, ttl_hours=ttl_hours)
            stats = cache.get_stats()
            
            self.lbl_cache_total.config(text=p.get("total_requests", "Total:").replace("{count}", str(stats['total_requests'])))
            self.lbl_cache_hits.config(text=p.get("hits", "Hits:").replace("{count}", str(stats['hits'])).replace("{miss}", str(stats['misses'])))
            self.lbl_cache_rate.config(text=p.get("hit_rate", "Rate:").replace("{rate}", str(stats['hit_rate'])))
            
            # モデル別Treeviewの更新
            for item in self.tree_models.get_children():
                self.tree_models.delete(item)
            
            for key, m_stats in stats.get('models', {}).items():
                self.tree_models.insert("", "end", values=(
                    key,
                    m_stats['requests'],
                    m_stats['hits'],
                    f"{m_stats['hit_rate']}%"
                ))
            
            # Tavily (configから)
            count = self.config.get("TAVILY_COUNT", 0)
            self.lbl_tavily_count.config(text=p.get("tavily_monthly", "Tavily:").replace("{count}", str(count)))
            
            # 1検索 $0.05 と仮定
            savings = round(stats['hits'] * 0.05, 2)
            self.lbl_tavily_cost.config(text=p.get("savings", "Savings:").replace("{amount}", str(savings)))

            # Grounding (configから)
            now = datetime.now()
            g_count = self.config.get("GROUNDING_COUNT", 0)
            g_text = p.get("search_usage_grounding", "Google Search: {count}").replace("{count}", str(g_count)).replace("{date}", now.strftime("%Y-%m-%d"))
            self.lbl_grounding_count.config(text=g_text)
            
            # DBサイズ
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(self.db_path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    total_size += os.path.getsize(fp)
            
            size_mb = round(total_size / (1024*1024), 2)
            self.lbl_db_size.config(text=p.get("db_size", "Size:").replace("{size}", str(size_mb)))
            self.lbl_mem_count.config(text=p.get("total_entries", "Entries:").replace("{count}", str(len(self.all_data))))
            
        except Exception as e:
            print(f"Dashboard Update Error: {e}")

    def load_data(self):
        # 既存データのクリア
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        try:
            # 改善: 接続プールで3-5倍高速化
            collection = get_chroma_collection(self.db_path)
            
            results = collection.get()
            self.all_data = []
            
            ids = results.get('ids', [])
            metas = results.get('metadatas', [])
            docs = results.get('documents', [])
            
            for i in range(len(ids)):
                ts = metas[i].get('timestamp', 'N/A') if metas and i < len(metas) else 'N/A'
                doc_text = docs[i]
                entry = (ids[i], ts, len(doc_text), doc_text)
                self.all_data.append(entry)
            
            # 日時でソート (新しい順)
            # 文字列ベースで確実にソート
            self.all_data.sort(key=lambda x: str(x[1]), reverse=True)
            self.filter_data()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load DB: {e}")

    def filter_data(self):
        search_txt = self.search_var.get().lower()
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        for entry in self.all_data:
            if search_txt in entry[3].lower() or search_txt in entry[0].lower():
                self.tree.insert("", "end", values=entry)

    def on_select(self, event):
        selected = self.tree.selection()
        if not selected: return
        
        val = self.tree.item(selected[0], "values")
        content = val[3]
        
        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", content)
        self.preview_text.config(state="disabled")

    def delete_selected(self):
        selected = self.tree.selection()
        if not selected: return
        
        if not messagebox.askyesno("Confirm", "Delete selected entry?"):
            return
            
        try:
            # 改善: 接続プールで3-5倍高速化
            collection = get_chroma_collection(self.db_path)
            
            for item in selected:
                val = self.tree.item(item, "values")
                entry_id = val[0]
                collection.delete(ids=[entry_id])
                
            self.load_data()
            messagebox.showinfo("Success", "Deleted successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Delete failed: {e}")

    def summarize_selected(self):
        selected = self.tree.selection()
        if not selected: return
        
        val = self.tree.item(selected[0], "values")
        entry_id = val[0]
        content = val[3]
        
        # ローディング表示
        self.btn_summarize.config(state="disabled", text="Summarizing...")
        
        def process():
            try:
                import ollama
                summary_model = self.config.get("MODEL_ID_SUMMARY", "gemma3:4b")
                
                prompt = (
                    f"以下の記憶内容を、本質を損なわず300文字以内で簡潔に要約してください。\n"
                    f"300文字に収まりきらない場合は、重要な単語を箇条書き（- 単語）で抽出してください。\n"
                    f"内容: {content}"
                )
                
                response = ollama.chat(
                    model=summary_model,
                    messages=[{'role': 'user', 'content': prompt}]
                )
                new_content = response['message']['content'].strip()
                
                # 日付推測ロジック
                def infer_date(eid, current_ts):
                    if current_ts != 'N/A' and current_ts:
                        return current_ts
                    match = re.search(r'(\d{14})', eid)
                    if match:
                        try:
                            dt = datetime.strptime(match.group(1), '%Y%m%d%H%M%S')
                            return dt.strftime('%Y-%m-%d %H:%M:%S')
                        except: pass
                    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                final_ts = infer_date(entry_id, val[1])
                
                # ChromaDB更新（改善: 接続プールで3-5倍高速化）
                collection = get_chroma_collection(self.db_path)
                
                collection.update(
                    ids=[entry_id],
                    documents=[new_content],
                    metadatas=[{"timestamp": final_ts}]
                )
                
                self.root.after(0, lambda: self.finish_summarize("Success", "Summarized successfully."))
            except Exception as e:
                self.root.after(0, lambda: self.finish_summarize("Error", f"Summary failed: {e}"))

        threading.Thread(target=process, daemon=True).start()

    def finish_summarize(self, title, msg):
        self.btn_summarize.config(state="normal", text=self.l_set.get("btn_summarize", "Summarize Selected"))
        if title == "Success":
            self.load_data()
            messagebox.showinfo(title, msg)
        else:
            messagebox.showerror(title, msg)

    def run_bulk_summarize(self):
        # 500文字以上、または日付データがないデータを抽出
        to_process = [entry for entry in self.all_data if entry[2] >= 500 or entry[1] == 'N/A' or not entry[1]]
        if not to_process:
            messagebox.showinfo("Info", "No entries needing summarization found (500+ chars or no date).")
            return

        if not messagebox.askyesno("Confirm", f"Summarize {len(to_process)} entries?"):
            return

        self.btn_bulk.config(state="disabled")
        
        def process():
            try:
                import ollama
                summary_model = self.config.get("MODEL_ID_SUMMARY", "gemma3:4b")
                # 改善: 接続プールで3-5倍高速化
                collection = get_chroma_collection(self.db_path)
                
                for i, entry in enumerate(to_process):
                    entry_id, ts, length, content = entry
                    
                    # プログレス表示
                    self.root.after(0, lambda e=entry_id, idx=i+1, total=len(to_process): 
                                    self.btn_bulk.config(text=f"({idx}/{total}) {e[:10]}..."))
                    
                    prompt = (
                        f"以下の記憶内容を、本質を損なわず300文字以内で簡潔に要約してください。\n"
                        f"300文字に収まりきらない場合は、重要な単語を箇条書き（- 単語）で抽出してください。\n"
                        f"内容: {content}"
                    )
                    
                    response = ollama.chat(
                        model=summary_model,
                        messages=[{'role': 'user', 'content': prompt}]
                    )
                    new_content = response['message']['content'].strip()
                    
                    # 日付推測ロジックを適用
                    final_ts = ts
                    if ts == 'N/A' or not ts:
                        match = re.search(r'(\d{14})', entry_id)
                        if match:
                            try:
                                dt = datetime.strptime(match.group(1), '%Y%m%d%H%M%S')
                                final_ts = dt.strftime('%Y-%m-%d %H:%M:%S')
                            except:
                                final_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            final_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    collection.update(
                        ids=[entry_id],
                        documents=[new_content],
                        metadatas=[{"timestamp": final_ts}]
                    )
                
                self.root.after(0, lambda: messagebox.showinfo("Success", "Bulk summarization completed."))
            except Exception as e:
                self.root.after(0, lambda ex=e: messagebox.showerror("Error", f"Bulk process failed: {ex}"))
            finally:
                self.root.after(0, self.load_data)
                self.root.after(0, lambda: self.btn_bulk.config(state="normal", text=self.l_set.get("btn_bulk_summarize", "Bulk Summarize")))

        threading.Thread(target=process, daemon=True).start()

    def run_cleanup(self):
        self.btn_cleanup.config(state="disabled", text="Cleanup Running...")
        
        def process():
            try:
                try:
                    from scripts import db_maintenance
                except ImportError:
                    import db_maintenance
                
                res = db_maintenance.clean_up_database(self.db_path, self.config_path)
                self.root.after(0, lambda: self.finish_cleanup(res))
            except Exception as e:
                self.root.after(0, lambda: self.finish_cleanup(f"Error: {e}"))
                
        threading.Thread(target=process, daemon=True).start()

    def finish_cleanup(self, res):
        self.btn_cleanup.config(state="normal", text=self.l_set.get("btn_db_cleanup", "Cleanup DB"))
        messagebox.showinfo("Result", res)
        self.load_data()

def open_memory_viewer(parent, config):
    return MemoryViewer(parent, config)
