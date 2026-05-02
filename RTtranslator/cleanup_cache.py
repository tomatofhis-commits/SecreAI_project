import json
import collections
from difflib import SequenceMatcher

# ===================================================================
# cleanup_cache.py — 開発用ユーティリティ（本番運用では不要）
#
# このスクリプトは translation_cache.json 内の類似キャッシュを
# 手動で一括整理するためのツールです。
# ※ 通常の起動時には TranslationController._auto_clean_cache() が
#    同等の処理を自動的に行うため、このスクリプトを実行する必要はありません。
# ===================================================================


with open('translation_cache.json', encoding='utf-8') as f:
    data = json.load(f)

new_data = collections.OrderedDict()
norm_keys = {}
deleted = 0

for k, v in data.items():
    if '::' not in k:
        new_data[k] = v
        continue
        
    text = k.split('::', 1)[1]
    norm = text.lower().replace(' ', '').replace('\n', '')
    
    found = False
    for nk, orig_k in norm_keys.items():
        if 0.5 <= len(norm)/max(len(nk),1) <= 2.0:
            if SequenceMatcher(None, norm, nk).ratio() >= 0.85:
                found = True
                break
                
    if not found:
        norm_keys[norm] = k
        new_data[k] = v
    else:
        deleted += 1

with open('translation_cache.json', 'w', encoding='utf-8') as f:
    json.dump(new_data, f, ensure_ascii=False, indent=2)

print(f"Deleted {deleted} fuzzy duplicates")
