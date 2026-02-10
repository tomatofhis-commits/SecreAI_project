import subprocess, sys, os, json, threading, chromadb, ctypes, re, time, queue, requests, pygame, psutil
import pygetwindow as gw
from PIL import ImageGrab, ImageTk, Image
import speech_recognition as sr
# import tkinter as tk  # REMOVED: No direct GUI access in this script
import edge_tts
import asyncio
import base64
from io import BytesIO
from datetime import datetime
import io

# --- 1. ロックとキューの準備 ---
background_task_queue = queue.Queue()
file_lock = threading.Lock()  # これを追加

def background_task_worker():
    """バックグラウンドで仕事を一つずつ順番に片付ける専用スタッフ"""
    while True:
        task = background_task_queue.get()
        if task is None: break
        
        func, args = task
        try:
            func(*args)
        except Exception as e:
            send_log_to_hub(f"Background Task Error: {e}", is_error=True)
        finally:
            background_task_queue.task_done()

threading.Thread(target=background_task_worker, daemon=True).start()

# --- 1. パス解決・ログ・言語管理 ---
def get_app_root():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(current_script_dir) == "scripts":
        return os.path.dirname(current_script_dir)
    return current_script_dir

def is_voicevox_up():
    """VOICEVOXエンジンが起動しており、応答するか確認する"""
    try:
        response = requests.get("http://127.0.0.1:50021/version", timeout=1)
        return response.status_code == 200
    except:
        return False

APP_ROOT = get_app_root()

def send_log_to_hub(message, is_error=False):
    try:
        url = "http://127.0.0.1:5000/api/log"
        requests.post(url, json={"message": message, "is_error": is_error}, timeout=1)
    except:
        print(message)

def load_lang_file(lang_code):
    path = os.path.join(APP_ROOT, "data", "lang", f"{lang_code}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {
            "log_messages": {
                "listening": "システム: 聞き取り中...", 
                "module_loaded": "システム: 記憶更新モジュールをロードしました。",
                "engine_starting": "システム: 音声エンジンを起動中...",
                "engine_fail": "エラー: エンジン起動失敗 {e}",
                "engine_path_error": "エラー: エンジンパスが見つかりません。"
            },
            "ai_prompt": {
                "role": "あなたは配信をサポートする頼もしい相棒です。", 
                "instruction": "要点をまとめ、丁寧な日本語で【{max_chars}】で回答してください。", 
                "stt_notice": "", 
                "memory_priority": ""
            },
            "system": {"you_prefix": "You: "}
        }

update_memory = None
try:
    import update_memory
except:
    try:
        from scripts import update_memory
    except:
        update_memory = None

# --- 2. 設定・履歴・コンテキスト管理 ---
def load_config_manual(root):
    path = os.path.join(root, "config", "config.json")
    if not os.path.exists(path): return {}, {}, root
    with open(path, "r", encoding="utf-8") as f:
        conf = json.load(f)
    paths = {k: os.path.join(root, v) for k, v in conf.get("FILES", {}).items()}
    return conf, paths, root

def load_history_manual(root):
    path = os.path.join(root, "data", "chat_history.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except: return []
    return []

def save_history_manual(history, root):
    path = os.path.join(root, "data", "chat_history.json")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except: pass

def get_mid_term_context(root):
    path = os.path.join(root, "data", "current_tags.json")
    if not os.path.exists(path): return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            tags = json.load(f).get("tags", [])
        return f"\n【参考：過去の話題キーワード】\n{', '.join(tags)}\n" if tags else ""
    except: return ""

def get_feedback_context(root):
    path = os.path.join(root, "data", "feedback_memory.json")
    if not os.path.exists(path): return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pos, neg = data.get("top_positive", []), data.get("top_negative", [])
        ctx = "\n### ユーザーからの評価に基づく追加指示 (重要)\n"
        if pos: ctx += f"【比較的に好評価スタイル】: {', '.join(pos)}\n"
        if neg: ctx += f"【絶対に避けるべき低評価スタイル】: {', '.join(neg)}\n"
        return ctx
    except: return ""

def search_long_term_memory(query, history=None, root=None, n_results=5):
    try:
        db_path = os.path.join(root, "memory_db")
        if not os.path.exists(db_path): return ""
        client_db = chromadb.PersistentClient(path=db_path)
        collection = client_db.get_collection("long_term_memory")
        search_query = query
        if history and len(history) >= 1:
            context_snippet = ""
            for msg in history[-2:]:
                clean_msg = re.sub(r"^(あなた|AI):\s*", "", msg)
                context_snippet += clean_msg + " "
            search_query = f"{context_snippet.strip()} {query}"
        results = collection.query(query_texts=[search_query], n_results=n_results)
        if results['documents'] and len(results['documents'][0]) > 0:
            docs = results['documents'][0]
            metas = results['metadatas'][0] if results['metadatas'] else []
            combined = []
            for i in range(len(docs)):
                combined.append({"doc": docs[i], "meta": metas[i] if metas else {}})
            combined.sort(key=lambda x: x["meta"].get("unix") or 0, reverse=True)
            context = "\n【過去の記憶からの関連情報】:\n"
            for item in combined:
                date_val = item["meta"].get("timestamp") or "日時不明"
                context += f"・[{date_val}] {item['doc']}\n"
            return context
    except: pass
    return ""

# --- 3. 検索・深掘り実行関数 ---
def increment_tavily_count(root):
    """Tavilyの検索回数をインクリメントする。月が変わっていたらリセットする。"""
    conf_path = os.path.join(root, "config", "config.json")
    with file_lock:
        try:
            with open(conf_path, "r", encoding="utf-8") as f:
                current_conf = json.load(f)
            
            now = datetime.now() 
            now_month = now.strftime("%Y-%m")
            saved_month = current_conf.get("TAVILY_MONTH", "")
            count = current_conf.get("TAVILY_COUNT", 0)

            if saved_month != now_month:
                count = 1
                current_conf["TAVILY_MONTH"] = now_month
            else:
                count += 1
            
            current_conf["TAVILY_COUNT"] = count
            with open(conf_path, "w", encoding="utf-8") as f:
                json.dump(current_conf, f, indent=4, ensure_ascii=False)
            return count
        except Exception as e:
            send_log_to_hub(f"Count Increment Error: {e}", is_error=True)
            return 0

def execute_background_search(search_query, config, root, session_data):
    summary = None
    try:
        from tavily import TavilyClient
        import ollama
        
        lang_data = load_lang_file(config.get("LANGUAGE", "ja"))
        log_m = lang_data.get("log_messages", {})
        ai_p = lang_data.get("ai_prompt", {})

        count = increment_tavily_count(root)
        
        exec_msg = log_m.get("search_executing", "システム: Tavily検索を実行します (今月 {count} 回目)").format(count=count)
        send_log_to_hub(exec_msg)

        api_key = config.get("TAVILY_API_KEY")
        summary_model = config.get("MODEL_ID_SUMMARY", "gemma2:9b")
        now = datetime.now()

        tavily = TavilyClient(api_key=api_key)
        search_res = tavily.search(
            query=f"{search_query} info as of {now.strftime('%Y-%m-%d')}", 
            search_depth="advanced", 
            max_results=3
        )
        
        contents = [f"Source: {r['url']}\nContent: {r['content']}" for r in search_res['results']]
        context = "\n---\n".join(contents)
        
        summary_role = ai_p.get("summary_role", "あなたは優秀なリサーチャーです。以下の英語の検索結果を読み、必ず【日本語で】要点をまとめてください。")
        summary_prompt = f"{summary_role}\n\n{context}"
        
        response = ollama.chat(
            model=summary_model, 
            messages=[{'role': 'user', 'content': summary_prompt}]
        )
        summary = response['message']['content']
        
        if summary:
            # --- 修正箇所：保存タスクをバックグラウンドキューに追加 ---
            background_task_queue.put((save_search_to_db, (summary, search_query, config, root)))
            
            while pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                time.sleep(0.5)

            # --- 修正: ステータスを明示的に 'speaking' に設定 ---
            session_id, session_getter, overlay_queue = session_data if session_data else (None, None, None)
            if overlay_queue:
                overlay_queue.put(("", None, "OFF", 0, 'speaking'))
            
            prefix = ai_p.get("search_appendix_prefix", "Here is some additional information.")
            final_text = f"{prefix} {summary}"
            # Pass full session_data logic (execute_background_search args would need update too, 
            # but for now we assume search thread might not need strict session check OR 
            # we need to pass session info to background task. 
            # Ideally background tasks should also be session-aware.)
            # For this quick fix, we omit session checks in background search effectively, 
            # OR we need to update how background tasks are queued.
            
            # Since execute_background_search is called via queue without session info in current structure,
            # let's try to infer or pass it if possible. 
            # However, refactoring execute_background_search signature entirely requires changing 159 too.
            # Let's see... execute_background_search is called with 4 args currently.
            # We will rely on speak_and_show ignoring None session_data gracefully or we update it.
            
            # The previous code passed 'stop_flag'. We should interpret that as session_data if refactored fully.
            # But wait, execute_background_search is queued.
            # Let's check where it is queued.
            
            speak_and_show(final_text, None, config, root, session_data, show_window=True)
            
    except Exception as e:
        send_log_to_hub(f"Background Search Error: {e}", is_error=True)

def save_search_to_db(full_summary, query, config, root):
    """検索結果をさらに短く要約して直接ChromaDBへ保存する"""
    try:
        import ollama
        import chromadb

        summary_model = config.get("MODEL_ID_SUMMARY", "gemma2:9b")
        
        # 200文字以内にするための再要約プロンプト
        save_prompt = (
            f"以下の検索結果を、将来参照する知識として【200文字以内の日本語】で極限まで簡潔にまとめてください。\n"
            f"内容: {full_summary}"
        )
        
        response = ollama.chat(
            model=summary_model,
            messages=[{'role': 'user', 'content': save_prompt}]
        )
        short_summary = response['message']['content'][:200].strip()

        # ChromaDBへ直接アクセス
        db_path = os.path.join(root, "memory_db")
        client_db = chromadb.PersistentClient(path=db_path)
        collection = client_db.get_or_create_collection(name="long_term_memory")
        
        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M")
        unix_time = time.time()
        
        # 指定のタグと日時を付与
        db_content = f"【ネット情報】({timestamp_str}) 検索: {query} / 内容: {short_summary}"
        
        collection.add(
            documents=[db_content],
            metadatas=[{
                "timestamp": timestamp_str, 
                "unix": unix_time,
                "source": "web_search",
                "tag": "ネット情報"
            }],
            ids=[f"web_{int(unix_time)}"]
        )
        
        send_log_to_hub(f"システム: 検索情報を「ネット情報」としてDBに記録しました。")

    except Exception as e:
        send_log_to_hub(f"Internal DB Save Error: {e}", is_error=True)

# --- 4. AIコア機能 ---
gemini_client = None
openai_client = None

def init_ai(config):
    global gemini_client, openai_client
    if config.get("GEMINI_API_KEY"):
        try:
            import google.genai as genai
            gemini_client = genai.Client(api_key=config["GEMINI_API_KEY"])
        except Exception as e:
            send_log_to_hub(f"Gemini Init Error: {e}", is_error=True)
    if config.get("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            openai_client = OpenAI(api_key=config["OPENAI_API_KEY"])
        except Exception as e:
            send_log_to_hub(f"OpenAI Init Error: {e}", is_error=True)

def chat_with_ai(prompt, image=None, config=None, root=None, lang_data=None):
    global gemini_client, openai_client
    history = load_history_manual(root)
    max_chars = config.get("MAX_CHARS", "700文字以内")
    long_term_ctx = search_long_term_memory(prompt, history, root)
    today_ctx_str = f"\n【現在の状況】: {config.get('TODAY_CONTEXT', '')}\n" if config.get('TODAY_CONTEXT') else ""
    feedback_ctx = get_feedback_context(root)
    mid_term_ctx = get_mid_term_context(root)
    p = lang_data["ai_prompt"]
    current_time_str = datetime.now().strftime("%Y年%m月%d日")
    
    system_instr = (
        f"{p['role']}\n"
        f"{p['instruction'].format(max_chars=max_chars)}\n"
        f"{p['stt_notice']}\n"
        f"{p['memory_priority']}\n"
        f"{today_ctx_str}{long_term_ctx}{feedback_ctx}{mid_term_ctx}"
        f"\n【前提条件に日時情報がなければ：】今日は {current_time_str} です。"
    )

# 検索スイッチがオンの時、辞書の search_logic を使用
    provider = config.get("AI_PROVIDER", "gemini").lower()
    if config.get("search_switch") is True and provider == "gemini":
        logic = p.get("search_logic", "")
        if logic:
            system_instr += logic
            # ログを追加
            send_log_to_hub("システム: 検索ロジックをシステム命令に統合しました。")
        else:
            send_log_to_hub("警告: search_switchはONですが、ja.json内にsearch_logicが見つかりません。", is_error=True)

    answer_text = ""
    image_bytes = None
    if image:
        if image.mode != "RGB":
            image = image.convert("RGB")
        buffered = BytesIO()
        image.save(buffered, format="JPEG", quality=95, optimize=True)
        image_bytes = buffered.getvalue()

    try:
        if provider == "local":
            url = config.get("OLLAMA_URL", "http://localhost:11434/v1")
            model_id = config.get("MODEL_ID_LOCAL", "llama3.2-vision:11b")
            messages = [{"role": "system", "content": system_instr}]
            for h in history[-10:]:
                role = "assistant" if h.startswith("AI:") else "user"
                content = h.replace("AI:", "").replace("You: ", "").replace("あなた: ", "").strip()
                messages.append({"role": role, "content": content})
            user_content = [{"type": "text", "text": prompt}]
            if image_bytes:
                base64_image = base64.b64encode(image_bytes).decode('utf-8')
                user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}})
            messages.append({"role": role, "content": user_content})
            res = requests.post(
                f"{url.rstrip('/')}/chat/completions",
                json={
                    "model": model_id, "messages": messages,
                    "options": {
                        "num_ctx": 4096, "temperature": 0.7, "repeat_penalty": 1.2, 
                        "num_predict": 400, "stop": ["\n\n", "###"]
                    }
                },
                timeout=(10, 600)
            )
            res.raise_for_status()
            answer_text = res.json()['choices'][0]['message']['content']

        elif provider == "openai" and openai_client:
            model_id = config.get("MODEL_ID_GPT", "gpt-5")
            messages = [{"role": "system", "content": system_instr}]
            for h in history[-10:]:
                role = "assistant" if h.startswith("AI:") else "user"
                content = h.replace("AI:", "").replace("You: ", "").replace("あなた: ", "").strip()
                messages.append({"role": role, "content": content})
            user_content = [{"type": "text", "text": prompt}]
            if image_bytes:
                base64_image = base64.b64encode(image_bytes).decode('utf-8')
                user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}})
            messages.append({"role": "user", "content": user_content})
            res = openai_client.chat.completions.create(model=model_id, messages=messages)
            answer_text = res.choices[0].message.content

        elif gemini_client:
            model_id = config.get("MODEL_ID", "gemini-2.5-flash")
            gemini_history = []
            for h in history[-10:]:
                role = "model" if h.startswith("AI:") else "user"
                content = h.replace("AI:", "").replace("You: ", "").replace("あなた: ", "").strip()
                gemini_history.append({"role": role, "parts": [{"text": content}]})
            chat = gemini_client.chats.create(model=model_id, config={"system_instruction": system_instr}, history=gemini_history)
            parts = [prompt]
            if image_bytes:
                parts.append(Image.open(BytesIO(image_bytes)))
            res = chat.send_message(parts)
            answer_text = res.text

        if answer_text:
            user_pref = lang_data["system"].get("you_prefix", "You: ")
            history.append(f"{user_pref}{prompt}")
            history.append(f"AI: {answer_text}")
            save_history_manual(history, root)
            return answer_text

    except Exception as e:
        send_log_to_hub(f"Chat Error ({provider}): {e}", is_error=True)
        return f"AI Error: The conversation stops."

# --- 5. オーバーレイ表示・音声合成 ---
current_overlay_root = None
speaker_lock = threading.Lock()

# Removed show_window_thread as it is unsafe.
# Logic moved to main_hub.py via overlay_queue.

def speak_and_show(text, image_path=None, config=None, root=None, session_data=None, show_window=True, skip_idle=False):
    if root is None: root = APP_ROOT
    # session_data: (session_id, session_getter, overlay_queue)
    session_id, session_getter, overlay_queue = session_data if session_data else (None, None, None)

    # CHECK SESSION
    if session_id and session_getter:
        if session_getter() != session_id:
            return # Stop processing

    send_log_to_hub(f"AI: {text}")
    lang_code = config.get("LANGUAGE", "ja")
    alpha = config.get("WINDOW_ALPHA", 0.6)
    
    if show_window and str(alpha) != "OFF" and overlay_queue:
        dt = config.get("DISPLAY_TIME", 60)
        # Put request to main thread queue with status 'speaking'
        overlay_queue.put((text, image_path, float(alpha), dt, 'speaking'))

    try:
        if lang_code == "ja":
            # VOICEVOXが利用可能かチェック
            if is_voicevox_up():
                run_voicevox_speak(text, config, root, session_data)
            else:
                send_log_to_hub("警告: VOICEVOXに接続できません。edge-ttsで代用します。")
                run_edge_tts_speak(text, "ja", config, root, session_data)
        else:
            run_edge_tts_speak(text, lang_code, config, root, session_data)
    finally:
        # Reset indicator to idle after speech finishes unless explicitly skipped
        if overlay_queue:
            if not skip_idle:
                overlay_queue.put((None, None, "OFF", 0, 'idle'))
            # 少し待機してからリセット（音声再生完了を確実にする）
            time.sleep(0.1)

def run_voicevox_speak(text, config, root, session_data):
    session_id, session_getter, _ = session_data if session_data else (None, None, None)
    
    # 音声データを貯めるキュー（最大2つ分先行生成しておく）
    audio_queue = queue.Queue(maxsize=2)
    sentences = [s.strip() for s in re.split(r'[。\n！？]', text) if s.strip()]
    speaker_id = config.get("SPEAKER_ID", 3)
    speed = config.get("VOICE_SPEED", 1.2)
    
    # --- [内部関数] 音声を生成してキューに入れる ---
    def generator():
        for s in sentences:
            if session_id and session_getter and session_getter() != session_id: break
            try:
                # 1. クエリ作成
                r1 = requests.post(f"http://127.0.0.1:50021/audio_query?text={s}&speaker={speaker_id}", timeout=10).json()
                r1["speedScale"] = speed
                r1["volumeScale"] = config.get("VOICE_VOLUME", 1.0)
                r1["postPhonemeLength"] = 0.1  # 先ほどの0.03設定
                
                # 2. 音声合成
                r2 = requests.post(f"http://127.0.0.1:50021/synthesis?speaker={speaker_id}", data=json.dumps(r1), timeout=30)
                if r2.status_code == 200:
                    audio_queue.put(r2.content) # 再生側が取り出すまで待機してくれる
            except Exception as e:
                send_log_to_hub(f"音声生成エラー: {e}", is_error=True)
        audio_queue.put(None) # 終了の合図

    # 生成スレッドを開始
    gen_thread = threading.Thread(target=generator, daemon=True)
    gen_thread.start()

    # --- [再生メイン処理] ---
    with speaker_lock:
        wav_dir = os.path.join(root, "data", "wav")
        os.makedirs(wav_dir, exist_ok=True)
        temp_wav_path = os.path.join(wav_dir, "current_speech.wav")

        # Pygame Mixer初期化（既存通り）
        if not pygame.mixer.get_init():
            target_device = config.get("DEVICE_NAME")
            try:
                if target_device and target_device != "デフォルト":
                    pygame.mixer.init(frequency=44100, size=-16, channels=1, devicename=target_device)
                else:
                    pygame.mixer.init(frequency=44100, size=-16, channels=1)
            except:
                pygame.mixer.init(frequency=44100, size=-16, channels=1)

        # 音量設定
        vol = 1.0 # エンジン側でコントロールするため固定

        while True:
            audio_data = audio_queue.get() # 生成が終わるまで待機
            if audio_data is None: break # 全文終了
            
            if session_id and session_getter and session_getter() != session_id:
                pygame.mixer.music.stop()
                break

            with open(temp_wav_path, "wb") as f:
                f.write(audio_data)
            
            pygame.mixer.music.load(temp_wav_path)
            pygame.mixer.music.set_volume(vol)
            pygame.mixer.music.play()
            
            while pygame.mixer.music.get_busy():
                if session_id and session_getter and session_getter() != session_id:
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.01)
            
            pygame.mixer.music.unload()

# Edge-TTS 言語コードから音声名へのマッピング
EDGE_TTS_VOICES = {
    "ja": "ja-JP-NanamiNeural",     # 日本語
    "en": "en-US-AriaNeural",      # 英語（米国）
    "zh": "zh-CN-XiaoxiaoNeural",  # 中国語（簡体字）
    "ko": "ko-KR-SunHiNeural",     # 韓国語
    "es": "es-ES-ElviraNeural",    # スペイン語
    "fr": "fr-FR-DeniseNeural",    # フランス語
    "de": "de-DE-KatjaNeural",     # ドイツ語
    "it": "it-IT-ElsaNeural",      # イタリア語
    "pt": "pt-BR-FranciscaNeural", # ポルトガル語（ブラジル）
    "ru": "ru-RU-SvetlanaNeural",  # ロシア語
    "vi": "vi-VN-HoaiMyNeural",    # ベトナム語
}

def run_edge_tts_speak(text, lang_code, config, root, session_data):
    """Edge-TTSを使用して音声合成を行う"""
    session_id, session_getter, _ = session_data if session_data else (None, None, None)
    
    # 言語コードから音声を取得（デフォルトは英語）
    voice = EDGE_TTS_VOICES.get(lang_code, "en-US-AriaNeural")
    
    # 保存先パスの準備
    wav_dir = os.path.join(root, "data", "wav")
    os.makedirs(wav_dir, exist_ok=True)
    temp_mp3_path = os.path.join(wav_dir, "edge_tts_speech.mp3")
    
    async def generate_speech():
        """Edge-TTSで音声を生成"""
        vol = config.get("VOICE_VOLUME", 1.0)
        # Edge-TTS volume: "+50%", "-20%" style
        perc = int((vol - 1.0) * 100)
        vol_str = f"{perc:+}%"
        communicate = edge_tts.Communicate(text, voice, volume=vol_str)
        await communicate.save(temp_mp3_path)
    
    try:
        # 非同期で音声ファイルを生成
        asyncio.run(generate_speech())
        
        if session_id and session_getter and session_getter() != session_id:
            return
        
        # pygame.mixer が未初期化なら初期化（デバイス指定）
        if not pygame.mixer.get_init():
            target_device = config.get("DEVICE_NAME")
            try:
                if target_device and target_device != "デフォルト":
                    pygame.mixer.init(devicename=target_device)
                else:
                    pygame.mixer.init()
            except:
                pygame.mixer.init()

        # デバイスから再生
        vol = 1.0 # エンジン側でコントロールするため固定
        pygame.mixer.music.load(temp_mp3_path)
        pygame.mixer.music.set_volume(vol)
        pygame.mixer.music.play()
        
        while pygame.mixer.music.get_busy():
            if session_id and session_getter and session_getter() != session_id:
                pygame.mixer.music.stop()
                break
            time.sleep(0.05)
        
        pygame.mixer.music.unload()

    except Exception as e:
        send_log_to_hub(f"Edge-TTS Playback Error: {e}", is_error=True)

# --- 6. キャプチャ・音声入力・メイン ---
def capture_target_screenshot(config, root):
    target = config.get("TARGET_GAME_TITLE", "All Capture")
    path = os.path.join(root, "data", "temp_ss.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        if target == "All Capture": raise ValueError()
        wins = gw.getWindowsWithTitle(target)
        win = next((w for w in wins if w.title == target), None)
        if win:
            bbox = (win.left, win.top, win.right, win.bottom)
            ImageGrab.grab(bbox=bbox, all_screens=True).save(path)
        else: ImageGrab.grab(all_screens=True).save(path)
    except: ImageGrab.grab(all_screens=True).save(path)
    return path

def ensure_voicevox_is_running(config, lang_data):
    vv_path = config.get("VV_PATH", "")
    target_name = os.path.basename(vv_path)
    if not target_name: return False
    for proc in psutil.process_iter(['name']):
        try:
            if target_name.lower() in proc.info['name'].lower(): return True
        except: continue
    if vv_path and os.path.exists(vv_path):
        send_log_to_hub(lang_data["log_messages"]["engine_starting"])
        try:
            subprocess.Popen([vv_path], creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
            time.sleep(3); return True
        except Exception as e:
            send_log_to_hub(lang_data["log_messages"]["engine_fail"].format(e=e), is_error=True)
    else: send_log_to_hub(lang_data["log_messages"]["engine_path_error"], is_error=True)
    return False

def get_voice_input(guide, config, root, lang_data, session_data, image_path=None):
    stt_lang = 'ja-JP' if config.get("LANGUAGE", "ja") == "ja" else 'en-US'
    session_id, session_getter, _ = session_data if session_data else (None, None, None)

    # ガイダンス音声を別スレッドで再生（同時に入力を開始できるようにする）
    threading.Thread(
        target=speak_and_show, 
        args=(guide, image_path, config, root, session_data, False, True), 
        daemon=True
    ).start()
    
    # 入力デバイス（マイク）の設定を解決
    input_device_name = config.get("INPUT_DEVICE_NAME", "デフォルト")
    device_index = None
    if input_device_name and input_device_name != "デフォルト":
        try:
            mic_list = sr.Microphone.list_microphone_names()
            if input_device_name in mic_list:
                device_index = mic_list.index(input_device_name)
        except: pass

    r = sr.Recognizer()
    # 終了を判断するタイミング（沈黙を許容する時間）を少し長くする（デフォルト0.8秒）
    r.pause_threshold = 1.2
    
    try:
        with sr.Microphone(device_index=device_index) as source:
            r.adjust_for_ambient_noise(source, duration=0.8)
            send_log_to_hub(lang_data["log_messages"]["listening"])
            
            # Send status:listening to overlay
            if session_data and session_data[2]:
                session_data[2].put(("", None, "OFF", 0, 'listening'))
            
            # セッションチェック
            if session_id and session_getter and session_getter() != session_id: return None
            
            # 待機時間を10秒、発話制限を20秒に延長
            audio = r.listen(source, timeout=10, phrase_time_limit=20)
            
            if session_id and session_getter and session_getter() != session_id: return None
            return r.recognize_google(audio, language=stt_lang)
    except: return None

def main(mode="voice", chat_text=None, session_id=None, session_getter=None, overlay_queue=None):
    session_data = (session_id, session_getter, overlay_queue)
    root = get_app_root()
    config, _, _ = load_config_manual(root)
    lang_code = config.get("LANGUAGE", "ja")
    lang_data = load_lang_file(lang_code)
    log_m = lang_data.get("log_messages", {})

    if lang_code == "ja": ensure_voicevox_is_running(config, lang_data)
    init_ai(config)
    init_ai(config)
    # Stop flag removal logic is no longer needed
    # stop_flag = os.path.join(root, "stop.flag")
    # if os.path.exists(stop_flag):
    #     try: os.remove(stop_flag)
    #     except: pass

    try:
        query, abs_path = None, None
        if mode == "vision":
            abs_path = os.path.abspath(capture_target_screenshot(config, root))
            query = get_voice_input(log_m.get("vision_guide", "Analyze"), config, root, lang_data, session_data, abs_path)
        elif mode == "chat" and chat_text:
            query = chat_text
        else:
            query = get_voice_input(log_m.get("voice_guide", "How can I help you?"), config, root, lang_data, session_data)

        if query:
            # Send status:thinking to overlay
            if session_data and session_data[2]:
                session_data[2].put(("", None, "OFF", 0, 'thinking'))
                
            # --- モード分岐：複合AIモードか通常モードか ---
            res = None
            if config.get("USE_INTERSECTING_AI", False):
                try:
                    from scripts.intersecting_ai import run_intersecting_ai
                    send_log_to_hub("システム: 複合AIモードで実行します。")
                    
                    # 修正前: res = run_intersecting_ai(query, abs_path, root)
                    # 修正後: 定義に合わせて 5つの引数 すべてを渡します
                    res = run_intersecting_ai(query, abs_path, config, root, lang_data)
                    
                except Exception as e:
                    send_log_to_hub(f"複合AIエラー: {e}。通常モードへフォールバックします。", is_error=True)
            
            # 複合AIがオフ、またはエラーで res が空の場合に通常モードを実行
            if not res:
                res = chat_with_ai(query, Image.open(abs_path) if abs_path else None, config, root, lang_data)

            if res:
                search_match = re.search(r'\[SEARCH:\s*(.*?)\]', res)
                clean_res = re.sub(r'\[SEARCH:.*\]', '', res).strip()

                if search_match and config.get("search_switch") is True and config.get("AI_PROVIDER", "gemini").lower() == "gemini":
                    s_query = search_match.group(1)
                    # 辞書から予約ログを取得
                    res_msg = log_m.get("search_reserved", "システム: 検索タスクを予約しました。")
                    send_log_to_hub(res_msg)
                    # Use session_data instead of stop_flag in background tasks if possible, 
                    # but for now we pass session_data as the last arg to execute_background_search 
                    # replacing stop_flag. Logic inside execute_background_search needs update for this.
                    background_task_queue.put((execute_background_search, (s_query, config, root, session_data)))

                speak_and_show(clean_res, abs_path, config, root, session_data)

        if update_memory and len(load_history_manual(root)) >= 16:
            # 辞書から予約ログを取得
            mem_msg = log_m.get("memory_update_reserved", "システム: 記憶整理タスクを予約しました。")
            send_log_to_hub(mem_msg)
            background_task_queue.put((update_memory.main, (root,)))
            
        # global current_overlay_root  # Removed
        # if current_overlay_root:
        #     try: current_overlay_root.after(0, current_overlay_root.destroy)
        #     except: pass
    except Exception as e:
        send_log_to_hub(f"Execution Error: {e}", is_error=True)

if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "voice"
    t = sys.argv[2] if len(sys.argv) > 2 else None
    main(m, t)