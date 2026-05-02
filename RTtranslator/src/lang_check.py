"""
lang_check.py
fastTextを使って、OCR結果が「翻訳先言語と同一かどうか」を高速に判定するガードレール。
翻訳先言語と同じテキストをOllamaへ送るムダを確実に排除する。
"""

from __future__ import annotations
import re
from pathlib import Path


# --- fastText モデルのパス ---
# ここに軽量な lid.176.ftz を配置する（約917KB）
_MODEL_PATH = Path(__file__).parent.parent / "models" / "lid.176.ftz"

_ft_model = None          # シングルトン（一度だけロードする）
_ft_available = False     # fastText が使えるかどうかのフラグ


def _ensure_model_loaded() -> bool:
    """fastText モデルを遅延ロードする。利用可能なら True を返す。"""
    global _ft_model, _ft_available

    if _ft_available:
        return True

    if not _MODEL_PATH.exists():
        print(f"[LangCheck] モデルファイルが見つかりません: {_MODEL_PATH}")
        return False

    try:
        # 読み込めるかテスト
        import fasttext
        # 一部の環境で eprint の上書きに失敗するため、単純なロードを試みる
        _ft_model = fasttext.load_model(str(_MODEL_PATH.absolute()))
        _ft_available = True
        print(f"[LangCheck] fastText モデルをロードしました: {_MODEL_PATH.name}")
        return True
    except ImportError:
        print("[LangCheck] ライブラリ 'fasttext' が見つかりません。pip install fasttext-wheel を確認してください。")
        return False
    except Exception as e:
        print(f"[LangCheck] ロード中に致命的なエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        return False


# fastText の言語コード → target_lang のベースコードへのマッピング
_FT_TO_BASE: dict[str, set[str]] = {
    "ja": {"ja"},
    "ko": {"ko"},
    "zh": {"zh", "zh-cn", "zh-tw"},
    "ru": {"ru"},
    "fr": {"fr"},
    "en": {"en"},
    "de": {"de"},
    "es": {"es"},
    "it": {"it"},
    "pt": {"pt"},
}


def is_same_as_target(text: str, target_lang: str, threshold: float = 0.7) -> bool:
    """
    text が target_lang と同じ言語かどうかを判定する。
    - fastText が使えない場合は正規表現フォールバックを使う。
    - threshold: fastText の信頼スコアがこれ以上なら「同じ言語」とみなす（デフォルト 0.7）。

    Returns:
        True  → すでに翻訳先言語 → 翻訳スキップ（スルー）
        False → 翻訳が必要
    """
    base_tgt = target_lang.split("-")[0].lower()

    # ------------------------------------------------------------------
    # 正規表現による高速チェック（fastText 不要の文字種固有の言語）
    # ------------------------------------------------------------------
    text_clean = re.sub(r"[\s\d\W]+", "", text)
    if not text_clean:
        return False

    total = len(text_clean)

    if base_tgt == "ja":
        kana = len(re.findall(r"[ぁ-んァ-ン]", text_clean))
        kanji = len(re.findall(r"[一-龥]", text_clean))
        if kana > 0 and kana / total > 0.1:
            return True
        if kanji / total > 0.5:
            return True

    elif base_tgt == "ko":
        hangul = len(re.findall(r"[가-힣]", text_clean))
        if hangul / total > 0.3:
            return True

    elif base_tgt in ("zh", "zh-cn", "zh-tw"):
        han = len(re.findall(r"[一-龥]", text_clean))
        kana = len(re.findall(r"[ぁ-んァ-ン]", text_clean))
        hangul = len(re.findall(r"[가-힣]", text_clean))
        if han > 0 and kana == 0 and hangul == 0 and han / total > 0.5:
            return True

    elif base_tgt == "ru":
        cyril = len(re.findall(r"[А-Яа-яЁё]", text_clean))
        if cyril / total > 0.4:
            return True

    # ------------------------------------------------------------------
    # fastText による言語判定（ラテン文字系 or 上記で判定できなかった場合）
    # ------------------------------------------------------------------
    if not _ensure_model_loaded():
        # fastText なしのフォールバック：ラテン文字系は同一判定が難しいため保守的に False
        return False

    try:
        # fastText は改行をスペースに変換しないと精度が落ちる
        text_single = text.replace("\n", " ").strip()
        if not text_single:
            return False

        labels, probs = _ft_model.predict(text_single, k=1)
        if not labels:
            return False

        detected = labels[0].replace("__label__", "").lower()
        confidence = float(probs[0])

        # 検出した言語が target_lang ファミリーに属するか確認
        for ft_lang, base_codes in _FT_TO_BASE.items():
            if detected == ft_lang:
                if base_tgt in base_codes:
                    return confidence >= threshold
                break

        return False

    except Exception:
        return False


def get_model_status() -> str:
    """設定画面などで表示用のステータス文字列を返す。"""
    if _ft_available:
        return f"fastText 有効 ({_MODEL_PATH.name})"
    
    if _ensure_model_loaded():
        return f"fastText 有効 ({_MODEL_PATH.name})"
    elif _MODEL_PATH.exists():
        return "fastText モデルあり [読込失敗]"
    else:
        return f"fastText モデルなし ({_MODEL_PATH.name})"


# fastText言語コード → ISO 639-1 コードへの相互変換マップ（発信元言語判定用）
_FT_TO_ISO: dict[str, str] = {
    "ja": "ja", "ko": "ko", "zh": "zh",
    "ru": "ru", "uk": "ru",  # ウクライナ語は近似としてru扱い
    "en": "en", "fr": "fr", "de": "de",
    "es": "es", "it": "it", "pt": "pt",
    "nl": "nl", "pl": "pl", "cs": "cs",
    "tr": "tr", "ar": "ar", "th": "th",
    "vi": "vi", "id": "id",
}


def detect_source_language(
    text: str,
    ocr_lang_hint: str = "en",
    confidence_threshold: float = 0.55,
) -> tuple[str, float]:
    """
    OCRで読み取ったテキストの「発信元言語」と「fastText信頼度」を判定して返す。
    Ollamaへのプロンプトで source_lang を明示指定するために使用する。

    Returns:
        (ISO 639-1 言語コード, fastText信頼度 0.0~1.0)
        信頼度 0.0 は fastText による判定不可またはフォールバックを示す。
    """
    text_clean = re.sub(r"[\s\d]+", "", text)
    if not text_clean:
        return ocr_lang_hint, 0.0

    total = len(text_clean)

    # --- ステップ1: 文字種による即時確定（記号が欠落しても確実な言語） ---
    kana   = len(re.findall(r"[ぁ-んァ-ン]", text_clean))
    hangul = len(re.findall(r"[가-힣]", text_clean))
    cyril  = len(re.findall(r"[А-Яа-яЁё]", text_clean))
    han    = len(re.findall(r"[一-龥]", text_clean))
    latin  = len(re.findall(r"[a-zA-ZÀ-ÿ]", text_clean))

    # かなが含まれれば日本語確定
    if kana > 0 and kana / total > 0.05:
        return "ja", 1.0
    # ハングル確定
    if hangul / total > 0.2:
        return "ko", 1.0
    # キリル文字確定
    if cyril / total > 0.3:
        return "ru", 1.0
    # かななしで漢字主体 → 中国語と仮定（fastTextで追確認）
    if han > 0 and kana == 0 and hangul == 0 and han / total > 0.4:
        # fastText があれば日本語か中国語かを確認
        if _ensure_model_loaded():
            try:
                labels, probs = _ft_model.predict(text.replace("\n", " ").strip(), k=1)
                if labels:
                    ft_lang = labels[0].replace("__label__", "").lower()
                    ft_score = float(probs[0])
                    if ft_lang == "ja" and ft_score >= confidence_threshold:
                        return "ja", ft_score
                    if ft_lang == "zh" and ft_score >= confidence_threshold:
                        return "zh", ft_score
            except Exception:
                pass
        # fallback: OCR の hint または zh
        fallback = "ja" if ocr_lang_hint == "ja" else "zh"
        return fallback, 0.5

    # --- ステップ2: ラテン文字主体 → fastText で個別言語を識別 ---
    if latin / max(1, total) >= 0.3:
        if not _ensure_model_loaded():
            # fastText なし → OCR hint をそのまま返す
            return (ocr_lang_hint if ocr_lang_hint else "en", 0.0)

        try:
            # k=3 で上位候補を取得する
            labels, probs = _ft_model.predict(text.replace("\n", " ").strip(), k=3)
            if labels:
                # 信頼度に関わらず fastText の実際のスコアを返す。
                # 閉値(0.55)未満でも 0.0 でなく実スコアを返すことで、
                # ゲーム用語混じりのイタリア語等が誤って事前ストライクされるのを防ぐ。
                for lbl, prob in zip(labels, probs):
                    ft_lang = lbl.replace("__label__", "").lower()
                    iso_code = _FT_TO_ISO.get(ft_lang)
                    if iso_code:
                        return iso_code, float(prob)
                # ISOマップにない言語だった場合も、少なくとも「何か判定した」ことを示すためスコアを返す
                return ocr_lang_hint or "en", float(probs[0])
        except Exception:
            pass

        # fastText が完全に利用不可（例外発生等）を 0.0 で示す
        return ocr_lang_hint if ocr_lang_hint else "en", 0.0

    # --- ステップ3: 上記以外（記号のみなど）→ OCR hint を使用 ---
    return ocr_lang_hint if ocr_lang_hint else "en", 0.0


def is_valid_translation(text: str, target_lang: str) -> bool:
    """
    翻訳結果が正しくターゲット言語になっているかを検証する（事後バリデーション）。

    「固有名詞が少量含まれている正常なケース」でリトライが走らないよう、
    文字種割合チェックと fastText を組み合わせた多層判定を行う。

    Returns:
        True  -> 翻訳は正常（またはグレーゾーンで許容）→ リトライ不要
        False -> 明らかに翻訳先言語になっていない        → リトライを推奨
    """
    base_tgt = target_lang.split("-")[0].lower()
    text_clean = re.sub(r"[\s\d]+", "", text)

    if not text_clean:
        return True  # 空文字はバリデーション対象外

    total = len(text_clean)

    # ------------------------------------------------------------------
    # 【日本語ターゲット】
    # ------------------------------------------------------------------
    if base_tgt == "ja":
        kana  = len(re.findall(r"[ぁ-んァ-ン]", text_clean))
        kanji = len(re.findall(r"[一-龥]", text_clean))

        # かなが少しでもあれば日本語と判断 → 固有名詞混じりは許容
        if kana > 0:
            return True

        # かなが一切なく漢字のみ → 中国語の可能性あり。fastText で追加確認
        if kanji > 0:
            if not _ensure_model_loaded():
                # fastText なしの場合は保守的に「OK」（誤リトライ防止優先）
                return True
            try:
                labels, probs = _ft_model.predict(text.replace("\n", " ").strip(), k=2)
                if not labels:
                    return True
                top_lang  = labels[0].replace("__label__", "").lower()
                top_score = float(probs[0])
                # 「日本語」判定 → OK
                if top_lang == "ja":
                    return True
                # 「中国語」と高信頼で判定かつかなが皆無 → 翻訳失敗の可能性
                # ただし確信度が 0.90 未満（曖昧）なら許容
                if top_lang == "zh" and top_score >= 0.90:
                    return False
                # その他の言語で かつ高信頼 → 問題あり
                if top_lang not in ("ja", "zh") and top_score >= 0.85:
                    return False
                return True
            except Exception:
                return True

        # かなも漢字もなく、ラテン文字主体 → fastText で厳格に確認
        latin  = len(re.findall(r"[a-zA-ZÀ-ÿ]", text_clean))
        hangul = len(re.findall(r"[가-힣]", text_clean))
        
        # ハングルが主体なら明らかに日本語以外 → 翻訳失敗
        if hangul / max(1, total) > 0.3:
            return False
        
        if latin / max(1, total) < 0.5:
            # ラテン文字が少ない場合はその他の文字種 → グレーゾーン許容
            return True

        if not _ensure_model_loaded():
            return True
        try:
            labels, probs = _ft_model.predict(text.replace("\n", " ").strip(), k=1)
            if not labels:
                return True
            top_lang  = labels[0].replace("__label__", "").lower()
            top_score = float(probs[0])
            # 確信度0.70以上で非日本語と判定 → 明らかに翻訳失敗
            # (0.90は高すぎて "Un esordio negli eventi" 等のイタリア語がスルーしてしまうため引き下げる)
            if top_lang != "ja" and top_score >= 0.70:
                return False
            return True
        except Exception:
            return True

    # ------------------------------------------------------------------
    # 【韓国語ターゲット】
    # ------------------------------------------------------------------
    elif base_tgt == "ko":
        hangul = len(re.findall(r"[가-힣]", text_clean))
        if hangul / max(1, total) >= 0.2:
            return True
        # ハングルがほぼない → fastText で確認
        if not _ensure_model_loaded():
            return True
        try:
            labels, probs = _ft_model.predict(text.replace("\n", " ").strip(), k=1)
            if not labels:
                return True
            top_lang  = labels[0].replace("__label__", "").lower()
            top_score = float(probs[0])
            if top_lang != "ko" and top_score >= 0.85:
                return False
            return True
        except Exception:
            return True

    # ------------------------------------------------------------------
    # 【ロシア語ターゲット】
    # ------------------------------------------------------------------
    elif base_tgt == "ru":
        cyril = len(re.findall(r"[А-Яа-яЁё]", text_clean))
        if cyril / max(1, total) >= 0.3:
            return True
        if not _ensure_model_loaded():
            return True
        try:
            labels, probs = _ft_model.predict(text.replace("\n", " ").strip(), k=1)
            if not labels:
                return True
            top_lang  = labels[0].replace("__label__", "").lower()
            top_score = float(probs[0])
            if top_lang != "ru" and top_score >= 0.85:
                return False
            return True
        except Exception:
            return True

    # ------------------------------------------------------------------
    # 【ラテン文字系ターゲット（英・仏・独・西・伊・葡）】
    # fastText のみで判定。確信度 0.85 未満は許容（固有名詞対策）
    # ------------------------------------------------------------------
    elif base_tgt in ("en", "fr", "de", "es", "it", "pt"):
        if not _ensure_model_loaded():
            return True
        try:
            labels, probs = _ft_model.predict(text.replace("\n", " ").strip(), k=1)
            if not labels:
                return True
            top_lang  = labels[0].replace("__label__", "").lower()
            top_score = float(probs[0])
            if top_lang != base_tgt and top_score >= 0.85:
                return False
            return True
        except Exception:
            return True

    # ------------------------------------------------------------------
    # 上記以外のターゲット言語はバリデーション対象外
    # ------------------------------------------------------------------
    return True
