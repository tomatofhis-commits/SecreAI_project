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
    ):
        self.model = model
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.last_error = "" # 接続エラー等の詳細を保持
        self.ollama_url = ollama_url.rstrip("/")
        
        # 優先順位ベースのバックグラウンドキューシステム
        self._pqueue = queue.PriorityQueue()
        self._pqueue_maxsize = 20  # 翻訳キューの上限
        self._counter = 0  # PriorityQueueのタプル比較時の一意性担保
        self._counter_lock = threading.Lock()  # カウンターのスレッド安全性を担保
        
        self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._worker_thread.start()

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
        """常にバックグラウンドでキューから最も優先度の高いテキストをポチポチ翻訳していく単一ワーカー"""
        import time
        while True:
            try:
                priority, cnt, chunk, callback, is_active_check = self._pqueue.get()
                
                # 順番が回ってきたときに既に画面から消えていれば基本的にスキップ
                if is_active_check and not is_active_check():
                    # ただし、優先度が著しく高い（長文である）場合は、のちのキャッシュ化のために画面に無くても翻訳を強行する
                    # 優先度は -(文字数*1000) 等の負の値。文字数が15文字以上なら priority は -15000 以下になる
                    if priority > -15000:
                        self._pqueue.task_done()
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
                            
                        payload = {
                            "model": self.model,
                            "messages": [msg],
                            "stream": False,
                            "options": {"temperature": 0.2},
                        }
                        # /v1 など OpenAI互换パスを除いてベースURLを取得
                        base_url = self.ollama_url.split("/v1")[0].rstrip("/")
                        response = requests.post(f"{base_url}/api/chat", json=payload, timeout=30)
                        response.raise_for_status()
                        translated = response.json().get("message", {}).get("content", "").strip()

                        # --- Translategemma等のおせっかいな前置きを削除 ---
                        prefixes = [
                            'Here is the translation of the text in the image:\n"',
                            'Here is the translation:\n"',
                            'Translation:\n"',
                            '"'
                        ]
                        for prefix in prefixes:
                            if translated.startswith(prefix):
                                translated = translated[len(prefix):]
                        if translated.endswith('"'):
                            translated = translated[:-1]
                        translated = translated.strip()

                        # --- 事後バリデーション & 安全なリトライ（最大1回）---
                        if translated and not _validate_translation(translated, self.target_lang):
                            print(f"[Translator] 翻訳検証失敗。リトライを実行します。 [{translated[:30]}...]")
                            retry_prompt = self._build_retry_prompt(text, source_lang=detected_src)
                            retry_payload = {
                                "model": self.model,
                                "messages": [{"role": "user", "content": retry_prompt}],
                                "stream": False,
                                "options": {"temperature": 0.1},
                            }
                            try:
                                retry_resp = requests.post(f"{base_url}/api/chat", json=retry_payload, timeout=30)
                                retry_resp.raise_for_status()
                                retry_result = retry_resp.json().get("message", {}).get("content", "").strip()
                                if retry_result and _validate_translation(retry_result, self.target_lang):
                                    # リトライ成功
                                    translated = retry_result
                                    print(f"[Translator] リトライ成功。")
                                else:
                                    # リトライも失敗 → コールバックを呼ばずスキップ（main.py側で改めて検証されるより早く捨てる）
                                    print(f"[Translator] リトライも検証失敗。スキップします。")
                                    translated = None
                            except Exception as retry_e:
                                print(f"[Translator] リトライ中にエラー: {retry_e}")
                                # リトライ失敗 → 初回結果もスキップ（不正な出力を伝播させない）
                                translated = None

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
                    
                self._pqueue.task_done()
            except Exception as e:
                print(f"[Queue Worker Crash] {e}")

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
                    print(f"[Translator] キュー上限超過: {len(dropped)}件を破棄しました")
                for item in keep:
                    self._pqueue.put_nowait(item)
            except Exception:
                pass

    @property
    def backlog_count(self) -> int:
        """未処理のキュー件数を返す"""
        return self._pqueue.qsize()

    def test_connection(self) -> bool:
        """Ollamaへの接続をテストする。"""
        try:
            # /v1 など OpenAI互換パスを除いてベースURLを取得
            base_url = self.ollama_url.split("/v1")[0].rstrip("/")
            response = requests.get(f"{base_url}/api/tags", timeout=5)
            response.raise_for_status()
            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            if self.model in model_names:
                return True
            # 部分一致チェック
            for name in model_names:
                if self.model.split(":")[0] in name:
                    return True
            print(f"[Translator Warning] モデル '{self.model}' が見つかりません。利用可能: {model_names}")
            return False
        except Exception as e:
            self.last_error = str(e)
            print(f"[Translator Error] Ollama接続テスト失敗 (URL: {self.ollama_url}): {e}")
            return False

    @staticmethod
    def get_available_models(ollama_url: str = "http://localhost:11434") -> list[str]:
        """Ollama APIから利用可能なモデルのリストを取得する"""
        try:
            url = ollama_url.split("/v1")[0].rstrip("/")
            response = requests.get(f"{url}/api/tags", timeout=3)
            response.raise_for_status()
            models = response.json().get("models", [])
            return [m.get("name", "") for m in models]
        except Exception as e:
            print(f"[Translator Error] モデルの取得に失敗しました: {e}")
            return []
