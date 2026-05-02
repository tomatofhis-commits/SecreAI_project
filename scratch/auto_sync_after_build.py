import os
import time
import subprocess

def check_and_copy():
    rtt_dist = r"D:\SecreAI_Build\RTtranslator\dist\main.dist"
    secre_dist = r"D:\SecreAI_Build\main_hub.dist"
    
    rtt_target = r"C:\Users\amach\OneDrive\デスクトップ\アップ用作業\RTtranslator_ver1.0.0"
    secre_target = r"C:\Users\amach\OneDrive\デスクトップ\アップ用作業\SecreAI_ver1.1.0"

    print("Monitoring build completion...")
    
    while True:
        # 両方の .exe が生成されているか確認
        rtt_ready = os.path.exists(os.path.join(rtt_dist, "RTtranslator_core.exe"))
        secre_ready = os.path.exists(os.path.join(secre_dist, "secreAI.exe"))
        
        # Nuitkaのビルドディレクトリが消えたか（ビルド完了のサイン）
        rtt_building = os.path.exists(r"D:\SecreAI_Build\RTtranslator\main.build")
        secre_building = os.path.exists(r"D:\SecreAI_Build\main_hub.build")

        if rtt_ready and secre_ready and not rtt_building and not secre_building:
            print("Both builds completed! Starting copy...")
            
            # SecreAI のコピー
            subprocess.run(['robocopy', secre_dist, secre_target, '/E', '/R:3', '/W:5'], shell=True)
            # RTT のコピー
            subprocess.run(['robocopy', rtt_dist, rtt_target, '/E', '/R:3', '/W:5'], shell=True)
            
            print("Copy finished. Ready for Inno Setup.")
            break
            
        time.sleep(30)

if __name__ == "__main__":
    check_and_copy()
