import os
import chromadb
import json
import numpy as np

# パス設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "memory_db")

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NumpyEncoder, self).default(obj)

try:
    client = chromadb.PersistentClient(path=db_path)
    # コレクション一覧を取得
    collections = client.list_collections()
    
    if not collections:
        print("❌ 記憶データ（コレクション）が見つかりません。")
    else:
        target_name = "long_term_memory" # 指定の名前
        collection = client.get_collection(name=target_name)
        
        # 全データを取得
        results = collection.get()
        
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        ids = results.get("ids", [])

        if not docs:
            print("記憶は空です。")
        else:
            # --- 1. データを最新順（unixタイムスタンプ降順）に並べ替え ---
            combined = []
            for i in range(len(docs)):
                combined.append({
                    "id": ids[i],
                    "doc": docs[i],
                    "meta": metas[i] if metas else {}
                })
            
            # unixの値でソート（値がない場合は0にする）
            combined.sort(key=lambda x: x["meta"].get("unix", 0), reverse=True)

            # --- 2. コンソール表示 ---
            print(f"\n=== {target_name} の中身 (最新順) ===")
            for item in combined:
                date_str = item["meta"].get("timestamp") or item["meta"].get("date") or "日時不明"
                # IDと日時を表示してから、内容を表示
                print(f"【{date_str} / {item['id']}】")
                print(f"{item['doc']}")
                print("-" * 50)

            # --- 3. JSON/TXTファイルへのエクスポート ---
            # JSON保存
            json_path = os.path.join(BASE_DIR, "memory_export.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(combined, f, ensure_ascii=False, indent=4, cls=NumpyEncoder)
            
            # TXT保存
            txt_path = os.path.join(BASE_DIR, "memory_export.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"--- SecreAI Memory Export (Latest First) ---\n\n")
                for item in combined:
                    date_str = item["meta"].get("timestamp") or item["meta"].get("date") or "日時不明"
                    f.write(f"日時: {date_str}\nID: {item['id']}\n内容: {item['doc']}\n")
                    f.write("-" * 30 + "\n")

            print(f"\n✅ ファイルに保存しました:")
            print(f"📁 TXT : {txt_path}")
            print(f"📁 JSON: {json_path}")

except Exception as e:
    print(f"❌ エラーが発生しました: {e}")