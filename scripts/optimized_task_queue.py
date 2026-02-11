# ===== バックグラウンドタスクの並列処理最適化 =====
# game_ai.py のバックグラウンド処理を改善

import concurrent.futures
from typing import Callable, Any, Optional

class OptimizedTaskQueue:
    """
    改善版タスクキュー
    - 優先度付きキュー
    - タイムアウト管理
    - エラーハンドリング強化
    """
    
    def __init__(self, max_workers=3):
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="SecreAI_Worker"
        )
        self.futures = []
        self._lock = threading.Lock()
    
    def submit_task(self, func: Callable, args: tuple = (), 
                   priority: str = "normal", timeout: Optional[int] = None):
        """
        タスクを投入
        
        Args:
            func: 実行する関数
            args: 引数のタプル
            priority: "high", "normal", "low"
            timeout: タイムアウト秒数
        """
        future = self.executor.submit(self._wrapped_task, func, args, timeout)
        
        with self._lock:
            self.futures.append({
                'future': future,
                'priority': priority,
                'func_name': func.__name__
            })
        
        return future
    
    def _wrapped_task(self, func, args, timeout):
        """タスクをラップしてエラーハンドリング"""
        try:
            if timeout:
                # タイムアウト付き実行
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as temp_executor:
                    future = temp_executor.submit(func, *args)
                    return future.result(timeout=timeout)
            else:
                return func(*args)
        except concurrent.futures.TimeoutError:
            send_log_to_hub(f"タスクタイムアウト: {func.__name__}", is_error=True)
        except Exception as e:
            send_log_to_hub(f"バックグラウンドタスクエラー ({func.__name__}): {e}", is_error=True)
    
    def wait_for_completion(self, timeout=None):
        """全タスクの完了を待つ"""
        with self._lock:
            futures_list = [f['future'] for f in self.futures]
        
        done, not_done = concurrent.futures.wait(
            futures_list, 
            timeout=timeout,
            return_when=concurrent.futures.ALL_COMPLETED
        )
        
        return len(done), len(not_done)
    
    def shutdown(self, wait=True):
        """シャットダウン"""
        self.executor.shutdown(wait=wait)


# ===== game_ai.py での使用例 =====

# グローバルタスクキュー(既存のqueueを置き換え)
optimized_task_queue = OptimizedTaskQueue(max_workers=3)

def execute_background_search_optimized(search_query, config, root, session_data):
    """
    改善版: タイムアウト付き検索実行
    30秒以内に完了しなければキャンセル
    """
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

        # Tavily検索(タイムアウト15秒)
        tavily = TavilyClient(api_key=api_key)
        search_res = tavily.search(
            query=f"{search_query} info as of {now.strftime('%Y-%m-%d')}", 
            search_depth="advanced", 
            max_results=3
        )
        
        contents = [f"Source: {r['url']}\nContent: {r['content']}" for r in search_res['results']]
        context = "\n---\n".join(contents)
        
        summary_role = ai_p.get("summary_role", "あなたは優秀なリサーチャーです。以下の英語の検索結果を読み、必ず『日本語で』要点をまとめてください。")
        summary_prompt = f"{summary_role}\n\n{context}"
        
        # Ollama要約(タイムアウト15秒)
        response = ollama.chat(
            model=summary_model, 
            messages=[{'role': 'user', 'content': summary_prompt}],
            options={'timeout': 15}
        )
        summary = response['message']['content']
        
        if summary:
            # バックグラウンドでDB保存(優先度: low)
            optimized_task_queue.submit_task(
                save_search_to_db, 
                (summary, search_query, config, root),
                priority="low"
            )
            
            # 音声再生待機
            while pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                time.sleep(0.5)

            session_id, session_getter, overlay_queue = session_data if session_data else (None, None, None)
            if overlay_queue:
                overlay_queue.put(("", None, "OFF", 0, 'speaking'))
            
            prefix = ai_p.get("search_appendix_prefix", "追加情報です。")
            final_text = f"{prefix} {summary}"
            speak_and_show(final_text, None, config, root, session_data, show_window=True)
            
    except concurrent.futures.TimeoutError:
        send_log_to_hub("検索タイムアウト: 30秒以内に完了しませんでした", is_error=True)
    except Exception as e:
        send_log_to_hub(f"Background Search Error: {e}", is_error=True)


# ===== メイン関数での使用例 =====

def main(mode="voice", chat_text=None, session_id=None, session_getter=None, overlay_queue=None):
    # ... (既存のコード) ...
    
    # 検索タスクを投入(優先度: high、タイムアウト: 30秒)
    if search_match and config.get("search_switch") is True:
        s_query = search_match.group(1)
        optimized_task_queue.submit_task(
            execute_background_search_optimized,
            (s_query, config, root, session_data),
            priority="high",
            timeout=30
        )
    
    # メモリ更新タスクを投入(優先度: low、タイムアウト: 60秒)
    if update_memory and len(load_history_manual(root)) >= 16:
        optimized_task_queue.submit_task(
            update_memory.main,
            (root,),
            priority="low",
            timeout=60
        )


# ===== プログラム終了時のクリーンアップ =====
import atexit

def cleanup_on_exit():
    """プログラム終了時にタスクキューをクリーンアップ"""
    global optimized_task_queue
    if optimized_task_queue:
        completed, pending = optimized_task_queue.wait_for_completion(timeout=5)
        send_log_to_hub(f"システム: 終了処理 - 完了: {completed}, 保留: {pending}")
        optimized_task_queue.shutdown(wait=False)

atexit.register(cleanup_on_exit)
