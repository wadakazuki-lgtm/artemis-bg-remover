"""類似領域の一括透過（スマート Flood Fill）の核ロジック。

GUI に依存しない純関数として切り出し、回帰テストから直接検証できるようにする。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class FloodFillResult:
    """塗りつぶし結果をまとめた不変オブジェクト。"""

    # 処理後の画像（変更なしのときは入力と同じ内容のコピーまたは同等画像）
    image: Image.Image
    # 1ピクセルでも透過したか
    changed: bool
    # 透過したピクセル数
    filled_count: int
    # UI 表示用の説明文
    message: str


def smart_flood_fill_transparent(
    image: Image.Image,
    start_x: int,
    start_y: int,
    tolerance: int,
) -> FloodFillResult:
    """開始点から似た色の連続領域を (0, 0, 0, 0) に透過する。

    透明ピクセル (A==0) を起点にした場合は何もしない。
    探索中も完全透明な画素は橋にしない（暗い被写体への誤伝播防止）。
    """
    # RGBA に揃える（入力が RGB などでも扱えるようにする）
    img_rgba = image.convert("RGBA")
    width, height = img_rgba.size

    # 開始座標が画像外なら安全に何もしない
    if not (0 <= start_x < width and 0 <= start_y < height):
        return FloodFillResult(
            image=img_rgba.copy(),
            changed=False,
            filled_count=0,
            message="開始座標が画像の範囲外です。",
        )

    sample = img_rgba.load()
    tr, tg, tb, ta = sample[start_x, start_y]

    # 透明起点は RGB が (0,0,0) になりがちで、黒髪などと誤判定しやすい
    if ta == 0:
        return FloodFillResult(
            image=img_rgba.copy(),
            changed=False,
            filled_count=0,
            message="透明な領域です。透過対象の色の上をクリックしてください。",
        )

    # ここから先は破壊的変更が入るのでコピー上で作業する（入力は不変に保つ）
    img = img_rgba.copy()
    pixels = img.load()

    queue: deque[tuple[int, int]] = deque([(start_x, start_y)])
    # visited[x, y] でアクセスする（main.py と同じ慣習）
    visited = np.zeros((width, height), dtype=bool)
    visited[start_x, start_y] = True

    max_color_diff = tolerance * 3
    fill_pixels: list[tuple[int, int]] = []

    while queue:
        cx, cy = queue.popleft()
        fill_pixels.append((cx, cy))

        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = cx + dx, cy + dy

            if not (0 <= nx < width and 0 <= ny < height):
                continue
            if visited[nx, ny]:
                continue

            nr, ng, nb, na = pixels[nx, ny]

            # 完全透明は探索しない（透明を橋にして暗い被写体へ伝播するのを防ぐ）
            if na == 0:
                visited[nx, ny] = True
                continue

            color_diff = (
                abs(int(nr) - int(tr))
                + abs(int(ng) - int(tg))
                + abs(int(nb) - int(tb))
            )
            if color_diff <= max_color_diff:
                visited[nx, ny] = True
                queue.append((nx, ny))

    for x, y in fill_pixels:
        pixels[x, y] = (0, 0, 0, 0)

    return FloodFillResult(
        image=img,
        changed=True,
        filled_count=len(fill_pixels),
        message=f"領域透過: {len(fill_pixels)} ピクセルを透明にしました。",
    )
