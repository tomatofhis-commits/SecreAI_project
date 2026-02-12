import json
import requests
import os
import time
import sys
import uuid
import threading  # <--- これを追加しました
from datetime import datetime, timedelta

# --- ライブラリのインポート ---
try:
    import pygame
    import numpy as np
    import google.genai as genai
    from openai import OpenAI
    import chromadb
    from chromadb_pool import get_chroma_collection
except ImportError as e:
    try:
        url = "http://127.0.0.1:5000/api/log"
        requests.post(url, json={"message": f"Critical: Dependency missing in update_memory: {e}", "is_error": True}, timeout=1)
    except:
        pass

# ChromaDB接続プールのインポート
try:
    from chromadb_pool import get_chroma_collection
except ImportError:
    try:
        from scripts.chromadb_pool import get_chroma_collection
    except ImportError:
        get_chroma_collection = None

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
        return {
            "log_messages": {
                "memory_update_start": "システム: 長期記憶の整理を開始します...",
                "memory_update_done": "システム: 記憶の整理が完了しました。"
            },
            "ai_prompt": {
                "summarize_start": "あなたは記憶整理の達人です。以下の会話履歴を、後で参照するための重要な事実に絞って簡潔に要約してください。日時は {time} です。\n【会話履歴】\n{history_text}",
                "extract_keywords": "以下の要約された記憶から、ユーザーの興味や現在の状況を表すキーワードを最大5個、カンマ区切りで抽出してください。回答はキーワードのみにしてください。:\n\n"
            }
        }

# --- 電子音生成 ---
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
    except:
        pass

# === メイン処理関数 ===
def main(base_path=None):
    base = base_path if base_path else get_app_root()
    config_path = os.path.join(base, "config", "config.json")

    if not os.path.exists(config_path):
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    provider = config.get("AI_PROVIDER", "gemini").lower()
    lang_code = config.get("LANGUAGE", "ja")
    lang_data = load_lang_file(lang_code)
    
    history_file = os.path.join(base, config.get("FILES", {}).get("HISTORY", "data/chat_history.json"))
    tags_file = os.path.join(base, "data", "current_tags.json")
    # --- メインAIプロバイダーとモデルの設定（game_ai.pyと同じ設定を使用） ---
    provider = config.get("AI_PROVIDER", "gemini").lower()
    
    # プロバイダーに応じたモデルIDを取得（game_ai.pyと同じ設定キーを使用）
    if provider == "openai":
        model_id = config.get("MODEL_ID_GPT", "gpt-5")
    elif provider == "local":
        model_id = config.get("MODEL_ID_LOCAL", "llama3.2-vision:11b")
    else:  # gemini
        model_id = config.get("MODEL_ID", "gemini-2.5-flash")

    if not os.path.exists(history_file): return
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            history = json.load(f)
    except:
        return

    # 履歴が16件以上ある場合に実行（10件を圧縮し、6件を直近の文脈として残す）
    if len(history) < 16: return

    try:
        send_log_to_hub(lang_data["log_messages"]["memory_update_start"])
        # 音を鳴らす（バックグラウンド処理なので控えめに）
        threading.Thread(target=play_sound, args=("up",), daemon=True).start()

        # 最初の10件を処理対象にし、残りを保持
        processing_target = history[:10]
        remaining_history = history[10:]

        # --- 2. 要約用テキストの準備 ---
        history_text = "\n".join(processing_target)
        now = datetime.now()
        time_str = now.strftime('%Y-%m-%d %H:%M')
        summary_prompt = lang_data["ai_prompt"]["summarize_start"].format(time=time_str, history_text=history_text)
        
        # --- 要約用モデルの設定（settings_ui.pyで設定されたDB_PROVIDER/DB_MODEL_IDを使用） ---
        db_provider = config.get("DB_PROVIDER", "local").lower()
        db_model_id = config.get("DB_MODEL_ID", "gemma3:4b")
        
        # --- generate_summary_text: 要約用（DB_PROVIDER/DB_MODEL_IDを使用） ---
        def generate_summary_text(prompt):
            """要約タスク用: settings_ui.pyで設定されたデータベース用モデルを使用"""
            if db_provider == "openai":
                client_oa = OpenAI(api_key=config.get("OPENAI_API_KEY"))
                response = client_oa.chat.completions.create(
                    model=db_model_id, 
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.choices[0].message.content.strip()

            elif db_provider == "local":
                url = config.get("OLLAMA_URL", "http://localhost:11434/v1")
                try:
                    res = requests.post(
                        f"{url.rstrip('/')}/chat/completions",
                        json={
                            "model": db_model_id,
                            "messages": [{"role": "user", "content": prompt}],
                            "options": {"num_ctx": 8192, "temperature": 0.3}
                        },
                        timeout=180
                    )
                    return res.json()['choices'][0]['message']['content'].strip()
                except:
                    return "Error: Local LLM summary failed."
    
            else: # gemini
                client_ge = genai.Client(api_key=config.get("GEMINI_API_KEY"))
                res = client_ge.models.generate_content(model=db_model_id, contents=prompt)
                return res.text.strip()

        # --- generate_text: キーワードタグ生成用（メインAIモデルを使用） ---
        def generate_text(prompt):
            """タグ生成タスク用: メインAIモデルを使用（game_ai.pyと同じ設定）"""
            if provider == "openai":
                client_oa = OpenAI(api_key=config.get("OPENAI_API_KEY"))
                response = client_oa.chat.completions.create(
                    model=model_id, 
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.choices[0].message.content.strip()

            elif provider == "local":
                url = config.get("OLLAMA_URL", "http://localhost:11434/v1")
                try:
                    res = requests.post(
                        f"{url.rstrip('/')}/chat/completions",
                        json={
                            "model": model_id,  # メインAIモデル
                            "messages": [{"role": "user", "content": prompt}],
                            "options": {"num_ctx": 8192, "temperature": 0.3}
                        },
                        timeout=180
                    )
                    return res.json()['choices'][0]['message']['content'].strip()
                except:
                    return "Error: Local LLM failed."
    
            else: # gemini
                client_ge = genai.Client(api_key=config.get("GEMINI_API_KEY"))
                res = client_ge.models.generate_content(model=model_id, contents=prompt)
                return res.text.strip()

        # 要約の実行（軽量モデルを使用）
        new_summary = generate_summary_text(summary_prompt)

        # --- 追加: db_pathの定義 ---
        # settings_ui や maintenance と同じく、APP_ROOT直下の memory_db を指定します
        db_path = os.path.join(base, "memory_db") 

        # --- 3. ChromaDBへの保存 (改善: 接続プール使用で3-5倍高速化) ---
        collection = get_chroma_collection(db_path)

        mem_id = f"mem_{now.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:4]}"
        collection.add(
            documents=[new_summary],
            metadatas=[{
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"), 
                "unix": now.timestamp()
            }],
            ids=[mem_id]
        )

        # --- 4. 古いデータの削除 (1年経過分) ---
        one_year_ago_ts = (now - timedelta(days=365)).timestamp()
        old_data = collection.get(where={"unix": {"$lt": one_year_ago_ts}})
        if old_data and old_data.get("ids"):
            collection.delete(ids=old_data["ids"])

        # --- 5. 最新のキーワードタグ生成 (5回に1回実行) ---
        counter_file = os.path.join(base, "data", "tags_counter.json")
        os.makedirs(os.path.dirname(counter_file), exist_ok=True) 
        
        tag_count = 0
        if os.path.exists(counter_file):
            try:
                with open(counter_file, "r") as f:
                    tag_count = json.load(f).get("count", 0)
            except: pass

        tag_count += 1

        if tag_count >= 5:
            one_week_ago_ts = (now - timedelta(days=7)).timestamp()
            recent_data = collection.get(where={"unix": {"$gt": one_week_ago_ts}})

            if recent_data and recent_data.get("documents"):
                all_memories_text = "\n".join(recent_data["documents"])
                tag_prompt = lang_data["ai_prompt"]["extract_keywords"] + all_memories_text
                
                tag_raw = generate_text(tag_prompt)
                tags = [t.strip() for t in tag_raw.split(",")]
                
                with open(tags_file, "w", encoding="utf-8") as f:
                    json.dump({"tags": tags, "updated_at": now.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False, indent=2)
            
            tag_count = 0 
        else:
            send_log_to_hub(f"システム: 記憶サイクル進行中 ({tag_count}/5)")

        with open(counter_file, "w") as f:
            json.dump({"count": tag_count}, f)

        # --- 6. 履歴ファイルの更新（古い10件を消し、新しい履歴を受け継ぐ） ---
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(remaining_history, f, ensure_ascii=False, indent=2)
        
        send_log_to_hub(lang_data["log_messages"]["memory_update_done"])
        threading.Thread(target=play_sound, args=("down",), daemon=True).start()

    except Exception as e:
        send_log_to_hub(f"Memory Update Error: {e}", is_error=True)

if __name__ == "__main__":
    main()