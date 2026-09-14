# Artemis Background Remover

Artemis Background Remover は、画像やアバターの背景除去と、透明度マスクの精密な編集を行うスタンドアロン GUI アプリケーションです。

## 機能
- **AI による背景除去**: `rembg` を使って、画像の背景を自動で除去します。
- **スマート塗りつぶし**: 許容値スライダーで調整しながら、近い色の連続領域をまとめて除去できます。
- **手動ブラシ**: ブラシサイズを調整できる消去・復元ブラシで、マスクを細かく整えられます。
- **高性能な無限ズームとパン**: ハードウェアアクセラレーションを使ったビューポート描画により、最大 4000% まで遅延なくズームできます。
- **ダークモード UI**: CustomTkinter で作られた、モダンなダークモードの画面です。

## インストール

仮想環境の利用を推奨します。

```bash
python -m venv .venv
source .venv/bin/activate  # Windows では .venv\Scripts\activate を使います
pip install -r requirements.txt
```

## 使い方

メインアプリケーションを起動します。

```bash
python main.py
```

### 操作
- **マウスホイール**: 縦方向のパン / ズーム（Ctrl/Cmd 同時押し）
- **Shift + ホイール**: 横方向のパン
- **右クリック / 中クリック / Space+ドラッグ**: キャンバスのパン
- **左クリック**: 選択中のツールを適用（塗りつぶし / 消去 / 復元）

## ライセンス

このプロジェクトは GNU General Public License v3.0 (GPLv3) の下でライセンスされています。
詳細は `LICENSE` ファイルを参照してください。
