import subprocess
import time
import requests
import os
import win32gui
from PIL import Image
import io

def get_any_visible_window():
    titles = []
    def enum_handler(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title and len(title) > 2:
                # 自身のウィンドウやオーバーレイは避ける
                if "RTtranslator" not in title and "test_cs" not in title:
                    titles.append(title)
    win32gui.EnumWindows(enum_handler, None)
    return titles[0] if titles else None

def main():
    exe_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RTtranslator_CS_Overlay.exe")
    print(f"Starting C# Overlay: {exe_path}")
    
    # WPFプロセスを起動
    proc = subprocess.Popen([exe_path])
    time.sleep(1.5)  # 起動待ち
    
    url_capture = "http://127.0.0.1:5002/api/capture"
    url_stop = "http://127.0.0.1:5002/api/stop"
    
    target_window = get_any_visible_window()
    if not target_window:
        print("Error: No visible window found to capture.")
        proc.terminate()
        return
        
    print(f"Target window for capture: '{target_window}'")
    
    # クライアント領域全体を取得するための仮座標（[0, 0, w, h] をC#側で自動取得させるため rect=None と同等の挙動）
    payload = {
        "window_title": target_window,
        "mode": "bitblt",
        "rect": None
    }
    
    try:
        print("Sending /api/capture request (Full Client Area)...")
        resp = requests.post(url_capture, json=payload, timeout=3.0)
        print("Response status code:", resp.status_code)
        
        if resp.status_code == 200 and resp.content:
            img = Image.open(io.BytesIO(resp.content))
            print(f"Success! Captured image dimensions: {img.width}x{img.height}")
            out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_capture_result_full.png")
            img.save(out_path)
            print(f"Captured full image successfully saved to: {out_path}")
        else:
            print("Failed to capture full image")

        # 部分領域 [10, 20, 300, 150] のキャプチャテスト
        sub_payload = {
            "window_title": target_window,
            "mode": "bitblt",
            "rect": [10, 20, 300, 150]
        }
        print("Sending /api/capture request (Sub-region)...")
        resp_sub = requests.post(url_capture, json=sub_payload, timeout=3.0)
        print("Response status code (Sub-region):", resp_sub.status_code)
        
        if resp_sub.status_code == 200 and resp_sub.content:
            img_sub = Image.open(io.BytesIO(resp_sub.content))
            print(f"Success! Captured sub-region dimensions: {img_sub.width}x{img_sub.height}")
            out_path_sub = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_capture_result_sub.png")
            img_sub.save(out_path_sub)
            print(f"Captured sub-region successfully saved to: {out_path_sub}")
        else:
            print("Failed to capture sub-region image")
                
    except Exception as e:
        print("Communication error:", e)
        
    finally:
        print("Stopping C# Overlay app...")
        try:
            requests.post(url_stop, timeout=2)
        except:
            pass
            
        proc.terminate()
        proc.wait()
        print("Done!")

if __name__ == "__main__":
    main()
