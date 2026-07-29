# ===== 全10言語対応 高度日時・期間・イベントパース専用モジュール =====
# [Ver 1.3.2]

import re
from datetime import datetime, timedelta

class MultilingualDateParser:
    """
    STT音声表記揺れ吸収、全10言語の日時・相対口語・複数日期間・月/年・季節・世界10か国大型連休を解析する統合モジュール
    """
    
    def __init__(self):
        # 1. 漢数字 -> アラビア数字 変換辞書
        self.kanji_num_map = {
            "三十一": "31", "三十": "30", "二十九": "29", "二十八": "28", "二十七": "27", "二十六": "26", "二十五": "25",
            "二十四": "24", "二十三": "23", "二十二": "22", "二十一": "21", "二十": "20", "十九": "19", "十八": "18",
            "十七": "17", "十六": "16", "十五": "15", "十四": "14", "十三": "13", "十二": "12", "十一": "11", "十": "10",
            "九": "9", "八": "8", "七": "7", "六": "6", "五": "5", "四": "4", "三": "3", "二": "2", "一": "1", "零": "0"
        }
        
        # 2. 英語・多言語数詞/月名 -> アラビア数字 変換辞書
        self.multilingual_num_map = {
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

    def normalize_stt_text(self, text: str) -> str:
        """STT（音声認識）入力で発生する漢数字・多言語数詞の表記揺れをアラビア数字へ変換"""
        if not text:
            return ""
        normalized = text.lower()
        for k, v in self.kanji_num_map.items():
            normalized = normalized.replace(k, v)
        for k, v in self.multilingual_num_map.items():
            if re.search(r'[a-z]', k):
                normalized = re.sub(r'\b' + re.escape(k) + r'\b', v, normalized)
            else:
                normalized = normalized.replace(k, v)
        return normalized

    def parse(self, text: str) -> dict:
        """
        ユーザー入力テキストを全10言語対応で解析し、単一日付、日付範囲（期間）、時間帯を抽出
        
        Returns:
            dict: {
                "date_str": str or None,    # 単一日 (YYYY-MM-DD)
                "short_date": str or None,   # MM-DD
                "start_date": str or None,  # 期間範囲の開始 (YYYY-MM-DD)
                "end_date": str or None,    # 期間範囲の終了 (YYYY-MM-DD)
                "is_range": bool,           # 範囲指定フラグ
                "start_hour": int or None,  # 0~23
                "end_hour": int or None     # 0~23
            }
        """
        if not text:
            return {
                "date_str": None, "short_date": None,
                "start_date": None, "end_date": None, "is_range": False,
                "start_hour": None, "end_hour": None
            }
            
        now = datetime.now()
        current_year = now.year
        clean_text = self.normalize_stt_text(text)
        
        date_str = None
        short_date = None
        start_date = None
        end_date = None
        is_range = False
        start_hour = None
        end_hour = None

        # ----------------------------------------------------
        # A. 世界10か国 大型連休・イベント判定
        # ----------------------------------------------------
        # 1. 日本: GW / ゴールデンウィーク (4/29 - 5/5)
        if re.search(r'(gw|ゴールデンウィーク|golden week)', clean_text, re.IGNORECASE):
            start_date = f"{current_year:04d}-04-29"
            end_date = f"{current_year:04d}-05-05"
            is_range = True
        # 2. 日本: お盆 (8/13 - 8/16)
        elif re.search(r'(お盆|obon)', clean_text, re.IGNORECASE):
            start_date = f"{current_year:04d}-08-13"
            end_date = f"{current_year:04d}-08-16"
            is_range = True
        # 3. 日本/世界: 年末年始 / お正月 / Holiday Season (12/28 - 1/3)
        elif re.search(r'(年末年始|お正月|新春|holiday season|holiday break)', clean_text, re.IGNORECASE):
            start_date = f"{current_year:04d}-12-28"
            end_date = f"{current_year:04d}-01-03"
            is_range = True
        # 4. 中国: 春節 / 旧正月 / 春节 (1/20 - 2/10頃)
        elif re.search(r'(春节|春節|旧正月|lunar new year|chinese new year)', clean_text, re.IGNORECASE):
            start_date = f"{current_year:04d}-01-20"
            end_date = f"{current_year:04d}-02-10"
            is_range = True
        # 5. 中国: 国慶節 / 十一 (10/1 - 10/7)
        elif re.search(r'(国庆|國慶|十一黄金周|national day holiday)', clean_text, re.IGNORECASE):
            start_date = f"{current_year:04d}-10-01"
            end_date = f"{current_year:04d}-10-07"
            is_range = True
        # 6. 韓国: チュソク / 추석 (8/20 - 9/25頃)
        elif re.search(r'(추석|秋夕|チュソク|chuseok)', clean_text, re.IGNORECASE):
            start_date = f"{current_year:04d}-08-20"
            end_date = f"{current_year:04d}-09-25"
            is_range = True
        # 7. 英語/欧州: Thanksgiving (11/20 - 11/30頃)
        elif re.search(r'(thanksgiving|サンクスギビング|感謝祭)', clean_text, re.IGNORECASE):
            start_date = f"{current_year:04d}-11-20"
            end_date = f"{current_year:04d}-11-30"
            is_range = True
        # 8. 欧州: イースター / Ostern / Pâques (3/20 - 4/25頃)
        elif re.search(r'(easter|ostern|pâques|paques|semana santa)', clean_text, re.IGNORECASE):
            start_date = f"{current_year:04d}-03-20"
            end_date = f"{current_year:04d}-04-25"
            is_range = True
        # 9. ロシア: マイ連休 / Майские (5/1 - 5/9)
        elif re.search(r'(майские|майские праздники)', clean_text, re.IGNORECASE):
            start_date = f"{current_year:04d}-05-01"
            end_date = f"{current_year:04d}-05-09"
            is_range = True

        # ----------------------------------------------------
        # B. 長期間・月/年・季節の範囲判定 (未判定時)
        # ----------------------------------------------------
        if not is_range:
            # 1. 先月 (Last Month)
            if re.search(r'(先月|last month|letzten monat|le mois dernier|el mes pasado|mês passado|прошлом месяце|지난달|上个月)', clean_text, re.IGNORECASE):
                first_of_this_month = now.replace(day=1)
                last_day_prev_month = first_of_this_month - timedelta(days=1)
                first_day_prev_month = last_day_prev_month.replace(day=1)
                start_date = first_day_prev_month.strftime("%Y-%m-%d")
                end_date = last_day_prev_month.strftime("%Y-%m-%d")
                is_range = True
            # 2. 今月 (This Month)
            elif re.search(r'(今月|this month|diesen monat|ce mois-ci|este mes|este mês|в этом месяце|이번 달|这个月)', clean_text, re.IGNORECASE):
                first_day = now.replace(day=1)
                start_date = first_day.strftime("%Y-%m-%d")
                end_date = now.strftime("%Y-%m-%d")
                is_range = True
            # 3. 今年 (This Year)
            elif re.search(r'(今年|this year|dieses jahr|cette année|este año|в этом году|올해)', clean_text, re.IGNORECASE):
                start_date = f"{current_year:04d}-01-01"
                end_date = now.strftime("%Y-%m-%d")
                is_range = True
            # 4. 過去1年間 / 直近1年 (Past 1 Year) - DB最大保管期間1年対応
            elif re.search(r'(過去1年|直近1年|past year|last 365 days|letztes jahr|l\'année dernière|último año|지난 1년|过去一年)', clean_text, re.IGNORECASE):
                start_date = (now - timedelta(days=365)).strftime("%Y-%m-%d")
                end_date = now.strftime("%Y-%m-%d")
                is_range = True
            # 5. 今年の夏 (This Summer)
            elif re.search(r'(夏|summer|sommer|été|verano|verão|лето|여름)', clean_text, re.IGNORECASE):
                start_date = f"{current_year:04d}-06-01"
                end_date = f"{current_year:04d}-08-31"
                is_range = True

        # ----------------------------------------------------
        # C. 複数日・数日間・週末の範囲判定 (未判定時)
        # ----------------------------------------------------
        if not is_range:
            # 1. この一週間 / 過去7日間 / 先週
            if re.search(r'(この一週間|この1週間|過去7日|直近7日|直近1週間|先週|past week|last 7 days|last week|letzte woche|dernière semaine|la semana pasada|지난주|지난 일주일|这周|最近一周)', clean_text, re.IGNORECASE):
                start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
                end_date = now.strftime("%Y-%m-%d")
                is_range = True
            # 2. この3日間 / 直近3日
            elif re.search(r'(この3日|直近3日|過去3日|last 3 days|past 3 days|letzten 3 tage|derniers 3 jours|últimos 3 días|최근 3일)', clean_text, re.IGNORECASE):
                start_date = (now - timedelta(days=3)).strftime("%Y-%m-%d")
                end_date = now.strftime("%Y-%m-%d")
                is_range = True
            # 3. 先週末 / 直近の週末
            elif re.search(r'(先週末|この前の週末|last weekend|letztes wochenende|dernière fin de semaine)', clean_text, re.IGNORECASE):
                offset = (now.weekday() - 5) % 7
                last_sat = now - timedelta(days=offset + 7 if offset < 0 else offset)
                last_sun = last_sat + timedelta(days=1)
                start_date = last_sat.strftime("%Y-%m-%d")
                end_date = last_sun.strftime("%Y-%m-%d")
                is_range = True

        # ----------------------------------------------------
        # D. 単一日付 ＆ 相対口語判定 (範囲指定がなかった場合)
        # ----------------------------------------------------
        if not is_range:
            # 1. 昨日 (Yesterday)
            if re.search(r'(昨日|yesterday|gestern|hier|ayer|ontem|вчера|어제|批判|昨日)', clean_text, re.IGNORECASE):
                target_dt = now - timedelta(days=1)
                date_str = target_dt.strftime("%Y-%m-%d")
                short_date = target_dt.strftime("%m-%d")
            # 2. 一昨日 (Day before yesterday)
            elif re.search(r'(一昨日|day before yesterday|vorgestern|avant-hier|anteayer|anteontem|позавчера|그저께|前天)', clean_text, re.IGNORECASE):
                target_dt = now - timedelta(days=2)
                date_str = target_dt.strftime("%Y-%m-%d")
                short_date = target_dt.strftime("%m-%d")
            # 3. 明示的な日付パターンの解析
            else:
                # 3-A. YYYY/MM/DD または YYYY-MM-DD
                m1 = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', clean_text)
                if m1:
                    y, m, d = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
                    date_str = f"{y:04d}-{m:02d}-{d:02d}"
                    short_date = f"{m:02d}-{d:02d}"
                else:
                    # 3-B. 欧州形式 (DD.MM.YYYY または DD.MM. / DD de M月 / DD M月)
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

                    # 3-C. M月D日 / M/D / M-D
                    if not date_str:
                        m2 = re.search(r'(\d{1,2})[/\-月]\s*(\d{1,2})日?', clean_text)
                        if m2:
                            m, d = int(m2.group(1)), int(m2.group(2))
                            date_str = f"{current_year:04d}-{m:02d}-{d:02d}"
                            short_date = f"{m:02d}-{d:02d}"

        # ----------------------------------------------------
        # E. 多言語時間・時間帯の解析
        # ----------------------------------------------------
        if re.search(r'(午前|朝|morning|morgen|matin|mañana|manhã|mattino|утро|아침|早晨|上午)', clean_text, re.IGNORECASE):
            start_hour, end_hour = 0, 12
        elif re.search(r'(午後|昼|日中|afternoon|noon|nachmittag|après-midi|tarde|pomeriggio|день|낮|下午)', clean_text, re.IGNORECASE):
            start_hour, end_hour = 12, 17
        elif re.search(r'(夕方|夜|夜間|晩|evening|night|abend|soir|noche|noite|sera|вечер|ночь|저녁|밤|晚上)', clean_text, re.IGNORECASE):
            start_hour, end_hour = 17, 24

        m_after = re.search(r'(\d{1,2})\s*(?:時|o\'clock|uhr|h)\s*(以降|から|より|after|onwards)?', clean_text, re.IGNORECASE)
        if m_after and m_after.group(2):
            start_hour = int(m_after.group(1))
            end_hour = 24

        return {
            "date_str": date_str,
            "short_date": short_date,
            "start_date": start_date,
            "end_date": end_date,
            "is_range": is_range,
            "start_hour": start_hour,
            "end_hour": end_hour
        }
