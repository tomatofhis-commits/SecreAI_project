# ===== ChromaDB接続プールの実装 =====
# game_ai.py、update_memory.py、clear_history.py などで使用

import threading
from functools import lru_cache

class ChromaDBPool:
    """
    ChromaDBクライアントのシングルトンプール
    複数のスクリプトで同じクライアントを再利用してパフォーマンスを向上
    """
    _instance = None
    _lock = threading.RLock()  # RLockに変更してデッドロックを回避
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._clients = {}
                    cls._instance._collections = {}
        return cls._instance
    
    def get_client(self, db_path):
        """指定パスのクライアントを取得(なければ作成)"""
        if db_path not in self._clients:
            with self._lock:
                if db_path not in self._clients:
                    import chromadb
                    self._clients[db_path] = chromadb.PersistentClient(path=db_path)
        return self._clients[db_path]
    
    def get_collection(self, db_path, collection_name="long_term_memory"):
        """指定パスとコレクション名のコレクションを取得"""
        key = f"{db_path}:{collection_name}"
        if key not in self._collections:
            with self._lock:
                if key not in self._collections:
                    # ロック内では_get_client_unlocked()ではなくget_client()を使う
                    # threading.RLockを使うことでデッドロックを回避
                    client = self.get_client(db_path)
                    self._collections[key] = client.get_or_create_collection(name=collection_name)
        return self._collections[key]
    
    def clear_cache(self):
        """キャッシュをクリア(メンテナンス後など)"""
        with self._lock:
            self._clients.clear()
            self._collections.clear()

# グローバルインスタンス
_chroma_pool = ChromaDBPool()

def get_chroma_collection(db_path, collection_name="long_term_memory"):
    """
    便利関数: ChromaDBコレクションを取得
    
    使用例:
        collection = get_chroma_collection(os.path.join(root, "memory_db"))
        results = collection.query(query_texts=[query], n_results=5)
    """
    return _chroma_pool.get_collection(db_path, collection_name)


# ===== 使用例: game_ai.py の search_long_term_memory 関数を置き換え =====

def search_long_term_memory(query, history=None, root=None, n_results=5):
    """改善版: 接続プールを使用"""
    try:
        db_path = os.path.join(root, "memory_db")
        if not os.path.exists(db_path): 
            return ""
        
        # 改善: 接続プールから取得(高速化)
        collection = get_chroma_collection(db_path)
        
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
    except Exception as e:
        send_log_to_hub(f"Memory Search Error: {e}", is_error=True)
    return ""


# ===== 使用例: update_memory.py と clear_history.py でも同様に適用 =====

def save_to_chromadb_optimized(summary, root, timestamp, unix_time):
    """改善版: 接続プールを使用した保存"""
    try:
        db_path = os.path.join(root, "memory_db")
        collection = get_chroma_collection(db_path)
        
        import uuid
        mem_id = f"mem_{timestamp.replace(' ', '').replace(':', '').replace('-', '')}_{uuid.uuid4().hex[:4]}"
        
        collection.add(
            documents=[summary],
            metadatas=[{
                "timestamp": timestamp, 
                "unix": unix_time
            }],
            ids=[mem_id]
        )
        return True
    except Exception as e:
        send_log_to_hub(f"ChromaDB Save Error: {e}", is_error=True)
        return False
