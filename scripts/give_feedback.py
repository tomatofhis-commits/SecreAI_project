import json
import os
import sys
import re
import time
import requests
from collections import Counter

# --- ライブラリのインポート ---
try:
    import google.genai as genai
    from openai import OpenAI
    import pygame
    import numpy as np
except ImportError:
    pass 

# === 1. パス解決・ログ・言語管理 ===
def get_app_root():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)
    if os.path.basename(script_dir) == "scripts":
        return os.path.dirname(script_dir)
    return script_dir

APP_ROOT = get_app_root()

def send_log_to_hub(message, is_error=False):
    try:
        url = "http://127.0.0.1:5000/api/log"
        requests.post(url, json={"message": message, "is_error": is_error}, timeout=1)
    except:
        pass

def load_lang_file(lang_code):
    path = os.path.join(APP_ROOT, "data", "lang", f"{lang_code}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

def play_sound(notes="up"):
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2)
        
        sample_rate = 44100
        duration = 0.15
        freqs = [523, 659, 784] if notes == "up" else [784, 659, 523]
        
        for f in freqs:
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            wave = (np.sin(2 * np.pi * f * t) * 32767).astype(np.int16)
            stereo_wave = np.column_stack((wave, wave))
            sound = pygame.sndarray.make_sound(stereo_wave)
            sound.play()
            time.sleep(duration)
        
        time.sleep(0.1)
        pygame.mixer.stop()
        pygame.mixer.quit()
    except:
        pass

# === プロバイダー共通生成関数 (ローカル対応版) ===
def generate_ai_text(prompt, config, system_instr=None, is_json=False):
    provider = config.get("AI_PROVIDER", "gemini").lower()
    
    # --- A. OpenAI プロバイダー ---
    if provider == "openai":
        client = OpenAI(api_key=config.get("OPENAI_API_KEY", ""))
        model_id = config.get("MODEL_ID_GPT", "gpt-5")
        
        messages = []
        if system_instr:
            messages.append({"role": "system", "content": system_instr})
        messages.append({"role": "user", "content": prompt})
        
        response_format = {"type": "json_object"} if is_json else None
        res = client.chat.completions.create(
            model=model_id,
            messages=messages,
            response_format=response_format,
        )
        return res.choices[0].message.content.strip()

    # --- B. Llama (Local Ollama) プロバイダー ---
    elif provider == "local":
        url = config.get("OLLAMA_URL", "http://localhost:11434/v1")
        model_id = config.get("MODEL_ID_LOCAL", "llama4:scout")
        
        # システム命令とユーザープロンプトを統合
        full_prompt = f"{system_instr}\n\n{prompt}" if system_instr else prompt
        if is_json:
            full_prompt += "\nOutput in JSON format."

        try:
            res = requests.post(
                f"{url.rstrip('/')}/chat/completions",
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": full_prompt}],
                    "options": {
                        "num_ctx": 8192,
                        "temperature": 0.5 # 分析と生成のバランスをとる
                    }
                },
                timeout=120
            )
            res.raise_for_status()
            return res.json()['choices'][0]['message']['content'].strip()
        except Exception as e:
            send_log_to_hub(f"Local Feedback Analysis Error: {e}", is_error=True)
            return "{}" if is_json else "Error: Local analysis failed."

    # --- C. Gemini プロバイダー (デフォルト) ---
    else:
        client = genai.Client(api_key=config.get("GEMINI_API_KEY", ""))
        # フィードバック分析(プロファイリング)には賢いProモデルを優先
        model_id = config.get("MODEL_ID_PRO" if system_instr else "MODEL_ID", "gemini-2.5-flash")
        
        gen_config = {}
        if system_instr:
            gen_config["system_instruction"] = system_instr
        if is_json:
            gen_config["response_mime_type"] = "application/json"
            
        res = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=gen_config if gen_config else None
        )
        return res.text.strip()

# === 2. AIによる回答分析ロジック ===
def analyze_last_response(feedback_type, config, root, lang_data):
    try:
        ai_p = lang_data.get("ai_prompt", {})
        log_msg = ai_p.get("feedback_analyze", "Analyzing...").format(type=feedback_type)
        send_log_to_hub(log_msg)
        play_sound("up")

        history_path = os.path.join(root, config.get("FILES", {}).get("HISTORY", "data/chat_history.json"))
        if not os.path.exists(history_path): return []
        
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
        
        if not history: return []
        
        # 直近のAIの回答を探す
        last_ai_res = next((h for h in reversed(history) if h.startswith("AI:")), None)
        if not last_ai_res: return []

        # 修正: キーの取得方法を変更
        if feedback_type == "positive":
            instruction = ai_p.get("analyze_good", "")
        else:
            instruction = ai_p.get("analyze_bad", "")
            
        format_instr = ai_p.get("analyze_format", "")

        prompt = f"{instruction}\n{format_instr}\nTarget: {last_ai_res}"
        
        text = generate_ai_text(prompt, config)
        
        # 文字列をクレンジングしてリスト化
        t = text.replace("、", ",").replace("\n", ",").replace(" ", "").replace("　", "")
        tags = [re.sub(r"^\d+[\.\)]", "", item.strip()) for item in t.split(",") if item.strip()]
        
        return [tag[:10] for tag in tags[:3]]
        
    except Exception as e:
        send_log_to_hub(f"Analysis Error: {e}", is_error=True)
        return []

# === 3. AIによるタグの洗練ロジック ===
def update_top_tags_with_ai(data, config, lang_data):
    try:
        ai_p = lang_data.get("ai_prompt", {})
        system_instr = (
            f"{ai_p.get('profiler_role', '')}\n"
            f"{ai_p.get('profiler_rules', '')}"
        )
        user_instr = ai_p.get("profiler_instruction", "")

        # 履歴の最後50件を分析対象にする
        prompt = (
            f"Positive history: {json.dumps(data['pos_raw'][-50:], ensure_ascii=False)}\n"
            f"Negative history: {json.dumps(data['neg_raw'][-50:], ensure_ascii=False)}\n"
            f"{user_instr}"
        )

        res_text = generate_ai_text(prompt, config, system_instr=system_instr, is_json=True)
        
        refined = json.loads(res_text)
        data["top_positive"] = refined.get("top_positive", [])[:3]
        data["top_negative"] = refined.get("top_negative", [])[:3]
            
    except:
        # フォールバック: AI分析に失敗した場合は単純な頻出順
        for r_key, t_key in [("pos_raw", "top_positive"), ("neg_raw", "top_negative")]:
            items = data.get(r_key, [])
            if items:
                counts = Counter(items)
                data[t_key] = [item[0] for item in counts.most_common(3)]

# === 4. メイン処理 ===
def main(feedback_type=None):
    if not feedback_type:
        if len(sys.argv) < 2: return
        feedback_type = sys.argv[1]

    root = get_app_root()
    config_path = os.path.join(root, "config", "config.json")
    if not os.path.exists(config_path): return

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    lang_code = config.get("LANGUAGE", "ja")
    lang_data = load_lang_file(lang_code)
    if not lang_data: return

    feedback_file = os.path.join(root, config.get("FILES", {}).get("FEEDBACK", "data/feedback_memory.json"))

    # 最新回答の分析
    new_tags = analyze_last_response(feedback_type, config, root, lang_data)
    if not new_tags: return

    # 既存データの読み込み
    data = {"pos_raw": [], "neg_raw": [], "top_positive": [], "top_negative": []}
    if os.path.exists(feedback_file):
        try:
            with open(feedback_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except: pass

    # 履歴への追加(最大50件保持)
    raw_key = "pos_raw" if feedback_type == "positive" else "neg_raw"
    data[raw_key].extend(new_tags)
    data[raw_key] = data[raw_key][-50:]

    # プロファイリングの更新
    update_top_tags_with_ai(data, config, lang_data)

    # 保存
    try:
        os.makedirs(os.path.dirname(feedback_file), exist_ok=True)
        with open(feedback_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        log_m = lang_data.get("log_messages", {})
        final_msg = log_m.get("feedback_applied", "Done").format(type=feedback_type)
        send_log_to_hub(final_msg)
        play_sound("down")
    except Exception as e:
        log_m = lang_data.get("log_messages", {})
        err_msg = log_m.get("save_error", "Save failed: {e}").format(e=e)
        send_log_to_hub(err_msg, is_error=True)

if __name__ == "__main__":
    main()
