import json
import requests
import os
import time
import sys
import uuid
from datetime import datetime, timedelta

# --- ライブラリのインポート ---
try:
    import pygame
    import numpy as np
    import google.genai as genai
    from openai import OpenAI
    import chromadb
except ImportError as e:
    # ログ関数がまだ定義されていないため print で出力
    print(f"Critical: Library missing: {e}")

# ChromaDB接続プールのインポート
try:
    from chromadb_pool import get_chroma_collection
except ImportError:
    try:
        from scripts.chromadb_pool import get_chroma_collection
    except ImportError:
        get_chroma_collection = None

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

# === 2. メイン処理 ===
def main():
    root = get_app_root()
    config_path = os.path.join(root, "config", "config.json")
    if not os.path.exists(config_path): return

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    db_provider = config.get("DB_PROVIDER", config.get("AI_PROVIDER", "gemini")).lower()
    db_model_id = config.get("DB_MODEL_ID", config.get("MODEL_ID", "gemini-2.5-flash"))
    lang_code = config.get("LANGUAGE", "ja")
    lang_data = load_lang_file(lang_code)
    if not lang_data: return

    history_file = os.path.join(root, config.get("FILES", {}).get("HISTORY", "data/chat_history.json"))
    tags_file = os.path.join(root, "data", "current_tags.json")
    db_path = os.path.join(root, "memory_db")
    stop_flag_path = os.path.join(root, "stop.flag")

    send_log_to_hub(lang_data["log_messages"].get("history_reset_start", "Resetting history..."))
    play_sound("up")

    # 進行中AIの停止フラグ
    try:
        with open(stop_flag_path, "w", encoding="utf-8") as f:
            f.write("stop")
    except: pass

    # 履歴読み込み
    history_data = []
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history_data = json.load(f)
        except: history_data = []

    now = datetime.now()

    if history_data:
        send_log_to_hub(f"システム: {len(history_data)}件の履歴を保存中...")
        
        try:
            now = datetime.now()
            # update_memory.py と同じ変数名・同じ渡し方に合わせる
            history_text = "\n".join(history_data) 
            time_str = now.strftime('%Y-%m-%d %H:%M')

            # --- ここがポイント：JSON側の {time} と {history_text} 両方に値を流し込む ---
            summary_prompt = lang_data["ai_prompt"]["summarize_start"].format(
                time=time_str, 
                history_text=history_text
            )

            def generate_text(prompt):
                if db_provider == "openai":
                    client_oa = OpenAI(api_key=config.get("OPENAI_API_KEY"))
                    response = client_oa.chat.completions.create(model=db_model_id, messages=[{"role": "user", "content": prompt}])
                    return response.choices[0].message.content.strip()
                elif db_provider == "local":
                    url = config.get("OLLAMA_URL", "http://localhost:11434/v1")
                    res = requests.post(f"{url.rstrip('/')}/chat/completions", json={"model": db_model_id, "messages": [{"role": "user", "content": prompt}], "options": {"num_ctx": 8192, "temperature": 0.3}}, timeout=240)
                    res.raise_for_status()
                    return res.json()['choices'][0]['message']['content'].strip()
                else: # Gemini
                    client_ge = genai.Client(api_key=config.get("GEMINI_API_KEY"))
                    res = client_ge.models.generate_content(model=db_model_id, contents=prompt)
                    return res.text.strip()

            # AI実行
            new_summary = generate_text(summary_prompt)

            # ChromaDBへの保存 (改善: 接続プール使用)
            if get_chroma_collection:
                collection = get_chroma_collection(db_path)
            else:
                # フォールバック
                db_client = chromadb.PersistentClient(path=db_path)
                collection = db_client.get_or_create_collection(name="long_term_memory")
            mem_id = f"mem_reset_{now.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:4]}"
            
            collection.add(
                documents=[new_summary],
                metadatas=[{
                    "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"), 
                    "unix": now.timestamp()
                }],
                ids=[mem_id]
            )

            # --- 履歴ファイルを先に空にする（タグ生成失敗でも履歴はクリア済みを保証） ---
            os.makedirs(os.path.dirname(history_file), exist_ok=True)
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump([], f)
            
            send_log_to_hub(lang_data["log_messages"].get("history_reset_done", "History reset."))

            # --- タグ生成（エラーでも履歴クリアには影響しない） ---
            try:
                # タグ生成用: メインAIモデル設定（game_ai.pyと同じ設定を使用）
                main_provider = config.get("AI_PROVIDER", "gemini").lower()
                if main_provider == "openai":
                    main_model_id = config.get("MODEL_ID_GPT", "gpt-5")
                elif main_provider == "local":
                    main_model_id = config.get("MODEL_ID_LOCAL", "llama3.2-vision:11b")
                else:  # gemini
                    main_model_id = config.get("MODEL_ID", "gemini-2.5-flash")
                
                def generate_text_main(prompt):
                    """タグ生成用: メインAIモデルを使用"""
                    if main_provider == "openai":
                        client_oa = OpenAI(api_key=config.get("OPENAI_API_KEY"))
                        response = client_oa.chat.completions.create(model=main_model_id, messages=[{"role": "user", "content": prompt}])
                        return response.choices[0].message.content.strip()
                    elif main_provider == "local":
                        url = config.get("OLLAMA_URL", "http://localhost:11434/v1")
                        res = requests.post(f"{url.rstrip('/')}/chat/completions", json={"model": main_model_id, "messages": [{"role": "user", "content": prompt}], "options": {"num_ctx": 8192, "temperature": 0.3}}, timeout=240)
                        res.raise_for_status()
                        return res.json()['choices'][0]['message']['content'].strip()
                    else: # Gemini
                        client_ge = genai.Client(api_key=config.get("GEMINI_API_KEY"))
                        res = client_ge.models.generate_content(model=main_model_id, contents=prompt)
                        return res.text.strip()

                # キーワードタグ生成（過去1週間のデータから）
                send_log_to_hub("システム: キーワードタグを更新中...")
                one_week_ago_ts = (now - timedelta(days=7)).timestamp()
                recent_data = collection.get(where={"unix": {"$gt": one_week_ago_ts}})

                if recent_data and recent_data.get("documents"):
                    all_memories_text = "\n".join(recent_data["documents"])
                    tag_prompt = lang_data["ai_prompt"]["extract_keywords"] + all_memories_text
                    
                    tag_raw = generate_text_main(tag_prompt)
                    tags = [t.strip() for t in tag_raw.split(",")]
                    
                    with open(tags_file, "w", encoding="utf-8") as f:
                        json.dump({"tags": tags, "updated_at": now.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False, indent=2)
                    
                    send_log_to_hub(f"システム: タグを更新しました: {', '.join(tags[:5])}...")

                # タグカウンターをリセット
                counter_file = os.path.join(root, "data", "tags_counter.json")
                with open(counter_file, "w") as f:
                    json.dump({"count": 0}, f)
                    
            except Exception as tag_error:
                send_log_to_hub(f"タグ生成エラー（履歴は正常にクリア済み）: {str(tag_error)}", is_error=True)

            play_sound("down")

        except Exception as e:
            # 要約・DB保存でのエラー
            send_log_to_hub(f"保存エラー: {str(e)}", is_error=True)

if __name__ == "__main__":
    main()