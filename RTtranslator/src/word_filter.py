"""
短文（1〜2語）が実在する単語かどうかを常用語辞書でチェックするモジュール。

【判定ルール】
- スペース区切りで 3 語以上 → 長文とみなしてスキップ（常に通過）
- CJK 文字（日本語・中国語・韓国語）を含む → 辞書チェックせずに通過
- 数字・記号のみ → 通過（ゲージ・FPS等）
- 1〜2 語のラテン文字主体のテキスト → いずれかの言語辞書に存在するか確認
  → 存在しなければ「ゴミOCR」とみなして破棄

【辞書の作成】
  python build_wordlists.py
を一度実行して data/wordlists/ 以下に辞書ファイルを生成しておくこと。
"""
from __future__ import annotations

import json
import os
import re

# 辞書データのパス
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "wordlists")

# 言語コード → 単語セット
_WORDLISTS: dict[str, set[str]] = {}
_LOADED = False


def _load_wordlists() -> None:
    """辞書を一度だけメモリに読み込む（遅延ロード）。"""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    if not os.path.isdir(_DATA_DIR):
        print(f"[WordFilter] 辞書ディレクトリが見つかりません: {_DATA_DIR}")
        print("[WordFilter] build_wordlists.py を実行して辞書を生成してください。")
        return

    for fname in sorted(os.listdir(_DATA_DIR)):
        if not fname.endswith(".json"):
            continue
        lang = fname[:-5]  # 拡張子除去
        fpath = os.path.join(_DATA_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                words: list[str] = json.load(f)
            _WORDLISTS[lang] = set(words)  # 既に小文字化済み
            print(f"[WordFilter] 読み込み完了: {lang} ({len(_WORDLISTS[lang])} 語)")
        except Exception as e:
            print(f"[WordFilter] 読み込み失敗 {fpath}: {e}")


def _is_loaded() -> bool:
    _load_wordlists()
    return bool(_WORDLISTS)


# --------------------------------------------------------------------------- #
# 公開 API
# --------------------------------------------------------------------------- #

def is_known_word(text: str) -> bool:
    """
    テキストが「実在する単語（またはその組み合わせ）」かどうかを返す。

    Returns:
        True  → 翻訳を許可（実在する単語、長文、CJK 文字含む）
        False → 翻訳を破棄（どの辞書にも存在しない短い文字列）
    """
    if not _is_loaded():
        return True  # 辞書が使えない場合は安全策として通過

    text_stripped = text.strip()
    if not text_stripped:
        return False

    # ① CJK 文字（日本語・中国語・韓国語）が含まれる → fastText に任せて通過
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7a3]", text_stripped):
        return True

    # ② 数字・記号・スペースのみ（ゲージ・FPS値・UIの線など）→ 通過
    if re.fullmatch(r"[\d\s\-\.\,\:\;\!\?\%\/\\\(\)\[\]\_\*\#\@\&]+", text_stripped):
        return True

    # ③ スペース区切りで単語に分解
    words = text_stripped.split()

    # ④ 3 語以上 かつ 平均単語長が3文字以上 → 自然な長文として辞書チェックをスキップ
    # （「II I I I」のように短い文字の羅列は長文扱いしない）
    if len(words) >= 3:
        avg_word_len = sum(len(w) for w in words) / len(words)
        if avg_word_len >= 3.0:
            return True

    # ⑤ 1〜2 語の短いテキスト → 辞書チェック
    valid_word_checked = 0  # 実際に辞書チェックを行った単語数
    for word in words:
        # 数字が混入している単語（danger00, amachi01等）→ ゴミ扱いでスキップ
        if re.search(r'\d', word):
            continue

        # アルファベット・アクセント付きラテン・キリル文字のみを抽出
        word_alpha = re.sub(r'[^a-zA-Z\u00c0-\u024f\u0400-\u04ff]', '', word).lower()
        if len(word_alpha) < 2:
            # 1文字以下（I, Aなど）はスキップ。ただし判定数には数えない
            continue

        # 同一文字の繰り返し（III, lllなど）→ ゴミ扱いでスキップ
        if len(set(word_alpha)) <= 1:
            continue

        valid_word_checked += 1
        # いずれかの辞書に存在すれば「実在する」と判定
        for lang_words in _WORDLISTS.values():
            if word_alpha in lang_words:
                return True

    # 有効な単語が1つも評価されなかった（全て1文字か数字混じり）→ ゴミ
    if valid_word_checked == 0:
        return False

    # 辞書に存在する単語が1つもなかった → ゴミ
    return False


def should_discard(text: str) -> bool:
    """
    短いテキスト（1〜2 語）を翻訳せずに破棄すべきかどうかを返す。

    Returns:
        True  → 破棄すべき（辞書にない = ゴミOCR）
        False → 翻訳を試みる
    """
    words = text.strip().split()

    # 3 語以上 かつ 平均単語長が3文字以上 → 自然な長文として破棄しない
    # （「II I I I」のように短い文字の羅列は長文扱いしない）
    if len(words) >= 3:
        avg_word_len = sum(len(w) for w in words) / len(words)
        if avg_word_len >= 3.0:
            return False

    return not is_known_word(text)
