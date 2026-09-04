import math

import pytest
from PIL import Image

from zoom_mcp import imaging
from zoom_mcp.imaging import Box, Budget

HIGH = Budget.for_tier("high")
STD = Budget.for_tier("standard")
CC = Budget.for_tier("claude-code")


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


def test_default_tier_is_claude_code():
    assert imaging.DEFAULT_TIER == "claude-code"
    assert CC.max_edge == 2000 and CC.zoom3x_max_box == 666


def test_render_zoom_uses_full_resolution():
    img = Image.new("RGB", (400, 200), "white")
    for x in range(98, 103):
        for y in range(48, 53):
            img.putpixel((x, y), (255, 0, 0))
    r = imaging.render_zoom(img, Box(90, 40, 110, 60), HIGH)
    out = r.image
    assert imaging.fits(out.width, out.height, HIGH)
    cx, cy = out.width // 2, out.height // 2
    red, g, b = out.getpixel((cx, cy))
    assert red > 200 and g < 100 and b < 100


def test_render_overview_never_upscales():
    img = Image.new("RGB", (300, 200), "white")
    assert imaging.render_overview(img, HIGH, grid=False).image.size == (300, 200)
    big = Image.new("RGB", (6000, 3000), "white")
    o = imaging.render_overview(big, HIGH, grid=False).image
    assert imaging.fits(o.width, o.height, HIGH) and o.width < 6000


@pytest.mark.parametrize("budget", [CC, HIGH, STD])
@pytest.mark.parametrize("box", [Box(0, 0, 1506, 1453), Box(0, 872, 753, 1453), Box(1205, 0, 1506, 1453)])
def test_grid_canvas_fits_budget(budget, box):
    img = Image.new("RGB", (1506, 1453), "white")
    z = imaging.render_zoom(img, box, budget, grid=True).image
    assert imaging.fits(z.width, z.height, budget), (z.size, budget)
    assert z.width <= budget.max_edge and z.height <= budget.max_edge
    o = imaging.render_overview(img, budget, grid=True).image
    assert imaging.fits(o.width, o.height, budget), (o.size, budget)


def test_grid_canvas_fits_budget_large_source():
    big = Image.new("RGB", (6000, 3000), "white")
    o = imaging.render_overview(big, CC, grid=True).image
    assert imaging.fits(o.width, o.height, CC) and o.width <= 2000


@pytest.mark.parametrize("span,expected", [(700, 100), (1200, 200), (3000, 500), (60, 10), (2000, 200), (1506, 200)])
def test_grid_step_round_numbers(span, expected):
    assert imaging.grid_step(span) == expected


def test_draw_grid_lines_land_on_original_multiples_in_margined_canvas():
    img = Image.new("RGB", (1000, 500), "white")
    box = Box(230, 100, 730, 350)  # 500x250 original px, 2x scale
    spec = imaging.grid_spec(box, img.size, step=100)
    out = imaging.draw_grid(img, box, spec, colour=(0, 0, 255))
    assert out.size == (1000 + spec.left, 500 + spec.top)
    # x=300 original -> left + (300-230)*2 rendered; sample at rendered y=390 (original 295, off any line).
    assert out.getpixel((spec.left + 140, spec.top + 390)) != (255, 255, 255)
    assert out.getpixel((spec.left + 150, spec.top + 390)) == (255, 255, 255)
    # y=200 original -> top + 200 rendered.
    assert out.getpixel((spec.left + 900, spec.top + 200)) != (255, 255, 255)
    assert out.getpixel((spec.left + 900, spec.top + 210)) == (255, 255, 255)
    # Content area is untouched by labels: top-left content pixel stays white.
    assert out.getpixel((spec.left + 5, spec.top + 5)) == (255, 255, 255)
    assert spec.font_px >= 14 and spec.left >= 24 and spec.top >= 24


def test_looks_like_fraction():
    assert imaging.looks_like_fraction(0.1, 0.2, 0.5, 0.9)
    assert not imaging.looks_like_fraction(0, 0, 0, 0)
    assert not imaging.looks_like_fraction(0, 0, 100, 50)


def test_encode_jpeg_roundtrip():
    img = Image.new("RGBA", (50, 50), (255, 0, 0, 255))
    data = imaging.encode_jpeg(img)
    assert data[:2] == b"\xff\xd8"
