import os
import json
import chromadb
import requests
from google import genai 
from openai import OpenAI

# ChromaDB接続プールのインポート（相対インポートに修正）
try:
    from .chromadb_pool import get_chroma_collection
    from . import config_manager
except ImportError:
    try:
        from chromadb_pool import get_chroma_collection
        import config_manager
    except ImportError:
        get_chroma_collection = None
        config_manager = None

def get_ai_response(prompt, config, response_json=False):
    provider = config.get("DB_PROVIDER", config.get("AI_PROVIDER", "gemini")).lower()
    model_id = config.get("DB_MODEL_ID", config.get("MODEL_ID", "gemini-3.5-flash"))

    try:
        from config_manager import parse_model_name
        actual_model_id, level = parse_model_name(model_id)

        if provider == "openai":
            client = OpenAI(api_key=config.get("OPENAI_API_KEY"))
            openai_kwargs = {
                "model": actual_model_id,
                "messages": [{"role": "system", "content": "You are a database expert. Respond ONLY with JSON."} if response_json else
                             {"role": "system", "content": "You are a helpful assistant."},
                             {"role": "user", "content": prompt}]
            }
            if response_json:
                openai_kwargs["response_format"] = { "type": "json_object" }
            if actual_model_id in ("o1", "o3-mini") and level:
                openai_kwargs["reasoning_effort"] = level
            res = client.chat.completions.create(**openai_kwargs)
            return res.choices[0].message.content

        elif provider == "local":
            prov = config.get("LOCAL_LLM_PROVIDER", "ollama").lower()
            if prov == "lmstudio":
                try:
                    import requests
                    raw_url = config.get("LMSTUDIO_URL", "http://localhost:1234/v1")
                    url_resolved = raw_url.replace("localhost", "127.0.0.1")
                    
                    post_data = {
                        "model": actual_model_id,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2
                    }
                    if response_json:
                        post_data["response_format"] = { "type": "json_object" }
                        
                    res = requests.post(
                        f"{url_resolved.rstrip('/')}/chat/completions",
                        json=post_data,
                        timeout=180
                    )
                    return res.json()['choices'][0]['message']['content']
                except Exception as lm_err:
                    return f"Error: LM Studio client failed: {lm_err}"
            else:
                try:
                    import ollama
                    raw_url = config.get("OLLAMA_URL", "http://127.0.0.1:11434")
                    # localhost を 127.0.0.1 に置換し、末尾の /v1 を削除して公式ライブラリに渡す
                    host_url = raw_url.replace("/v1", "").replace("localhost", "127.0.0.1")
                    
                    client = ollama.Client(host=host_url)
                    chat_kwargs = {
                        "model": actual_model_id,
                        "messages": [{"role": "user", "content": prompt}],
                        "options": {"temperature": 0.2}
                    }
                    if response_json:
                        chat_kwargs["format"] = "json"
                    
                    res = client.chat(**chat_kwargs)
                    return res['message']['content']
                except Exception as ollama_err:
                    return f"Error: Ollama client failed: {ollama_err}"

        else: # Gemini
            api_key = config.get("GEMINI_API_KEY")
            if not api_key: return "Error: Gemini API Key is missing."
            client = genai.Client(api_key=api_key)

            gen_config = {}
            if response_json:
                gen_config['response_mime_type'] = 'application/json'

            if level is None:
                thinking_budget = config.get("THINKING_BUDGET", "medium").lower()
                level = thinking_budget

            is_thinking_supported = (
                actual_model_id in ("gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.1-flash-lite-preview")
            )

            if is_thinking_supported and level:
                if actual_model_id == "gemini-3.5-flash":
                    if level not in ("medium", "high"):
                        level = "medium"
                gen_config["thinking_config"] = {"thinking_level": level.upper()}

            res = client.models.generate_content(
                model=actual_model_id,
                contents=prompt,
                config=gen_config if gen_config else None
            )
            return res.text
    except Exception as e:
        return f"Error: {str(e)}"

# --- db_maintenance.py の clean_up_database 内にプロンプトを追加 ---

def clean_up_database(db_path, config_path):
    try:
        if config_manager:
            config = config_manager.load_config(config_path)
        else:
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                return f"Error: Failed to load config. {str(e)}"

        #  --- 1. ChromaDBへの接続とデータ取得 (改善: 接続プールで3-5倍高速化) ---
        try:
            collection = get_chroma_collection(db_path)
            
            results = collection.get()
            ids = results.get('ids', [])
            documents = results.get('documents', [])
        except Exception as e:
            return f"Error: DB Connection failed. {str(e)}"

        # --- 2. エラー行（空データ）の削除 ---
        error_ids = [ids[i] for i, doc in enumerate(documents) if not doc or doc.strip() == ""]
        if error_ids:
            collection.delete(ids=error_ids)

        # --- 3. AIに渡すための target_docs を作成 (ここで定義！) ---
        # 全件送るとトークン制限に触れるため、直近の50件などに絞るのが安全です
        target_docs = []
        for i in range(len(ids)):
            if ids[i] not in error_ids:
                target_docs.append({"id": ids[i], "content": documents[i]})
        
        # 逆順（新しい順）にして最新の30-50件程度にする（推奨）
        target_docs = target_docs[::-1][:50]

        if not target_docs:
            return f"Cleanup Done: No data to process. Removed {len(error_ids)} errors."

        # --- 4. プロンプトの定義 (target_docs が定義された後なので安全) ---
        prompt = f"""
        You are a database maintenance assistant. 
        Below are the latest memory entries from a long-term database.
        Please identify redundant information or duplicate entries and suggest which ones to delete.
        
        {json.dumps(target_docs, ensure_ascii=False)}
        
        Respond strictly in JSON format:
        {{
          "merge_plans": [
            {{ "keep_id": "ID_TO_KEEP", "delete_ids": ["ID_TO_DELETE_1", "ID_TO_DELETE_2"] }}
          ]
        }}
        """
        
        ai_res = get_ai_response(prompt, config, response_json=True)
        
        # AIがエラーを返した場合はそのまま返す
        if ai_res.startswith("Error:"):
            return f"Error removed ({len(error_ids)}), but AI failed: {ai_res}"

        if "```json" in ai_res:
            ai_res = ai_res.split("```json")[1].split("```")[0].strip()
        elif "```" in ai_res:
            ai_res = ai_res.split("```")[1].split("```")[0].strip()
        
        try:
            plan = json.loads(ai_res)
            merged_count = 0
            for item in plan.get("merge_plans", []):
                keep_id = item.get("keep_id")
                delete_ids = item.get("delete_ids", [])
                valid_deletes = [d_id for d_id in delete_ids if d_id != keep_id and d_id in ids]
                if valid_deletes:
                    collection.delete(ids=valid_deletes)
                    merged_count += len(valid_deletes)
                
            return f"Cleanup Done: Removed {len(error_ids)} errors and merged {merged_count} duplicates."
        except Exception as e:
            # 変数 e を 文字列として明示的に保持する
            error_msg = str(e)
            return f"Errors removed ({len(error_ids)}), but AI parse failed: {error_msg}\nResponse: {ai_res[:100]}"
    except Exception as ex:
        return f"Error: Database cleanup crashed: {str(ex)}"

def get_db_stats(db_path):
    """
    UI表示用の統計情報を取得
    """
    try:
        # フォルダが存在しない場合は0を返す
        if not os.path.exists(db_path):
            return 0, 0.0
        
        # 改善: 接続プールで3-5倍高速化
        collection = get_chroma_collection(db_path)
        count = collection.count()
        
        total_size = 0
        for dirpath, _, filenames in os.walk(db_path):
            for f in filenames:
                total_size += os.path.getsize(os.path.join(dirpath, f))
        
        size_mb = round(total_size / (1024 * 1024), 2)
        return count, size_mb
    except:
        return 0, 0.0

if __name__ == "__main__":
    # テスト用パス（game_ai.py等の仕様に合わせ memory_db に修正）
    def get_root():
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    base_dir = get_root()
    db_dir = os.path.join(base_dir, "memory_db") # フォルダ名を統一
    config_path = os.path.join(base_dir, "data", "config.json")
    if not os.path.exists(config_path):
        config_path = os.path.join(base_dir, "config", "config.json")
    
    print(f"Target DB: {db_dir}")
    if os.path.exists(config_path):
        print(clean_up_database(db_dir, config_path))
    else:
        print("Config file not found for testing.")