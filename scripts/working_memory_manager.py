# -*- coding: utf-8 -*-
"""
working_memory_manager.py - Ver 1.3.2 ワーキングメモリ管理モジュール
SecreAI における会話キャッシュ、キーワード抽出、ネット検索スロット、およびプロンプト制限文字数（1500〜3000文字）制御を担う。
"""

import re
import os
import sys

# 全10言語の意図検知パターン（各言語の過去形・活用変化・口語・表記揺れを包括）
GLOBAL_SUMMARY_INTENT_PATTERN = r"(まとめ|要約|おさらい|振り返|どんな話|経緯|ダイジェスト|要点|整理|記録|リスト|一覧|かいくまんで|summariz|summary|recap|overview|digest|review|wrap up|what did we talk|main point|roundup|gist|brief|总结|摘要|概括|回顾|盘点|综述|梳理|之前聊了|刚才说了|提炼|简述|요약|정리|복습|되돌아|줄거리|개요|무슨 이야기|지금까지|resum|recopila|repas|puntos clave|síntes|de qué hablamos|compendio|résum|récap|grandes lignes|de quoi on a parlé|de quoi on a parl|zusammenfass|zusammengefass|überblick|überprüf|hauptpunkt|fazit|worüber haben wir|resümee|zusammen|итог|резюм|обобщ|кратко|главное|о чем|говор|конспект|выжимка|обзор|recapitul|pontos principais|visão geral|do que falamos|riassum|ricapitol|panoramica|di cosa abbiamo parlato|sommario)"
SUMMARY_INTENT_PATTERN = GLOBAL_SUMMARY_INTENT_PATTERN

class WorkingMemoryManager:
    def __init__(self, max_context_chars: int = 3000, default_ttl: int = 3):
        """
        ワーキングメモリ管理クラスの初期化
        
        Args:
            max_context_chars (int): プロンプトに組み込む記憶の最大文字数 (デフォルト: 3000文字)
            default_ttl (int): ネット検索結果の生存ターン数 (デフォルト: 3ターン)
        """
        self.max_context_chars = max_context_chars
        self.default_ttl = default_ttl
        
        # ネット検索結果スロット
        self.web_search_slot = None  # Dict: {"query": str, "summary": str}
        self.web_search_ttl = 0
        
        # 直前のコンテキスト記憶キャッシュ (重複排除用)
        self.recent_memory_hashes = set()

    def is_summary_request(self, text: str, custom_pattern: str = None) -> bool:
        """
        ユーザー入力が「まとめ・要約・振り返り」などの特定指示を含んでいるかを判定（全10言語対応）
        """
        if not text:
            return False
        
        pattern = custom_pattern if custom_pattern else GLOBAL_SUMMARY_INTENT_PATTERN
        return bool(re.search(pattern, text, re.IGNORECASE))

    def extract_search_keywords(self, text: str) -> list:
        """
        ユーザー入力から検索に有用なキーワード（固有名詞・名詞相当の単語）を抽出
        """
        if not text:
            return []
        
        # 不要な記号や助詞・指示語の簡易除外
        stop_words = {"これ", "それ", "あれ", "どれ", "私", "あなた", "僕", "俺", "今日", "昨日", "明日", "こと", "もの", "ため", "よう", "さん", "ちゃん", "くん", "様", "情報", "内容", "話", "件"}
        
        # 漢字・カタカナ・ひらがな含む単語、英数字の連続語（2文字以上）を抽出
        # 指示語（まとめて/要約等）を除去したテキストを作成
        clean_input = re.sub(SUMMARY_INTENT_PATTERN, "", text)
        
        tokens = re.findall(r'[一-龠ァ-ヶa-zA-Z0-9_]{2,}', clean_input)
        
        keywords = []
        for token in tokens:
            if token not in stop_words and len(token) >= 2:
                keywords.append(token)
        
        # 重複を保持順を保って排除
        seen = set()
        unique_keywords = []
        for k in keywords:
            if k not in seen:
                seen.add(k)
                unique_keywords.append(k)
                
        return unique_keywords

    def update_web_search_slot(self, query: str, summary: str, ttl: int = None):
        """
        ネット検索完了時にワーキングメモリのネット検索スロットを更新
        """
        if ttl is None:
            ttl = self.default_ttl
            
        self.web_search_slot = {
            "query": query,
            "summary": summary
        }
        self.web_search_ttl = ttl

    def decrement_ttl(self):
        """
        会話が1ターン経過するごとにネット検索スロットのTTLを1減らす
        """
        if self.web_search_ttl > 0:
            self.web_search_ttl -= 1
            if self.web_search_ttl == 0:
                self.web_search_slot = None

    def filter_and_format_memory(self, docs_with_meta: list, query: str) -> str:
        """
        ChromaDBから取得した候補群（上位30〜50件）から、
        キーワード一致優先度＋ベクトル類似度順で厳選し、最大文字数内に収めてプロンプト用にフォーマット。
        
        Args:
            docs_with_meta (list): [{'doc': str, 'meta': dict}, ...]
            query (str): ユーザー入力文
            
        Returns:
            str: プロンプト挿入用文字列
        """
        if not docs_with_meta:
            formatted_web = self.get_formatted_web_slot()
            return formatted_web

        keywords = self.extract_search_keywords(query)
        
        # スコアリング: キーワード一致数（重み強） + 元の取得順位スコア
        scored_items = []
        for idx, item in enumerate(docs_with_meta):
            doc_text = item.get("doc", "")
            meta = item.get("meta", {})
            
            keyword_score = 0
            for kw in keywords:
                if kw in doc_text:
                    keyword_score += 10  # キーワード直接ヒットに高い重み
            
            # 元の類似度上位ほど少しスコア加算
            order_score = max(0, 50 - idx)
            total_score = keyword_score + order_score
            
            scored_items.append((total_score, doc_text, meta))
            
        # スコア降順ソート
        scored_items.sort(key=lambda x: x[0], reverse=True)
        
        # 重複排除と文字数制限（max_context_chars）内での厳選
        selected_docs = []
        current_length = 0
        seen_texts = set()
        
        # ネット検索スロットがあれば優先的に文字数枠を確保
        web_text = self.get_formatted_web_slot()
        if web_text:
            current_length += len(web_text)

        for score, text, meta in scored_items:
            # 短すぎる/完全重複の除外
            clean_text = text.strip()
            if not clean_text or clean_text in seen_texts:
                continue
                
            # メタデータから日付情報取得
            date_val = meta.get("timestamp") or "過去"
            entry_str = f"・[{date_val}] {clean_text}\n"
            
            if current_length + len(entry_str) <= self.max_context_chars:
                selected_docs.append(entry_str)
                current_length += len(entry_str)
                seen_texts.add(clean_text)
            else:
                # 文字数上限に達した場合は打ち切り
                break
                
        # 最終プロンプトテキストの構築
        result_parts = []
        if web_text:
            result_parts.append(web_text)
            
        if selected_docs:
            result_parts.append("【過去の記憶・関連情報】:")
            result_parts.extend(selected_docs)
            
        return "\n".join(result_parts)

    def get_formatted_web_slot(self) -> str:
        """
        現在有効なネット検索スロットの情報をフォーマットして取得
        """
        if self.web_search_slot and self.web_search_ttl > 0:
            q = self.web_search_slot.get("query", "")
            s = self.web_search_slot.get("summary", "")
            return f"【直前のネット検索結果 (参照可能)】:\n検索ワード: {q}\n検索要約: {s}\n"
        return ""
