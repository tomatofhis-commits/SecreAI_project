"""
test_multilingual_alias_validator.py - 多層防御エイリアスバリデータの単体テスト
"""

import sys
import os
import unittest

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.alias_validator import (
    validate_alias,
    get_learn_alias_prompt,
    calculate_phonetic_similarity,
    normalize_japanese_kana,
    expand_kanji_to_readings,
    simple_metaphone,
    decompose_hangul
)


class TestMultilingualAliasValidator(unittest.TestCase):

    def test_prompt_generation_all_10_languages(self):
        """data/lang の10言語すべてで適切なプロンプトが取得できるか"""
        expected_langs = ["de", "en", "es", "fr", "it", "ja", "ko", "pt", "ru", "zh-CN"]
        for lang in expected_langs:
            prompt = get_learn_alias_prompt(lang)
            self.assertTrue(len(prompt) > 20, f"{lang} のプロンプトが空または短すぎます")
            self.assertIn("LEARN_ALIAS", prompt, f"{lang} のプロンプトにタグ形式が含まれていません")

    def test_mtg_card_and_kanji_phonetic_matching(self):
        """MTGカード名および漢字当て字（音読み・訓読み）のテスト"""
        # 1. ユーザー様の実例: 『嵐の目、ウギン = 嵐の目 右舷』
        valid, reason = validate_alias("嵐の目、ウギン", "嵐の目 右舷", "ja")
        self.assertTrue(valid, f"嵐の目、ウギンが不当に除外されました: {reason}")

        # 2. 単体の漢字当て字: 『ウギン = 右舷』
        valid, reason = validate_alias("ウギン", "右舷", "ja")
        self.assertTrue(valid, f"ウギン＝右舷が不当に除外されました: {reason}")

        # 3. 単体の漢字当て字: 『ヨーテボリ = 両手掘り』
        valid, reason = validate_alias("ヨーテボリ", "両手掘り", "ja")
        self.assertTrue(valid, f"ヨーテボリ＝両手掘りが不当に除外されました: {reason}")

        # 4. 二つ名を持つカード名: 『精神を刻む者、ジェイス = 精神を刻む者 ジュース』
        valid, reason = validate_alias("精神を刻む者、ジェイス", "精神を刻む者 ジュース", "ja")
        self.assertTrue(valid, f"ジェイス二つ名が不当に除外されました: {reason}")

        # 5. 弾くべきケース: 無関係な漢字単語 (効果発動、攻撃力)
        valid, reason = validate_alias("ウギン", "効果発動", "ja")
        self.assertFalse(valid, f"効果発動が誤って通過しました: {reason}")
        self.assertIn("音韻類似度", reason)

    def test_sentence_and_question_filters(self):
        """第1防壁: 質問文・文章表現の除外テスト"""
        # 質問文末尾（？）
        valid, reason = validate_alias("ポーション", "これは何ですか？", "ja")
        self.assertFalse(valid)
        self.assertIn("文末", reason)

        # 質問表現が含まれるもの（どうすればいい）
        valid, reason = validate_alias("ポーション", "どうすればいい", "ja")
        self.assertFalse(valid)
        self.assertIn("質問", reason)

        # 助詞付きフレーズ
        valid, reason = validate_alias("ポーション", "ポーションを", "ja")
        self.assertFalse(valid)
        self.assertIn("助詞", reason)

        # 英語の質問文
        valid, reason = validate_alias("Excalibur", "what is this", "en")
        self.assertFalse(valid)
        self.assertIn("質問", reason)

        # URL
        valid, reason = validate_alias("検索", "https://google.com", "ja")
        self.assertFalse(valid)
        self.assertIn("URL", reason)

    def test_english_and_european_phonetics(self):
        """英語および欧州言語のMetaphone音韻テスト"""
        # 英語: 綴りが異なる同音語 (Phoenix -> Feenix)
        valid, reason = validate_alias("Phoenix", "Feenix", "en")
        self.assertTrue(valid, f"Phoenix -> Feenix が除外されました: {reason}")

        # 英語: 綴りが異なる同音語 (Knight -> Night)
        valid, reason = validate_alias("Knight", "Night", "en")
        self.assertTrue(valid, f"Knight -> Night が除外されました: {reason}")

        # フランス語 (Château -> Chato)
        valid, reason = validate_alias("Château", "Chato", "fr")
        self.assertTrue(valid, f"Château -> Chato が除外されました: {reason}")

        # ドイツ語 ストップワード除外
        valid, reason = validate_alias("Drache", "danke", "de")
        self.assertFalse(valid)

        # スペイン語 ストップワード除外
        valid, reason = validate_alias("Caballero", "gracias", "es")
        self.assertFalse(valid)

    def test_asian_and_russian_phonetics(self):
        """アジア言語 (ko, zh-CN) およびロシア語のテスト"""
        # 韓国語 (ハングル分解照合: 포션 -> 보션)
        valid, reason = validate_alias("포션", "보션", "ko")
        self.assertTrue(valid, f"포션 -> 보션 が除外されました: {reason}")

        # 韓国語 質問文除外
        valid, reason = validate_alias("포션", "이게 뭐야", "ko")
        self.assertFalse(valid)

        # 中国語 ストップワード除外
        valid, reason = validate_alias("巨龙", "你好", "zh-CN")
        self.assertFalse(valid)

        # ロシア語 (Дракон -> Драко)
        valid, reason = validate_alias("Дракон", "Драко", "ru")
        self.assertTrue(valid, f"Дракон -> Драко が除外されました: {reason}")

        # ロシア語 ストップワード除外
        valid, reason = validate_alias("Дракон", "спасибо", "ru")
        self.assertFalse(valid)


if __name__ == "__main__":
    unittest.main()
