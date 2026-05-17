import subprocess
import time
import requests
import os

def main():
    exe_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RTtranslator_CS_Overlay.exe")
    print(f"Starting C# Overlay: {exe_path}")
    
    # Launch overlay in the background
    proc = subprocess.Popen([exe_path])
    time.sleep(1.5)  # Wait for HttpListener to start
    
    url_update = "http://127.0.0.1:5002/api/update"
    url_clear = "http://127.0.0.1:5002/api/clear"
    url_stop = "http://127.0.0.1:5002/api/stop"
    
    # Sample labels simulating real-time translations
    payload = {
        "overlays": [
            {
                "id": "label_1",
                "text": "[C# WPF Overlay Test] ハロー、ワールド！",
                "x": 300,
                "y": 200,
                "width": 500,
                "height": 60,
                "font_size": 22,
                "font_color": "white",
                "bg_color": "rgba(0, 0, 0, 0.6)"
            },
            {
                "id": "label_2",
                "text": "This text has a round semi-transparent background drawn by DirectX.",
                "x": 300,
                "y": 280,
                "width": 600,
                "height": 50,
                "font_size": 16,
                "font_color": "#00ff00",
                "bg_color": "rgba(30, 30, 30, 0.7)"
            }
        ]
    }
    
    try:
        print("Sending overlay data...")
        resp = requests.post(url_update, json=payload, timeout=2)
        print("Response:", resp.json())
        
        print("Displaying for 5 seconds. Please look at the screen...")
        time.sleep(5.0)
        
        # Test updating a single label (label_1 is updated, label_2 is implicitly removed because it's not in the payload)
        print("Testing single update (sync & prune)...")
        update_payload = {
            "overlays": [
                {
                    "id": "label_1",
                    "text": "[Updated] Only this label remains. The second label has been pruned automatically!",
                    "x": 300,
                    "y": 200,
                    "width": 700,
                    "height": 60,
                    "font_size": 18,
                    "font_color": "yellow",
                    "bg_color": "rgba(50, 0, 0, 0.8)"
                }
            ]
        }
        resp = requests.post(url_update, json=update_payload, timeout=2)
        print("Response:", resp.json())
        
        time.sleep(4.0)
        
        print("Clearing all overlays...")
        resp = requests.post(url_clear, timeout=2)
        print("Response:", resp.json())
        
        time.sleep(1.0)
        
    except Exception as e:
        print("Communication error:", e)
        
    finally:
        print("Stopping C# Overlay app...")
        try:
            requests.post(url_stop, timeout=2)
        except:
            pass
        
        # Ensure process is dead
        proc.terminate()
        proc.wait()
        print("Done!")

if __name__ == "__main__":
    main()
