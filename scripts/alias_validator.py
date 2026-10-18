"""
alias_validator.py - 多言語対応 固有名詞エイリアス学習バリデータ (Ver 1.3.9 改訂版)

data/lang でサポートされる10言語 (de, en, es, fr, it, ja, ko, pt, ru, zh-CN) に対応。
多層防御（Defense in Depth）設計：
  【第1防壁】明らかな間違い（文章・質問文・日常会話）の高速排除
             （※固有名詞内の連結記号「、」「,」「・」「:」「-」は保護）
  【第2防壁】10言語対応 音韻・発音（Phonetic）照合
             ・日本語 (ja): 漢字音訓展開 ＋ カナ・ローマ字音韻照合（ウギン＝右舷、ヨーテボリ＝両手掘り 等の当て字に対応）
             ・ラテン圏 (en, de, fr, es, pt, it): 簡易Metaphone/Soundex音韻コード照合
             ・韓国語 (ko): ハングルUnicode数式分解（初声・中声・終声）照合
             ・中国語 (zh-CN): 漢字・ピンイン照合
             ・ロシア語 (ru): キリル文字正規化照合
"""

import os
import re
import json
import unicodedata
import logging
from typing import Tuple, Dict, Set, List, Optional

logger = logging.getLogger("AliasValidator")

# 10言語対応の学習指示プロンプト（最小限のトークン数で厳格化）
PROMPT_LEARN_ALIAS: Dict[str, str] = {
    "ja": (
        "\n【固有名詞学習】画面上の固有名詞を言おうとして音声誤認識されたと判断できる場合のみ、"
        "回答末尾に `[LEARN_ALIAS: 正式名称 = 誤認識単語]` を出力してください（推測や無関係な単語は出力厳禁）。\n"
    ),
    "en": (
        "\n[Proper Noun Learning] Output `[LEARN_ALIAS: Canonical = Misrecognized]` at the end "
        "ONLY when confident of a speech error matching a proper noun on screen (Do NOT guess or add unrelated words).\n"
    ),
    "zh-CN": (
        "\n【专有名词学习】仅在确信语音输入因口误/识别错误对应画面上的专有名词时，"
        "在回复末尾输出 `[LEARN_ALIAS: 正式名称 = 错误词]`（严禁猜测或添加无关词汇）。\n"
    ),
    "ko": (
        "\n【고유명사 학습】화면의 고유명사를 말하려다 음성 오인식이 발생한 것이 확실한 경우에만, "
        "답변 끝에 `[LEARN_ALIAS: 정식명칭 = 오인식단어]`를 출력하세요(추측이나 무관한 단어 출력 엄금).\n"
    ),
    "de": (
        "\n[Eigennamen-Lernen] Geben Sie am Ende `[LEARN_ALIAS: Name = Fehlwort]` NUR DANN aus, "
        "wenn ein klarer Sprachfehler für einen Namen auf dem Bildschirm vorliegt (Kein Raten, keine Fremdwörter).\n"
    ),
    "fr": (
        "\n[Apprentissage noms propres] Écrivez `[LEARN_ALIAS: Nom = Erreur]` à la fin "
        "UNIQUEMENT en cas d'erreur vocale évidente pour un mot à l'écran (Interdit de deviner des mots sans rapport).\n"
    ),
    "es": (
        "\n[Aprendizaje de nombres] Escriba `[LEARN_ALIAS: Nombre = Error]` al final "
        "SOLO si hay un claro error de voz respecto a una palabra en pantalla (Prohibido adivinar palabras no relacionadas).\n"
    ),
    "pt": (
        "\n[Aprendizado de nomes] Escreva `[LEARN_ALIAS: Nome = Erro]` ao final "
        "APENAS quando tiver certeza de erro de voz referente a palavra na tela (Proibido adivinhar palavras aleatórias).\n"
    ),
    "it": (
        "\n[Apprendimento nomi] Scrivi `[LEARN_ALIAS: Nome = Errore]` alla fine "
        "SOLO in caso di evidente errore vocale per un nome sullo schermo (Vietato indovinare parole non correlate).\n"
    ),
    "ru": (
        "\n[Изучение имен собственных] Выводите `[LEARN_ALIAS: Имя = Ошибка]` в конце "
        "ТОЛЬКО при явной ошибке распознавания имени с экрана (Запрещено угадывать несвязанные слова).\n"
    ),
}

# 10言語対応のストップワード（助詞・前置詞・冠詞・日常挨拶・相槌）
STOPWORDS_BY_LANG: Dict[str, Set[str]] = {
    "ja": {
        "はい", "いいえ", "うん", "ええ", "こんにちは", "ありがとう", "ありがとうございます",
        "おはよう", "こんばんは", "さようなら", "お願いします", "これ", "それ", "あれ", "どれ",
        "なん", "なに", "何", "どう", "どこ", "いつ", "だれ", "誰", "について", "ですが",
        "ですか", "ます", "です", "でした", "ました", "こと", "もの", "よう", "そう", "もう",
        "また", "ただ", "でも", "しかし", "そして", "から", "まで", "より", "ほど"
    },
    "en": {
        "the", "a", "an", "is", "are", "was", "were", "to", "in", "on", "at", "for", "with",
        "about", "against", "between", "into", "through", "during", "before", "after", "above",
        "below", "from", "up", "down", "out", "off", "over", "under", "again", "further",
        "then", "once", "here", "there", "when", "where", "why", "how", "all", "any", "both",
        "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only",
        "own", "same", "so", "than", "too", "very", "can", "will", "just", "don", "should",
        "now", "hello", "hi", "hey", "yes", "yeah", "nope", "thanks", "thank", "you", "please",
        "ok", "okay", "what", "which", "who", "whom", "this", "that", "these", "those"
    },
    "zh-CN": {
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
        "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
        "自己", "这", "那", "什么", "怎么", "哪里", "哪个", "你好", "谢谢", "再见", "对",
        "不对", "可以", "不行", "请问", "好的", "没问题"
    },
    "ko": {
        "이", "그", "저", "것", "수", "등", "들", "및", "에서", "그리고", "하지만", "안녕",
        "안녕하세요", "네", "예", "아니오", "아니요", "감사합니다", "고마워", "고맙습니다",
        "무엇", "어디", "언제", "누구", "어떻게", "왜", "이것", "그것", "저것", "있다", "없다"
    },
    "de": {
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "eines", "einem",
        "einen", "und", "ist", "in", "zu", "mit", "von", "hallo", "danke", "bitte",
        "ja", "nein", "gut", "was", "wer", "wo", "wann", "wie", "warum", "nicht", "auch",
        "es", "sie", "er", "wir", "ihr", "ich", "du"
    },
    "fr": {
        "le", "la", "les", "un", "une", "des", "du", "de", "et", "est", "dans", "en", "pour",
        "avec", "sur", "bonjour", "merci", "oui", "non", "quoi", "qui", "où", "quand",
        "comment", "pourquoi", "pas", "plus", "ce", "cette", "ces", "je", "tu", "il", "elle"
    },
    "es": {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "en", "y", "es", "por",
        "para", "con", "hola", "gracias", "si", "no", "que", "qué", "quién", "dónde", "cuándo",
        "cómo", "por qué", "pero", "este", "esta", "estos", "estas", "yo", "tú", "él", "ella"
    },
    "pt": {
        "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "em", "e", "é", "por", "para",
        "com", "olá", "obrigado", "obrigada", "sim", "não", "que", "quem", "onde", "quando",
        "como", "por que", "mas", "este", "esta", "estes", "estas", "eu", "você", "ele", "ela"
    },
    "it": {
        "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "a", "da", "in", "con",
        "su", "per", "tra", "fra", "ciao", "grazie", "si", "sì", "no", "cosa", "chi", "dove",
        "quando", "come", "perché", "questo", "questa", "questi", "queste", "io", "tu", "lui", "lei"
    },
    "ru": {
        "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все",
        "она", "так", "его", "но", "да", "нет", "привет", "спасибо", "пожалуйста", "где",
        "когда", "кто", "почему", "это", "этот", "эта", "эти", "был", "быть"
    },
}

# 10言語の質問フレーズ・疑問表現（文章排除用）
QUESTION_PATTERNS_BY_LANG: Dict[str, List[re.Pattern]] = {
    "ja": [
        re.compile(r'(何|なに|どう|どこ|いつ|誰|だれ|どれ|なぜ|どうやって|教えて|強い|使える|とは|って何|ですか|ますか)'),
    ],
    "en": [
        re.compile(r'\b(what|how|why|where|when|who|which|can i|tell me|is this|are there)\b', re.IGNORECASE),
    ],
    "zh-CN": [
        re.compile(r'(什么|怎么|哪里|哪个|为什么|请问|如何|是不是)'),
    ],
    "ko": [
        re.compile(r'(무엇|어떻게|어디|언제|누구|왜|인가요|있나요|알려줘)'),
    ],
    "de": [
        re.compile(r'\b(was|wie|wo|wann|warum|wer|welche|kann ich)\b', re.IGNORECASE),
    ],
    "fr": [
        re.compile(r'\b(quoi|comment|où|quand|pourquoi|qui|quel|est-ce)\b', re.IGNORECASE),
    ],
    "es": [
        re.compile(r'\b(qué|cómo|dónde|cuándo|por qué|quién|cuál)\b', re.IGNORECASE),
    ],
    "pt": [
        re.compile(r'\b(que|como|onde|quando|por que|quem|qual)\b', re.IGNORECASE),
    ],
    "it": [
        re.compile(r'\b(cosa|come|dove|quando|perché|chi|quale)\b', re.IGNORECASE),
    ],
    "ru": [
        re.compile(r'\b(что|как|где|когда|почему|кто|какой)\b', re.IGNORECASE),
    ],
}

# 文末記号（明らかな文章の判定）
RE_END_OF_SENTENCE = re.compile(r'[\.\?\!。？！\n\r\t]$')
RE_URL_PATTERN = re.compile(r'https?://|www\.')
# 日本語助詞の連続や文節パターン
RE_JA_PARTICLES = re.compile(r'(について|から|まで|より|へ|を|に|で|が|は|と|も|の|や)$')

# 漢字音訓辞書キャッシュ
_KANJI_READINGS: Optional[Dict[str, List[str]]] = None


def _load_kanji_readings() -> Dict[str, List[str]]:
    """常用・ゲーム漢字の音訓読みデータをロード"""
    global _KANJI_READINGS
    if _KANJI_READINGS is not None:
        return _KANJI_READINGS
    
    # パス探索
    base_dirs = [
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        os.path.dirname(os.path.abspath(__file__)),
        os.getcwd()
    ]
    for b in base_dirs:
        p = os.path.join(b, "data", "kanji_readings.json")
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    _KANJI_READINGS = json.load(f)
                    return _KANJI_READINGS
            except Exception as e:
                logger.warning(f"kanji_readings.json ロード失敗: {e}")
                break
    _KANJI_READINGS = {}
    return _KANJI_READINGS


def normalize_japanese_kana(text: str) -> str:
    """カタカナをひらがなに統一し、長音符や記号を整理"""
    text = unicodedata.normalize('NFKC', text)
    result = []
    for c in text:
        code = ord(c)
        if 0x30A1 <= code <= 0x30F6:  # カタカナ -> ひらがな
            result.append(chr(code - 0x60))
        elif c in ['ー', '〜', '～', ' ']:
            continue
        else:
            result.append(c)
    return "".join(result)


def expand_kanji_to_readings(text: str) -> List[str]:
    """
    漢字を含む文字列から、代表的な音訓読み（ひらがな列）を展開する。
    例: '右舷' -> ['うげん', 'ゆうげん', 'みぎげん']
    """
    k_map = _load_kanji_readings()
    normalized = normalize_japanese_kana(text)
    
    # 漢字ごとの読みリストを収集
    char_options: List[List[str]] = []
    has_kanji = False
    
    for c in normalized:
        # CJK統合漢字範囲
        if '\u4e00' <= c <= '\u9fff' and c in k_map:
            has_kanji = True
            char_options.append(k_map[c][:2])  # 最も主要な上位2読み
        else:
            char_options.append([c])
            
    if not has_kanji:
        return [normalized]

    # 直積展開（最大8通りの読み候補）
    import itertools
    combinations = list(itertools.product(*char_options))[:8]
    return ["".join(comb) for comb in combinations]


def simple_metaphone(text: str) -> str:
    """
    ラテン文字圏 (en, de, fr, es, pt, it) 用の簡易音韻コード生成
    発音が同じ文字（ph->f, c->k, z->s 等）を統一し、母音を正規化
    """
    s = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii').upper()
    s = re.sub(r'[^A-Z]', '', s)
    if not s:
        return ""
    
    # 音韻置換規則
    s = re.sub(r'KN|GN|PN|WR', lambda m: m.group(0)[1], s)
    s = re.sub(r'PH', 'F', s)
    s = re.sub(r'CK', 'K', s)
    s = re.sub(r'C[EIY]', 'S', s)
    s = re.sub(r'C', 'K', s)
    s = re.sub(r'Q', 'K', s)
    s = re.sub(r'X', 'KS', s)
    s = re.sub(r'Z', 'S', s)
    s = re.sub(r'V', 'F', s)
    s = re.sub(r'J', 'G', s)
    s = re.sub(r'TH', 'T', s)
    s = re.sub(r'SH|CH', 'X', s)
    
    # 連続文字の重複排除
    s = re.sub(r'(.)\1+', r'\1', s)
    # 先頭以外の母音を圧縮
    if len(s) > 1:
        first = s[0]
        rest = re.sub(r'[AEIOUWY]', '', s[1:])
        s = first + rest
    return s[:6]


def decompose_hangul(text: str) -> str:
    """韓国語ハングルを初声・中声・終声に分解して音韻文字列化"""
    CHOSUNG = ['ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']
    JUNGSUNG = ['ㅏ', 'ㅐ', 'ㅑ', 'ㅒ', 'ㅓ', 'ㅔ', 'ㅕ', 'ㅖ', 'ㅗ', 'ㅘ', 'ㅙ', 'ㅚ', 'ㅛ', 'ㅜ', 'ㅝ', 'ㅞ', 'ㅟ', 'ㅠ', 'ㅡ', 'ㅢ', 'ㅣ']
    JONGSUNG = ['', 'ㄱ', 'ㄲ', 'ㄳ', 'ㄴ', 'ㄵ', 'ㄶ', 'ㄷ', 'ㄹ', 'ㄺ', 'ㄻ', 'ㄼ', 'ㄽ', 'ㄾ', 'ㄿ', 'ㅀ', 'ㅁ', 'ㅂ', 'ㅄ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']
    
    result = []
    for c in text:
        code = ord(c)
        if 0xAC00 <= code <= 0xD7A3:
            s_index = code - 0xAC00
            cho = s_index // 588
            jung = (s_index % 588) // 28
            jong = s_index % 28
            result.append(CHOSUNG[cho])
            result.append(JUNGSUNG[jung])
            if jong > 0:
                result.append(JONGSUNG[jong])
        else:
            result.append(c)
    return "".join(result)


def levenshtein_similarity(s1: str, s2: str) -> float:
    """正規化レーベンシュタイン類似度 (0.0 〜 1.0)"""
    s1 = unicodedata.normalize('NFKC', s1).strip().lower()
    s2 = unicodedata.normalize('NFKC', s2).strip().lower()

    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)
    dp = list(range(len2 + 1))
    for i in range(1, len1 + 1):
        prev = dp[0]
        dp[0] = i
        c1 = s1[i - 1]
        for j in range(1, len2 + 1):
            temp = dp[j]
            cost = 0 if c1 == s2[j - 1] else 1
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
            prev = temp

    distance = dp[len2]
    max_len = max(len1, len2)
    return 1.0 - (distance / max_len)


def calculate_phonetic_similarity(c_name: str, m_alias: str, lang_code: str) -> float:
    """
    言語特性に応じた音韻（発音）類似度を計算する
    """
    # 連結記号（「、」「,」「・」「:」「-」「＝」およびスペース）を除去したコア文字列
    c_core = re.sub(r'[\s、,，・:：\-＝=]', '', c_name)
    m_core = re.sub(r'[\s、,，・:：\-＝=]', '', m_alias)

    # 1. 直接の文字一致度
    raw_sim = levenshtein_similarity(c_core, m_core)
    if raw_sim >= 0.70:
        return raw_sim

    # 2. 言語固有の音韻照合
    if lang_code == "ja":
        # ひらがな・カタカナ正規化
        c_hira = normalize_japanese_kana(c_core)
        m_hira = normalize_japanese_kana(m_core)
        kana_sim = levenshtein_similarity(c_hira, m_hira)
        
        # 漢字の音訓読み展開（当て字対応）
        c_readings = expand_kanji_to_readings(c_core)
        m_readings = expand_kanji_to_readings(m_core)
        
        best_sim = max(raw_sim, kana_sim)
        for cr in c_readings:
            for mr in m_readings:
                s = levenshtein_similarity(cr, mr)
                if s > best_sim:
                    best_sim = s
        return best_sim

    elif lang_code in ("en", "de", "fr", "es", "pt", "it"):
        # 簡易Metaphoneによる音韻コード照合
        c_meta = simple_metaphone(c_core)
        m_meta = simple_metaphone(m_core)
        if c_meta and m_meta and c_meta == m_meta:
            return 0.85
        meta_sim = levenshtein_similarity(c_meta, m_meta)
        return max(raw_sim, meta_sim * 0.9)

    elif lang_code == "ko":
        # ハングルUnicode分解（初声・中声・終声）
        c_jamo = decompose_hangul(c_core)
        m_jamo = decompose_hangul(m_core)
        return max(raw_sim, levenshtein_similarity(c_jamo, m_jamo))

    # デフォルト（ロシア語・中国語等）
    return raw_sim


def get_learn_alias_prompt(lang_code: str = "ja") -> str:
    """指定された言語コード（data/lang準拠）に適合するプロンプト指示文を返す"""
    return PROMPT_LEARN_ALIAS.get(lang_code, PROMPT_LEARN_ALIAS.get("en", ""))


def validate_alias(
    canonical_name: str,
    misrecognized_alias: str,
    lang_code: str = "ja",
    min_similarity: float = 0.30
) -> Tuple[bool, str]:
    """
    抽出された [LEARN_ALIAS: 正式名称 = 誤認識単語] の組み合わせを
    多層防御（文章排除 ＋ 10言語音韻照合）で高速精査する。

    Returns:
        (is_valid, reason): 登録可否と判定理由メッセージ
    """
    c_name = canonical_name.strip()
    m_alias = misrecognized_alias.strip()

    # 1. 基本的な文字数チェック (短すぎ・長すぎの除外)
    if len(c_name) < 2 or len(m_alias) < 2:
        return False, f"単語が短すぎます (正式: {len(c_name)}文字, エイリアス: {len(m_alias)}文字)"
    if len(c_name) > 30 or len(m_alias) > 30:
        return False, f"単語が長すぎます（文章混入と判定） (正式: {len(c_name)}文字, エイリアス: {len(m_alias)}文字)"

    # 2. 完全一致のチェック（同一ならエイリアス学習不要）
    if c_name.lower() == m_alias.lower():
        return False, "正式名称とエイリアスが同一のため学習不要です"

    # 3. URLパターンの除外
    if RE_URL_PATTERN.search(c_name) or RE_URL_PATTERN.search(m_alias):
        return False, "URLパターンが含まれています"

    # =========================================================================
    # 【第1防壁】明らかな文章・質問文・日常会話の高速排除
    # =========================================================================

    # 文末の句点・疑問符・感嘆符チェック（誤認識側が文章で終わっているか）
    if RE_END_OF_SENTENCE.search(m_alias):
        return False, "文末に句読点・疑問符が含まれており、文章と判定されました"
    if '\n' in c_name or '\r' in c_name or '\n' in m_alias or '\r' in m_alias:
        return False, "改行コードが含まれています"

    # 各言語の質問・疑問フレーズのチェック（誤認識側に質問が含まれている場合）
    q_patterns = QUESTION_PATTERNS_BY_LANG.get(lang_code, []) + QUESTION_PATTERNS_BY_LANG.get("en", [])
    for q_pat in q_patterns:
        if q_pat.search(m_alias):
            return False, f"質問・疑問表現が検知されました: '{m_alias}'"

    # 日本語特有の文節・助詞連鎖チェック
    if lang_code == "ja":
        # 末尾の助詞（3文字以上で末尾が助詞、例: 「ポーションを」）
        if len(m_alias) >= 3 and RE_JA_PARTICLES.search(m_alias):
            return False, f"エイリアス末尾に助詞が含まれています: '{m_alias}'"
        # 助詞が複数含まれる文章構造の検知（「〜は〜を」など）
        particles_found = len(re.findall(r'(について|から|まで|へ|を|に|で|が|は|と|も|の)', m_alias))
        if particles_found >= 3:
            return False, f"複数の助詞が含まれており文章と判定されました: '{m_alias}'"

    # ストップワード（挨拶・日常語）の完全一致チェック
    lang_stopwords = STOPWORDS_BY_LANG.get(lang_code, set()) | STOPWORDS_BY_LANG.get("en", set())
    if c_name.lower() in lang_stopwords or m_alias.lower() in lang_stopwords:
        return False, "一般的なストップワード（挨拶・日常語）と一致したため破棄されました"

    # =========================================================================
    # 【第2防壁】10言語対応 音韻・発音（Phonetic）照合
    # =========================================================================
    phonetic_sim = calculate_phonetic_similarity(c_name, m_alias, lang_code)
    
    # 部分一致（片方がもう片方に含まれる略称パターン、例: 「ドラクエ」 in 「ドラゴンクエスト」）
    c_clean = re.sub(r'[\s、,，・:：\-＝=]', '', c_name).lower()
    m_clean = re.sub(r'[\s、,，・:：\-＝=]', '', m_alias).lower()
    is_substring = (c_clean in m_clean) or (m_clean in c_clean)

    if not is_substring and phonetic_sim < min_similarity:
        return False, f"音韻類似度が基準未満です (類似度: {phonetic_sim:.2f} < 閾値: {min_similarity})"

    return True, f"合格 (音韻類似度: {phonetic_sim:.2f})"
