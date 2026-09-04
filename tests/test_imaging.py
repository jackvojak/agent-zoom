import math

import pytest
from PIL import Image

from zoom_mcp import imaging
from zoom_mcp.imaging import Box, Budget

HIGH = Budget.for_tier("high")
STD = Budget.for_tier("standard")


def test_resized_size_unchanged_when_fits():
    assert imaging.resized_size(800, 600, HIGH) == (800, 600)


def test_resized_size_shrinks_to_budget_and_keeps_aspect():
    w, h = imaging.resized_size(6000, 3000, HIGH)
    assert imaging.fits(w, h, HIGH)
    assert not imaging.fits(w + 1, round(h * (w + 1) / w), HIGH)
    assert abs(w / h - 2.0) < 0.01


def test_zoom_size_fills_budget():
    w, h = imaging.zoom_size(100, 50, HIGH)
    assert imaging.fits(w, h, HIGH)
    assert w <= HIGH.max_edge and imaging.token_count(w, h) <= HIGH.max_tokens
    assert abs(w / h - 2.0) < 0.02
    ws, hs = imaging.zoom_size(100, 50, STD)
    assert ws <= 1568 and imaging.token_count(ws, hs) <= 1568


def test_unknown_tier():
    with pytest.raises(ValueError, match="valid tiers"):
        Budget.for_tier("ultra")


def test_region_box_and_unknown():
    assert imaging.region_box("bottom_half", 1000, 400) == (0, 200, 1000, 400)
    assert imaging.region_box("x_axis", 1000, 400) == (0, 340, 1000, 400)
    with pytest.raises(ValueError, match="Valid regions"):
        imaging.region_box("nowhere", 10, 10)


def test_normalise_box_clamps_and_validates():
    b = imaging.normalise_box(-10, -10, 5000, 5000, 1000, 800)
    assert (b.x1, b.y1, b.x2, b.y2) == (0, 0, 1000, 800) and not b.padded
    with pytest.raises(ValueError):
        imaging.normalise_box(500, 100, 400, 200, 1000, 800)
    with pytest.raises(ValueError):
        imaging.normalise_box(1200, 0, 1300, 100, 1000, 800)


def test_normalise_box_pads_tiny_boxes():
    b = imaging.normalise_box(500, 400, 510, 405, 1000, 800)
    assert b.padded
    assert b.width >= imaging.MIN_BOX_SIDE and b.height >= imaging.MIN_BOX_SIDE
    assert b.x1 <= 500 and b.x2 >= 510 and b.y1 <= 400 and b.y2 >= 405
    # Near the edge the padding shifts inward rather than falling off the image.
    e = imaging.normalise_box(995, 795, 1000, 800, 1000, 800)
    assert e.x2 == 1000 and e.y2 == 800 and e.width == imaging.MIN_BOX_SIDE


def test_flatten_transparency_to_white():
    img = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    assert imaging.flatten(img).getpixel((0, 0)) == (255, 255, 255)


def test_crop_and_zoom_uses_full_resolution():
    img = Image.new("RGB", (400, 200), "white")
    for x in range(98, 103):
        for y in range(48, 53):
            img.putpixel((x, y), (255, 0, 0))
    out = imaging.crop_and_zoom(img, Box(90, 40, 110, 60), HIGH)
    assert imaging.fits(out.width, out.height, HIGH)
    # The red pixel sits at the centre of the crop after scaling.
    cx, cy = out.width // 2, out.height // 2
    r, g, b = out.getpixel((cx, cy))
    assert r > 200 and g < 100 and b < 100


def test_overview_never_upscales():
    img = Image.new("RGB", (300, 200), "white")
    assert imaging.overview(img, HIGH).size == (300, 200)
    big = Image.new("RGB", (6000, 3000), "white")
    o = imaging.overview(big, HIGH)
    assert imaging.fits(o.width, o.height, HIGH) and o.width < 6000


@pytest.mark.parametrize("span,expected", [(700, 100), (1200, 200), (3000, 500), (60, 10), (2000, 200), (1506, 200)])
def test_grid_step_round_numbers(span, expected):
    assert imaging.grid_step(span) == expected


def test_draw_grid_lines_land_on_original_multiples():
    img = Image.new("RGB", (1000, 500), "white")
    box = Box(230, 100, 730, 350)  # 500x250 original px, 2x scale
    out = imaging.draw_grid(img, box, step=100, colour=(0, 0, 255))
    # x=300 original -> (300-230)*2 = 140 rendered; sample away from labels and
    # off the horizontal lines (rendered y=390 is original y=295).
    assert out.getpixel((140, 390)) != (255, 255, 255)
    assert out.getpixel((150, 390)) == (255, 255, 255)
    # y=200 original -> (200-100)*2 = 200 rendered.
    assert out.getpixel((900, 200)) != (255, 255, 255)
    assert out.getpixel((900, 210)) == (255, 255, 255)


def test_encode_jpeg_roundtrip():
    img = Image.new("RGBA", (50, 50), (255, 0, 0, 255))
    data = imaging.encode_jpeg(img)
    assert data[:2] == b"\xff\xd8"
