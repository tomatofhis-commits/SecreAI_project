"""
UIモジュール
翻訳結果を表示するウィンドウ（クリック透過・フォーカス非奪取・常に最前面）
"""

import sys
import os
import subprocess
import time
import threading
import requests
import ctypes
import ctypes.wintypes
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QLabel,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont

import win32gui
import win32con


# Windows API 定数
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
GWL_EXSTYLE = -20


class TranslationOverlay(QMainWindow):
    """
    翻訳結果を表示するオーバーレイウィンドウ。
    - 常に最前面
    - クリック透過（ゲーム操作を阻害しない）
    - フォーカスを奪わない
    - タスクバーに表示しない
    """

    # スレッドセーフなシグナル (cid, chunk, translated_text, target_lang, font_size)
    single_translation_received = pyqtSignal(str, dict, str, str, object)
    font_size_calculated = pyqtSignal(str, int)
    status_updated = pyqtSignal(str)
    clear_requested = pyqtSignal()

    def __init__(
        self,
        font_size: int = 16,
        opacity: float = 0.85,
        bg_color: str = "#1a1a2e",
        text_color: str = "#e0e0e0",
        use_csharp: bool = True,
    ):
        super().__init__()
        self.font_size = font_size
        self.opacity = opacity
        self.bg_color = bg_color
        self.text_color = text_color
        self._click_through = True
        
        # 固有IDでラベルコンポーネントを管理
        self.active_labels = {}
        self.valid_cids = set()

        # --- C# WPF Overlay 管理属性 ---
        self.use_csharp = False
        self.cs_api_url = "http://127.0.0.1:5002"
        self.cs_process = None
        self._init_csharp_overlay(use_csharp)

        self._setup_window()
        self._setup_ui()
        self._apply_click_through()
        self._connect_signals()

    def _init_csharp_overlay(self, force_enabled: bool):
        """C# WPF Overlayの検出およびバックグラウンド起動を試みる"""
        if not force_enabled:
            print("[C# Overlay] 設定によりC#外部オーバーレイ描画エンジンは無効化されています。")
            return
        # C# 実行ファイルの探索パス
        rtt_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # D:\SecreAI_Build\RTtranslator 相当
        base_dir = os.path.dirname(rtt_dir) # D:\SecreAI_Build 相当
        
        potential_paths = [
            os.path.join(base_dir, "WPF", "RTtranslator_CS_Overlay.exe"),
            os.path.join(rtt_dir, "RTtranslator_CS_Overlay.exe"),
            os.path.join(os.path.abspath("."), "RTtranslator_CS_Overlay.exe"),
        ]
        
        cs_exe = None
        for p in potential_paths:
            if os.path.exists(p):
                cs_exe = p
                break
                
        if not cs_exe:
            print("[C# Overlay] 実行ファイルが見つかりません。PyQtモードで起動します。")
            return

        # 既にポート5002で起動中か確認
        try:
            resp = requests.get(f"{self.cs_api_url}/api/status", timeout=0.3)
            if resp.status_code == 200:
                print("[C# Overlay] 既存のC#プロセスが既に起動しています。")
                self.use_csharp = True
                return
        except:
            pass

        # 起動していない場合は新規起動
        try:
            print(f"[C# Overlay] 新規プロセスを起動します: {cs_exe}")
            # creationflags=0x08000000 (CREATE_NO_WINDOW) で余計なコンソール窓を出さない
            self.cs_process = subprocess.Popen([cs_exe], creationflags=0x08000000)
            
            # 起動応答待ち (最大2.0秒)
            for _ in range(10):
                time.sleep(0.2)
                try:
                    resp = requests.get(f"{self.cs_api_url}/api/status", timeout=0.2)
                    if resp.status_code == 200:
                        print("[C# Overlay] C# プロセスとのローカル通信接続に成功しました！(Port 5002)")
                        self.use_csharp = True
                        break
                except:
                    pass
        except Exception as e:
            print(f"[C# Overlay] 起動に失敗しました: {e}")

    def _setup_window(self):
        """ウィンドウの基本プロパティを設定する。"""
        self.setWindowTitle("Real Time Translate Overlay")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(self.opacity)
        # 初期サイズ設定（あとで同期される）
        self.setGeometry(0, 0, 800, 600)

        # スクリーンキャプチャにこのウィンドウ自体が写り込まないようにする魔法のAPI
        # WDA_EXCLUDEFROMCAPTURE = 0x00000011 (Windows 10 Version 2004 以降用)
        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000011)
        except Exception as e:
            print(f"[Warning] Failed to set window display affinity: {e}")

    def update_geometry(self, rect_tuple):
        """メインプログラムから呼び出され、ターゲットウィンドウの座標に追従する"""
        left, top, width, height = rect_tuple
        self.setGeometry(left, top, width, height)
        # ステータスバーをターゲットの幅に合わせる
        self.status_label.setFixedWidth(width)
        
        # C#側へも座標追従をプッシュ更新する
        if self.use_csharp and self.active_labels:
            self._push_csharp_update()

    def _setup_ui(self):
        """完全透過のキャンバスとステータス表示のみ用意する。"""
        self.central = QWidget()
        self.setCentralWidget(self.central)
        self.central.setStyleSheet("background-color: transparent;")

        # ステータスを最上部に固定（全幅）
        self.status_label = QLabel("⏳ 待機中...", self.central)
        self.status_label.setFont(QFont("Yu Gothic UI", 10, QFont.Weight.Bold))
        # 背景を少し透過させた黒、文字を緑に。全幅のタイトルバーのようなスタイル
        self.status_label.setStyleSheet("color: #00FF00; background-color: rgba(0,0,0,0.7); padding: 4px 10px; border-bottom: 1px solid rgba(0,255,0,0.3);")
        self.status_label.setGeometry(0, 0, self.width(), 28)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

    def _connect_signals(self):
        self.single_translation_received.connect(self._on_single_translation_received)
        self.status_updated.connect(self._on_status_updated)
        self.clear_requested.connect(self._on_clear_requested)

    def sync_active_ids(self, active_ids: set):
        """画面から消えたID（active_idsに含まれないもの）のラベルを破棄する"""
        self.valid_cids = active_ids
        
        if self.use_csharp:
            for cid in list(self.active_labels.keys()):
                if cid not in active_ids:
                    del self.active_labels[cid]
            self._push_csharp_update()
        else:
            for cid in list(self.active_labels.keys()):
                if cid not in active_ids:
                    self.active_labels[cid].deleteLater()
                    del self.active_labels[cid]

    def update_translation_position(self, cid: str, rect: dict):
        """既に表示されているラベルがあるなら、最新の座標に合わせて移動させる"""
        if cid in self.active_labels:
            if self.use_csharp:
                # C#座標のリアルタイム同期更新
                item = self.active_labels[cid]
                nx = self.x() + int(rect["x"]) - 3
                ny = self.y() + int(rect["y"])
                if abs(item["x"] - nx) > 3 or abs(item["y"] - ny) > 3:
                    item["x"] = nx
                    item["y"] = ny
                    self._push_csharp_update()
            else:
                label = self.active_labels[cid]
                # 座標を更新（新規生成時と同じ x-3, y に合わせる）
                nx = int(rect["x"]) - 3
                ny = int(rect["y"])
                
                # OCRの微小な揺れ（3ピクセル以内）によるUIのプルプル震えを防止
                cx = label.x()
                cy = label.y()
                if abs(cx - nx) > 3 or abs(cy - ny) > 3:
                    label.move(nx, ny)

    @pyqtSlot(str, dict, str, str, object)
    def _on_single_translation_received(self, cid: str, chunk: dict, translated: str, target_lang: str = "ja", font_size: int = None):
        """単一の翻訳結果を受け取り、画面に配置する"""
        if not translated:
            return
            
        rect = chunk["rect"]
        nx, ny = int(rect["x"]), int(rect["y"])
        nw, nh = int(rect["w"]), int(rect["h"])

        # --- C# WPF オーバーレイ描画ルート ---
        if self.use_csharp:
            abs_x = self.x() + nx - 3
            abs_y = self.y() + ny

            bg_color = chunk.get("bg_color", "rgba(0, 0, 0, 0.63)")
            text_color = chunk.get("text_color", "#ffffff")

            lines_count = chunk.get("lines_count", 1)
            if font_size is None:
                line_height_px = nh / max(1, lines_count)
                font_size = max(10, min(32, int(line_height_px) + 2))

            item = {
                "id": cid,
                "text": translated,
                "x": abs_x,
                "y": abs_y,
                "width": nw,
                "height": nh,
                "font_size": font_size,
                "font_color": text_color,
                "bg_color": bg_color
            }
            self.active_labels[cid] = item
            self._push_csharp_update()
            return

        # --- PyQt 描画ルート (フォールバック) ---
        # すでに表示中のラベルがある場合のガードと高速更新
        if cid in self.active_labels:
            label = self.active_labels[cid]
            # 1. テキスト内容が同じなら位置・サイズの更新のみ（再描画スキップ）
            if getattr(label, '_last_text', '') == translated:
                label.move(nx, ny)
                label.setFixedSize(nw, nh)
                return
        else:
            # 新規作成
            label = QLabel(self.central)
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.RichText)
            self.active_labels[cid] = label

        label._last_text = translated
        
        lines_count = chunk.get("lines_count", 1)
        x, y, w, h = nx, ny, nw, nh
        
        # 翻訳先言語に応じたフォントファミリーの決定
        target_base = target_lang.split("-")[0].lower()
        if target_base == "ko":
            font_family = "'Malgun Gothic', 'Yu Gothic UI', sans-serif"
            font_min = 10
            boost = 4
        elif target_base in ["ja", "zh"]:
            font_family = "'Yu Gothic UI', 'Meiryo', 'MS Gothic', sans-serif"
            font_min = 10
            boost = 4
        else:
            font_family = "'Yu Gothic UI', sans-serif"
            font_min = 8
            boost = 0

        line_height_px = h / max(1, lines_count)
        base_px = max(font_min, min(32, int(line_height_px) + boost))
        
        bg_color = chunk.get("bg_color", "rgba(0, 0, 0, 1.0)")
        text_color = chunk.get("text_color", "#eeeeee")
        
        label.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                color: {text_color};
                border: none;
                border-radius: 3px;
                padding: 1px 2px;
            }}
        """)
        
        label_w = w
        best_px = font_size # 保存されたサイズがあればそれを使う
        
        if lines_count == 1 and '\n' not in translated:
            if ' ' not in translated.strip() and '　' not in translated.strip():
                w += 2
                h += 2
                label_w = w
            
            label.setWordWrap(False)
            text_to_render = translated.replace('\n', '').replace('\r', '')
            
            if best_px is None:
                lo, hi = font_min, 32
                best_px = font_min
                while lo <= hi:
                    mid = (lo + hi) // 2
                    html = f'<div style="font-size: {mid}px; font-weight: bold; font-family: {font_family}; white-space: nowrap; line-height: 1.0;"><nobr>{text_to_render}</nobr></div>'
                    label.setText(html)
                    label.adjustSize()
                    if label.width() <= label_w and label.height() <= h:
                        best_px = mid
                        lo = mid + 1
                    else:
                        hi = mid - 1
                # 計算結果を通知
                self.font_size_calculated.emit(cid, best_px)
            
            margin_top = 0
            if best_px >= h * 0.8:
                margin_top = -min(4, int((best_px - h * 0.8) * 0.5) + 1)
            
            final_html = f'<div style="font-size: {best_px}px; font-weight: bold; font-family: {font_family}; white-space: nowrap; line-height: 1.0; margin-top: {margin_top}px;"><nobr>{text_to_render}</nobr></div>'
            label.setText(final_html)
            label.setFixedSize(w, h)
            label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        else:
            text_to_render = translated.replace('\n', '').replace('\r', '')
            if best_px is None:
                lo, hi = font_min, 32
                best_px = font_min
                while lo <= hi:
                    mid = (lo + hi) // 2
                    html = f'<div style="font-size: {mid}px; font-weight: bold; font-family: {font_family}; line-height: 1.0;">{text_to_render}</div>'
                    label.setText(html)
                    label.setFixedWidth(label_w)
                    label.adjustSize()
                    if label.height() <= h:
                        best_px = mid
                        lo = mid + 1
                    else:
                        hi = mid - 1
                # 計算結果を通知
                self.font_size_calculated.emit(cid, best_px)
            
            final_html = f'<div style="font-size: {best_px}px; font-weight: bold; font-family: {font_family}; line-height: 1.0;">{text_to_render}</div>'
            label.setText(final_html)
            label.setFixedSize(w, h)
            label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        label.move(x, y)
        label.show()
        self.active_labels[cid] = label
        
        self._sort_labels_z_order()
        self.raise_()

    def _push_csharp_update(self):
        """C# WPF Overlayプロセスへ同期リクエストを送信する"""
        if not self.use_csharp:
            return
        
        # C#側の形式にデータを整形
        overlays_list = []
        # PyQt座標追従の geometry をベースに絶対座標を再計算
        target_x = self.x()
        target_y = self.y()

        for cid, item in list(self.active_labels.items()):
            # 常に最新のウィンドウ座標をオフセットとして適用する
            # item内のx, yはローカル座標からの計算なので、self.x()/self.y()を最新にする
            # 注: show_translation時点で item["x"] に self.x() を加算してあるが、ドラッグやリサイズで窓が動いた場合に対応
            overlays_list.append(item)

        payload = {"overlays": overlays_list}
        
        def _task():
            try:
                resp = requests.post(f"{self.cs_api_url}/api/update", json=payload, timeout=0.5)
                if resp.status_code != 200:
                    raise Exception("Status error")
            except Exception as e:
                print(f"[C# Overlay Error] 同期に失敗しました: {e} | PyQtモードへフォールバックします")
                self.use_csharp = False
                
        # ネットワークI/Oでメインスレッドをブロックしないよう非同期実行
        threading.Thread(target=_task, daemon=True).start()

    def _sort_labels_z_order(self):
        """小さなラベル（内側の要素）が大きなラベル（外側の背景）に隠れないように、
        面積の大きいものから順に下になるようにZオーダーを並べ替える。"""
        labels = list(self.active_labels.values())
        # 面積（width * height）の大きい順に並べ替える
        labels.sort(key=lambda lbl: lbl.width() * lbl.height(), reverse=True)
        for lbl in labels:
            lbl.raise_()

    @pyqtSlot(str)
    def _on_status_updated(self, status: str):
        self.status_label.setText(status)
        self.status_label.adjustSize()

    @pyqtSlot()
    def _on_clear_requested(self):
        """スレッドセーフにすべてのラベルを消去する"""
        if self.use_csharp:
            self.active_labels.clear()
            self.valid_cids.clear()
            try:
                requests.post(f"{self.cs_api_url}/api/clear", timeout=0.5)
            except:
                pass
        else:
            for label in self.active_labels.values():
                label.deleteLater()
            self.active_labels.clear()
            self.valid_cids.clear()
            self.update()

    def clear_labels(self):
        """外部スレッドから消去を依頼する"""
        self.clear_requested.emit()

    def update_labels(self, chunks, target_lang="ja"):
        """一括更新用（将来的な拡張性のために定義）"""
        pass

    def show_translation(self, cid: str, chunk: dict, translated: str, target_lang: str = "ja", font_size: int = None):
        """スレッドセーフに単一のUI更新コール"""
        self.single_translation_received.emit(cid, chunk, translated, target_lang, font_size)

    def set_status(self, status: str):
        self.status_updated.emit(status)

    def _apply_click_through(self):
        """Win32 APIでクリック透過を適用する。オーバーレイなので常に透過。"""
        hwnd = int(self.winId())
        ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ex_style = ex_style | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)

        # 翻訳UI自体がスクリーンキャプチャに映り込む「合わせ鏡」を防ぐため、
        # Windowsの録画・キャプチャAPIからこのウィンドウを完全に除外（ステルス化）する。
        # WDA_EXCLUDEFROMCAPTURE = 0x00000011 (Windows 10 Version 2004 以降用)
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000011)
        except Exception as e:
            print(f"[UI Warning] キャプチャ除外の設定に失敗しました (OSバージョンが古い等の理由): {e}")

    def showEvent(self, event):
        """ウィンドウ表示時にクリック透過を適用する。"""
        super().showEvent(event)
        # 少し遅延をかけてからWin32属性を適用（ウィンドウ生成完了を待つ）
        QTimer.singleShot(100, self._apply_click_through)

    def closeEvent(self, event):
        """終了時にC# Overlayプロセスも安全にキルする"""
        if self.use_csharp:
            try:
                requests.post(f"{self.cs_api_url}/api/stop", timeout=0.5)
            except:
                pass
        super().closeEvent(event)

    def mousePressEvent(self, event):
        """クリック透過でない場合のドラッグ移動対応。"""
        if not self._click_through and event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """ドラッグ移動。"""
        if not self._click_through and hasattr(self, '_drag_pos'):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

