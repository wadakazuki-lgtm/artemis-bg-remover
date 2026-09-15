# ==============================================================================
# AVATAR EDITOR - BACKGROUND TRANSPARENCY & MASK MANIPULATOR
#
# 【設計・高速化コンセプト】
# 1. ビューポートクリッピングレンダリング (Viewport-based Crop Rendering)
#    画像を拡大した際、画像全体をリサイズするのではなく、キャンバスの可視領域 (Viewport) に
#    対応する元画像部分だけを crop 切り出し、画面サイズ以下に制限して resize 合成する。
#    これにより、何千％にズームしても画像処理負荷が O(1) (常に一定) に保たれ、極めて滑らかに動作する。
#
# 2. 倍乗タイリング (O(log N) Checkerboard Generation)
#    チェッカーボードパターンの生成において、二重ループによるタイルの貼り付けを廃止。
#    初期パターンを bg.paste(bg.crop(...)) を用いて幅・高さを2のべき乗でコピー拡張する。
#    Pythonのループオーバーヘッドを排除し、タイリング処理時間をミリ秒以下に短縮する。
#
# 3. 位相ズレ補正 (Scroll Phase Offset Correction)
#    切り出されたクロップ座標の端数から市松模様の位相ズレ (phase_x, phase_y) を算出して補正する。
#    スクロールバー操作やドラッグ (パン) 時にも背景の市松模様が動かず固定されている視覚効果を作る。
# ==============================================================================

import math
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

from flood_fill import smart_flood_fill_transparent

# 既存のテーマ設定を取り込む
try:
    from theme import (
        C_BG,
        C_DANGER,
        C_DANGER_HOVER,
        C_PANEL,
        C_PRIMARY,
        C_PRIMARY_HOVER,
        C_SECONDARY,
        C_SECONDARY_HOVER,
        C_TEXT,
        C_TEXT_LIGHT,
    )
    # 文字列の場合はタプルにノーマライズ
    C_BG = (C_BG, C_BG) if isinstance(C_BG, str) else C_BG
    C_PANEL = (C_PANEL, C_PANEL) if isinstance(C_PANEL, str) else C_PANEL
    C_TEXT = (C_TEXT, C_TEXT) if isinstance(C_TEXT, str) else C_TEXT
    C_TEXT_LIGHT = (C_TEXT_LIGHT, C_TEXT_LIGHT) if isinstance(C_TEXT_LIGHT, str) else C_TEXT_LIGHT
    C_PRIMARY = (C_PRIMARY, C_PRIMARY) if isinstance(C_PRIMARY, str) else C_PRIMARY
    C_PRIMARY_HOVER = (C_PRIMARY_HOVER, C_PRIMARY_HOVER) if isinstance(C_PRIMARY_HOVER, str) else C_PRIMARY_HOVER
    C_SECONDARY = (C_SECONDARY, C_SECONDARY) if isinstance(C_SECONDARY, str) else C_SECONDARY
    C_SECONDARY_HOVER = (C_SECONDARY_HOVER, C_SECONDARY_HOVER) if isinstance(C_SECONDARY_HOVER, str) else C_SECONDARY_HOVER
    C_DANGER = (C_DANGER, C_DANGER) if isinstance(C_DANGER, str) else C_DANGER
    C_DANGER_HOVER = (C_DANGER_HOVER, C_DANGER_HOVER) if isinstance(C_DANGER_HOVER, str) else C_DANGER_HOVER
except Exception:
    # フォールバックテーマ
    C_BG = ("#F5F5F7", "#161617")
    C_PANEL = ("#FFFFFF", "#1E1E1F")
    C_TEXT = ("#1D1D1F", "#F5F5F7")
    C_TEXT_LIGHT = ("#86868B", "#8E8E93")
    C_PRIMARY = ("#0071E3", "#0A84FF")
    C_PRIMARY_HOVER = ("#005BB5", "#0064D2")
    C_SECONDARY = ("#E8E8ED", "#323236")
    C_SECONDARY_HOVER = ("#D2D2D7", "#48484A")
    C_DANGER = ("#FF453A", "#FF453A")
    C_DANGER_HOVER = ("#D1241B", "#D1241B")

class AvatarEditorApp(ctk.CTk):
    def __init__(self, initial_image_path=None):
        super().__init__()
        
        self.title("Artemis Pro Avatar Transparency & Mask Editor")
        self.geometry("1200x850")
        self.lift()
        self.focus_force()
        # macOS/Windowsで他のウィンドウに隠れないよう起動時のみ最前面化し、その後解除する
        self._set_topmost_safe(True)
        self.after(500, lambda: self._set_topmost_safe(False))
        
        # 外観のカラー設定
        self.configure(fg_color=C_BG[1])

        
        # 編集対象データ
        self.image_path = initial_image_path
        self.original_img = None  # PIL.Image.Image (RGBA)
        self.current_img = None   # PIL.Image.Image (RGBA)
        
        # Undo / Redo スタック
        self.undo_stack = []
        self.redo_stack = []
        self.max_stack_size = 30
        
        # ズーム・パン状態
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.scroll_speed = 2
        
        # ツール選択状態
        self.active_tool = "flood_fill"  # "flood_fill", "brush_erase", "brush_restore", "pan"
        self.brush_size = 15
        self.tolerance = 30
        
        # プレビュー表示設定
        self.preview_bg_mode = "checkerboard"  # "checkerboard", "black", "white"
        
        # UI初期化
        self.setup_ui()
        
        # 画像ロード
        if self.image_path and os.path.exists(self.image_path):
            self.load_image(self.image_path)
        else:
            self.load_fallback_image()
            
    def setup_ui(self):
        # メインコンテナのレイアウト
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=3) # キャンバス領域
        self.grid_columnconfigure(1, weight=1) # コントロールパネル領域
        self.grid_columnconfigure(1, minsize=320)
        
        # ==========================================
        # 左側: キャンバス領域（スクロールバー対応）
        # ==========================================
        self.canvas_container = ctk.CTkFrame(self, fg_color=C_BG[1], corner_radius=0)
        self.canvas_container.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.canvas_container.grid_rowconfigure(0, weight=1)
        self.canvas_container.grid_columnconfigure(0, weight=1)
        
        # 縦横スクロールバー
        self.v_scrollbar = tk.Scrollbar(self.canvas_container, orient="vertical")
        self.v_scrollbar.grid(row=0, column=1, sticky="ns")
        
        self.h_scrollbar = tk.Scrollbar(self.canvas_container, orient="horizontal")
        self.h_scrollbar.grid(row=1, column=0, sticky="ew")
        
        self.canvas = tk.Canvas(
            self.canvas_container,
            bg="#161617",
            highlightthickness=0,
            cursor="crosshair",
            xscrollcommand=self.h_scrollbar.set,
            yscrollcommand=self.v_scrollbar.set
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        
        self.v_scrollbar.config(command=lambda *args: (self.canvas.yview(*args), self.update_canvas()))
        self.h_scrollbar.config(command=lambda *args: (self.canvas.xview(*args), self.update_canvas()))
        
        # キャンバスイベントバインド
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Button-2>", self.start_pan) # Mac/Wheel button
        self.canvas.bind("<B2-Motion>", self.pan_image)
        self.canvas.bind("<Button-3>", self.start_pan) # Right click
        self.canvas.bind("<B3-Motion>", self.pan_image)
        # マウスホイール・タッチパッドのバインド（スクロールとズームの分離）
        self.canvas.bind("<MouseWheel>", self.on_scroll_y)         # 上下スクロール
        self.canvas.bind("<Shift-MouseWheel>", self.on_scroll_x)   # 左右スクロール
        self.canvas.bind("<Command-MouseWheel>", self.on_zoom)     # Mac: Command + スクロールでズーム
        self.canvas.bind("<Control-MouseWheel>", self.on_zoom)     # Windows/Linux: Control + スクロールでズーム
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        
        # Spaceキーでの一時的なPanツール切り替え
        self.bind("<KeyPress-space>", self.on_space_press)
        self.bind("<KeyRelease-space>", self.on_space_release)
        self.is_space_pressed = False
        
        # ==========================================
        # 右側: コントロールパネル
        # ==========================================
        self.control_panel = ctk.CTkFrame(self, fg_color=C_PANEL[1], corner_radius=12, border_width=1, border_color="#323236")
        self.control_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 15), pady=15)
        
        # パネルタイトル
        title_label = ctk.CTkLabel(
            self.control_panel,
            text="AVATAR EDITOR",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=C_TEXT[1]
        )
        title_label.pack(anchor="w", padx=20, pady=(20, 10))
        
        # ------------------------------------------
        # セクション 1: ファイル操作
        # ------------------------------------------
        btn_frame = ctk.CTkFrame(self.control_panel, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=5)
        
        self.btn_open = ctk.CTkButton(
            btn_frame, text="画像を開く", command=self.open_image_dialog,
            fg_color=C_SECONDARY[1], hover_color=C_SECONDARY_HOVER[1], text_color=C_TEXT[1]
        )
        self.btn_open.pack(side="left", expand=True, fill="x", padx=(0, 5))
        
        self.btn_save = ctk.CTkButton(
            btn_frame, text="上書き保存", command=self.save_image,
            fg_color=C_PRIMARY[1], hover_color=C_PRIMARY_HOVER[1], text_color="#FFFFFF"
        )
        self.btn_save.pack(side="right", expand=True, fill="x", padx=(5, 0))
        
        # ------------------------------------------
        # セクション 2: AI背景透過
        # ------------------------------------------
        ai_frame = ctk.CTkFrame(self.control_panel, fg_color="#242426", corner_radius=8)
        ai_frame.pack(fill="x", padx=15, pady=10)
        
        ai_label = ctk.CTkLabel(
            ai_frame, text="AIアシスト切り抜き (rembg)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=C_TEXT_LIGHT[1]
        )
        ai_label.pack(anchor="w", padx=10, pady=(8, 2))
        
        self.btn_rembg = ctk.CTkButton(
            ai_frame, text="AIで外側の背景を自動透過", command=self.apply_rembg,
            fg_color="#30d158", hover_color="#248a3d", text_color="#FFFFFF"
        )
        self.btn_rembg.pack(fill="x", padx=10, pady=(2, 10))
        
        # ------------------------------------------
        # セクション 3: ツール選択
        # ------------------------------------------
        tool_label = ctk.CTkLabel(
            self.control_panel, text="編集ツール",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=C_TEXT[1]
        )
        tool_label.pack(anchor="w", padx=20, pady=(15, 5))
        
        # ツールセグメントボタン
        self.tool_var = tk.StringVar(value="flood_fill")
        self.btn_tool_fill = ctk.CTkRadioButton(
            self.control_panel, text="類似領域を一括透過 (クリック)", value="flood_fill",
            variable=self.tool_var, command=self.change_tool, text_color=C_TEXT[1]
        )
        self.btn_tool_fill.pack(anchor="w", padx=25, pady=5)
        
        self.btn_tool_erase = ctk.CTkRadioButton(
            self.control_panel, text="手動消しゴム (なぞって透過)", value="brush_erase",
            variable=self.tool_var, command=self.change_tool, text_color=C_TEXT[1]
        )
        self.btn_tool_erase.pack(anchor="w", padx=25, pady=5)
        
        self.btn_tool_restore = ctk.CTkRadioButton(
            self.control_panel, text="透過復元ブラシ (なぞって復活)", value="brush_restore",
            variable=self.tool_var, command=self.change_tool, text_color=C_TEXT[1]
        )
        self.btn_tool_restore.pack(anchor="w", padx=25, pady=5)
        
        # ------------------------------------------
        # セクション 4: スライダーパラメーター
        # ------------------------------------------
        # 許容誤差スライダー (Flood Fill用)
        self.tolerance_frame = ctk.CTkFrame(self.control_panel, fg_color="transparent")
        self.tolerance_frame.pack(fill="x", padx=20, pady=(10, 5))
        
        self.lbl_tolerance = ctk.CTkLabel(
            self.tolerance_frame, text=f"透過色の許容誤差: {self.tolerance}",
            font=ctk.CTkFont(size=12), text_color=C_TEXT[1]
        )
        self.lbl_tolerance.pack(anchor="w")
        
        self.slider_tolerance = ctk.CTkSlider(
            self.tolerance_frame, from_=0, to=150, number_of_steps=150,
            command=self.update_tolerance, progress_color=C_PRIMARY[1]
        )
        self.slider_tolerance.set(self.tolerance)
        self.slider_tolerance.pack(fill="x", pady=2)
        
        # ブラシサイズスライダー
        self.brush_frame = ctk.CTkFrame(self.control_panel, fg_color="transparent")
        self.brush_frame.pack(fill="x", padx=20, pady=5)
        
        self.lbl_brush = ctk.CTkLabel(
            self.brush_frame, text=f"ブラシの大きさ: {self.brush_size} px",
            font=ctk.CTkFont(size=12), text_color=C_TEXT[1]
        )
        self.lbl_brush.pack(anchor="w")
        
        self.slider_brush = ctk.CTkSlider(
            self.brush_frame, from_=2, to=100, number_of_steps=98,
            command=self.update_brush_size, progress_color=C_PRIMARY[1]
        )
        self.slider_brush.set(self.brush_size)
        self.slider_brush.pack(fill="x", pady=2)
        
        # スクロール感度スライダー
        self.scroll_frame = ctk.CTkFrame(self.control_panel, fg_color="transparent")
        self.scroll_frame.pack(fill="x", padx=20, pady=5)
        
        self.lbl_scroll = ctk.CTkLabel(
            self.scroll_frame, text=f"スクロール感度: {self.scroll_speed}x",
            font=ctk.CTkFont(size=12), text_color=C_TEXT[1]
        )
        self.lbl_scroll.pack(anchor="w")
        
        self.slider_scroll = ctk.CTkSlider(
            self.scroll_frame, from_=1, to=10, number_of_steps=9,
            command=self.update_scroll_speed, progress_color=C_PRIMARY[1]
        )
        self.slider_scroll.set(self.scroll_speed)
        self.slider_scroll.pack(fill="x", pady=2)
        
        # ------------------------------------------
        # セクション 5: プレビュー背景トグル
        # ------------------------------------------
        bg_label = ctk.CTkLabel(
            self.control_panel, text="背景プレビューの切り替え",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=C_TEXT[1]
        )
        bg_label.pack(anchor="w", padx=20, pady=(15, 5))
        
        bg_btn_frame = ctk.CTkFrame(self.control_panel, fg_color="transparent")
        bg_btn_frame.pack(fill="x", padx=15, pady=5)
        
        self.bg_segmented = ctk.CTkSegmentedButton(
            bg_btn_frame,
            values=["格子模様", "黒背景", "白背景"],
            command=self.change_bg_preview
        )
        self.bg_segmented.set("格子模様")
        self.bg_segmented.pack(fill="x")
        
        # ------------------------------------------
        # セクション 6: Undo / Redo & ズーム初期化
        # ------------------------------------------
        history_frame = ctk.CTkFrame(self.control_panel, fg_color="transparent")
        history_frame.pack(fill="x", padx=15, pady=15)
        
        self.btn_undo = ctk.CTkButton(
            history_frame, text="元に戻す", command=self.undo, width=80,
            fg_color=C_SECONDARY[1], hover_color=C_SECONDARY_HOVER[1], text_color=C_TEXT[1]
        )
        self.btn_undo.pack(side="left", expand=True, fill="x", padx=(0, 2))
        
        self.btn_redo = ctk.CTkButton(
            history_frame, text="やり直す", command=self.redo, width=80,
            fg_color=C_SECONDARY[1], hover_color=C_SECONDARY_HOVER[1], text_color=C_TEXT[1]
        )
        self.btn_redo.pack(side="left", expand=True, fill="x", padx=2)
        
        self.btn_reset_zoom = ctk.CTkButton(
            history_frame, text="等倍リセット", command=self.reset_zoom, width=90,
            fg_color=C_SECONDARY[1], hover_color=C_SECONDARY_HOVER[1], text_color=C_TEXT[1]
        )
        self.btn_reset_zoom.pack(side="left", expand=True, fill="x", padx=(2, 0))
        
        # ------------------------------------------
        # セクション 7: ズームコントロールボタン (追加)
        # ------------------------------------------
        self.lbl_zoom_percent = ctk.CTkLabel(
            self.control_panel, text="ズーム倍率: 100%",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=C_TEXT[1]
        )
        self.lbl_zoom_percent.pack(anchor="w", padx=20, pady=(10, 2))

        zoom_btn_frame = ctk.CTkFrame(self.control_panel, fg_color="transparent")
        zoom_btn_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        self.btn_zoom_in = ctk.CTkButton(
            zoom_btn_frame, text="🔍 拡大 (+)", command=self.zoom_in,
            fg_color=C_SECONDARY[1], hover_color=C_SECONDARY_HOVER[1], text_color=C_TEXT[1]
        )
        self.btn_zoom_in.pack(side="left", expand=True, fill="x", padx=(0, 2))
        
        self.btn_zoom_out = ctk.CTkButton(
            zoom_btn_frame, text="🔍 縮小 (-)", command=self.zoom_out,
            fg_color=C_SECONDARY[1], hover_color=C_SECONDARY_HOVER[1], text_color=C_TEXT[1]
        )
        self.btn_zoom_out.pack(side="left", expand=True, fill="x", padx=(2, 0))
        
        # ------------------------------------------
        # ステータスバー（最下部情報）
        # ------------------------------------------
        self.lbl_status = ctk.CTkLabel(
            self.control_panel, text="画像を読み込んでください",
            font=ctk.CTkFont(size=11), text_color=C_TEXT_LIGHT[1]
        )
        self.lbl_status.pack(side="bottom", fill="x", pady=15, padx=20)
        
    # ==========================================
    # 画像ロード & 表示マネージャ
    # ==========================================
    def zoom_in(self):
        # 画面中央付近を基準に拡大
        cw = self.canvas.winfo_width() / 2
        ch = self.canvas.winfo_height() / 2
        old_zoom = self.zoom_level
        self.zoom_level = min(40.0, self.zoom_level * 1.25)
        self.pan_x = cw - (cw - self.pan_x) * (self.zoom_level / old_zoom)
        self.pan_y = ch - (ch - self.pan_y) * (self.zoom_level / old_zoom)
        self.update_canvas()

    def zoom_out(self):
        # 画面中央付近を基準に縮小
        cw = self.canvas.winfo_width() / 2
        ch = self.canvas.winfo_height() / 2
        old_zoom = self.zoom_level
        self.zoom_level = max(0.05, self.zoom_level / 1.25)
        self.pan_x = cw - (cw - self.pan_x) * (self.zoom_level / old_zoom)
        self.pan_y = ch - (ch - self.pan_y) * (self.zoom_level / old_zoom)
        self.update_canvas()

    def _set_topmost_safe(self, enabled: bool) -> None:
        # Tkの最前面属性を設定する（非対応・失敗時は例外を握りつぶさず stderr に出す）
        try:
            self.attributes("-topmost", enabled)
        except tk.TclError as err:
            print(
                f"[警告] -topmost の設定に失敗しました (enabled={enabled}): {err}",
                file=sys.stderr,
            )

    def _run_with_modal_focus(self, action):
        # ファイルダイアログ等の前に最前面固定を解除し、終了後も常時最前面には戻さない
        self._set_topmost_safe(False)
        try:
            return action()
        finally:
            self._set_topmost_safe(False)

    def _show_error_dialog(self, title: str, message: str) -> None:
        # messagebox がメインウィンドウの裏に隠れないよう、表示中だけ最前面を解除する
        def show_error() -> None:
            messagebox.showerror(title, message)

        self._run_with_modal_focus(show_error)

    def load_image(self, path):
        try:
            self.image_path = path
            img = Image.open(path)
            self.original_img = img.convert("RGBA")
            self.current_img = self.original_img.copy()
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.reset_zoom()
            self.lbl_status.configure(text=f"読込完了: {os.path.basename(path)} ({img.width}x{img.height})")
            self.update_canvas()
        except Exception as e:
            self._show_error_dialog("エラー", f"画像の読み込みに失敗しました:\n{e}")

    def load_fallback_image(self):
        # ワークスペース内の preset アバターを探索
        import glob
        presets = glob.glob("assets/avatars/preset_*.png")
        if presets:
            self.load_image(presets[0])
        else:
            # モックイメージを生成
            mock = Image.new("RGBA", (500, 500), (255, 255, 255, 255))
            # 白背景にシンプルなグラデーションを描画
            pixels = mock.load()
            for x in range(500):
                for y in range(500):
                    if (x-250)**2 + (y-250)**2 < 180**2:
                        pixels[x, y] = (150, 100, 250, 255) # 円形オブジェクト
            self.original_img = mock
            self.current_img = self.original_img.copy()
            self.reset_zoom()
            self.update_canvas()
            self.lbl_status.configure(text="アバター画像が見つからないため、一時的なプレースホルダーを表示中")
            
    def open_image_dialog(self):
        def pick_open_path() -> str:
            return filedialog.askopenfilename(
                parent=self,
                filetypes=[("PNG Images", "*.png"), ("All Files", "*.*")],
            )

        path = self._run_with_modal_focus(pick_open_path)
        if path:
            self.load_image(path)

    def save_image(self):
        if not self.image_path:

            def pick_save_path() -> str:
                return filedialog.asksaveasfilename(
                    parent=self,
                    defaultextension=".png",
                    filetypes=[("PNG Image", "*.png")],
                )

            path = self._run_with_modal_focus(pick_save_path)
            if not path:
                return
            self.image_path = path

        try:
            self.current_img.save(self.image_path, "PNG")
            # 保存完了はステータスバーのみで通知する（モーダル不要のためダイアログは出さない）
            self.lbl_status.configure(
                text=f"✓ 保存完了: {os.path.basename(self.image_path)}"
            )
        except PermissionError:
            self.lbl_status.configure(text="⚠ 保存失敗: ファイルが使用中です")
            self._show_error_dialog(
                "保存エラー",
                f"ファイルへの書き込み権限がありません:\n{self.image_path}",
            )
        except Exception as e:
            self.lbl_status.configure(text=f"⚠ 保存失敗: {e}")
            self._show_error_dialog("保存エラー", f"画像の保存に失敗しました:\n{e}")

    # ==========================================
    # 画像編集ロジック (Undo/Redo 含む)
    # ==========================================
    def push_state(self):
        # スタックサイズ制限
        if len(self.undo_stack) >= self.max_stack_size:
            self.undo_stack.pop(0)
        self.undo_stack.append(self.current_img.copy())
        self.redo_stack.clear() # 新しい操作があったらRedoを消去
        
    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.current_img.copy())
            self.current_img = self.undo_stack.pop()
            self.update_canvas()
            self.lbl_status.configure(text="「元に戻す(Undo)」を実行しました。")
        else:
            self.lbl_status.configure(text="これ以上元に戻せません。")
            
    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.current_img.copy())
            self.current_img = self.redo_stack.pop()
            self.update_canvas()
            self.lbl_status.configure(text="「やり直す(Redo)」を実行しました。")
        else:
            self.lbl_status.configure(text="これ以上やり直せません。")

    # ==========================================
    # ツールアクション処理
    # ==========================================
    def change_tool(self):
        self.active_tool = self.tool_var.get()
        self.lbl_status.configure(text=f"ツール変更: {self.active_tool}")
        if self.active_tool == "flood_fill":
            self.canvas.configure(cursor="crosshair")
        elif self.active_tool in ["brush_erase", "brush_restore"]:
            self.canvas.configure(cursor="circle")
        else:
            self.canvas.configure(cursor="fleur")
            
    def update_tolerance(self, val):
        self.tolerance = int(val)
        self.lbl_tolerance.configure(text=f"透過色の許容誤差: {self.tolerance}")
        
    def update_brush_size(self, val):
        self.brush_size = int(val)
        self.lbl_brush.configure(text=f"ブラシの大きさ: {self.brush_size} px")

    def update_scroll_speed(self, val):
        self.scroll_speed = int(float(val))
        self.lbl_scroll.configure(text=f"スクロール感度: {self.scroll_speed}x")

    def change_bg_preview(self, mode_str):
        if mode_str == "格子模様":
            self.preview_bg_mode = "checkerboard"
        elif mode_str == "黒背景":
            self.preview_bg_mode = "black"
        else:
            self.preview_bg_mode = "white"
        self.update_canvas()

    # AI背景透過の適用
    def apply_rembg(self):
        if not self.current_img:
            return
        
        self.lbl_status.configure(text="AI背景透過処理中...")
        self.update() # UI更新を強制
        
        try:
            from rembg import remove
            self.push_state()
            # rembg.remove にPIL画像を渡して処理
            output_img = remove(self.current_img)
            self.current_img = output_img
            self.update_canvas()
            self.lbl_status.configure(text="AI背景透過が成功しました！残った内側を調整してください。")
        except ImportError:
            self._show_error_dialog(
                "インポートエラー",
                "rembg ライブラリがロードできません。仮想環境の依存関係を確認してください。",
            )
            self.lbl_status.configure(text="AI背景透過に失敗しました（ライブラリ不在）")
        except Exception as e:
            self._show_error_dialog("エラー", f"AI背景透過実行中にエラーが発生しました:\n{e}")
            self.lbl_status.configure(text="AI背景透過エラー")

    # ==========================================
    # 高度な Flood Fill 透過アルゴリズム
    # ==========================================
    def apply_smart_flood_fill(self, start_x, start_y):
        # GUI から核ロジックへ委譲する（詳細は flood_fill.py / 回帰テスト参照）
        if self.current_img is None:
            return

        result = smart_flood_fill_transparent(
            self.current_img,
            start_x,
            start_y,
            self.tolerance,
        )

        # 透明起点など「変更なし」のときは Undo 履歴を積まない
        if not result.changed:
            self.lbl_status.configure(text=result.message)
            return

        self.push_state()
        self.current_img = result.image
        self.update_canvas()
        self.lbl_status.configure(text=result.message)

    # ==========================================
    # ブラシ（手動消しゴム・復元）
    # ==========================================
    def apply_brush(self, px, py, is_erase=True):
        # 描画対象のキャンバスから元のピクセル座標を算出してペイント
        img = self.current_img.copy()
        width, height = img.size
        pixels = img.load()
        orig_pixels = self.original_img.load()
        
        r = self.brush_size
        
        # ブラシの円形領域にペイント
        for x in range(max(0, px - r), min(width, px + r + 1)):
            for y in range(max(0, py - r), min(height, py + r + 1)):
                # 円形ブラシ内の判定
                if (x - px)**2 + (y - py)**2 <= r**2:
                    if is_erase:
                        # 完全に透過
                        pixels[x, y] = (0, 0, 0, 0)
                    else:
                        # オリジナルアバター（不透過）の色で復元
                        pixels[x, y] = orig_pixels[x, y]
                        
        self.current_img = img
        self.update_canvas()

    # ==========================================
    # ズーム & パン Canvas イベント
    # ==========================================
    def reset_zoom(self):
        if not self.current_img:
            return
        
        self.update_idletasks()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            cw, ch = 800, 750 # 初期フォールバック
            
        iw, ih = self.current_img.size
        
        # 画面に丁度収まる倍率を計算
        ratio_w = cw / iw
        ratio_h = ch / ih
        self.zoom_level = min(ratio_w, ratio_h, 1.0) * 0.95
        if self.zoom_level < 0.1:
            self.zoom_level = 0.1
            
        # 画像中央揃え
        self.pan_x = (cw - iw * self.zoom_level) / 2
        self.pan_y = (ch - ih * self.zoom_level) / 2
        self.update_canvas()

    def on_scroll_y(self, event):
        # 上下スクロール
        self.pan_y += event.delta * self.scroll_speed
        self.update_canvas()

    def on_scroll_x(self, event):
        # 左右スクロール
        self.pan_x += event.delta * self.scroll_speed
        self.update_canvas()

    def on_zoom(self, event):
        # スクロールによる拡大・縮小
        old_zoom = self.zoom_level
        if event.delta > 0: # Wheel up
            self.zoom_level *= 1.15
        else: # Wheel down
            self.zoom_level /= 1.15
            
        # 限界の設定
        self.zoom_level = max(0.05, min(self.zoom_level, 40.0))
        
        # マウスポインタのある位置を固定して拡大するようにパンを再計算
        mx, my = event.x, event.y
        self.pan_x = mx - (mx - self.pan_x) * (self.zoom_level / old_zoom)
        self.pan_y = my - (my - self.pan_y) * (self.zoom_level / old_zoom)
        
        self.update_canvas()
        
    def start_pan(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        
    def pan_image(self, event):
        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y
        self.pan_x += dx
        self.pan_y += dy
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.update_canvas()
        
    def on_space_press(self, event):
        if not self.is_space_pressed:
            self.is_space_pressed = True
            self.canvas.configure(cursor="fleur")
            
    def on_space_release(self, event):
        self.is_space_pressed = False
        self.change_tool()

    # ==========================================
    # クリック・ドラッグ（描画系アクション）
    # ==========================================
    def get_image_pixel_coords(self, canvas_x, canvas_y):
        # キャンバス座標を元画像のピクセルインデックスに逆変換 (スクロールオフセットを考慮)
        if not self.current_img:
            return None
        
        # スクロールオフセットを加味した正確なキャンバス座標
        scrolled_x = self.canvas.canvasx(canvas_x)
        scrolled_y = self.canvas.canvasy(canvas_y)
        
        px = int((scrolled_x - self.pan_x) / self.zoom_level)
        py = int((scrolled_y - self.pan_y) / self.zoom_level)
        
        iw, ih = self.current_img.size
        if 0 <= px < iw and 0 <= py < ih:
            return px, py
        return None
        
    def on_canvas_click(self, event):
        # 右クリック・中クリック・Spaceキー押下中はPanモードを優先
        if self.is_space_pressed:
            self.start_pan(event)
            return
            
        coords = self.get_image_pixel_coords(event.x, event.y)
        if not coords:
            return
            
        px, py = coords
        
        if self.active_tool == "flood_fill":
            self.apply_smart_flood_fill(px, py)
        elif self.active_tool in ["brush_erase", "brush_restore"]:
            self.push_state()
            self.apply_brush(px, py, is_erase=(self.active_tool == "brush_erase"))
            
    def on_canvas_drag(self, event):
        if self.is_space_pressed:
            self.pan_image(event)
            return
            
        if self.active_tool in ["brush_erase", "brush_restore"]:
            coords = self.get_image_pixel_coords(event.x, event.y)
            if coords:
                px, py = coords
                self.apply_brush(px, py, is_erase=(self.active_tool == "brush_erase"))
                
    def on_canvas_release(self, event):
        pass
        
    def on_canvas_resize(self, event):
        # 描画位置調整（初回のみ自動リセット）
        if not hasattr(self, "_canvas_initialized"):
            self._canvas_initialized = True
            self.after(100, self.reset_zoom)

    # ==========================================
    # レンダラー: 市松模様背景 + 透過イメージの描画
    # 可視領域 (Viewport) に限定して切り出し処理を行うことで処理負荷を O(1) に抑える
    # ==========================================
    def update_canvas(self):
        if not self.current_img:
            return
            
        # ズーム倍率ラベルの更新
        if hasattr(self, 'lbl_zoom_percent'):
            self.lbl_zoom_percent.configure(text=f"ズーム倍率: {int(self.zoom_level * 100)}%")
            
        # キャンバスサイズ取得
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            return
            
        # 表示サイズ全体の計算
        iw, ih = self.current_img.size
        tw = int(iw * self.zoom_level)
        th = int(ih * self.zoom_level)
        
        if tw <= 0 or th <= 0:
            return
            
        # キャンバスの現在のスクロール位置を考慮した可視領域の計算
        cx1 = self.canvas.canvasx(0)
        cy1 = self.canvas.canvasy(0)
        cx2 = self.canvas.canvasx(cw)
        cy2 = self.canvas.canvasy(ch)

        # 画面内に見える部分の計算 (クリッピング領域)
        vx1 = max(0, cx1 - self.pan_x)
        vy1 = max(0, cy1 - self.pan_y)
        vx2 = min(tw, cx2 - self.pan_x)
        vy2 = min(th, cy2 - self.pan_y)
        
        if vx2 <= vx1 or vy2 <= vy1:
            # 画面外の場合はキャンバスをクリアして終了
            self.canvas.delete("all")
            return
            
        # 元画像上のピクセル座標に逆算
        ix1 = int(vx1 / self.zoom_level)
        iy1 = int(vy1 / self.zoom_level)
        ix2 = int(math.ceil(vx2 / self.zoom_level))
        iy2 = int(math.ceil(vy2 / self.zoom_level))
        
        # 境界値クランプ
        ix1 = max(0, min(iw - 1, ix1))
        iy1 = max(0, min(ih - 1, iy1))
        ix2 = max(ix1 + 1, min(iw, ix2))
        iy2 = max(iy1 + 1, min(ih, iy2))
        
        # 1. 見えている範囲だけ元画像からクロップ
        cropped_img = self.current_img.crop((ix1, iy1, ix2, iy2))
        
        # キャンバス上での表示ピクセルサイズ
        tw_crop = int((ix2 - ix1) * self.zoom_level)
        th_crop = int((iy2 - iy1) * self.zoom_level)
        
        if tw_crop <= 0 or th_crop <= 0:
            return
            
        # 2. プレビュー用背景画像の構築 (画面に見えるクロップ幅だけ生成)
        bg = Image.new("RGB", (tw_crop, th_crop))
        if self.preview_bg_mode == "checkerboard":
            # 高性能なチェッカーボードパターン生成
            square_size = 16 # 格子のピクセルサイズ
            # クロップのズレを考慮した位相の計算
            phase_x = int(ix1 * self.zoom_level) % (square_size * 2)
            phase_y = int(iy1 * self.zoom_level) % (square_size * 2)
            
            checker = Image.new("RGB", (square_size * 2, square_size * 2))
            c_pixels = checker.load()
            for x in range(square_size * 2):
                for y in range(square_size * 2):
                    # 市松模様
                    color = (255, 255, 255) if ((x < square_size) ^ (y < square_size)) else (204, 204, 204)
                    c_pixels[x, y] = color
            
            # クロップ位置の位相ズレを補正しつつ高速タイリング
            bg_extended = Image.new("RGB", (tw_crop + square_size * 2, th_crop + square_size * 2))
            bg_extended.paste(checker, (0, 0))
            w_cur, h_cur = square_size * 2, square_size * 2
            while w_cur < tw_crop + square_size * 2:
                bg_extended.paste(bg_extended.crop((0, 0, w_cur, h_cur)), (w_cur, 0))
                w_cur *= 2
            while h_cur < th_crop + square_size * 2:
                bg_extended.paste(bg_extended.crop((0, 0, tw_crop + square_size * 2, h_cur)), (0, h_cur))
                h_cur *= 2
                
            bg = bg_extended.crop((phase_x, phase_y, phase_x + tw_crop, phase_y + th_crop))
        elif self.preview_bg_mode == "black":
            bg = Image.new("RGB", (tw_crop, th_crop), (0, 0, 0))
        elif self.preview_bg_mode == "white":
            bg = Image.new("RGB", (tw_crop, th_crop), (255, 255, 255))
            
        # 3. 現在の編集画像を拡大縮小
        resample_method = Image.Resampling.NEAREST if self.zoom_level >= 1.0 else Image.Resampling.LANCZOS
        resized_crop = cropped_img.resize((tw_crop, th_crop), resample_method)
        
        # 4. 背景に貼り付け (アルファチャンネルをマスクとして利用)
        bg.paste(resized_crop, (0, 0), resized_crop)
        
        # 5. Canvasに表示
        self.photo_img = ImageTk.PhotoImage(bg)
        
        # クロップ領域のキャンバス上での描画開始理論座標
        cx = self.pan_x + ix1 * self.zoom_level
        cy = self.pan_y + iy1 * self.zoom_level
        
        self.canvas.delete("all")
        self.canvas.create_image(cx, cy, image=self.photo_img, anchor="nw")
        
        # スクロール可能範囲（scrollregion）を画像全体＋余白に合わせて動的更新
        pad = 200 # スクロール領域に設ける周囲の余白
        x1 = min(0, self.pan_x - pad)
        y1 = min(0, self.pan_y - pad)
        x2 = max(cw, self.pan_x + tw + pad)
        y2 = max(ch, self.pan_y + th + pad)
        self.canvas.config(scrollregion=(x1, y1, x2, y2))
        
        # ブラシのサイズプレビューを描画 (ブラシツールアクティブ時のみ)
        if self.active_tool in ["brush_erase", "brush_restore"]:
            # マウスポインタの現在位置を取得して円を描く
            mx = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx()
            my = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
            if 0 <= mx < cw and 0 <= my < ch:
                # スクロールオフセットを考慮した座標に円を描画
                sx = self.canvas.canvasx(mx)
                sy = self.canvas.canvasy(my)
                r_canvas = self.brush_size * self.zoom_level
                self.canvas.create_oval(
                    sx - r_canvas, sy - r_canvas,
                    sx + r_canvas, sy + r_canvas,
                    outline="#FF453A", width=1.5, tags="brush_preview"
                )

if __name__ == "__main__":
    # 引数があればファイルパスとして読み込み
    path = sys.argv[1] if len(sys.argv) > 1 else None
    app = AvatarEditorApp(path)
    
    # マウス移動時にブラシプレビューを更新するためバインド
    def on_mouse_move(event):
        if app.active_tool in ["brush_erase", "brush_restore"]:
            app.update_canvas()
    app.canvas.bind("<Motion>", on_mouse_move)
    
    app.mainloop()
