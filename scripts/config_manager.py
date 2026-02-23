import json
import os
import hashlib

# --- 設定ファイルのバージョン管理 ---
CONFIG_VERSION = "2.0"

# --- デフォルト設定 ---
DEFAULT_CONFIG = {
    "CONFIG_VERSION": CONFIG_VERSION,
    "AI_PROVIDER": "gemini",
    "GEMINI_API_KEY": "",
    "OPENAI_API_KEY": "",
    "TAVILY_API_KEY": "",
    "MODEL_ID": "gemini-2.0-flash",
    "MODEL_ID_PRO": "gemini-2.0-flash-thinking-exp",
    "MODEL_ID_GPT": "gpt-5",
    "OLLAMA_URL": "http://localhost:11434/v1",
    "MODEL_ID_LOCAL": "gemma3:12b",
    "MODEL_ID_SUMMARY": "gemma3:4b",
    "DB_PROVIDER": "gemini",
    "DB_MODEL_ID": "gemini-2.0-flash",
    "search_switch": False,
    "API_CACHE_ENABLED": True,
    "API_CACHE_TTL_HOURS": 24,
    "TAVILY_COUNT": 3,
    "TAVILY_MONTH": 1,
    "MAX_CHARS": 700,
    "SPEAKER_NAME": "ずんだもん",
    "SPEAKER_ID": 3,
    "VOICE_SPEED": 1.2,
    "VV_PATH": "",
    "DEVICE_NAME": "デフォルト",
    "INPUT_DEVICE_NAME": "デフォルト",
    "VOICE_VOLUME": 0.7,
    "DISPLAY_TIME": 60,
    "LOG_FONT_SIZE": 13,
    "WINDOW_ALPHA": 0.6,
    "TODAY_CONTEXT": "",
    "TARGET_GAME_TITLE": "All Capture",
    "LANGUAGE": "ja",
    "USE_INTERSECTING_AI": False,
    "FILES": {
        "HISTORY": "data/chat_history.json",
        "CURRENT_TAGS": "data/current_tags.json",
        "FEEDBACK": "data/feedback_memory.json",
        "TEMP_SS": "data/temp_ss.png"
    },
    "HOTKEYS": {
        "voice_mode": "ctrl+alt+v",
        "vision_mode": "ctrl+alt+s",
        "stop_ai": "ctrl+alt+x"
    }
}

def migrate_config(config):
    """
    設定ファイルの自動マイグレーション
    古いバージョンの設定を最新バージョンに変換し、不足しているキーをデフォルト値で補完します。
    """
    old_version = config.get("CONFIG_VERSION", "1.0")
    migrated = False

    if old_version == "1.0":
        # v1.0 -> v2.0 への移行
        print(f"Migrating config: {old_version} -> 2.0")
        config["CONFIG_VERSION"] = "2.0"
        
        # 2.0で必須となるデフォルト値の確認（既にある場合は上書きしない）
        new_defaults_2_0 = {
            "API_CACHE_ENABLED": True,
            "API_CACHE_TTL_HOURS": 24,
            "search_switch": False,
            "DB_PROVIDER": config.get("AI_PROVIDER", "gemini"),
            "DB_MODEL_ID": config.get("MODEL_ID", "gemini-2.0-flash"),
            "USE_INTERSECTING_AI": False
        }
        for k, v in new_defaults_2_0.items():
            if k not in config:
                config[k] = v
        
        migrated = True

    # 常に最新のデフォルト値で不足しているキーを補完する
    for key, default_value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = default_value
            migrated = True
        elif isinstance(default_value, dict) and isinstance(config[key], dict):
            # 入れ子になった辞書の補完（FILESやHOTKEYSなど）
            for sub_key, sub_default in default_value.items():
                if sub_key not in config[key]:
                    config[key][sub_key] = sub_default
                    migrated = True

    # バージョン番号を最新に更新
    if config.get("CONFIG_VERSION") != CONFIG_VERSION:
        config["CONFIG_VERSION"] = CONFIG_VERSION
        migrated = True

    return config, migrated

def load_config(config_path):
    """設定ファイルを読み込み、マイグレーションを適用して返します。"""
    config = DEFAULT_CONFIG.copy()
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                config.update(user_config)
        except Exception as e:
            print(f"Config load error: {e}")

    # マイグレーションと不整合の補正
    config, migrated = migrate_config(config)
    
    # 必要に応じて保存（新規作成や構造変更時）
    if migrated or not os.path.exists(config_path):
        save_config(config_path, config)
        
    return config

def save_config(config_path, config):
    """設定ファイルを保存します。"""
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    try:
        # 保存前にバージョン情報を付与
        config["CONFIG_VERSION"] = CONFIG_VERSION
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Config save error: {e}")
        return False
