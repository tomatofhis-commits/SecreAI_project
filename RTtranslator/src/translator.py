"""
翻訳モジュール
Ollama (TranslateGemma) を使ってテキストを翻訳する
"""

import requests
import json
import threading
import queue

try:
    from src.lang_check import is_valid_translation as _validate_translation
except ImportError:
    from lang_check import is_valid_translation as _validate_translation


class Translator:
    """
    Ollamaの翻訳モデルを使ってテキストを翻訳する。
    非同期（スレッドベース）で翻訳を実行し、UIスレッドをブロックしない。
    """

    def __init__(
        self,
        model: str = "translategemma:4b",
        ollama_url: str = "http://localhost:11434",
        target_lang: str = "ja",
        source_lang: str = "auto",
        local_llm_provider: str = "ollama"
    ):
        self.model = model
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.last_error = "" # 接続エラー等の詳細を保持
        self.ollama_url = ollama_url.rstrip("/")
        self.local_llm_provider = local_llm_provider
        
        # 優先順位ベースのバックグラウンドキューシステム
        self._pqueue = queue.PriorityQueue()
        self._pqueue_maxsize = 60  # 翻訳キューの上限 (デフォルトを3倍の60に引き上げ)
        self._counter = 0  # PriorityQueueのタプル比較時の一意性担保
        self._counter_lock = threading.Lock()  # カウンターのスレッド安全性を担保
        self._active_requests = 0  # 現在実行中のリクエスト数
        self._active_lock = threading.Lock()
        
        # 3つのワーカースレッドを並列で実行し、Ollamaへの同時リクエストを可能にする
        self._worker_threads = []
        for i in range(3):
            t = threading.Thread(target=self._process_queue, daemon=True, name=f"TranslatorWorker-{i}")
            t.start()
            self._worker_threads.append(t)

        # 応答時間計測用
        self.avg_latency = 0.0
        self._latency_samples = []
        
        # 言語コード -> 正式名称マッピング
        self._lang_map = {
            "ja": "Japanese",
            "en": "English",
            "fr": "French",
            "ru": "Russian",
            "ko": "Korean",
            "zh-CN": "Simplified Chinese",
            "zh-TW": "Traditional Chinese",
            "es": "Spanish",
            "pt": "Portuguese",
            "de": "German",
            "it": "Italian"
        }

    def _get_lang_name(self, code: str) -> str:
        """コードから正式な言語名を取得する（Ollamaの理解を助ける）"""
        # "ja" などのベースコードを取得
        base_code = code.split("-")[0].lower()
        if code in self._lang_map:
            return self._lang_map[code]
        if base_code in self._lang_map:
            return self._lang_map[base_code]
        return code # 不明な場合はそのまま返す

    def _build_prompt(self, text: str, source_lang: str | None = None, has_image: bool = False) -> str:
        """TranslateGemma用のプロンプトを構築する。
        source_lang が指定された場合（fastText判定済み）は明示的に指定する。
        """
        target_name = self._get_lang_name(self.target_lang)
        effective_src = source_lang or self.source_lang
        if effective_src == "language_unknown":
            effective_src = "auto"
        
        if has_image:
            return (
                f"添付した画像に書かれているテキストを「{target_name}」に翻訳してください"
                f"（参考までにWinRTのOCR結果は『{text}』です）\n"
                f"Output ONLY the translated text without any explanations or preambles."
            )
            
        if effective_src == "auto":
            return (
                f"Translate the following text to {target_name}. "
                f"Output ONLY the translated text without any labels, preambles, or explanations:\n\n{text}"
            )
        else:
            source_name = self._get_lang_name(effective_src)
            # モデルが指示文を翻訳対象と勘違いしないよう、指示文は必ずテキストの前に置く
            return (
                f"Important: Output ONLY the translated text in {target_name}. Do NOT include any explanations, greetings, or conversational filler.\n\n"
                f"<<<source>>>{source_name}<<<target>>>{target_name}<<<text>>>{text}"
            )


    def _build_retry_prompt(self, text: str, source_lang: str | None = None) -> str:
        """
        リトライ用の強制力高めのプロンプト。
        翻訳先言語以外の出力を禁止するよう指示する。
        """
        target_name = self._get_lang_name(self.target_lang)
        effective_src = source_lang or self.source_lang
        if effective_src == "language_unknown":
            effective_src = "auto"
        src_hint = ""
        if effective_src and effective_src != "auto":
            src_name = self._get_lang_name(effective_src)
            src_hint = f"The source language is {src_name}. "
        return (
            f"{src_hint}Translate ONLY the text below into {target_name}. "
            f"Output ONLY the {target_name} translation. "
            f"Do NOT output any explanation, English text, or the original text.\n{text}"
        )

    def _process_queue(self):
        """常にバックグラウンドでキューから最も優先度の高いテキストをポチポチ翻訳していくワーカー"""
        import time
        import requests
        while True:
            try:
                priority, cnt, chunk, callback, is_active_check = self._pqueue.get()

                # 実行中カウントを増やす
                with self._active_lock:
                    self._active_requests += 1

                try:
                    # 順番が回ってきたときに既に画面から消えていれば基本的にスキップ
                    if is_active_check and not is_active_check():
                        # ただし、優先度が著しく高い（長文である）場合は、のちのキャッシュ化のために画面に無くても翻訳を強行する
                        if priority > -15000:
                            continue
                        
                    translated = None
                    start_time = time.time()
                    try:
                        text = chunk.get("text", "")
                        if text:
                            # チャンクに fastText が判定した発信元言語があれば使用（なければ auto）
                            detected_src = chunk.get("detected_source_lang", None)
                            has_image = bool(chunk.get("image_b64"))
                            prompt = self._build_prompt(text, source_lang=detected_src, has_image=has_image)
                            
                            msg = {"role": "user", "content": prompt}
                            if has_image:
                                msg["images"] = [chunk["image_b64"]]
                                
                            provider = self.local_llm_provider
                            if provider == "ollama":
                                payload = {
                                    "model": self.model,
                                    "messages": [msg],
                                    "stream": False,
                                    "options": {"temperature": 0.2},
                                }
                                base_url = self.ollama_url.split("/v1")[0].rstrip("/")
                                req_url = f"{base_url}/api/chat"
                            else: # lmstudio
                                payload = {
                                    "model": self.model,
                                    "messages": [msg],
                                    "stream": False,
                                    "temperature": 0.2
                                }
                                base_url = self.ollama_url
                                req_url = f"{base_url.rstrip('/')}/chat/completions"

                            response = requests.post(req_url, json=payload, timeout=30)
                            
                            if response.status_code == 200:
                                res_json = response.json()
                                if provider == "ollama":
                                    translated = res_json.get("message", {}).get("content", "").strip()
                                else:
                                    translated = res_json.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                                
                                # --- 1.1.2 強化: 翻訳結果のバリデーション ---
                                preambles = ["はい、", "もちろん、", "翻訳案", "翻訳結果"]
                                if translated and any(p in translated[:10] for p in preambles):
                                    print(f"[Translator] 前置き混入を検知。リトライします: '{translated[:20]}...'")
                                    if provider == "ollama":
                                        payload["options"]["temperature"] = 0.4
                                    else:
                                        payload["temperature"] = 0.4
                                    try:
                                        retry_resp = requests.post(req_url, json=payload, timeout=30)
                                        if retry_resp.status_code == 200:
                                            res_retry_json = retry_resp.json()
                                            if provider == "ollama":
                                                translated = res_retry_json.get("message", {}).get("content", "").strip()
                                            else:
                                                translated = res_retry_json.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                                    except Exception as retry_e:
                                        print(f"[Translator] リトライ中にエラー: {retry_e}")

                    except Exception as e:
                        print(f"[Translator Error in Queue] Ollama接続エラー (URL: {self.ollama_url}, Model: {self.model}): {e}")
                
                    # 応答時間を記録（移動平均）
                    duration = time.time() - start_time
                    self._latency_samples.append(duration)
                    if len(self._latency_samples) > 10:
                        self._latency_samples.pop(0)
                    self.avg_latency = sum(self._latency_samples) / len(self._latency_samples)
                        
                    if translated:
                        callback(chunk, translated)
                finally:
                    with self._active_lock:
                        self._active_requests -= 1
                    self._pqueue.task_done()
            except Exception as e:
                print(f"[Queue Worker Crash] {e}")

    def clear_queue(self):
        """翻訳キューに入っている未処理のリクエストをすべて破棄する"""
        try:
            # PriorityQueue の中身を空にする
            while not self._pqueue.empty():
                try:
                    self._pqueue.get_nowait()
                    self._pqueue.task_done()
                except queue.Empty:
                    break
            print("[Translator] 翻訳キューの未処理リクエストをすべてクリア（パージ）しました。")
        except Exception as e:
            print(f"[Translator] キューのクリア中にエラー: {e}")

    def set_queue_limit(self, limit: int):
        """キューの上限を動的に変更する"""
        self._pqueue_maxsize = limit
        print(f"[Translator] キュー上限を {limit} に変更しました")

    def translate_single_async(self, chunk: dict, callback, is_active_check=None) -> None:
        """
        単一のチャンクを受け取り、非同期で翻訳のためのキューに投入する。
        """
        with self._counter_lock:
            self._counter += 1
            cnt = self._counter
        
        # プライオリティ: 文字数が多いほど、フォントが大きいほど優先度が高い（数字が小さいほどQueueの先頭）
        text_len = len(chunk.get("text", ""))
        font_h = chunk.get("rect", {}).get("h", 0)
        priority_score = -(text_len * 1000 + font_h)
        
        self._pqueue.put((priority_score, cnt, chunk, callback, is_active_check))
        
        # --- キュー上限制御: 上限を超えたら最低優先度（数値が最大 = 最古・最短文）を破棄 ---
        if self._pqueue.qsize() > self._pqueue_maxsize:
            # PriorityQueue は直接アイテムを取り出せないため、一時リストで整理する
            try:
                items = []
                while not self._pqueue.empty():
                    items.append(self._pqueue.get_nowait())
                # 優先度の昇順（数値が小さいほど高優先）で並べ、末尾を捨てる
                items.sort(key=lambda x: x[0])
                keep = items[:self._pqueue_maxsize]
                dropped = items[self._pqueue_maxsize:]
                if dropped:
                    for d_item in dropped:
                        d_chunk = d_item[2]
                        print(f"[Translator] キュー上限超過のため破棄: '{d_chunk.get('text', '')[:20]}'")
                for item in keep:
                    self._pqueue.put_nowait(item)
            except Exception:
                pass

    @property
    def backlog_count(self):
        """待ち件数 + 実行中の合計を返す"""
        with self._active_lock:
            return self._pqueue.qsize() + self._active_requests

    def test_connection(self) -> bool:
        """ローカルLLMへの接続をテストする。"""
        try:
            provider = self.local_llm_provider
            models = Translator.get_available_models(self.ollama_url, provider=provider)
            if self.model in models:
                return True
            # 部分一致チェック
            for name in models:
                if self.model.split(":")[0] in name or name.split(":")[0] in self.model:
                    return True
            print(f"[Translator Warning] モデル '{self.model}' が見つかりません。利用可能: {models}")
            return False
        except Exception as e:
            self.last_error = str(e)
            print(f"[Translator Error] 接続テスト失敗 (URL: {self.ollama_url}, Provider: {self.local_llm_provider}): {e}")
            return False

    @staticmethod
    def get_available_models(ollama_url: str = "http://localhost:11434", provider: str = "ollama") -> list[str]:
        """APIから利用可能なモデルのリストを取得する"""
        try:
            if provider == "ollama":
                url = ollama_url.split("/v1")[0].rstrip("/")
                response = requests.get(f"{url}/api/tags", timeout=3)
                response.raise_for_status()
                models = response.json().get("models", [])
                return [m.get("name", "") for m in models]
            else: # lmstudio
                # URLに /v1 が含まれていなければ追加
                url = ollama_url.rstrip("/")
                response = requests.get(f"{url}/models", timeout=3)
                response.raise_for_status()
                models = response.json().get("data", [])
                return [m.get("id", "") for m in models]
        except Exception as e:
            print(f"[Translator Error] モデルの取得に失敗しました (Provider: {provider}): {e}")
            return []
