# ローカルLLM（Ollama / LM Studio）統合および切り替え仕様ルール

今後、他のアプリケーション開発で Ollama と LM Studio の切り替えロジックを追加・更新する際は、以下のルールと設計方針に従ってください。

---

## 1. 接続設定とプロバイダの識別ルール

ローカルLLMは、メインプロバイダが `local` として選択されているときに使用されます。その内部での切り替え（Ollama または LM Studio）は、以下のキーで識別・管理します。

1. **`LOCAL_LLM_PROVIDER`** (文字列):
   - ローカルAIのプロバイダを示します。値は `"ollama"` または `"lmstudio"` のいずれかです。

2. **接続エンドポイントの個別管理**:
   - Ollama用URL: **`OLLAMA_URL`** (規定値: `http://localhost:11434/v1`)
   - LM Studio用URL: **`LMSTUDIO_URL`** (規定値: `http://localhost:1234/v1`)
   - **注意点**: 以前のように1つのURL入力欄を共有して上書きするのではなく、両方のエンドポイントを個別に保持し、設定UI上でもそれぞれの入力欄を設けて保存します。

3. **モデルリストの個別キャッシュ**:
   - Ollama用モデル: **`CACHED_OLLAMA_MODELS`**
   - LM Studio用モデル: **`CACHED_LMSTUDIO_MODELS`**
   - APIからモデル一覧を取得した際は、選択中のプロバイダに対応するキャッシュのみを更新します。

---

## 2. 設定UIにおけるレイアウト方針

設定UIでの表示のコンパクト化と利便性向上のため、以下のUIレイアウトを標準とします。

1. **一行（横並び）配置**:
   - `Local Provider`（プロバイダ選択ドロップダウン）を**左側**に配置します。
   - `Local Model ID`（AIモデル選択ドロップダウン）を**右側**に配置します。
   - これらを `tk.Frame` などを用いて横並びに配置し、縦方向の領域を節約します。

2. **接続先サーバー入力欄の常時個別表示**:
   - ドロップダウンでの選択状態に関わらず、`Ollama Endpoint` と `LM Studio Endpoint` の入力欄（Entry）を上下にそれぞれ常時（個別に）表示します。これにより、両方の設定を視覚的に同時に確認・編集できます。

3. **モデルフェッチのタイムアウト緩和**:
   - ローカルAIサーバーはモデルロードや起動に時間がかかる場合があるため、リスト取得時のAPIタイムアウト値は **5.0秒** 以上に設定します。

---

## 3. 各バックエンドスクリプトにおける接続分岐ルール

バックエンドスクリプト（集約、翻訳、DBメンテナンス等）でローカルLLMへ接続する際は、以下の構成でAPIクライアントを作成します。

```python
provider = config.get("LOCAL_LLM_PROVIDER", "ollama")
model_id = config.get("MODEL_ID_LOCAL", "gemma3:4b")

if provider == "lmstudio":
    # LM Studio 接続 (OpenAI互換)
    base_url = config.get("LMSTUDIO_URL", "http://localhost:1234/v1")
    # APIキーはダミーまたはLM Studio規定の値を使用
    client = OpenAI(base_url=base_url, api_key="lm-studio")
else:
    # Ollama 接続
    base_url = config.get("OLLAMA_URL", "http://localhost:11434/v1")
    # Ollama用クライアントまたはOpenAI互換クライアントで接続
```
