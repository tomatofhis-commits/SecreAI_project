# ===== パフォーマンス・コスト最適化のための推奨設定 =====

"""
このファイルは config.json に追加すべき最適化設定を含みます
"""

OPTIMIZED_CONFIG = {
    # ===== API コスト削減設定 =====
    "API_OPTIMIZATION": {
        "ENABLE_CACHE": True,  # APIキャッシュを有効化
        "CACHE_TTL_HOURS": 24,  # キャッシュ保持時間(時間)
        "MAX_HISTORY_FOR_CONTEXT": 10,  # AIに送る履歴の最大件数(少ないほど安い)
        "USE_COMPRESSION": True  # 長い履歴を圧縮してトークン削減
    },
    
    # ===== メモリ管理設定 =====
    "MEMORY_MANAGEMENT": {
        "AUTO_CLEANUP_DAYS": 365,  # 1年以上前のデータを自動削除
        "MAX_MEMORIES_PER_QUERY": 5,  # 検索時の最大取得件数
        "ENABLE_MEMORY_POOL": True,  # ChromaDB接続プールを使用
        "COMPRESS_OLD_MEMORIES": True  # 古い記憶を圧縮
    },
    
    # ===== パフォーマンス設定 =====
    "PERFORMANCE": {
        "MAX_BACKGROUND_WORKERS": 3,  # バックグラウンドワーカー数
        "SEARCH_TIMEOUT": 30,  # 検索タイムアウト(秒)
        "AI_TIMEOUT": 60,  # AI応答タイムアウト(秒)
        "ENABLE_PARALLEL_PROCESSING": True,  # 並列処理を有効化
        "PRELOAD_MODELS": False  # モデルの事前ロード(メモリ使用増)
    },
    
    # ===== 音声設定の最適化 =====
    "AUDIO_OPTIMIZATION": {
        "VOICE_QUEUE_SIZE": 2,  # 音声生成の先読み数
        "CLEANUP_TEMP_FILES": True,  # 一時ファイルを自動削除
        "REUSE_MIXER": True,  # pygame.mixerを再利用
        "AUDIO_BUFFER_SIZE": 2048  # バッファサイズ(大きいほど安定)
    },
    
    # ===== Tavily検索の最適化 =====
    "TAVILY_OPTIMIZATION": {
        "MAX_MONTHLY_SEARCHES": 900,  # 月間上限(1000の90%)
        "WARN_AT_PERCENTAGE": 0.8,  # 80%で警告
        "CACHE_SEARCH_RESULTS": True,  # 検索結果をキャッシュ
        "SEARCH_RESULT_TTL_HOURS": 6  # 検索キャッシュ保持時間
    },
    
    # ===== モデル選択の最適化 =====
    "MODEL_OPTIMIZATION": {
        # 軽量タスクには軽量モデルを使用
        "USE_LITE_FOR_SIMPLE_TASKS": True,
        "SIMPLE_TASK_MODEL": "gemini-2.5-flash-lite",  # 最も安い
        
        # タスク別モデル設定
        "TASK_MODELS": {
            "chat": "gemini-2.5-flash",  # 通常会話
            "vision": "gemini-2.5-flash",  # 画像分析
            "analysis": "gemini-3-flash-preview",  # 複雑な分析
            "summary": "gemma3:4b",  # ローカル要約(無料)
            "feedback": "gemini-3-flash-preview"  # フィードバック分析
        }
    }
}


# ===== コスト削減のベストプラクティス =====

COST_SAVING_TIPS = """
1. **キャッシュを活用**
   - 同じ質問には API を呼ばない
   - 画像+質問の組み合わせもキャッシュ可能

2. **履歴の圧縮**
   - 10件以上の履歴は要約して送信
   - 古い会話は ChromaDB に移動

3. **モデルの使い分け**
   - 簡単な質問: gemini-2.5-flash-lite (最安)
   - 通常の会話: gemini-2.5-flash (標準)
   - 複雑な分析: gemini-3-flash-preview (高性能)

4. **ローカルモデルの活用**
   - 要約: gemma3:4b (無料・高速)
   - フィードバック分析: gemma3:12b (無料・高性能)

5. **Tavily検索の節約**
   - 月間900回以下に抑える
   - 検索結果を6時間キャッシュ
   - 80%到達で警告表示

6. **バッチ処理**
   - 複数の小タスクをまとめて処理
   - 夜間にメンテナンスタスクを実行
"""


# ===== パフォーマンス向上のベストプラクティス =====

PERFORMANCE_TIPS = """
1. **接続プールの使用**
   - ChromaDB クライアントを再利用
   - API クライアントも再利用

2. **並列処理**
   - 検索とAI応答を並列実行
   - バックグラウンドでメモリ整理

3. **タイムアウト設定**
   - 検索: 30秒
   - AI応答: 60秒
   - 長時間タスクは自動キャンセル

4. **リソース管理**
   - pygame.mixer を適切に解放
   - 一時ファイルを定期削除
   - メモリリークを防止

5. **インデックス最適化**
   - ChromaDB の定期メンテナンス
   - 古いデータの圧縮・削除

6. **プリロード vs オンデマンド**
   - メモリ豊富: モデルをプリロード
   - メモリ少ない: オンデマンドロード
"""


# ===== 設定例: 節約モード =====

ECONOMY_MODE = {
    "AI_PROVIDER": "local",  # ローカルモデル優先
    "MODEL_ID_LOCAL": "gemma3:4b",  # 軽量モデル
    "search_switch": False,  # Web検索オフ
    "USE_INTERSECTING_AI": False,  # 複合AIオフ
    "API_OPTIMIZATION": {
        "ENABLE_CACHE": True,
        "CACHE_TTL_HOURS": 48  # 長めに保持
    }
}


# ===== 設定例: 高性能モード =====

PERFORMANCE_MODE = {
    "AI_PROVIDER": "gemini",
    "MODEL_ID": "gemini-3-flash-preview",  # 最高性能
    "search_switch": True,
    "USE_INTERSECTING_AI": True,  # 複合AI有効
    "PERFORMANCE": {
        "MAX_BACKGROUND_WORKERS": 5,
        "ENABLE_PARALLEL_PROCESSING": True,
        "PRELOAD_MODELS": True
    }
}


# ===== 設定例: バランスモード(推奨) =====

BALANCED_MODE = {
    "AI_PROVIDER": "gemini",
    "MODEL_ID": "gemini-2.5-flash",  # コスパ良好
    "MODEL_ID_SUMMARY": "gemma3:4b",  # ローカル要約
    "search_switch": True,
    "USE_INTERSECTING_AI": False,  # 必要時のみ
    "API_OPTIMIZATION": {
        "ENABLE_CACHE": True,
        "CACHE_TTL_HOURS": 24,
        "MAX_HISTORY_FOR_CONTEXT": 10
    },
    "PERFORMANCE": {
        "MAX_BACKGROUND_WORKERS": 3,
        "ENABLE_PARALLEL_PROCESSING": True,
        "PRELOAD_MODELS": False
    }
}
