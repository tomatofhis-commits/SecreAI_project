# -*- coding: utf-8 -*-
"""
working_memory_manager.py - Ver 1.3.2 ハイブリッド最適化モジュール
ステートレスなユーティリティ関数（意図判定・日時パース・重複排除・キーワード抽出）と、
最小限の状態保持クラス（ネット検索結果の3ターンTTL管理）を提供する。
"""

import re
import os
import sys

# 全10言語の意図検知パターン（各言語の過去形・活用変化・口語・表記揺れを包括）
GLOBAL_SUMMARY_INTENT_PATTERN = r"(まとめ|要約|おさらい|振り返|どんな話|経緯|ダイジェスト|要点|整理|記録|リスト|一覧|かいくまんで|summariz|summary|recap|overview|digest|review|wrap up|what did we talk|main point|roundup|gist|brief|总结|摘要|概括|回顾|盘点|综述|梳理|之前聊了|刚才说了|提炼|简述|요약|정리|복습|되돌아|줄거리|개요|무슨 이야기|지금까지|resum|recopila|repas|puntos clave|síntes|de qué hablamos|compendio|résum|récap|grandes lignes|de quoi on a parlé|de quoi on a parl|zusammenfass|zusammengefass|überblick|überprüf|hauptpunkt|fazit|worüber haben wir|resümee|zusammen|итог|резюм|обобщ|кратко|главное|о чем|говор|конспект|выжимка|обзор|recapitul|pontos principais|visão geral|do que falamos|riassum|ricapitol|panoramica|di cosa abbiamo parlato|sommario)"

# ----------------------------------------------------------------------
# ⚡ 1. 軽量・ステートレス純粋関数 (Stateless Pure Functions)
# ----------------------------------------------------------------------

def is_summary_request(text: str, custom_pattern: str = None) -> bool:
    """
    ユーザー入力が「まとめ・要約・振り返り」などの特定指示を含んでいるかを判定（全10言語対応）
    """
    if not text:
        return False
    pattern = custom_pattern if custom_pattern else GLOBAL_SUMMARY_INTENT_PATTERN
    return bool(re.search(pattern, text, re.IGNORECASE))

def normalize_stt_text(text: str) -> str:
    """STT（音声認識）入力の表記揺れデコード（MultilingualDateParserヘ委譲）"""
    try:
        from .multilingual_date_parser import MultilingualDateParser
    except ImportError:
        from multilingual_date_parser import MultilingualDateParser
    return MultilingualDateParser().normalize_stt_text(text)

def parse_datetime_filter(text: str) -> dict:
    """全10言語対応の日時・期間・イベントパース（MultilingualDateParserヘ委譲）"""
    try:
        from .multilingual_date_parser import MultilingualDateParser
    except ImportError:
        from multilingual_date_parser import MultilingualDateParser
    return MultilingualDateParser().parse(text)

def extract_search_keywords(text: str) -> list:
    """
    プロンプトから名詞・固有名詞などの検索キーとなる重要な単語を抽出
    """
    if not text:
        return []
    import re
    # 記号除去と名詞相当の単語抽出
    clean_t = re.sub(r'[^\w\s\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', ' ', text)
    tokens = [w.strip() for w in clean_t.split() if len(w.strip()) >= 2]
    # ストップワード
    stopwords = {"まとめ", "要約", "教え", "くだ", "さい", "お願い", "について", "話", "こと", "これ", "それ", "あれ", "昨日", "今日"}
    return [t for t in tokens if t not in stopwords][:5]

def deduplicate_logs(logs: list) -> list:
    """
    抽出ログの高速重複排除（O(1) ハッシュ判定）
    """
    if not logs:
        return []
    seen = set()
    unique_logs = []
    for item in logs:
        text = item.get("doc", "").strip() if isinstance(item, dict) else str(item).strip()
        if text and text not in seen:
            seen.add(text)
            unique_logs.append(item)
    return unique_logs


# ----------------------------------------------------------------------
# 🧱 2. 最小限の状態保持クラス (Minimal Stateful Class)
# ----------------------------------------------------------------------

class WebSearchContextManager:
    """
    直前ネット検索結果の保持 ＆ 3ターン自動消去 (TTLカウントダウン) を担当する最小クラス
    """
    def __init__(self, default_ttl: int = 3):
        self.default_ttl = default_ttl
        self.web_search_slot = None  # Dict: {"query": str, "summary": str}
        self.web_search_ttl = 0

    def is_summary_request(self, text: str, custom_pattern: str = None) -> bool:
        return is_summary_request(text, custom_pattern)

    def parse_datetime_filter(self, text: str) -> dict:
        return parse_datetime_filter(text)

    def extract_search_keywords(self, text: str) -> list:
        return extract_search_keywords(text)

    def set_web_search_slot(self, query: str, summary: str, ttl: int = None):
        """ネット検索結果をスロットに保持しTTLを初期化"""
        self.web_search_slot = {"query": query, "summary": summary}
        self.web_search_ttl = ttl if ttl is not None else self.default_ttl

    def decrement_ttl(self):
        """会話ターン経過に伴いTTLをデクリメント"""
        if self.web_search_ttl > 0:
            self.web_search_ttl -= 1
            if self.web_search_ttl == 0:
                self.web_search_slot = None

    def get_formatted_web_slot(self) -> str:
        """有効なネット検索スロットのフォーマット文字列を取得"""
        if self.web_search_slot and self.web_search_ttl > 0:
            q = self.web_search_slot.get("query", "")
            s = self.web_search_slot.get("summary", "")
            return f"【直前のネット検索結果 (参照可能)】:\n検索ワード: {q}\n検索要約: {s}\n"
        return ""

    def clear(self):
        """スロットのクリア"""
        self.web_search_slot = None
        self.web_search_ttl = 0


# 後方互換性のためのエイリアス
WorkingMemoryManager = WebSearchContextManager
