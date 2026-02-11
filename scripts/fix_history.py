import json
import os
import sys

# === 1. パス解決・言語管理 ===
def get_app_root():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)
    if os.path.basename(script_dir) == "scripts":
        return os.path.dirname(script_dir)
    return script_dir

APP_ROOT = get_app_root()

def load_lang_file(lang_code):
    path = os.path.join(APP_ROOT, "data", "lang", f"{lang_code}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

# === 2. メイン処理 ===
def main():
    """
    直近のAIの回答に「間違い」のマークを追記する
    """
    root = get_app_root()
    config_path = os.path.join(root, "config", "config.json")

    if not os.path.exists(config_path):
        return

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        # 言語ファイルの読み込み
        lang_code = config.get("LANGUAGE", "ja")
        lang_data = load_lang_file(lang_code)
        if not lang_data:
            return

        # 履歴ファイルのパスを特定
        history_file = os.path.join(root, config["FILES"]["HISTORY"])

        if not os.path.exists(history_file):
            return

        # 1. 読み込み
        with open(history_file, "r", encoding="utf-8") as f:
            history = json.load(f)
        
        if not history:
            return

        # 2. 履歴リストの末尾から、最後のAI発言を探してマークを追記
        found_ai_msg = False
        # ja.json: "ai_prompt" -> "feedback_mark_bad"
        mark_text = lang_data["ai_prompt"].get("feedback_mark_bad", " (marked as wrong)")
        
        for i in range(len(history)-1, -1, -1):
            if history[i].startswith("AI:"):
                # 二重にマークが付かないようにチェック
                if mark_text not in history[i]:
                    history[i] += mark_text
                found_ai_msg = True
                break
        
        # AIの発言が見つからなかった場合の通知文
        # ja.json: "ai_prompt" -> "feedback_notice_bad"
        if not found_ai_msg:
            notice_text = lang_data["ai_prompt"].get("feedback_notice_bad", "[Notice: Mistakes included]")
            history.append(notice_text)

        # 3. 上書き保存
        os.makedirs(os.path.dirname(history_file), exist_ok=True)
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
            
    except Exception as e:
        # Hub側のコンソールにエラーが出るよう、標準エラー出力に流す
        print(f"History Fix Error: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()