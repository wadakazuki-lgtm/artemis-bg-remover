"""透明起点の Flood Fill が暗い被写体を消さないことの回帰テスト。"""

from PIL import Image

from flood_fill import smart_flood_fill_transparent


def _make_transparent_corner_with_black_rect() -> Image.Image:
    """透明な角と、中央の黒い不透明矩形を持つ小さな RGBA 画像を作る。

    レイアウト (8x8):
      - 全体: 透明 (0, 0, 0, 0)
      - (2,2)-(5,5): 黒・不透明 (0, 0, 0, 255)  … 黒髪などのつもり
    """
    img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    pixels = img.load()
    for x in range(2, 6):
        for y in range(2, 6):
            pixels[x, y] = (0, 0, 0, 255)
    return img


def test_flood_fill_from_transparent_corner_does_not_erase_black_rect():
    """透明な角から塗っても、黒い矩形は変化しないこと（今回のバグの回帰防止）。"""
    original = _make_transparent_corner_with_black_rect()
    before_black = [
        original.getpixel((x, y))
        for x in range(2, 6)
        for y in range(2, 6)
    ]

    # 既定の許容誤差 30 のまま、透明な左上 (0, 0) から実行
    result = smart_flood_fill_transparent(original, 0, 0, tolerance=30)

    # 変更なしであること
    assert result.changed is False
    assert result.filled_count == 0

    # 黒い矩形の全ピクセルが、処理前と同じ不透明黒のままであること
    after = result.image
    after_black = [
        after.getpixel((x, y))
        for x in range(2, 6)
        for y in range(2, 6)
    ]
    assert after_black == before_black
    assert all(px == (0, 0, 0, 255) for px in after_black)


def test_flood_fill_from_opaque_color_still_works():
    """不透明色からの塗りつぶしは、従来どおり似た領域を透過すること。"""
    # 白背景に黒矩形（白だけ消えて黒は残る想定）
    img = Image.new("RGBA", (8, 8), (255, 255, 255, 255))
    pixels = img.load()
    for x in range(2, 6):
        for y in range(2, 6):
            pixels[x, y] = (0, 0, 0, 255)

    result = smart_flood_fill_transparent(img, 0, 0, tolerance=30)

    assert result.changed is True
    assert result.image.getpixel((0, 0)) == (0, 0, 0, 0)
    assert result.image.getpixel((7, 7)) == (0, 0, 0, 0)
    # 黒矩形は残る
    assert result.image.getpixel((3, 3)) == (0, 0, 0, 255)
