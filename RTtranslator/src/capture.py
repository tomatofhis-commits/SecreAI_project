"""
画面キャプチャモジュール
指定されたウィンドウの画面をキャプチャして画像として返す
"""

import ctypes
import ctypes.wintypes
import mss
from PIL import Image
import win32gui
import win32con


def get_client_rect_on_screen(window_title: str) -> tuple[int, int, int, int] | None:
    """
    指定されたウィンドウのクライアント領域（枠の内側のゲーム画面）の
    スクリーン座標における矩形（left, top, width, height）を取得する。
    """
    hwnd = win32gui.FindWindow(None, window_title)
    if hwnd == 0:
        return None

    # ウィンドウが最小化されている場合はスキップ
    if win32gui.IsIconic(hwnd):
        return None

    # クライアント領域のサイズを取得 (0, 0, width, height)
    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        width = right - left
        height = bottom - top

        # クライアント領域の左上座標(0,0)を全体スクリーン座標に変換
        p = win32gui.ClientToScreen(hwnd, (0, 0))
        screen_left, screen_top = p[0], p[1]
        
        if width <= 0 or height <= 0:
            return None

        return (screen_left, screen_top, width, height)
    except Exception:
        return None



def list_windows() -> list[str]:
    """
    現在開いているすべてのウィンドウのタイトルをリストで返す（デバッグ用）。
    """
    titles = []

    def enum_handler(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                titles.append(title)

    win32gui.EnumWindows(enum_handler, None)
    return sorted(titles)


def capture_window(window_title: str, rect: tuple = None) -> Image.Image | None:
    """
    指定されたタイトルのウィンドウ領域をキャプチャし、PIL Imageとして返す。
    rectが渡された場合はget_window_rectの重複呼び出しをスキップする。
    """
    if rect is None:
        rect = get_client_rect_on_screen(window_title)
    if rect is None:
        return None

    left, top, width, height = rect

    monitor = {
        "left": left,
        "top": top,
        "width": width,
        "height": height,
    }

    with mss.mss() as sct:
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

    return img
