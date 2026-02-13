import customtkinter as ctk
from tkinter import messagebox
import webbrowser

class ErrorHandler:
    @classmethod
    def show_error(cls, parent, error_code, lang_data=None):
        """
        エラーダイアログを表示し、解決策を提示する
        """
        # 親アプリの言語データを優先し、なければデフォルト（英語か空辞書）
        e_msg = lang_data.get("error_messages", {}) if lang_data else {}
        codes = e_msg.get("codes", {})
        info = codes.get(error_code)

        if not info:
            # 未定義のエラーコードの場合は標準のメッセージボックス
            messagebox.showerror("Error", f"An unexpected error occurred: {error_code}")
            return

        # カスタムダイアログの作成
        dialog = ctk.CTkToplevel(parent)
        dialog.title(info["title"])
        dialog.geometry("500x380")
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        # レイアウト
        frame = ctk.CTkFrame(dialog, corner_radius=10)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        title_lbl = ctk.CTkLabel(frame, text=info["title"], font=("Arial", 18, "bold"), text_color="#e74c3c")
        title_lbl.pack(pady=(10, 5))

        msg_lbl = ctk.CTkLabel(frame, text=info["message"], font=("Arial", 14), wraplength=440)
        msg_lbl.pack(pady=5)

        divider = ctk.CTkFrame(frame, height=2, fg_color="gray30")
        divider.pack(fill="x", padx=10, pady=10)

        sol_title = e_msg.get("solution_header", "【Solution】")
        sol_title_lbl = ctk.CTkLabel(frame, text=sol_title, font=("Arial", 13, "bold"))
        sol_title_lbl.pack()

        sol_lbl = ctk.CTkLabel(frame, text=info["solution"], font=("Arial", 13), wraplength=440, justify="left")
        sol_lbl.pack(pady=10)

        if info.get("doc_link"):
            link_text = e_msg.get("view_docs", "View Documentation")
            link_btn = ctk.CTkButton(frame, text=link_text, fg_color="transparent", border_width=1, 
                                     command=lambda: webbrowser.open(info["doc_link"]))
            link_btn.pack(pady=5)

        close_btn = ctk.CTkButton(frame, text="OK", command=dialog.destroy, width=100)
        close_btn.pack(pady=(15, 0))

def notify_error(parent, error_code, lang_data=None):
    ErrorHandler.show_error(parent, error_code, lang_data)
