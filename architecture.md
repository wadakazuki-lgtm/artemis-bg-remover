# Artemis Background Remover — アーキテクチャ

スタンドアロン GUI（Python / CustomTkinter）です。画面・編集・描画はほぼすべて `main.py` の `AvatarEditorApp` にあり、配色は `theme.py` から取り込みます。

## ソース構成

| パス | 役割 |
|------|------|
| `main.py` | エントリポイント。ウィンドウ、I/O、編集、ビューポート描画 |
| `theme.py` | ダークモードとカラー定数 |
| `requirements.txt` | `customtkinter`, `Pillow`, `rembg`, `numpy` |
| `assets/avatars/` | 起動時フォールバック用 preset（あれば） |

## コンポーネントと依存関係

```mermaid
flowchart TB
  subgraph entry["起動"]
    Main["main.py\nif __name__"]
  end

  subgraph themeMod["theme.py"]
    Theme["配色定数\nC_BG / C_PANEL など"]
  end

  subgraph app["AvatarEditorApp main.py"]
    UI["setup_ui\nキャンバス + 右パネル"]
    IO["ファイル I/O\nopen_image_dialog\nload_image / save_image"]
    State["編集状態\noriginal_img\ncurrent_img\nundo_stack / redo_stack"]
    Tools["編集ツール\napply_rembg\napply_smart_flood_fill\napply_brush"]
    History["履歴\npush_state / undo / redo"]
    Viewport["ビューポート\nzoom / pan / scroll"]
    Render["update_canvas\n可視領域クロップ + 合成"]
  end

  subgraph ext["外部ライブラリ"]
    CTk["customtkinter / tkinter"]
    PIL["Pillow"]
    Rembg["rembg.remove"]
    NP["numpy"]
  end

  subgraph disk["ファイルシステム"]
    PNG["PNG 画像"]
  end

  Main --> Theme
  Main --> UI
  Theme --> UI
  UI --> CTk
  UI --> IO
  IO --> PIL
  IO --> PNG
  IO --> State
  UI --> Tools
  Tools --> Rembg
  Tools --> PIL
  Tools --> NP
  Tools --> History
  History --> State
  UI --> Viewport
  Viewport --> Render
  State --> Render
  Render --> PIL
  Render --> CTk
```

## データの流れ（画像を開く → 編集 → 保存）

```mermaid
sequenceDiagram
  actor User as ユーザー
  participant UI as 右パネル / キャンバス
  participant IO as load_image / save_image
  participant State as current_img
  participant Hist as undo_stack
  participant Tool as rembg / flood / brush
  participant Render as update_canvas
  participant Disk as PNG ファイル

  User->>UI: 「画像を開く」
  UI->>IO: open_image_dialog
  IO->>Disk: ファイル選択
  Disk-->>IO: パス
  IO->>State: RGBA として original / current に保持
  IO->>Render: update_canvas
  Render-->>UI: キャンバスにプレビュー

  User->>UI: AI透過 / 塗りつぶし / ブラシ
  UI->>Hist: push_state 現在画像を退避
  UI->>Tool: 編集実行
  Tool->>State: current_img を更新したコピーで置換
  Tool->>Render: update_canvas
  Render-->>UI: 透過プレビュー再描画

  User->>UI: 「上書き保存」
  UI->>IO: save_image
  IO->>Disk: current_img を PNG 書き出し
```

## 状態モデル

```mermaid
flowchart LR
  File["ディスク上の PNG"] --> Orig["original_img"]
  Orig --> Curr["current_img"]
  Curr -->|"編集前に copy"| Undo["undo_stack"]
  Curr -->|"Undo 時に copy"| Redo["redo_stack"]
  Curr --> Crop["可視領域 crop"]
  Crop --> Comp["格子 / 黒 / 白 と合成"]
  Comp --> Canvas["tk.Canvas 表示"]
```

- 編集は `current_img` を直接破壊せず、コピーしたうえで差し替えます（`push_state` でスナップショット）。
- プレビュー背景（`preview_bg_mode`）は表示専用で、保存されるアルファには混ぜません。
- `apply_rembg` は実行時に `from rembg import remove` します。
