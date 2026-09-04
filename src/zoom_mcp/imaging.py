"""Pure image functions for the zoom MCP server.

All coordinates handed to and returned from these functions are in the pixel
space of the ORIGINAL image, origin top-left. Crops are always taken from the
full-resolution source, then upscaled to fill the visual token budget. When a
grid is requested, the ruler margins are included in the budget so the final
canvas never exceeds it.
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

RULER_TOP = 24
"""Height of the top ruler margin when a grid is drawn."""

RULER_MIN_LEFT = 24
"""Minimum width of the left ruler margin; widened to fit the longest label."""

DEFAULT_TIER = "claude-code"

TIERS: dict[str, tuple[int, int]] = {
    "claude-code": (2000, 4784),
    "high": (2576, 4784),
    "standard": (1568, 1568),
}
"""Tier name -> (max_edge, max_tokens). claude-code matches the long-edge cap
Claude Code applies when displaying tool images."""

REGION_NAMES = (
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
    "center",
    "left_half",
    "right_half",
    "top_half",
    "bottom_half",
    "x_axis",
    "y_axis",
    "legend_right",
    "title",
)

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

    @property
    def zoom3x_max_box(self) -> int:
        """Widest original-pixel box that still reaches 3x magnification."""
        return self.max_edge // 3


def token_count(w: int, h: int) -> int:
    return math.ceil(w / PATCH) * math.ceil(h / PATCH)


def fits(w: int, h: int, budget: Budget) -> bool:
    return (
        math.ceil(w / PATCH) * PATCH <= budget.max_edge
        and math.ceil(h / PATCH) * PATCH <= budget.max_edge
        and token_count(w, h) <= budget.max_tokens
    )


def resized_size(
    w: int, h: int, budget: Budget, pad: tuple[int, int] = (0, 0)
) -> tuple[int, int]:
    """Size the API would downscale (w, h) to. Unchanged if it already fits.

    Otherwise the largest aspect-preserving width that fits, found by binary
    search. pad = (extra_width, extra_height) is reserved space (ruler margins)
    that must fit alongside the content.
    """
    pw, ph = pad
    if fits(w + pw, h + ph, budget):
        return w, h
    lo, hi = 1, w
    while lo < hi:
        mid = (lo + hi + 1) // 2
        mh = max(1, round(h * mid / w))
        if fits(mid + pw, mh + ph, budget):
            lo = mid
        else:
            hi = mid - 1
    return lo, max(1, round(h * lo / w))


def zoom_size(w: int, h: int, budget: Budget, pad: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    """Largest aspect-preserving size within budget, regardless of source size."""
    return resized_size(w * 10_000, h * 10_000, budget, pad)


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


def looks_like_fraction(x1: float, y1: float, x2: float, y2: float) -> bool:
    """True when a pixel-mode box is almost certainly fractional (all in 0..1)."""
    return all(0 <= v <= 1 for v in (x1, y1, x2, y2)) and (x2, y2) != (0, 0)


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
    ix1, ix2, p1 = _pad_span(ix1, ix2, w, min_side)
    iy1, iy2, p2 = _pad_span(iy1, iy2, h, min_side)
    return Box(ix1, iy1, ix2, iy2, p1 or p2)


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


def _resize(img: Image.Image, target: tuple[int, int]) -> Image.Image:
    """LANCZOS resize, with an integer reduce() first on large downscales to
    keep memory down."""
    if img.size == target:
        return img
    k = min(img.width // target[0], img.height // target[1])
    if k >= 2:
        img = img.reduce(k)
    return img.resize(target, Image.LANCZOS)


def grid_step(span: int, target_lines: int = 10) -> int:
    """A round step (1/2/5 x 10^k) giving roughly target_lines lines across span."""
    raw = max(1, span / target_lines)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if m * mag >= raw:
            return int(m * mag)
    return int(10 * mag)


@dataclass(frozen=True)
class GridSpec:
    step: int
    font_px: int
    left: int
    top: int

    @property
    def pad(self) -> tuple[int, int]:
        return self.left, self.top


def grid_spec(box: Box, content_size: tuple[int, int], step: int | None = None) -> GridSpec:
    """Choose step, font and ruler margins for a grid over box rendered at content_size."""
    if step is None:
        step = grid_step(max(box.width, box.height))
    font_px = max(14, min(20, min(content_size) // 100))
    font = ImageFont.load_default(size=font_px)
    longest = str(max(box.x2, box.y2))
    left = max(RULER_MIN_LEFT, math.ceil(font.getlength(longest)) + 8)
    top = max(RULER_TOP, font_px + 8)
    return GridSpec(step, font_px, left, top)


def draw_grid(
    img: Image.Image,
    box: Box,
    spec: GridSpec,
    colour: tuple[int, int, int] = (0, 120, 255),
) -> Image.Image:
    """Paste img onto a canvas with ruler margins and draw a grid labelled in
    ORIGINAL pixel coordinates. img is the rendered crop; box is the
    original-pixel region it depicts.
    """
    canvas = Image.new("RGB", (img.width + spec.left, img.height + spec.top), "white")
    canvas.paste(img, (spec.left, spec.top))
    draw = ImageDraw.Draw(canvas, "RGBA")
    font = ImageFont.load_default(size=spec.font_px)
    line = colour + (110,)
    fg = colour + (255,)
    sx = img.width / box.width
    sy = img.height / box.height
    draw.line([(spec.left, spec.top), (canvas.width, spec.top)], fill=fg, width=1)
    draw.line([(spec.left, spec.top), (spec.left, canvas.height)], fill=fg, width=1)

    for gx in range(math.ceil(box.x1 / spec.step) * spec.step, box.x2 + 1, spec.step):
        px = spec.left + (gx - box.x1) * sx
        draw.line([(px, spec.top), (px, canvas.height)], fill=line, width=1)
        draw.text((px + 2, 2), str(gx), font=font, fill=fg)

    for gy in range(math.ceil(box.y1 / spec.step) * spec.step, box.y2 + 1, spec.step):
        py = spec.top + (gy - box.y1) * sy
        draw.line([(spec.left, py), (canvas.width, py)], fill=line, width=1)
        draw.text((spec.left - 4, py + 1), str(gy), font=font, fill=fg, anchor="ra")
    return canvas


@dataclass(frozen=True)
class Rendered:
    image: Image.Image
    box: Box
    content_size: tuple[int, int]
    grid_step: int | None

    @property
    def scale(self) -> float:
        return self.content_size[0] / self.box.width


def render_zoom(img: Image.Image, box: Box, budget: Budget, grid: bool = False) -> Rendered:
    """Crop the full-resolution image to box, upscale to fill the budget, and
    optionally add a labelled grid. The whole canvas fits the budget."""
    crop = flatten(img.crop((box.x1, box.y1, box.x2, box.y2)))
    if not grid:
        target = zoom_size(box.width, box.height, budget)
        return Rendered(_resize(crop, target), box, target, None)
    spec = grid_spec(box, zoom_size(box.width, box.height, budget))
    target = zoom_size(box.width, box.height, budget, spec.pad)
    out = draw_grid(_resize(crop, target), box, spec)
    return Rendered(out, box, target, spec.step)


def render_overview(
    img: Image.Image, budget: Budget, grid: bool = True, step: int | None = None
) -> Rendered:
    """The whole image downscaled to fit the budget (never upscaled), with an
    optional labelled grid. img may be lazily loaded; JPEG sources are decoded
    at reduced scale where possible."""
    full = Box(0, 0, img.width, img.height)
    if grid:
        spec = grid_spec(full, resized_size(img.width, img.height, budget), step)
        target = resized_size(img.width, img.height, budget, spec.pad)
    else:
        spec = None
        target = resized_size(img.width, img.height, budget)
    if getattr(img, "format", None) == "JPEG":
        img.draft("RGB", target)
    out = _resize(flatten(img), target)
    if spec is None:
        return Rendered(out, full, target, None)
    return Rendered(draw_grid(out, full, spec), full, target, spec.step)
