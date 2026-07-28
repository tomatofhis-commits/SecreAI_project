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

    def normalize_stt_text(self, text: str) -> str:
        """
        STT（音声認識）入力で発生する漢数字・英語/多言語数詞の表記揺れをアラビア数字にデコード・正規化
        """
        if not text:
            return ""
            
        normalized = text.lower()
        
        # 1. 漢数字 -> アラビア数字 変換辞書
        kanji_num_map = {
            "三十一": "31", "三十": "30", "二十九": "29", "二十八": "28", "二十七": "27", "二十六": "26", "二十五": "25",
            "二十四": "24", "二十三": "23", "二十二": "22", "二十一": "21", "二十": "20", "十九": "19", "十八": "18",
            "十七": "17", "十六": "16", "十五": "15", "十四": "14", "十三": "13", "十二": "12", "十一": "11", "十": "10",
            "九": "9", "八": "8", "七": "7", "六": "6", "五": "5", "四": "4", "三": "3", "二": "2", "一": "1", "零": "0"
        }
        for k, v in kanji_num_map.items():
            normalized = normalized.replace(k, v)
            
        # 2. 英語・多言語数詞/月名 -> アラビア数字 変換辞書
        multilingual_num_map = {
            "twenty eighth": "28", "twenty-eighth": "28", "twenty seventh": "27", "twenty-seventh": "27",
            "twenty sixth": "26", "twenty-sixth": "26", "twenty fifth": "25", "twenty-fifth": "25",
            "twenty fourth": "24", "twenty-fourth": "24", "twenty third": "23", "twenty-third": "23",
            "twenty second": "22", "twenty-second": "22", "twenty first": "21", "twenty-first": "21",
            "twentieth": "20", "nineteenth": "19", "eighteenth": "18", "seventeenth": "17", "sixteenth": "16",
            "fifteenth": "15", "fourteenth": "14", "thirteenth": "13", "twelfth": "12", "eleventh": "11",
            "tenth": "10", "ninth": "9", "eighth": "8", "seventh": "7", "sixth": "6", "fifth": "5",
            "fourth": "4", "third": "3", "second": "2", "first": "1",
            "january": "1月", "february": "2月", "march": "3月", "april": "4月", "may": "5月", "june": "6月",
            "july": "7月", "juli": "7月", "juillet": "7月", "julio": "7月", "julho": "7月", "luglio": "7月", "июля": "7月", "июль": "7月", "7월": "7月",
            "august": "8月", "september": "9月", "october": "10月", "november": "11月", "december": "12月",
            "sieben": "7", "sept": "7", "siete": "7", "sette": "7", "семь": "7",
            "acht": "8", "huit": "8", "ocho": "8", "oito": "8", "восемь": "8"
        }
        for k, v in multilingual_num_map.items():
            if re.search(r'[a-z]', k):
                normalized = re.sub(r'\b' + re.escape(k) + r'\b', v, normalized)
            else:
                normalized = normalized.replace(k, v)
            
        return normalized

    def parse_datetime_filter(self, text: str) -> dict:
        """
        STT正規化を行い、ユーザー入力から全10言語の日付・月名・口語（昨日/yesterday/gestern等）および時間帯を解析して抽出
        
        Returns:
            dict: {
                "date_str": "2026-07-28",     # YYYY-MM-DD 形式
                "short_date": "07-28",        # MM-DD 形式
                "start_hour": int,            # 0~23
                "end_hour": int               # 0~23
            }
        """
        if not text:
            return {"date_str": None, "short_date": None, "start_hour": None, "end_hour": None}
            
        from datetime import datetime, timedelta
        now = datetime.now()
        current_year = now.year
        
        # 0. STT入力テキストの表記揺れデコード
        clean_text = self.normalize_stt_text(text)
        
        date_str = None
        short_date = None
        start_hour = None
        end_hour = None

        # 1. 全10言語の相対日付（口語表現）判定
        # 昨日 (Yesterday)
        if re.search(r'(昨日|yesterday|gestern|hier|ayer|ontem|вчера|어제|昨天)', clean_text, re.IGNORECASE):
            target_dt = now - timedelta(days=1)
            date_str = target_dt.strftime("%Y-%m-%d")
            short_date = target_dt.strftime("%m-%d")
        # 一昨日 (Day before yesterday)
        elif re.search(r'(一昨日|day before yesterday|vorgestern|avant-hier|anteayer|anteontem|позавчера|그저께|前天)', clean_text, re.IGNORECASE):
            target_dt = now - timedelta(days=2)
            date_str = target_dt.strftime("%Y-%m-%d")
            short_date = target_dt.strftime("%m-%d")

        # 2. 明示的な日付パターンの解析（相対日付が指定されなかった場合）
        if not date_str:
            # 2-A. YYYY/MM/DD または YYYY-MM-DD
            m1 = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', clean_text)
            if m1:
                y, m, d = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
                date_str = f"{y:04d}-{m:02d}-{d:02d}"
                short_date = f"{m:02d}-{d:02d}"
            else:
                # 2-B. 欧州形式 (DD.MM.YYYY または DD.MM. / DD de M月 / DD M月 / DD. M月)
                m_eu = re.search(r'(\d{1,2})\s*(?:\.|\s*de\s*|\s+)?\s*(\d{1,2})\s*月', clean_text)
                if m_eu:
                    d, m = int(m_eu.group(1)), int(m_eu.group(2))
                    date_str = f"{current_year:04d}-{m:02d}-{d:02d}"
                    short_date = f"{m:02d}-{d:02d}"
                else:
                    m_eu2 = re.search(r'(\d{1,2})\.(\d{1,2})\.?(?:(\d{4}))?', clean_text)
                    if m_eu2:
                        d, m = int(m_eu2.group(1)), int(m_eu2.group(2))
                        y = int(m_eu2.group(3)) if m_eu2.group(3) else current_year
                        date_str = f"{y:04d}-{m:02d}-{d:02d}"
                        short_date = f"{m:02d}-{d:02d}"

                # 2-C. M月D日 / M/D / M-D
                if not date_str:
                    m2 = re.search(r'(\d{1,2})[/\-月]\s*(\d{1,2})日?', clean_text)
                    if m2:
                        m, d = int(m2.group(1)), int(m2.group(2))
                        date_str = f"{current_year:04d}-{m:02d}-{d:02d}"
                        short_date = f"{m:02d}-{d:02d}"

        # 3. 多言語時間・時間帯の解析
        # 午前 / 朝: 0~12時
        if re.search(r'\b(午前|朝|morning|morgen|matin|mañana|manhã|mattino|утро|아침|早晨|上午)\b', clean_text):
            start_hour, end_hour = 0, 12
        # 午後 / 昼: 12~17時
        elif re.search(r'\b(午後|昼|日中|afternoon|noon|nachmittag|après-midi|tarde|pomeriggio|день|낮|下午)\b', clean_text):
            start_hour, end_hour = 12, 17
        # 夕方 / 夜 / 夜間: 17~24時
        elif re.search(r'\b(夕方|夜|夜間|晩|evening|night|abend|soir|noche|noite|sera|вечер|ночь|저녁|밤|晚上)\b', clean_text):
            start_hour, end_hour = 17, 24

        # 明示的な「X時以降」「X o'clock」「X Uhr」
        m_after = re.search(r'(\d{1,2})\s*(?:時|o\'clock|uhr|h)\s*(以降|から|より|after|onwards)?', clean_text)
        if m_after and m_after.group(2):
            start_hour = int(m_after.group(1))
            end_hour = 24

        return {
            "date_str": date_str,
            "short_date": short_date,
            "start_hour": start_hour,
            "end_hour": end_hour
        }

    def extract_search_keywords(self, text: str) -> list:
        """
        ユーザー入力から検索に有用なキーワード（固有名詞・名詞相当の単語）を抽出
        （7/28 や 2026-07-28 などの日付表現を保護）
        """
        if not text:
            return []
        
        stop_words = {"これ", "それ", "あれ", "どれ", "私", "あなた", "僕", "俺", "今日", "昨日", "明日", "こと", "もの", "ため", "よう", "さん", "ちゃん", "くん", "様", "情報", "内容", "話", "件"}
        
        # 指示語（まとめて/要約等）を除去
        clean_input = re.sub(SUMMARY_INTENT_PATTERN, "", text)
        
        # 日付パターン（7/28, 7月28日等）をあらかじめ退避・抽出
        dates_found = re.findall(r'\d{1,4}[/\-月]\d{1,2}(?:[/\-日]\d{1,2})?日?', clean_input)
        
        # 漢字・カタカナ・ひらがな含む単語、英数字の連続語（2文字以上）を抽出
        tokens = re.findall(r'[一-龠ァ-ヶa-zA-Z0-9_]{2,}', clean_input)
        
        keywords = []
        for d in dates_found:
            keywords.append(d)
            
        for token in tokens:
            if token not in stop_words and len(token) >= 2 and not token.isdigit():
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
