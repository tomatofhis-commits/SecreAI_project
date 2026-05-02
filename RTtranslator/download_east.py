import os
import urllib.request

def download_east_model():
    url = "https://github.com/oyyd/frozen_east_text_detection.pb/raw/master/frozen_east_text_detection.pb"
    filename = "frozen_east_text_detection.pb"
    
    if os.path.exists(filename):
        print(f"[EAST] {filename} は既に存在します。")
        return True
        
    print(f"[EAST] モデルファイルをダウンロード中... ({url})")
    try:
        # 進捗表示付きでダウンロード
        def report(blocknum, blocksize, totalsize):
            readsofar = blocknum * blocksize
            if totalsize > 0:
                percent = readsofar * 1e2 / totalsize
                s = f"\r[EAST] ダウンロード進行状況: {percent:.1f}%"
                print(s, end="")
            else:
                print(f"\r[EAST] ダウンロード中: {readsofar} bytes", end="")
                
        urllib.request.urlretrieve(url, filename, report)
        print("\n[EAST] ダウンロード完了！")
        return True
    except Exception as e:
        print(f"\n[EAST] ダウンロード失敗: {e}")
        # 代替URLを試す（もしあれば）
        return False

if __name__ == "__main__":
    download_east_model()
