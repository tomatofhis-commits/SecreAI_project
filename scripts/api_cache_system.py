# ===== API応答キャッシュシステム =====
# 同じクエリに対する重複API呼び出しを防ぎコストを削減

import hashlib
import json
import time
import os
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
        
        # 統計情報
        self.stats_file = self.cache_dir / "stats.json"
        self.stats = self._load_stats()
    
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
        self.stats["total_requests"] = self.stats.get("total_requests", 0) + 1
        
        try:
            image_hash = self._get_image_hash(image_path)
            cache_key = self._get_cache_key(query, image_hash, provider, model)
            cache_file = self.cache_dir / f"{cache_key}.json"
            
            if not cache_file.exists():
                self.stats["misses"] = self.stats.get("misses", 0) + 1
                self._update_model_stats(provider, model, hit=False)
                self._save_stats()
                return None
            
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # TTLチェック
            if time.time() - cache_data['timestamp'] > self.ttl_seconds:
                cache_file.unlink()  # 期限切れ削除
                self.stats["misses"] = self.stats.get("misses", 0) + 1
                self._update_model_stats(provider, model, hit=False)
                self._save_stats()
                return None
            
            self.stats["hits"] = self.stats.get("hits", 0) + 1
            self._update_model_stats(provider, model, hit=True)
            self._save_stats()
            return cache_data['response']
        except:
            self.stats["misses"] = self.stats.get("misses", 0) + 1
            self._update_model_stats(provider, model, hit=False)
            self._save_stats()
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
                if cache_file.name == "stats.json":
                    continue
                try:
                    with open(cache_file, 'r') as f:
                        data = json.load(f)
                    if current_time - data['timestamp'] > self.ttl_seconds:
                        cache_file.unlink()
                except:
                    pass
        except:
            pass
    
    def get_stats(self):
        """統計情報を取得"""
        total = self.stats.get("total_requests", 0)
        hits = self.stats.get("hits", 0)
        misses = self.stats.get("misses", 0)
        
        hit_rate = (hits / total * 100) if total > 0 else 0
        
        # キャッシュファイル数
        cache_count = len([f for f in self.cache_dir.glob("*.json") if f.name != "stats.json"])
        
        # モデル別統計の加工（レート計算など）
        models_summary = {}
        for key, m_stats in self.stats.get("models", {}).items():
            m_total = m_stats.get("requests", 0)
            m_hits = m_stats.get("hits", 0)
            m_rate = (m_hits / m_total * 100) if m_total > 0 else 0
            models_summary[key] = {
                "requests": m_total,
                "hits": m_hits,
                "hit_rate": round(m_rate, 2)
            }

        return {
            "total_requests": total,
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hit_rate, 2),
            "cache_count": cache_count,
            "models": models_summary
        }
    
    def _update_model_stats(self, provider, model, hit=True):
        """モデル別の統計を更新"""
        if "models" not in self.stats:
            self.stats["models"] = {}
        
        key = f"{provider}:{model}" if model else provider
        if key not in self.stats["models"]:
            self.stats["models"][key] = {"requests": 0, "hits": 0}
        
        self.stats["models"][key]["requests"] += 1
        if hit:
            self.stats["models"][key]["hits"] += 1
    
    def clear_all(self):
        """全キャッシュをクリア"""
        count = 0
        try:
            for cache_file in self.cache_dir.glob("*.json"):
                if cache_file.name != "stats.json":
                    cache_file.unlink()
                    count += 1
        except:
            pass
        return count
    
    def _load_stats(self):
        """統計情報を読み込み"""
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {"total_requests": 0, "hits": 0, "misses": 0}
    
    def _save_stats(self):
        """統計情報を保存"""
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, ensure_ascii=False, indent=2)
        except:
            pass
