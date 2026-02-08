import asyncio
import sys
import os
import json
import base64
from datetime import datetime
from google import genai  # gemini-2.5-flash用
from openai import AsyncOpenAI
from ollama import AsyncClient as OllamaClient
from tavily import TavilyClient
from PIL import Image

# パス解決のカッコが正しく閉じられているか確認してください
sys.path.append(os.path.dirname(os.path.abspath(__file__))) 

try:
    # ここで game_ai から関数をインポートする際のカッコもチェック
    from game_ai import save_history_manual, load_history_manual, send_log_to_hub, increment_tavily_count
except ImportError:
    from scripts.game_ai import save_history_manual, load_history_manual, send_log_to_hub, increment_tavily_count

# --- 1. 画像変換ヘルパー ---
def encode_image_to_base64(image_path):
    """OpenAI API用に画像をBase64に変換"""
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except:
        return None

# --- 2. 各種 API クライアントの並列呼び出し用関数 ---

def call_gemini_sync(query, image_obj, system_instr, config):
    """Gemini 2.5 Flash への問い合わせ (同期型SDKをスレッドで実行)"""
    try:
        model_id = config.get("MODEL_ID", "gemini-2.5-flash")
        client = genai.Client(api_key=config.get("GEMINI_API_KEY"))
        
        contents = [query]
        if image_obj:
            contents.append(image_obj)

        response = client.models.generate_content(
            model=model_id,
            config={"system_instruction": system_instr},
            contents=contents
        )
        return f"【Gemini ({model_id}) の見解】\n{response.text}"
    except Exception as e:
        return f"Gemini Error: {e}"

async def call_openai_async(query, image_path, system_instr, config):
    """OpenAI への問い合わせ (完全非同期)"""
    try:
        model_id = config.get("MODEL_ID_GPT", "gpt-5") # 2026年時点の標準
        client = AsyncOpenAI(api_key=config.get("OPENAI_API_KEY"))
        
        content_list = [{"type": "text", "text": query}]
        if image_path and os.path.exists(image_path):
            base64_image = encode_image_to_base64(image_path)
            if base64_image:
                content_list.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                })

        response = await client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": system_instr},
                {"role": "user", "content": content_list}
            ]
        )
        return f"【OpenAI ({model_id}) の見解】\n{response.choices[0].message.content}"
    except Exception as e:
        return f"OpenAI Error: {e}"

def call_tavily_sync(query, config, root):
    """Web検索の実行 (同期型SDKをスレッドで実行)"""
    try:
        api_key = config.get("TAVILY_API_KEY")
        if not api_key: return "【最新情報】: 検索APIキー未設定。"
        
        # 検索回数を更新
        count = increment_tavily_count(root)
        send_log_to_hub(f"システム: Tavily検索を実行します (今月 {count} 回目)")

        tavily = TavilyClient(api_key=api_key)
        now_str = datetime.now().strftime('%Y-%m-%d')
        search_res = tavily.search(query=f"{query} info as of {now_str}", max_results=3)
        
        contents = [f"Source: {r['url']}\nContent: {r['content']}" for r in search_res['results']]
        return f"【最新のWeb検索結果】\n" + "\n---\n".join(contents)
    except Exception as e:
        return f"Tavily Error: {e}"

# --- 3. 合議と統合のメインロジック ---

async def generate_intersecting_response(query, image_path, config, root, lang_data):
    """三位一体の回答を統合し、履歴を保存する"""
    history = load_history_manual(root)
    p = lang_data.get("ai_prompt", {})
    max_chars = config.get("MAX_CHARS", "700文字以内")
    current_time_str = datetime.now().strftime("%Y年%m月%d日")
    
    base_instr = (
        f"{p.get('role', '')}\n"
        f"{p.get('instruction', '').format(max_chars=max_chars)}\n"
        f"現在は {current_time_str} です。"
    )

    image_obj = None
    if image_path and os.path.exists(image_path):
        image_obj = Image.open(image_path)

    send_log_to_hub("システム: Simultaneously executes two AI and internet searches")

    # STEP 1: 並列実行 (同期関数は to_thread で非同期化)
    tasks = [
        asyncio.to_thread(call_gemini_sync, query, image_obj, base_instr, config),
        call_openai_async(query, image_path, base_instr, config),
        asyncio.to_thread(call_tavily_sync, query, config, root)
    ]
    raw_responses = await asyncio.gather(*tasks)
    combined_context = "\n\n".join(raw_responses)

    # STEP 2: 統合（総督）用プロンプト
    local_model = config.get("MODEL_ID_LOCAL", "gemma2:9b")
    
    final_prompt = f"""
あなたは SecreAI の「総督」を務める統合知能です。
以下の「外部AIの分析結果」と「最新Web情報」を精査し、一つの完成された回答を生成してください。

【外部AI・検索の収集データ】
{combined_context}

【ユーザーの質問】
{query}

【制約】
・画像に関する言及がある場合、GeminiとOpenAIの分析を統合すること。
・情報の鮮度は検索結果を最重視すること。
・回答は必ず日本語で『{max_chars}』にまとめ、一貫性を持たせること。
・SecreAIとして、丁寧かつ知的に振る舞うこと。
"""

    # STEP 3: ローカルモデルで最終集約
    try:
        client = OllamaClient()
        response = await client.chat(
            model=local_model,
            messages=[{'role': 'user', 'content': final_prompt}]
        )
        answer_text = response['message']['content']
        
        # STEP 4: 履歴保存
        if answer_text:
            user_pref = lang_data.get("system", {}).get("you_prefix", "You: ")
            history.append(f"{user_pref}{query}")
            history.append(f"AI: {answer_text}")
            save_history_manual(history, root)
            send_log_to_hub("システム: 統合思考が完了しました。")
            
        return answer_text

    except Exception as e:
        error_msg = f"Integration Error: {e}"
        send_log_to_hub(error_msg, is_error=True)
        return f"AI Error: 統合処理に失敗しました。\n{combined_context[:300]}..."

# --- 4. 外部からのエントリポイント (game_ai.py と完全に一致) ---
def run_intersecting_ai(query, image_path, config, root, lang_data):
    """
    game_ai.py から呼び出されるメインエントリ。
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            generate_intersecting_response(query, image_path, config, root, lang_data)
        )
    finally:
        loop.close()