# ===== API応答キャッシュシステム =====
# 同じクエリに対する重複API呼び出しを防ぎコストを削減

import hashlib
import json
import time
from pathlib import Path

class APICache:
    """
    API応答をキャッシュしてコスト削減
    - Gemini/OpenAI/Tavily など高コストAPI用
    - 24時間有効なキャッシュ
    """
    
    def __init__(self, cache_dir, ttl_hours=24):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_hours * 3600
    
    def _get_cache_key(self, query, image_hash=None, provider="gemini", model=""):
        """クエリからキャッシュキーを生成"""
        key_data = f"{provider}:{model}:{query}"
        if image_hash:
            key_data += f":{image_hash}"
        return hashlib.sha256(key_data.encode()).hexdigest()
    
    def _get_image_hash(self, image_path):
        """画像のハッシュを計算"""
        if not image_path or not os.path.exists(image_path):
            return None
        try:
            with open(image_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return None
    
    def get(self, query, image_path=None, provider="gemini", model=""):
        """キャッシュから取得"""
        try:
            image_hash = self._get_image_hash(image_path)
            cache_key = self._get_cache_key(query, image_hash, provider, model)
            cache_file = self.cache_dir / f"{cache_key}.json"
            
            if not cache_file.exists():
                return None
            
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # TTLチェック
            if time.time() - cache_data['timestamp'] > self.ttl_seconds:
                cache_file.unlink()  # 期限切れ削除
                return None
            
            return cache_data['response']
        except:
            return None
    
    def set(self, query, response, image_path=None, provider="gemini", model=""):
        """キャッシュに保存"""
        try:
            image_hash = self._get_image_hash(image_path)
            cache_key = self._get_cache_key(query, image_hash, provider, model)
            cache_file = self.cache_dir / f"{cache_key}.json"
            
            cache_data = {
                'query': query,
                'response': response,
                'timestamp': time.time(),
                'provider': provider,
                'model': model
            }
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def clear_old_caches(self):
        """期限切れキャッシュを一括削除"""
        try:
            current_time = time.time()
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    with open(cache_file, 'r') as f:
                        data = json.load(f)
                    if current_time - data['timestamp'] > self.ttl_seconds:
                        cache_file.unlink()
                except:
                    pass
        except:
            pass


# ===== game_ai.py での使用例 =====

# グローバルキャッシュインスタンス
_api_cache = None

def get_api_cache(root):
    """APIキャッシュインスタンスを取得"""
    global _api_cache
    if _api_cache is None:
        cache_dir = os.path.join(root, "data", "api_cache")
        _api_cache = APICache(cache_dir, ttl_hours=24)
    return _api_cache


def chat_with_ai(prompt, image=None, config=None, root=None, lang_data=None):
    """改善版: キャッシュ機能付きAI呼び出し"""
    
    # キャッシュチェック
    provider = config.get("AI_PROVIDER", "gemini").lower()
    model_id = config.get("MODEL_ID", "gemini-2.5-flash")
    
    image_path = None
    if image:
        # 画像を一時保存してパスを取得
        temp_img_path = os.path.join(root, "data", "temp_query_image.png")
        image.save(temp_img_path)
        image_path = temp_img_path
    
    cache = get_api_cache(root)
    cached_response = cache.get(prompt, image_path, provider, model_id)
    
    if cached_response:
        send_log_to_hub("システム: キャッシュから応答を取得しました (APIコスト削減)")
        # 履歴に追加
        history = load_history_manual(root)
        user_pref = lang_data["system"].get("you_prefix", "You: ")
        history.append(f"{user_pref}{prompt}")
        history.append(f"AI: {cached_response}")
        save_history_manual(history, root)
        return cached_response
    
    # キャッシュになければ通常のAPI呼び出し
    # ... (既存のchat_with_ai のロジック) ...
    
    # 応答をキャッシュに保存
    if answer_text:
        cache.set(prompt, answer_text, image_path, provider, model_id)
    
    return answer_text


# ===== メンテナンス用: 定期的なキャッシュクリーンアップ =====
# db_maintenance.py に追加

def cleanup_api_cache(root):
    """期限切れAPIキャッシュを削除"""
    try:
        cache = get_api_cache(root)
        cache.clear_old_caches()
        return "API cache cleaned successfully."
    except Exception as e:
        return f"Cache cleanup error: {e}"
