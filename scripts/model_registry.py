# -*- coding: utf-8 -*-
"""
scripts/model_registry.py - SecreAI モデルレジストリ一元管理モジュール

Gemini, OpenAI, ローカルLLM(Ollama/LM Studio)のモデルメタデータ、
思考レベル(Thinking Budget)対応判定、パース、および移行ルールを一元管理します。
"""

import re
from typing import Tuple, Optional, List, Dict, Any

# ==============================================================================
# 1. モデル定義とメタデータ
# ==============================================================================

# デフォルトモデル設定
DEFAULT_MODELS = {
    "gemini": {
        "normal": "gemini-3.7-flash",
        "pro": "gemini-3.7-flash（中）",
        "db": "gemini-3.7-flash（中）",
    },
    "openai": {
        "normal": "gpt-5.4-mini",
        "pro": "gpt-5.6-sol",
        "db": "gpt-5.4-mini",
    },
    "local": {
        "normal": "gemma3:12b",
        "summary": "gemma3:4b",
        "db": "gemma3:4b",
    }
}

# UI用モデル選択肢リスト
GEMINI_NORMAL_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.1-pro-preview"
]

GEMINI_PRO_MODELS = [
    "gemini-3-flash-preview",
    "gemini-3.6-flash（中）",
    "gemini-3.6-flash（高）",
    "gemini-3.7-flash（中）",
    "gemini-3.7-flash（高）",
    "gemini-3.1-pro-preview"
]

GEMINI_DB_MODELS = [
    "gemini-3.7-flash（高）",
    "gemini-3.7-flash（中）",
    "gemini-3.7-flash（低）",
    "gemini-3.7-flash（最小）",
    "gemini-3.6-flash（高）",
    "gemini-3.6-flash（中）",
    "gemini-3.6-flash（低）",
    "gemini-3.6-flash（最小）",
    "gemini-3.5-flash-lite（高）",
    "gemini-3.5-flash-lite（中）",
    "gemini-3.1-flash-lite（高）",
    "gemini-3.1-flash-lite（中）",
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview"
]

OPENAI_MODELS = [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.4-mini",
    "gpt-5.4-nano"
]

# 思考レベル（Thinking Budget）をサポートするGeminiモデルID群
THINKING_SUPPORTED_MODELS = {
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.1-flash-lite-preview"
}

# 思考レベルの日本語・英語マッピング
THINKING_LEVEL_MAP = {
    "最小": "minimal",
    "minimal": "minimal",
    "低": "low",
    "low": "low",
    "中": "medium",
    "medium": "medium",
    "高": "high",
    "high": "high"
}

# ==============================================================================
# 2. モデルマイグレーション置換マッピング
# ==============================================================================

# 旧世代・廃止モデルの自動移行ルール
MODEL_RENAME_MAP = {
    # OpenAI
    "gpt-5-mini": "gpt-5.4-mini",
    "gpt-5.2": "gpt-5.4",
    "gpt-4o": "gpt-5.4",
    "gpt-4o-mini": "gpt-5.4-mini",
    "gpt-5.5-2026-04-23": "gpt-5.5",
    "o3-mini（低）": "gpt-5.4-mini",
    "o3-mini（中）": "gpt-5.4-mini",
    "o3-mini（高）": "gpt-5.4-mini",
    "o1（低）": "gpt-5.6-sol",
    "o1（中）": "gpt-5.6-sol",
    "o1（高）": "gpt-5.6-sol",
    # Gemini
    "gemini-2.0-flash": "gemini-3.7-flash",
    "gemini-2.5-flash-lite": "gemini-3.7-flash",
    "gemini-2.5-flash": "gemini-3.7-flash",
    "gemini-3.5-flash": "gemini-3.7-flash",
    "gemini-2.0-flash-thinking-exp": "gemini-3.7-flash（中）",
    "gemini-3.5-flash（中）": "gemini-3.7-flash（中）",
    "gemini-3.5-flash（高）": "gemini-3.7-flash（中）",
    "gemini-3.5-flash（低）": "gemini-3.7-flash（中）",
    "gemini-3.5-flash（最小）": "gemini-3.7-flash（中）",
}

# ==============================================================================
# 3. ユーティリティ関数（一元化API）
# ==============================================================================

def parse_model_name(model_name: str) -> Tuple[str, Optional[str]]:
    """
    モデル名から実モデル名と指定された思考レベル（またはreasoning_effort）をパースする。
    例:
      'gemini-3.7-flash（中）' -> ('gemini-3.7-flash', 'medium')
      'o3-mini（低）' -> ('o3-mini', 'low')
      'gemini-3.7-flash' -> ('gemini-3.7-flash', None)
    """
    if not model_name:
        return "", None

    # 全角・半角カッコの両方に対応
    m = re.match(r"^([a-zA-Z0-9\.\-_:]+)[（\‍(]([^）\‍)]+)[）\‍)]$", str(model_name).strip())
    if m:
        actual_name = m.group(1).strip()
        level_str = m.group(2).strip()
        level = THINKING_LEVEL_MAP.get(level_str, None)
        return actual_name, level

    return str(model_name).strip(), None


def supports_thinking(model_name: str) -> bool:
    """
    指定されたモデル名（または実モデルID）が思考レベル制御（Thinking Budget）に対応しているかを判定する。
    """
    if not model_name:
        return False
    actual_name, _ = parse_model_name(model_name)
    return actual_name in THINKING_SUPPORTED_MODELS


def migrate_model_name(model_name: str) -> Tuple[str, bool]:
    """
    指定されたモデル名が古い世代の場合、最新の推奨モデルに置換する。
    Returns:
      (置換後モデル名, 置換が発生したかどうかのbool)
    """
    if not model_name:
        return model_name, False

    clean_name = str(model_name).strip()
    if clean_name in MODEL_RENAME_MAP:
        return MODEL_RENAME_MAP[clean_name], True

    # DB_MODEL_ID や MODEL_ID_PRO で 2.x 系列などが指定されている場合の包括的フォールバック
    if any(clean_name.startswith(prefix) for prefix in ("gemini-2.0", "gemini-2.5")):
        return "gemini-3.7-flash", True

    return clean_name, False
