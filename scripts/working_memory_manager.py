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
    プロンプトから名詞・固有名詞および実日付（相対日付からの変換含む）を抽出
    """
    if not text:
        return []
    import re
    from datetime import datetime

    keywords = []

    # 1. 日時解析（「今日」「昨日」「6月15日」などの実日付数値化・変換）
    date_res = parse_datetime_filter(text)
    if date_res.get("date_str"):
        d_str = date_res["date_str"]  # YYYY-MM-DD
        keywords.append(d_str)
        try:
            dt = datetime.strptime(d_str, "%Y-%m-%d")
            jp_date = f"{dt.month}月{dt.day}日"
            jp_full_date = f"{dt.year}年{dt.month}月{dt.day}日"
            keywords.append(jp_date)
            keywords.append(jp_full_date)
        except:
            pass

    # 2. 記号除去と名詞相当の単語抽出
    clean_t = re.sub(r'[^\w\s\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', ' ', text)
    tokens = [w.strip() for w in clean_t.split() if len(w.strip()) >= 2]
    # ストップワード（今日・昨日・一昨日は除去せず実日付化で対応するため除外）
    stopwords = {"まとめ", "要約", "教え", "くだ", "さい", "お願い", "について", "話", "こと", "これ", "それ", "あれ"}
    
    for t in tokens:
        if t not in stopwords and t not in keywords:
            keywords.append(t)
            
    return keywords[:8]

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
    （全旧メソッドおよびキーワード引数を完全互換サポート）
    """
    def __init__(self, max_context_chars: int = 3000, default_ttl: int = 3, **kwargs):
        self.max_context_chars = max_context_chars
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

    def update_web_search_slot(self, query: str, summary: str, ttl: int = None):
        """set_web_search_slot の完全互換エイリアス"""
        self.set_web_search_slot(query, summary, ttl)

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

    def filter_and_format_memory(self, candidate_list, query=""):
        """後方互換用: 重複排除およびフォーマット処理"""
        unique_list = deduplicate_logs(candidate_list)
        web_text = self.get_formatted_web_slot()
        res_parts = []
        if web_text:
            res_parts.append(web_text)
        if unique_list:
            res_parts.append("【過去の記憶・関連情報】:")
            for item in unique_list:
                doc = item.get("doc", "") if isinstance(item, dict) else str(item)
                ts = item.get("meta", {}).get("timestamp", "過去") if isinstance(item, dict) else "過去"
                res_parts.append(f"・[{ts}] {doc}")
        return "\n".join(res_parts)

    def clear(self):
        """スロットのクリア"""
        self.web_search_slot = None
        self.web_search_ttl = 0


# 後方互換性のためのエイリアス
WorkingMemoryManager = WebSearchContextManager
