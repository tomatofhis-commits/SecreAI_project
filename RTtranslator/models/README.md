# models/ ディレクトリ

ここに fastText の言語判定モデルを配置してください。

## fastText 軽量モデルのダウンロード（lid.176.ftz）

以下のいずれかの方法で `lid.176.ftz` をこのフォルダに配置してください。

### PowerShell でダウンロード

```powershell
# このフォルダ (D:\Real_Time_Translate\models\) をカレントにして実行
Invoke-WebRequest -Uri "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz" -OutFile "lid.176.ftz"
```

### または直接ダウンロードして配置

[https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz](https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz)

ファイルサイズは約917KBです。 `lid.176.bin`（高精度・大きい）も利用可能ですが、`.ftz`で十分な精度が出ます。

---

## PaddleOCR のモデルについて

PaddleOCR のモデル（Server版）は `paddleocr` ライブラリの初回実行時に自動的にユーザーディレクトリへダウンロードされます。
このフォルダへの配置は不要です。
