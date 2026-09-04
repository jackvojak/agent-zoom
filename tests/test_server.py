"""Tool-function tests. The MCPServer.tool decorator returns the original
function, so the tools can be called directly."""

import base64
import io

import pytest
from PIL import Image

from zoom_mcp import imaging, server


@pytest.fixture
def png(tmp_path):
    img = Image.new("RGBA", (800, 400), (0, 0, 0, 0))
    for x in range(300, 320):
        for y in range(150, 170):
            img.putpixel((x, y), (255, 0, 0, 255))
    path = tmp_path / "plot.png"
    img.save(path)
    return str(path)


def _images(blocks):
    return [Image.open(io.BytesIO(base64.b64decode(b.data))) for b in blocks if b.type == "image"]


def _texts(blocks):
    return [b.text for b in blocks if b.type == "text"]


def test_image_info_reports_size_and_3x_hint(png, monkeypatch):
    monkeypatch.delenv("ZOOM_MCP_TIER", raising=False)
    blocks = server.image_info(png)
    text = _texts(blocks)[0]
    assert "Original size: 800x400 px" in text
    assert "at most 666 original px wide" in text
    (img,) = _images(blocks)
    assert imaging.fits(img.width, img.height, imaging.Budget.for_tier("claude-code"))


def test_zoom_pixel_box_and_transparency_white(png):
    blocks = server.zoom(png, 290, 140, 330, 180)
    (img,) = _images(blocks)
    assert img.getpixel((2, 2)) == (255, 255, 255) or sum(img.getpixel((2, 2))) > 700
    assert "padded" in _texts(blocks)[0]


def test_zoom_fraction_guard(png):
    (text,) = _texts(server.zoom(png, 0.1, 0.1, 0.5, 0.5))
    assert text.startswith("Error") and "coords='fraction'" in text
    # Same values are accepted in fraction mode.
    assert _images(server.zoom(png, 0.1, 0.1, 0.5, 0.5, coords="fraction"))


def test_zoom_errors_are_text(png):
    assert _texts(server.zoom("/nope/missing.png", 0, 0, 10, 10))[0].startswith("Error")
    assert _texts(server.zoom(png, 100, 100, 50, 200))[0].startswith("Error")
    assert _texts(server.zoom(png, region="nowhere"))[0].startswith("Error")


def test_zoom_grid_fits_budget(png):
    blocks = server.zoom(png, region="bottom_half", grid=True)
    (img,) = _images(blocks)
    assert imaging.fits(img.width, img.height, imaging.Budget.for_tier("claude-code"))
    assert "Grid every" in _texts(blocks)[0]


def test_zoom_many_order_and_labels(png):
    boxes = [[0, 0, 400, 200], [400, 0, 800, 200], [0.0, 0.5, 1.0, 1.0]]
    blocks = server.zoom_many(png, boxes[:2] + [[0, 200, 800, 400]], labels=["a", "b", "c"])
    texts, images = _texts(blocks), _images(blocks)
    assert len(texts) == 3 and len(images) == 3
    assert [b.type for b in blocks] == ["text", "image"] * 3
    assert texts[0].startswith("Box 1 of 3") and "Label: a" in texts[0]
    assert "x 0-800, y 200-400" in texts[2]
    budget = imaging.Budget.for_tier("claude-code")
    assert all(imaging.fits(i.width, i.height, budget) for i in images)


def test_zoom_many_limits_and_partial_errors(png):
    assert _texts(server.zoom_many(png, []))[0].startswith("Error")
    assert "at most 6" in _texts(server.zoom_many(png, [[0, 0, 10, 10]] * 7))[0]
    assert "labels has 1" in _texts(server.zoom_many(png, [[0, 0, 10, 10]] * 2, labels=["x"]))[0]
    blocks = server.zoom_many(png, [[0, 0, 100, 100], [50, 50, 10, 10], [0, 0, 1]])
    texts = _texts(blocks)
    assert len(_images(blocks)) == 1
    assert texts[1].startswith("Box 2 of 3: Error") and texts[2].startswith("Box 3 of 3: Error")


def test_decompression_bomb_is_text_error(tmp_path, monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    path = tmp_path / "big.png"
    Image.new("L", (200, 200)).save(path)
    text = _texts(server.image_info(str(path)))[0]
    assert text.startswith("Error") and "exceeds limit" in text
