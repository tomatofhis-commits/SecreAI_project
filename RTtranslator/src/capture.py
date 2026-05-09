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
import win32ui
import win32api


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


def capture_bitblt(rect: tuple) -> Image.Image | None:
    """
    BitBltを使用してスクリーン領域をキャプチャする。
    CAPTUREBLTフラグを使用しないため、レイヤードウィンドウ（翻訳オーバーレイ等）を除外できる。
    """
    left, top, w, h = rect
    try:
        hwnd = win32gui.GetDesktopWindow()
        hwndDC = win32gui.GetWindowDC(hwnd)
        mfcDC  = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()
        
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
        saveDC.SelectObject(saveBitMap)
        
        # SRCCOPY (0x00CC0020) のみを使用し、CAPTUREBLT (0x40000000) を含めない
        # これによりレイヤードウィンドウ（WS_EX_LAYERED）が無視される
        saveDC.BitBlt((0, 0), (w, h), mfcDC, (left, top), win32con.SRCCOPY)
        
        bmpinfo = saveBitMap.GetInfo()
        bmpstr = saveBitMap.GetBitmapBits(True)
        img = Image.frombuffer('RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRX', 0, 1)
        
        # リソース解放
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndDC)
        
        return img
    except Exception:
        return None


def get_dpi_scale(hwnd: int) -> float:
    """
    指定されたウィンドウのDPIスケーリング倍率を取得する。
    Windows 10 Version 1607以降を想定。
    """
    try:
        # GetDpiForWindow は Windows 10 1607以降で利用可能
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
        return dpi / 96.0
    except Exception:
        # 取得できない場合はシステム全体のDPIを試す
        try:
            hdc = win32gui.GetDC(0)
            dpi = win32ui.GetDeviceCaps(hdc, win32con.LOGPIXELSX)
            win32gui.ReleaseDC(0, hdc)
            return dpi / 96.0
        except Exception:
            return 1.0


def capture_bitblt(rect: tuple, window_title: str) -> Image.Image | None:
    """
    BitBltを使用して物理ピクセル精度でキャプチャする（高画質版）。
    """
    hwnd = win32gui.FindWindow(None, window_title)
    if not hwnd: return None
    
    scale = get_dpi_scale(hwnd)
    left, top, w, h = rect
    
    # 物理ピクセルサイズを計算 (端数によるジッターを防ぐため round を使用)
    p_left, p_top = int(round(left * scale)), int(round(top * scale))
    p_w, p_h = int(round(w * scale)), int(round(h * scale))

    try:
        hwnd_desktop = win32gui.GetDesktopWindow()
        hwndDC = win32gui.GetWindowDC(hwnd_desktop)
        mfcDC  = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()
        
        saveBitMap = win32ui.CreateBitmap()
        # 物理サイズのビットマップを作成
        saveBitMap.CreateCompatibleBitmap(mfcDC, p_w, p_h)
        saveDC.SelectObject(saveBitMap)
        
        # 物理座標(p_left, p_top)から物理サイズ(p_w, p_h)でコピー
        saveDC.BitBlt((0, 0), (p_w, p_h), mfcDC, (p_left, p_top), win32con.SRCCOPY)
        
        bmpinfo = saveBitMap.GetInfo()
        bmpstr = saveBitMap.GetBitmapBits(True)
        img = Image.frombuffer('RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRX', 0, 1)
        
        # リソース解放
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd_desktop, hwndDC)
        
        return img
    except Exception:
        return None


def capture_printwindow(window_title: str, rect: tuple) -> Image.Image | None:
    """
    PrintWindowを使用して物理ピクセル精度でキャプチャする（高画質版）。
    """
    hwnd = win32gui.FindWindow(None, window_title)
    if not hwnd:
        return None
    
    scale = get_dpi_scale(hwnd)
    _, _, w, h = rect
    
    # 物理ピクセルサイズ (端数によるジッターを防ぐため round を使用)
    p_w, p_h = int(round(w * scale)), int(round(h * scale))
    
    try:
        # ウィンドウDCの取得と互換DCの作成
        hwndDC = win32gui.GetWindowDC(hwnd)
        mfcDC  = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()
        
        # 物理サイズのビットマップを作成
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(mfcDC, p_w, p_h)
        saveDC.SelectObject(saveBitMap)
        
        # PrintWindowの実行 (フラグ 1 = PW_CLIENTONLY)
        # Windowsの内部で自動的に物理サイズにスケーリングされて描画されます
        result = ctypes.windll.user32.PrintWindow(hwnd, int(saveDC.GetSafeHdc()), 1)
        
        if result != 0:
            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            img = Image.frombuffer('RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']), bmpstr, 'raw', 'BGRX', 0, 1)
        else:
            img = None
        
        # リソース解放
        win32gui.DeleteObject(saveBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndDC)
        
        return img
    except Exception:
        return None


def capture_window(window_title: str, rect: tuple = None, mode: str = "bitblt") -> Image.Image | None:
    """
    指定されたタイトルのウィンドウ領域をキャプチャし、PIL Imageとして返す。
    """
    if rect is None:
        rect = get_client_rect_on_screen(window_title)
    if rect is None:
        return None

    if mode == "bitblt":
        img = capture_bitblt(rect, window_title)
        # 真っ黒（extremaがすべて0）でなければ採用
        if img and img.getextrema() != ((0, 0), (0, 0), (0, 0)):
            return img
        # BitBltが失敗した、または真っ黒な場合はフォールバックとしてPrintWindowを試す
        return capture_printwindow(window_title, rect)

    elif mode == "printwindow":
        return capture_printwindow(window_title, rect)

    elif mode == "mss":
        # mss 方式 (常に物理ピクセルで取得される)
        left, top, width, height = rect
        monitor = {"left": left, "top": top, "width": width, "height": height}
        try:
            with mss.mss() as sct:
                screenshot = sct.grab(monitor)
                return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        except Exception:
            return None

    return None
