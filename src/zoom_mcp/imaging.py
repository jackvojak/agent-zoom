"""Pure image functions for the zoom MCP server.

All coordinates handed to and returned from these functions are in the pixel
space of the ORIGINAL image, origin top-left. Crops are always taken from the
full-resolution source, then upscaled to fill the visual token budget.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

PATCH = 28
"""Side of one visual-token patch in pixels."""

MIN_BOX_SIDE = 64
"""Boxes narrower than this on either side are padded out before cropping."""

JPEG_QUALITY = 92

TIERS: dict[str, tuple[int, int]] = {
    "high": (2576, 4784),
    "standard": (1568, 1568),
}
"""Tier name -> (max_edge, max_tokens)."""

REGIONS: dict[str, tuple[float, float, float, float]] = {
    "top_left": (0.0, 0.0, 0.5, 0.5),
    "top_right": (0.5, 0.0, 1.0, 0.5),
    "bottom_left": (0.0, 0.5, 0.5, 1.0),
    "bottom_right": (0.5, 0.5, 1.0, 1.0),
    "center": (0.25, 0.25, 0.75, 0.75),
    "left_half": (0.0, 0.0, 0.5, 1.0),
    "right_half": (0.5, 0.0, 1.0, 1.0),
    "top_half": (0.0, 0.0, 1.0, 0.5),
    "bottom_half": (0.0, 0.5, 1.0, 1.0),
    "x_axis": (0.0, 0.85, 1.0, 1.0),
    "y_axis": (0.0, 0.0, 0.15, 1.0),
    "legend_right": (0.8, 0.0, 1.0, 1.0),
    "title": (0.0, 0.0, 1.0, 0.1),
}
"""Named presets as fractions (x1, y1, x2, y2) of the original image."""


@dataclass(frozen=True)
class Budget:
    max_edge: int
    max_tokens: int

    @classmethod
    def for_tier(cls, tier: str) -> "Budget":
        try:
            return cls(*TIERS[tier])
        except KeyError:
            raise ValueError(f"Unknown tier {tier!r}; valid tiers: {', '.join(TIERS)}") from None


def token_count(w: int, h: int) -> int:
    return math.ceil(w / PATCH) * math.ceil(h / PATCH)


def fits(w: int, h: int, budget: Budget) -> bool:
    return (
        math.ceil(w / PATCH) * PATCH <= budget.max_edge
        and math.ceil(h / PATCH) * PATCH <= budget.max_edge
        and token_count(w, h) <= budget.max_tokens
    )


def resized_size(w: int, h: int, budget: Budget) -> tuple[int, int]:
    """Size the API would downscale (w, h) to. Unchanged if it already fits.

    Otherwise the largest aspect-preserving width that fits, found by binary search.
    """
    if fits(w, h, budget):
        return w, h
    lo, hi = 1, w
    while lo < hi:
        mid = (lo + hi + 1) // 2
        mh = max(1, round(h * mid / w))
        if fits(mid, mh, budget):
            lo = mid
        else:
            hi = mid - 1
    return lo, max(1, round(h * lo / w))


def zoom_size(w: int, h: int, budget: Budget) -> tuple[int, int]:
    """Largest aspect-preserving size within budget, regardless of source size."""
    return resized_size(w * 10_000, h * 10_000, budget)


def flatten(img: Image.Image) -> Image.Image:
    """Return an RGB copy with any transparency composited onto white."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(bg, rgba).convert("RGB")
    return img.convert("RGB")


def encode_jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    flatten(img).save(buf, format="JPEG", quality=JPEG_QUALITY, subsampling=0)
    return buf.getvalue()


def region_box(name: str, w: int, h: int) -> tuple[int, int, int, int]:
    """Pixel box for a named preset region. Raises ValueError on unknown names."""
    if name not in REGIONS:
        raise ValueError(f"Unknown region {name!r}. Valid regions: {', '.join(REGIONS)}")
    fx1, fy1, fx2, fy2 = REGIONS[name]
    return round(fx1 * w), round(fy1 * h), round(fx2 * w), round(fy2 * h)


def fraction_box(
    x1: float, y1: float, x2: float, y2: float, w: int, h: int
) -> tuple[int, int, int, int]:
    return round(x1 * w), round(y1 * h), round(x2 * w), round(y2 * h)


@dataclass(frozen=True)
class Box:
    x1: int
    y1: int
    x2: int
    y2: int
    padded: bool = False
    """True when the box was expanded to meet the minimum side length."""

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1


def normalise_box(
    x1: float, y1: float, x2: float, y2: float, w: int, h: int, min_side: int = MIN_BOX_SIDE
) -> Box:
    """Clamp to the image, validate ordering, and pad tiny boxes symmetrically.

    Raises ValueError when the box is empty or inverted after clamping.
    """
    ix1, iy1 = max(0, math.floor(x1)), max(0, math.floor(y1))
    ix2, iy2 = min(w, math.ceil(x2)), min(h, math.ceil(y2))
    if ix1 >= ix2 or iy1 >= iy2:
        raise ValueError(
            f"Empty box after clamping to {w}x{h}: got ({x1}, {y1}) to ({x2}, {y2}). "
            "Require x1 < x2 and y1 < y2 inside the image."
        )
    padded = False
    ix1, ix2, p1 = _pad_span(ix1, ix2, w, min_side)
    iy1, iy2, p2 = _pad_span(iy1, iy2, h, min_side)
    padded = p1 or p2
    return Box(ix1, iy1, ix2, iy2, padded)


def _pad_span(a: int, b: int, limit: int, min_len: int) -> tuple[int, int, bool]:
    if b - a >= min_len or limit < min_len:
        if limit < min_len and b - a < limit:
            return 0, limit, True
        return a, b, False
    need = min_len - (b - a)
    a -= need // 2
    b += need - need // 2
    if a < 0:
        b -= a
        a = 0
    if b > limit:
        a -= b - limit
        b = limit
    return max(0, a), b, True


def crop_and_zoom(img: Image.Image, box: Box, budget: Budget) -> Image.Image:
    """Crop the full-resolution image to box and upscale to fill the budget."""
    crop = img.crop((box.x1, box.y1, box.x2, box.y2))
    target = zoom_size(box.width, box.height, budget)
    return flatten(crop).resize(target, Image.LANCZOS)


def overview(img: Image.Image, budget: Budget) -> Image.Image:
    """The whole image downscaled to fit the budget (never upscaled)."""
    target = resized_size(img.width, img.height, budget)
    out = flatten(img)
    if target != img.size:
        out = out.resize(target, Image.LANCZOS)
    return out


def grid_step(span: int, target_lines: int = 10) -> int:
    """A round step (1/2/5 x 10^k) giving roughly target_lines lines across span."""
    raw = max(1, span / target_lines)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if m * mag >= raw:
            return int(m * mag)
    return int(10 * mag)


def draw_grid(
    img: Image.Image,
    box: Box,
    step: int | None = None,
    colour: tuple[int, int, int] = (0, 120, 255),
) -> Image.Image:
    """Overlay a coordinate grid labelled in ORIGINAL pixel coordinates.

    img is the rendered (cropped and rescaled) image; box is the original-pixel
    region it depicts. Lines land on multiples of step in original space.
    """
    out = img.copy()
    draw = ImageDraw.Draw(out, "RGBA")
    if step is None:
        step = grid_step(max(box.width, box.height))
    sx = img.width / box.width
    sy = img.height / box.height
    font_px = max(10, min(18, img.width // 110))
    font = ImageFont.load_default(size=font_px)
    line = colour + (110,)
    text_bg = (255, 255, 255, 200)
    text_fg = colour + (255,)

    first_x = math.ceil(box.x1 / step) * step
    for gx in range(first_x, box.x2 + 1, step):
        px = (gx - box.x1) * sx
        draw.line([(px, 0), (px, img.height)], fill=line, width=1)
        _label(draw, str(gx), (px + 2, 1), font, text_bg, text_fg)

    first_y = math.ceil(box.y1 / step) * step
    for gy in range(first_y, box.y2 + 1, step):
        py = (gy - box.y1) * sy
        draw.line([(0, py), (img.width, py)], fill=line, width=1)
        _label(draw, str(gy), (1, py + 2), font, text_bg, text_fg)
    return out


def _label(draw, text, xy, font, bg, fg):
    x, y = xy
    l, t, r, b = draw.textbbox((x, y), text, font=font)
    draw.rectangle((l - 1, t - 1, r + 1, b + 1), fill=bg)
    draw.text((x, y), text, font=font, fill=fg)
