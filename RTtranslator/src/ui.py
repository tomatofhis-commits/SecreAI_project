"""
UIモジュール
翻訳結果を表示するウィンドウ（クリック透過・フォーカス非奪取・常に最前面）
"""

import sys
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

    # スレッドセーフなシグナル (cid, chunk, translated_text, target_lang)
    single_translation_received = pyqtSignal(str, dict, str, str)
    status_updated = pyqtSignal(str)
    clear_requested = pyqtSignal()

    def __init__(
        self,
        font_size: int = 16,
        opacity: float = 0.85,
        bg_color: str = "#1a1a2e",
        text_color: str = "#e0e0e0",
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

        self._setup_window()
        self._setup_ui()
        self._apply_click_through()
        self._connect_signals()

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
        for cid in list(self.active_labels.keys()):
            if cid not in active_ids:
                self.active_labels[cid].deleteLater()
                del self.active_labels[cid]

    def update_translation_position(self, cid: str, rect: dict):
        """既に表示されているラベルがあるなら、最新の座標に合わせて移動させる"""
        if cid in self.active_labels:
            label = self.active_labels[cid]
            # 座標を更新（新規生成時と同じ x-3, y に合わせる）
            nx = int(rect["x"]) - 3
            ny = int(rect["y"])
            
            # OCRの微小な揺れ（3ピクセル以内）によるUIのプルプル震えを防止
            cx = label.x()
            cy = label.y()
            if abs(cx - nx) > 3 or abs(cy - ny) > 3:
                label.move(nx, ny)

    @pyqtSlot(str, dict, str, str)
    def _on_single_translation_received(self, cid: str, chunk: dict, translated: str, target_lang: str = "ja"):
        """単一の翻訳結果を受け取り、画面に配置する"""
        if not translated:
            return
            
        # 翻訳中に画面から消えていたら描画しない（このチェックは遅延による不一致を防ぐためのものだが、
        # cidが毎フレーム変動する場合にUIが一切描画されない原因になるため削除）
        # if cid not in getattr(self, "valid_cids", set()):
        #     return
            
        # すでに描画済みならスキップ
        if cid in self.active_labels:
            return

        lines_count = chunk.get("lines_count", 1)
        rect = chunk["rect"]
        x = int(rect["x"])
        y = int(rect["y"])
        w = int(rect["w"])
        h = int(rect["h"])
        
        # --- フォントサイズ: 枠内に収まる最大サイズをバイナリサーチで決定 ---
        # 上限: 枠の高さ÷行数、ただし上限32px / 下限8px
        # 翻訳先言語に応じたフォントファミリーの決定
        target_base = target_lang.split("-")[0].lower()
        if target_base == "ko":
            font_family = "'Malgun Gothic', 'Yu Gothic UI', sans-serif"
            font_min = 10  # ハングルは8pxだと潰れやすいため10pxを最小に
            boost = 4     # ブーストを4へ増加
        elif target_base in ["ja", "zh"]:
            font_family = "'Yu Gothic UI', 'Meiryo', 'MS Gothic', sans-serif"
            font_min = 10
            boost = 4     # ブーストを4へ増加
        else:
            font_family = "'Yu Gothic UI', sans-serif"
            font_min = 8
            boost = 0

        # --- フォントサイズ: 枠内に収まる最大サイズをバイナリサーチで決定 ---
        # 上限: 枠の高さ÷行数、ただし上限32px / 下限 font_min
        line_height_px = h / max(1, lines_count)
        base_px = int(line_height_px) + boost
        base_px = max(font_min, min(32, base_px))
        
        bg_color = chunk.get("bg_color", "rgba(0, 0, 0, 1.0)")
        text_color = chunk.get("text_color", "#eeeeee")
        
        # QLabelを使用し、幅固定・高さ自動調整(WordWrap)にする
        label = QLabel(self.central)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        
        # パディングを最小化し、枠内の文字領域を最大化する
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
            # 一単語（空白なし）の場合、枠を少しだけ(+2px)大きくする
            if ' ' not in translated.strip() and '　' not in translated.strip():
                w += 2
                h += 2
                label_w = w
                
            # === 1行モード: white-space:nowrap で最大フォントを探す ===
            label.setWordWrap(False)
            text_to_render = translated.replace('\n', '').replace('\r', '')
            
            lo = font_min
            hi = 32
            best_px = font_min
            
            def _test_render_single(px):
                html = f'<div style="font-size: {px}px; font-weight: bold; font-family: {font_family}; white-space: nowrap; line-height: 1.0;"><nobr>{text_to_render}</nobr></div>'
                label.setText(html)
                label.adjustSize()
                return label.width() <= label_w and label.height() <= h
            
            # 二分探索で枠内に収まる最大のフォントサイズを特定
            while lo <= hi:
                mid = (lo + hi) // 2
                if _test_render_single(mid):
                    best_px = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            
            # 文字サイズが枠の高さに対して大きい場合、上の余白を削る（上に引き上げる）
            margin_top = 0
            if best_px >= h * 0.8:
                margin_top = -min(4, int((best_px - h * 0.8) * 0.5) + 1)
            
            html = f'<div style="font-size: {best_px}px; font-weight: bold; font-family: {font_family}; white-space: nowrap; line-height: 1.0; margin-top: {margin_top}px;"><nobr>{text_to_render}</nobr></div>'
            label.setText(html)
            
            label.setFixedSize(w, h)
            label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        else:
            # === 複数行モード: 高さ厳守で最大フォントを探す ===
            # 改行コードを一度すべてリセットし、PyQtのWordWrapに完全自動改行させる
            text_to_render = translated.replace('\n', '').replace('\r', '')
            
            lo = font_min
            hi = 32
            best_px = font_min
            
            def _test_render(px):
                html = f'<div style="font-size: {px}px; font-weight: bold; font-family: {font_family}; line-height: 1.0;">{text_to_render}</div>'
                label.setText(html)
                label.setFixedWidth(label_w)
                label.adjustSize()
                return label.height() <= h
            
            # 二分探索で枠内に収まる最大のフォントサイズを特定
            while lo <= hi:
                mid = (lo + hi) // 2
                if _test_render(mid):
                    best_px = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            
            # 最適なフォントサイズで最終描画
            html = f'<div style="font-size: {best_px}px; font-weight: bold; font-family: {font_family}; line-height: 1.0;">{text_to_render}</div>'
            label.setText(html)
            label.setFixedWidth(label_w)
            label.adjustSize()
            
            label.setFixedSize(w, h)
            label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        # 元のテキスト位置にぴったり重ねる
        label.move(x, y)
        
        label.show()
        self.active_labels[cid] = label
        
        self._sort_labels_z_order()
        self.raise_()

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

    def show_translation(self, cid: str, chunk: dict, translated: str, target_lang: str = "ja"):
        """スレッドセーフに単一のUI更新コール"""
        self.single_translation_received.emit(cid, chunk, translated, target_lang)

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
