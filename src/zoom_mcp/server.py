"""MCP server exposing `zoom` and `image_info` for reading fine detail in images.

Runs over stdio. Select the visual token budget with ZOOM_MCP_TIER=high|standard.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ContentBlock, ImageContent, TextContent
from PIL import Image, UnidentifiedImageError

from zoom_mcp import imaging

mcp = MCPServer(
    "zoom-mcp",
    instructions=(
        "Tools for inspecting plot and figure images at full resolution. "
        "Call image_info first to learn the original pixel size, then zoom into "
        "regions before reading any small text or values."
    ),
)


def _budget() -> imaging.Budget:
    return imaging.Budget.for_tier(os.environ.get("ZOOM_MCP_TIER", "high"))


def _text(msg: str) -> list[ContentBlock]:
    return [TextContent(type="text", text=msg)]


def _image_block(img: Image.Image) -> ImageContent:
    data = base64.b64encode(imaging.encode_jpeg(img)).decode()
    return ImageContent(type="image", data=data, mime_type="image/jpeg")


def _open(image_path: str) -> Image.Image:
    path = Path(image_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    img = Image.open(path)
    img.load()
    return img


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
    except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
        return _text(f"Error: {exc}")
    budget = _budget()
    view = imaging.overview(img, budget)
    full = imaging.Box(0, 0, img.width, img.height)
    step = None
    if grid:
        step = grid_step or imaging.grid_step(max(img.width, img.height))
        view = imaging.draw_grid(view, full, step)
    size_kb = Path(image_path).expanduser().stat().st_size / 1024
    lines = [
        f"File: {image_path}",
        f"Original size: {img.width}x{img.height} px (width x height), mode {img.mode}, {size_kb:.1f} KB.",
        f"Overview returned at {view.width}x{view.height} px.",
        "Coordinates for `zoom` are ORIGINAL pixels, origin top-left, x right, y down.",
    ]
    if grid:
        lines.append(f"Grid lines every {step} original px; labels give original pixel positions.")
    return [TextContent(type="text", text="\n".join(lines)), _image_block(view)]


@mcp.tool(structured_output=False)
def zoom(
    image_path: str,
    x1: float = 0,
    y1: float = 0,
    x2: float = 0,
    y2: float = 0,
    label: str | None = None,
    region: str | None = None,
    coords: str = "pixel",
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
        region: Named preset that replaces the box: top_left, top_right,
            bottom_left, bottom_right, center, left_half, right_half, top_half,
            bottom_half, x_axis, y_axis, legend_right, title.
        coords: "pixel" (default) or "fraction".
        grid: Overlay a grid labelled in ORIGINAL pixel coordinates on the
            returned crop, to refine the next zoom precisely.
    """
    try:
        img = _open(image_path)
    except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
        return _text(f"Error: {exc}")
    w, h = img.size
    try:
        if region is not None:
            bx = imaging.region_box(region, w, h)
        elif coords == "fraction":
            bx = imaging.fraction_box(x1, y1, x2, y2, w, h)
        elif coords == "pixel":
            bx = (x1, y1, x2, y2)
        else:
            return _text(f"Error: coords must be 'pixel' or 'fraction', got {coords!r}.")
        box = imaging.normalise_box(*bx, w, h)
    except ValueError as exc:
        return _text(f"Error: {exc}")

    budget = _budget()
    out = imaging.crop_and_zoom(img, box, budget)
    if grid:
        out = imaging.draw_grid(out, box)
    scale = out.width / box.width

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
    lines.append(f"Returned at {out.width}x{out.height} px ({scale:.1f}x magnification).")
    if grid:
        lines.append("Grid labels are ORIGINAL pixel coordinates.")
    return [TextContent(type="text", text="\n".join(lines)), _image_block(out)]


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
