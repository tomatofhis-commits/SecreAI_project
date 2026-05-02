"""
各言語の頻出単語リスト（常用上位 10000 語）を構築するスクリプト。
wordfreq ライブラリを使用して data/wordlists/ 以下に保存する。

一度だけ実行すれば OK。
  python build_wordlists.py
"""
import json
import os

try:
    from wordfreq import top_n_list
except ImportError:
    print("wordfreq をインストールしてください: pip install wordfreq")
    exit(1)

# ビルドする言語と語数
LANGS = {
    "en": "English",
    "it": "Italian",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "pt": "Portuguese",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
}
N_WORDS = 10_000

OUT_DIR = os.path.join(os.path.dirname(__file__), "data", "wordlists")
os.makedirs(OUT_DIR, exist_ok=True)

total_size = 0
for lang_code, lang_name in LANGS.items():
    print(f"Building {lang_name} ({lang_code}) ... ", end="", flush=True)
    try:
        words = top_n_list(lang_code, N_WORDS, wordlist="best")
        # 全て小文字化して重複除去
        words_lower = sorted(set(w.lower() for w in words))
        out_path = os.path.join(OUT_DIR, f"{lang_code}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(words_lower, f, ensure_ascii=False, separators=(",", ":"))
        size_kb = os.path.getsize(out_path) / 1024
        total_size += size_kb
        print(f"{len(words_lower)} 語 ({size_kb:.1f} KB) → {out_path}")
    except Exception as e:
        print(f"FAILED: {e}")

print(f"\n完了！ 合計ディスク使用量: {total_size:.1f} KB ({total_size/1024:.2f} MB)")
