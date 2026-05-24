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


def ensure_contrast(text_color: str, bg_color: str) -> str:
    """文字色と背景色の輝度を計算し、同化しそうな場合は明るい文字色（#ffffff）を強制する"""
    import re
    
    # デフォルト値
    tc_rgb = (255, 255, 255)
    bg_rgb = (0, 0, 0)
    
    # text_color (Hex or Name) の解析
    tc = text_color.strip().lower()
    if tc.startswith("#"):
        try:
            h = tc.lstrip('#')
            if len(h) == 3:
                h = ''.join([c*2 for c in h])
            tc_rgb = tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
        except:
            pass
            
    # bg_color (rgba or Hex) の解析
    bg = bg_color.strip().lower()
    if bg.startswith("rgba") or bg.startswith("rgb"):
        try:
            nums = [int(x) for x in re.findall(r'\d+', bg)]
            if len(nums) >= 3:
                bg_rgb = (nums[0], nums[1], nums[2])
        except:
            pass
    elif bg.startswith("#"):
        try:
            h = bg.lstrip('#')
            if len(h) == 3:
                h = ''.join([c*2 for c in h])
            bg_rgb = tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
        except:
            pass

    # 相対輝度計算 (Y = 0.299R + 0.587G + 0.114B)
    tc_lum = 0.299 * tc_rgb[0] + 0.587 * tc_rgb[1] + 0.114 * tc_rgb[2]
    bg_lum = 0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]

    # もし文字色が非常に暗く（輝度 < 90）、背景も暗い（輝度 < 120）なら、文字色を強制的に白にする
    if tc_lum < 90 and bg_lum < 120:
        return "#ffffff"
        
    return text_color


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
    fallback_triggered = pyqtSignal()

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
        self.csharp_overlays = {}  # C# WPFオーバーレイへの送信用シリアライズデータを厳格に分離管理（混在バグ根絶）
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

        # C# WPFオーバーレイ動作時は、PyQt側の透明ウィンドウ自体を画面から完全に非表示にし、
        # Windowsのグラフィックス合成（DWM）負荷をほぼ完全に「ゼロ」に抑え込む（超省電力化・超低CPU負荷化）
        if self.use_csharp:
            self.hide()

    def _init_csharp_overlay(self, force_enabled: bool):
        """C# WPF Overlayの検出およびバックグラウンド起動を試みる"""
        if not force_enabled:
            print("[C# Overlay] 設定によりC#外部オーバーレイ描画エンジンは無効化されています。")
            return
        # C# 実行ファイルの探索パス
        rtt_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # D:\SecreAI_Build\RTtranslator 相当
        base_dir = os.path.dirname(rtt_dir) # D:\SecreAI_Build 相当
        
        potential_paths = [
            os.path.join(rtt_dir, "RTtranslator_CS_Overlay.exe"),
            os.path.join(base_dir, "RTtranslator_CS_Overlay.exe"),
            os.path.join(base_dir, "WPF", "bin", "Release", "RTtranslator_CS_Overlay.exe"),
            os.path.join(base_dir, "WPF", "RTtranslator_CS_Overlay.exe"),
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

        # ゾンビプロセスの多重起動およびポート5002の競合を100%排除するため、
        # 疎通チェックによる古いプロセスの再利用は行わず、無条件でOSレベルのタスクキルを実行します。
        try:
            subprocess.run(["taskkill", "/F", "/IM", "RTtranslator_CS_Overlay.exe"], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
            print("[C# Overlay] ポート競合を防ぐため、以前の古い C# プロセスを一掃しました。")
            time.sleep(0.3) # ポートがOSにより完全に解放されるのを待つウェイト
        except Exception as kill_e:
            print(f"[C# Overlay] 既存プロセスのクリーンアップに失敗: {kill_e}")

        # 起動していない場合は新規起動
        try:
            print(f"[C# Overlay] 新規プロセスを起動します: {cs_exe}")
            # creationflags=0x08000000 (CREATE_NO_WINDOW) で余計なコンソール窓を出さない
            self.cs_process = subprocess.Popen([cs_exe, str(os.getpid())], creationflags=0x08000000)
            
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
        self.fallback_triggered.connect(self._on_fallback_triggered)

    @pyqtSlot()
    def _on_fallback_triggered(self):
        """C#通信エラー時にPyQt描画モードへ安全に移行する"""
        if not self.use_csharp:
            return
        print("[UI] PyQt描画モードへ切り替えます。ラベルキャッシュをクリアし、透過ウィンドウを表示します。")
        self.use_csharp = False
        
        # dictオブジェクトを完全にパージして、次回描画時にQLabelが正しく新規作成されるようにする
        for cid in list(self.active_labels.keys()):
            if isinstance(self.active_labels[cid], dict):
                del self.active_labels[cid]
        
        self.show()

    def sync_active_ids(self, active_ids: set):
        """画面から消えたID（active_idsに含まれないもの）のラベルを破棄する"""
        self.valid_cids = active_ids
        
        if self.use_csharp:
            changed = False
            for cid in list(self.active_labels.keys()):
                if cid not in active_ids:
                    del self.active_labels[cid]
            for cid in list(self.csharp_overlays.keys()):
                if cid not in active_ids:
                    del self.csharp_overlays[cid]
                    changed = True
            if changed:
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
                item = self.csharp_overlays.get(cid)
                if item:
                    nx = self.x() + int(rect["x"]) - 3
                    ny = self.y() + int(rect["y"])
                    if abs(item["x"] - nx) > 3 or abs(item["y"] - ny) > 3:
                        item["x"] = nx
                        item["y"] = ny
                        # 個別の即時HTTP送信スレッド起動を完全に廃止し、フレーム単位で一括バッチ送信させてCPU/スレッド負荷を劇的に低減！
            else:
                label = self.active_labels[cid]
                # フォールバック時に dict が残っている可能性があるため、型チェックを行う
                if isinstance(label, dict):
                    del self.active_labels[cid]
                    return

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

        bg_color = chunk.get("bg_color", "rgba(0, 0, 0, 0.63)")
        text_color = chunk.get("text_color", "#ffffff")
        
        # Ensure contrast dynamically before displaying
        text_color = ensure_contrast(text_color, bg_color)

        # --- 共通フォントファミリーおよびフィッティングパラメータの決定 ---
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

        # 仮のラベルを使用して、裏で PyQt 側の高精度バイナリサーチを行って最適なフォントサイズを算出する
        # キャッシュされたフォントサイズがある場合でも、文字数が大幅に変化している（例：再翻訳で長さが変わった）場合は
        # フィッティングをスキップせず、再度高精度な自動フィッティング計算を実行する（文字数変化による巨大化バグの完全根絶）
        best_px = font_size
        old_item = self.csharp_overlays.get(cid) if self.use_csharp else self.active_labels.get(cid)
        old_text = old_item.get("text", "") if isinstance(old_item, dict) else (getattr(old_item, "_last_text", "") if old_item else "")
        
        if best_px is None or (old_text and abs(len(translated) - len(old_text)) > 2):
            best_px = None
            
        if best_px is None:
            # 測定用のテンポラリラベル（無ければ作成）
            if not hasattr(self, '_measure_label'):
                self._measure_label = QLabel(self.central)
                self._measure_label.setWordWrap(True)
                self._measure_label.setTextFormat(Qt.TextFormat.RichText)
                self._measure_label.hide()
            
            lines_count = chunk.get("lines_count", 1)
            text_to_render = translated.replace('\n', '').replace('\r', '')
            
            # 微調整用マージン
            measure_w = nw
            measure_h = nh
            if lines_count == 1 and '\n' not in translated:
                if ' ' not in translated.strip() and '　' not in translated.strip():
                    measure_w += 2
                    measure_h += 2

                lo, hi = font_min, 32
                best_px = font_min
                while lo <= hi:
                    mid = (lo + hi) // 2
                    html = f'<div style="font-size: {mid}px; font-weight: bold; font-family: {font_family}; white-space: nowrap; line-height: 1.0;"><nobr>{text_to_render}</nobr></div>'
                    self._measure_label.setText(html)
                    self._measure_label.adjustSize()
                    if self._measure_label.width() <= measure_w and self._measure_label.height() <= measure_h:
                        best_px = mid
                        lo = mid + 1
                    else:
                        hi = mid - 1
            else:
                lo, hi = font_min, 32
                best_px = font_min
                while lo <= hi:
                    mid = (lo + hi) // 2
                    html = f'<div style="font-size: {mid}px; font-weight: bold; font-family: {font_family}; line-height: 1.0;">{text_to_render}</div>'
                    self._measure_label.setText(html)
                    self._measure_label.setFixedWidth(measure_w)
                    self._measure_label.adjustSize()
                    if self._measure_label.height() <= measure_h:
                        best_px = mid
                        lo = mid + 1
                    else:
                        hi = mid - 1
            
            # キャッシュへの保存をトリガー
            self.font_size_calculated.emit(cid, best_px)

        # --- C# WPF オーバーレイ描画ルート ---
        if self.use_csharp:
            abs_x = self.x() + nx - 3
            abs_y = self.y() + ny

            item = {
                "id": cid,
                "text": translated,
                "x": abs_x,
                "y": abs_y,
                "width": nw,
                "height": nh,
                "font_size": best_px,  # PyQtの完璧な自動フィッティングアルゴリズムが算出したフォントサイズ！
                "font_color": text_color,
                "bg_color": bg_color
            }
            self.csharp_overlays[cid] = item
            self.active_labels[cid] = item  # C#モード時もアクティブIDの管理辞書に登録し、消去検知や追従位置更新を完全に機能させる！
            self._push_csharp_update()
            return

        # --- PyQt 描画ルート (フォールバック) ---
        # すでに表示中のラベルがある場合のガードと高速更新
        if cid in self.active_labels:
            label = self.active_labels[cid]
            if isinstance(label, dict):
                # 古いC#用の辞書が残っている場合は削除して新規QLabelを作成する
                del self.active_labels[cid]
                label = QLabel(self.central)
                label.setWordWrap(True)
                label.setTextFormat(Qt.TextFormat.RichText)
                self.active_labels[cid] = label

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
        if lines_count == 1 and '\n' not in translated:
            if ' ' not in translated.strip() and '　' not in translated.strip():
                w += 2
                h += 2
                label_w = w
            
            label.setWordWrap(False)
            text_to_render = translated.replace('\n', '').replace('\r', '')
            
            margin_top = 0
            if best_px >= h * 0.8:
                margin_top = -min(4, int((best_px - h * 0.8) * 0.5) + 1)
            
            final_html = f'<div style="font-size: {best_px}px; font-weight: bold; font-family: {font_family}; white-space: nowrap; line-height: 1.0; margin-top: {margin_top}px;"><nobr>{text_to_render}</nobr></div>'
            label.setText(final_html)
            label.setFixedSize(w, h)
            label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        else:
            text_to_render = translated.replace('\n', '').replace('\r', '')
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
        for cid, item in list(self.csharp_overlays.items()):
            # シリアライズデータのみを確実に追加（QLabelウィジェットの混在汚染を完全シャットアウト）
            overlays_list.append(item)

        payload = {"overlays": overlays_list}
        
        def _task():
            try:
                resp = requests.post(f"{self.cs_api_url}/api/update", json=payload, timeout=0.5)
                if resp.status_code != 200:
                    raise Exception(f"HTTP {resp.status_code}")
                # 成功したらエラーカウンターをリセット
                self._cs_error_count = 0
            except Exception as e:
                self._cs_error_count = getattr(self, "_cs_error_count", 0) + 1
                if self._cs_error_count >= 3:
                    # 3回連続失敗した場合のみフォールバック（一時的なタイムアウトで切り替わるバグを防止）
                    print(f"[C# Overlay Error] {self._cs_error_count}回連続失敗: {e} | PyQtモードへフォールバックします")
                    self.fallback_triggered.emit()
                else:
                    print(f"[C# Overlay Warning] 通信失敗({self._cs_error_count}/3): {e}")
                
        # ネットワークI/Oでメインスレッドをブロックしないよう非同期実行
        threading.Thread(target=_task, daemon=True).start()

    def _sort_labels_z_order(self):
        """小さなラベル（内側の要素）が大きなラベル（外側の背景）に隠れないように、
        面積の大きいものから順に下になるようにZオーダーを並べ替える。"""
        # C#モード用のdictオブジェクトが混在する可能性を完全に排除し、PyQtのウィジェットのみをソート対象にする
        labels = [lbl for lbl in self.active_labels.values() if isinstance(lbl, QWidget)]
        if not labels:
            return
            
        # 面積（width * height）の大きい順に並べ替える
        labels.sort(key=lambda lbl: lbl.width() * lbl.height(), reverse=True)
        for lbl in labels:
            lbl.raise_()

    @pyqtSlot(str)
    def _on_status_updated(self, status: str):
        self.status_label.setText(status)
        self.status_label.adjustSize()
        
        # C# WPF 側へもステータス文字列と現在のウィンドウ位置を送信する！
        if self.use_csharp:
            payload = {
                "status": status,
                "x": self.x(),
                "y": self.y(),
                "width": self.width()
            }
            def _send_status():
                try:
                    requests.post(f"{self.cs_api_url}/api/set_status", json=payload, timeout=0.3)
                except:
                    pass
            threading.Thread(target=_send_status, daemon=True).start()

    @pyqtSlot()
    def _on_clear_requested(self):
        """スレッドセーフにすべてのラベルを消去する"""
        if self.use_csharp:
            self.active_labels.clear()
            self.csharp_overlays.clear()
            self.valid_cids.clear()
            try:
                requests.post(f"{self.cs_api_url}/api/clear", timeout=0.5)
            except:
                pass
        else:
            for label in self.active_labels.values():
                label.deleteLater()
            self.active_labels.clear()
            self.csharp_overlays.clear()
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

    def hideEvent(self, event):
        """非表示（翻訳停止）時にもC# Overlayプロセスも安全にキルする"""
        if self.use_csharp:
            try:
                requests.post(f"{self.cs_api_url}/api/stop", timeout=0.5)
            except:
                pass
        super().hideEvent(event)

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

