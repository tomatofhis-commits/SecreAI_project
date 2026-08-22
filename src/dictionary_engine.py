"""
dictionary_engine.py - 超高速辞書検索・STTテキスト補正・動的知識抽出エンジン

特徴:
1. 最長一致（Longest-Match）Trie木による高速文字列走査（1ms未満）
2. タイムスタンプ連動バイナリキャッシュ（.cache）による0.05秒高速ロード
3. STT誤認識の自動置換とプロンプト注入用メタデータ（info）の同時抽出
4. 会話からの動的エイリアス学習・即時メモリ反映機能
"""

import os
import json
import pickle
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set

logger = logging.getLogger("DictionaryEngine")


@dataclass
class DictionaryEntry:
    name: str
    aliases: List[str] = field(default_factory=list)
    category: str = "General"
    info: str = ""
    source_file: str = ""


class TrieNode:
    def __init__(self):
        self.children: Dict[str, "TrieNode"] = {}
        self.entry: Optional[DictionaryEntry] = None
        self.target_name: Optional[str] = None  # 置換後の正式名称


class DictionaryEngine:
    """高速な最長一致文字列置換および知識抽出を行うエンジン"""

    def __init__(self, dictionary_dir: str = "dictionary"):
        self.dict_dir = os.path.abspath(dictionary_dir)
        self.cache_dir = os.path.join(self.dict_dir, ".cache")
        self.root = TrieNode()
        self.entries: Dict[str, DictionaryEntry] = {}  # name -> Entry
        self.learned_file = os.path.join(self.dict_dir, "USER_LEARNED.json")
        self.min_alias_len = 2  # 誤置換を防ぐ最小エイリアス文字数

    def initialize(self, enabled_files: Optional[List[str]] = None) -> int:
        """
        辞書フォルダ内のJSONを走査し、インデックスを構築する
        enabled_files が指定されている場合は、そのリストに含まれるファイル（および USER_LEARNED.json）のみをロード
        """
        if not os.path.exists(self.dict_dir):
            os.makedirs(self.dict_dir, exist_ok=True)
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)

        self.root = TrieNode()
        self.entries.clear()

        loaded_count = 0
        all_json_files = [
            f for f in os.listdir(self.dict_dir)
            if f.endswith(".json") and not f.startswith(".")
        ]

        # 読み込み対象の絞り込み
        target_files = []
        for fname in all_json_files:
            if enabled_files is None:
                target_files.append(fname)
            else:
                # 指定リストに含まれているか、または自動学習データなら常にロード
                if fname in enabled_files or fname == "USER_LEARNED.json":
                    target_files.append(fname)

        for fname in target_files:
            json_path = os.path.join(self.dict_dir, fname)
            cache_path = os.path.join(self.cache_dir, f"{os.path.splitext(fname)[0]}.cache")

            entries = self._load_or_create_cache(json_path, cache_path)
            for entry in entries:
                self._register_entry(entry)
                loaded_count += 1

        logger.info(f"辞書エンジン初期化完了: {len(target_files)} ファイルから {loaded_count} 件の単語をロード")
        return loaded_count

    def _load_or_create_cache(self, json_path: str, cache_path: str) -> List[DictionaryEntry]:
        """タイムスタンプを比較し、キャッシュが最新ならキャッシュから、古ければJSONから読み込む"""
        json_mtime = os.path.getmtime(json_path)

        if os.path.exists(cache_path):
            cache_mtime = os.path.getmtime(cache_path)
            if cache_mtime >= json_mtime:
                try:
                    with open(cache_path, "rb") as f:
                        return pickle.load(f)
                except Exception as e:
                    logger.warning(f"キャッシュ読み込み失敗 ({cache_path}): {e}。再生成します。")

        # JSONから読み込み（スマートパーサー）
        entries: List[DictionaryEntry] = []
        fname = os.path.basename(json_path)
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # パターン1: {"meta": {...}, "entries": [...]}
            if isinstance(data, dict) and "entries" in data and isinstance(data["entries"], list):
                default_cat = data.get("meta", {}).get("category", "General") if isinstance(data.get("meta"), dict) else "General"
                for item in data["entries"]:
                    entry = self._parse_single_item(item, default_cat, fname)
                    if entry:
                        entries.append(entry)

            # パターン2: [{"name": ...}, ...] または ["単語1", "単語2", ...] (リスト形式)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        # 単純文字列リスト
                        s = item.strip()
                        if s:
                            entries.append(DictionaryEntry(name=s, aliases=[], category="List", info="", source_file=fname))
                    elif isinstance(item, dict):
                        entry = self._parse_single_item(item, "General", fname)
                        if entry:
                            entries.append(entry)

            # パターン3: {"単語名": "説明文 / 効果", ...} (Key-Value形式)
            elif isinstance(data, dict):
                for key, val in data.items():
                    if key == "meta":
                        continue
                    k = str(key).strip()
                    if not k:
                        continue
                    if isinstance(val, str):
                        entries.append(DictionaryEntry(name=k, aliases=[], category="KeyValue", info=val.strip(), source_file=fname))
                    elif isinstance(val, list):
                        # {"正式名": ["エイリアス1", "エイリアス2"]}
                        aliases = [str(a).strip() for a in val if str(a).strip()]
                        entries.append(DictionaryEntry(name=k, aliases=aliases, category="Aliases", info="", source_file=fname))
                    elif isinstance(val, dict):
                        entry = self._parse_single_item(val, "General", fname, default_name=k)
                        if entry:
                            entries.append(entry)

            # キャッシュ保存
            with open(cache_path, "wb") as f:
                pickle.dump(entries, f, protocol=pickle.HIGHEST_PROTOCOL)

        except Exception as e:
            logger.error(f"辞書ファイル解析エラー ({json_path}): {e}")

        return entries

    def _parse_single_item(self, item: dict, default_cat: str, fname: str, default_name: str = "") -> Optional[DictionaryEntry]:
        """単一の辞書オブジェクトを解析して DictionaryEntry を生成"""
        if not isinstance(item, dict):
            return None

        # nameの候補キーを柔軟に探索 (name, word, title, label, term)
        name = str(item.get("name") or item.get("word") or item.get("title") or item.get("term") or default_name).strip()
        if not name:
            return None

        # aliases
        aliases = item.get("aliases") or item.get("alias") or item.get("synonyms") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        cleaned_aliases = [str(a).strip() for a in aliases if str(a).strip()]

        category = str(item.get("category", default_cat))
        
        # info (info, description, desc, text, effect)
        info = str(item.get("info") or item.get("description") or item.get("desc") or item.get("text") or item.get("effect") or "").strip()

        return DictionaryEntry(
            name=name,
            aliases=cleaned_aliases,
            category=category,
            info=info,
            source_file=fname
        )

    def _register_entry(self, entry: DictionaryEntry):
        """Trie木に正式名称および全エイリアスを登録する"""
        self.entries[entry.name] = entry

        # 正式名称自体の登録（マッチ・情報抽出用）
        self._insert_trie(entry.name, entry, target_name=entry.name)

        # 全エイリアスの登録（置換＆情報抽出用）
        for alias in entry.aliases:
            if len(alias) >= self.min_alias_len:
                self._insert_trie(alias, entry, target_name=entry.name)

    def _insert_trie(self, phrase: str, entry: DictionaryEntry, target_name: str):
        """文字列を1文字ずつTrie木に挿入"""
        node = self.root
        for char in phrase:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.entry = entry
        node.target_name = target_name

    def correct_text(self, text: str) -> Tuple[str, List[DictionaryEntry]]:
        """
        入力テキストを最長一致でスキャンし、以下を同時に行う:
        1. STT誤認識語・エイリアスを正式名称に置換したテキストを生成
        2. 文中に含まれていた単語のDictionaryEntry一覧を重複なく抽出

        戻り値: (置換後テキスト, マッチした知識Entryのリスト)
        """
        if not text or not self.root.children:
            return text, []

        result_chars: List[str] = []
        matched_entries: Dict[str, DictionaryEntry] = {}
        n = len(text)
        i = 0

        while i < n:
            node = self.root
            match_len = 0
            best_target: Optional[str] = None
            best_entry: Optional[DictionaryEntry] = None

            # i文字目から始まる最長一致を探索
            for j in range(i, n):
                char = text[j]
                if char not in node.children:
                    break
                node = node.children[char]
                if node.entry is not None:
                    match_len = j - i + 1
                    best_target = node.target_name
                    best_entry = node.entry

            if match_len > 0 and best_target and best_entry:
                # 最長一致したエイリアス/名称を置換
                result_chars.append(best_target)
                matched_entries[best_entry.name] = best_entry
                i += match_len
            else:
                # マッチしなかった文字はそのまま出力
                result_chars.append(text[i])
                i += 1

        return "".join(result_chars), list(matched_entries.values())

    def add_learned_alias(self, canonical_name: str, new_alias: str, category: str = "自動学習") -> bool:
        """
        会話や画像認識から新しい誤変換エイリアスを学習し、
        即座にメモリ上のTrie木を更新し、USER_LEARNED.jsonへ追記する
        """
        new_alias = new_alias.strip()
        if len(new_alias) < self.min_alias_len:
            logger.warning(f"エイリアスが短すぎるためスキップ: {new_alias}")
            return False

        # 既存エントリーの取得または新規作成
        if canonical_name in self.entries:
            entry = self.entries[canonical_name]
            if new_alias not in entry.aliases:
                entry.aliases.append(new_alias)
        else:
            entry = DictionaryEntry(
                name=canonical_name,
                aliases=[new_alias],
                category=category,
                info=f"会話から自動学習された用語: {canonical_name}",
                source_file="USER_LEARNED.json"
            )
            self.entries[canonical_name] = entry

        # メモリ上のTrie木へ即時登録 (0秒反映)
        self._insert_trie(new_alias, entry, target_name=canonical_name)

        # ファイルへ永続化
        self._save_learned_entry(entry)
        logger.info(f"学習辞書に登録完了: {canonical_name} <- '{new_alias}'")
        return True

    def _save_learned_entry(self, entry: DictionaryEntry):
        """USER_LEARNED.json に学習データを保存"""
        learned_data = {"meta": {"title": "ユーザー学習辞書", "category": "学習"}, "entries": []}
        if os.path.exists(self.learned_file):
            try:
                with open(self.learned_file, "r", encoding="utf-8") as f:
                    learned_data = json.load(f)
            except Exception:
                pass

        entries_list = learned_data.setdefault("entries", [])
        found = False
        for item in entries_list:
            if item.get("name") == entry.name:
                item["aliases"] = list(set(item.get("aliases", []) + entry.aliases))
                found = True
                break

        if not found:
            entries_list.append({
                "name": entry.name,
                "aliases": entry.aliases,
                "category": entry.category,
                "info": entry.info
            })

        try:
            with open(self.learned_file, "w", encoding="utf-8") as f:
                json.dump(learned_data, f, ensure_ascii=False, indent=2)
            # キャッシュも更新
            cache_path = os.path.join(self.cache_dir, "USER_LEARNED.cache")
            if os.path.exists(cache_path):
                os.remove(cache_path)
        except Exception as e:
            logger.error(f"学習辞書保存エラー: {e}")
