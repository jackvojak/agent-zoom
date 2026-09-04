"""MCP server exposing `zoom`, `zoom_many` and `image_info` for reading fine
detail in images.

Runs over stdio. Select the visual token budget with
ZOOM_MCP_TIER=claude-code|high|standard.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ContentBlock, ImageContent, TextContent
from PIL import Image, UnidentifiedImageError

from zoom_mcp import imaging

Region = Literal[
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
]
Coords = Literal["pixel", "fraction"]

MAX_MANY = 6
"""Upper bound on boxes per zoom_many call."""

OPEN_ERRORS = (FileNotFoundError, UnidentifiedImageError, Image.DecompressionBombError, OSError)

mcp = MCPServer(
    "zoom-mcp",
    instructions=(
        "Tools for inspecting plot and figure images at full resolution. "
        "Call image_info first to learn the original pixel size, then zoom into "
        "regions before reading any small text or values."
    ),
)


def _budget() -> imaging.Budget:
    return imaging.Budget.for_tier(os.environ.get("ZOOM_MCP_TIER", imaging.DEFAULT_TIER))


def _text(msg: str) -> list[ContentBlock]:
    return [TextContent(type="text", text=msg)]


def _image_block(img: Image.Image) -> ImageContent:
    data = base64.b64encode(imaging.encode_jpeg(img)).decode()
    return ImageContent(type="image", data=data, mime_type="image/jpeg")


def _open(image_path: str) -> Image.Image:
    """Open lazily; pixel data is decoded by the render step."""
    path = Path(image_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    return Image.open(path)


def _resolve_box(
    img: Image.Image,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    coords: str,
    region: str | None = None,
) -> imaging.Box:
    """Turn tool arguments into a clamped original-pixel Box. Raises ValueError."""
    w, h = img.size
    if region is not None:
        bx = imaging.region_box(region, w, h)
    elif coords == "fraction":
        bx = imaging.fraction_box(x1, y1, x2, y2, w, h)
    elif coords == "pixel":
        if imaging.looks_like_fraction(x1, y1, x2, y2):
            raise ValueError(
                f"Box ({x1}, {y1}, {x2}, {y2}) looks fractional but coords='pixel'. "
                f"Pass coords='fraction', or give original pixel coordinates (image is {w}x{h})."
            )
        bx = (x1, y1, x2, y2)
    else:
        raise ValueError(f"coords must be 'pixel' or 'fraction', got {coords!r}.")
    return imaging.normalise_box(*bx, w, h)


def _describe(r: imaging.Rendered, w: int, h: int, label: str | None, region: str | None) -> str:
    box = r.box
    lines = []
    if label:
        lines.append(f"Label: {label}")
    if region:
        lines.append(f"Region preset: {region}")
    lines.append(f"Original image: {w}x{h} px.")
    lines.append(
        f"Zoomed region (original px): x {box.x1}-{box.x2}, y {box.y1}-{box.y2} "
        f"({box.width}x{box.height} px)."
    )
    if box.padded:
        lines.append(
            f"Requested box was smaller than {imaging.MIN_BOX_SIDE} px on a side; "
            "it was padded to the region above."
        )
    lines.append(
        f"Returned at {r.image.width}x{r.image.height} px ({r.scale:.1f}x magnification)."
    )
    if r.grid_step is not None:
        lines.append(
            f"Grid every {r.grid_step} original px; ruler labels are ORIGINAL pixel coordinates."
        )
    return "\n".join(lines)


@mcp.tool(structured_output=False)
def image_info(image_path: str, grid: bool = True, grid_step: int | None = None) -> list[ContentBlock]:
    """Report an image's original size and return a downscaled overview with a
    coordinate grid labelled in ORIGINAL pixel coordinates.

    Call this first for any image you intend to inspect. Use the grid labels to
    choose pixel boxes for `zoom`. Set grid=False for a clean overview. grid_step
    overrides the automatic line spacing (in original pixels).
    """
    try:
        img = _open(image_path)
        w, h, mode = img.width, img.height, img.mode
        budget = _budget()
        r = imaging.render_overview(img, budget, grid, grid_step)
    except OPEN_ERRORS as exc:
        return _text(f"Error: {exc}")
    size_kb = Path(image_path).expanduser().stat().st_size / 1024
    lines = [
        f"File: {image_path}",
        f"Original size: {w}x{h} px (width x height), mode {mode}, {size_kb:.1f} KB.",
        f"Overview returned at {r.image.width}x{r.image.height} px.",
        "Coordinates for `zoom` are ORIGINAL pixels, origin top-left, x right, y down.",
        f"For at least 3x magnification keep zoom boxes at most {budget.zoom3x_max_box} original px wide.",
    ]
    if r.grid_step is not None:
        lines.append(
            f"Grid every {r.grid_step} original px; ruler labels give original pixel positions."
        )
    return [TextContent(type="text", text="\n".join(lines)), _image_block(r.image)]


@mcp.tool(structured_output=False)
def zoom(
    image_path: str,
    x1: float = 0,
    y1: float = 0,
    x2: float = 0,
    y2: float = 0,
    label: str | None = None,
    region: Region | None = None,
    coords: Coords = "pixel",
    grid: bool = False,
) -> list[ContentBlock]:
    """Zoom into a rectangular region of a plot or image, cropped from the
    full-resolution original and magnified to fill the image budget.

    USE THIS BEFORE reading any small text, axis tick label, legend entry,
    annotation, cell value or fine detail. Do not guess at small text from the
    full view. Coordinates are absolute pixels of the ORIGINAL file, origin
    top-left; call `image_info` first if you don't know the file's size. Zoom
    again on a sub-region for finer detail.

    Args:
        image_path: Path to the image file.
        x1, y1, x2, y2: Box corners (top-left and bottom-right). Original pixels
            by default; fractions 0..1 of width/height when coords="fraction".
        label: Free text echoed back, e.g. "row 3 of heatmap".
        region: Named preset that replaces the box.
        coords: Interpretation of x1..y2.
        grid: Add ruler margins with a grid labelled in ORIGINAL pixel
            coordinates, to refine the next zoom precisely.
    """
    try:
        img = _open(image_path)
        w, h = img.size
        box = _resolve_box(img, x1, y1, x2, y2, coords, region)
        r = imaging.render_zoom(img, box, _budget(), grid)
    except (ValueError, *OPEN_ERRORS) as exc:
        return _text(f"Error: {exc}")
    return [TextContent(type="text", text=_describe(r, w, h, label, region)), _image_block(r.image)]


@mcp.tool(structured_output=False)
def zoom_many(
    image_path: str,
    boxes: list[list[float]],
    labels: list[str] | None = None,
    coords: Coords = "pixel",
    grid: bool = False,
) -> list[ContentBlock]:
    """Zoom into several regions of one image in a single call. Each box gets
    the full image budget and is returned in order as a text block followed by
    its image.

    Args:
        image_path: Path to the image file.
        boxes: Up to 6 boxes, each [x1, y1, x2, y2] in ORIGINAL pixels (or
            fractions 0..1 when coords="fraction").
        labels: Optional free-text label per box, same length as boxes.
        coords: Interpretation of the box values.
        grid: Add labelled ruler margins to every crop.
    """
    if not boxes:
        return _text("Error: boxes is empty.")
    if len(boxes) > MAX_MANY:
        return _text(f"Error: at most {MAX_MANY} boxes per call, got {len(boxes)}.")
    if labels is not None and len(labels) != len(boxes):
        return _text(f"Error: labels has {len(labels)} entries but boxes has {len(boxes)}.")
    try:
        img = _open(image_path)
        w, h = img.size
    except OPEN_ERRORS as exc:
        return _text(f"Error: {exc}")
    budget = _budget()
    out: list[ContentBlock] = []
    for i, b in enumerate(boxes):
        label = labels[i] if labels else None
        head = f"Box {i + 1} of {len(boxes)}"
        try:
            if len(b) != 4:
                raise ValueError(f"box {i + 1} must have 4 values [x1, y1, x2, y2], got {len(b)}.")
            box = _resolve_box(img, *b, coords)
            r = imaging.render_zoom(img, box, budget, grid)
        except (ValueError, *OPEN_ERRORS) as exc:
            out.append(TextContent(type="text", text=f"{head}: Error: {exc}"))
            continue
        out.append(TextContent(type="text", text=f"{head}\n{_describe(r, w, h, label, None)}"))
        out.append(_image_block(r.image))
    return out


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
