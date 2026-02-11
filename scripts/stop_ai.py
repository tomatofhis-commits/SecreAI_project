import os
import sys
import json

def load_config():
    # 実行ファイル(exe)かスクリプト(py)かでルートを特定
    if getattr(sys, 'frozen', False):
        curr_dir = os.path.dirname(sys.executable)
    else:
        # scripts/ フォルダ内にいるので、その親フォルダが APP_ROOT
        script_path = os.path.abspath(__file__)
        script_dir = os.path.dirname(script_path)
        if os.path.basename(script_dir) == "scripts":
            curr_dir = os.path.dirname(script_dir)
        else:
            curr_dir = script_dir
    
    # APP_ROOT/config/config.json を見に行く
    config_path = os.path.join(curr_dir, "config", "config.json")
    
    if not os.path.exists(config_path):
        # 予備として、このスクリプトだけ動かす場合のパス解決
        return curr_dir

    # ここで BASE_DIR (APP_ROOT) を返すだけで十分です
    return curr_dir

def stop_ai():
    # load_config からは APP_ROOT のパスが返ってくる
    BASE_DIR = load_config()
    STOP_FLAG = os.path.join(BASE_DIR, "stop.flag")
    
    # stop.flag ファイルを作成して、game_ai.py に停止を知らせる
    try:
        with open(STOP_FLAG, "w", encoding="utf-8") as f:
            f.write("stop") # 念のため中身を書き込む
        print(f"停止信号（stop.flag）を送信しました: {STOP_FLAG}")
    except Exception as e:
        print(f"停止信号送信エラー: {e}")

if __name__ == "__main__":
    stop_ai()