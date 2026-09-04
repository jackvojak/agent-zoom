"""Start the server over stdio the way Claude Code does and exercise both tools.

Usage: uv run python tests/smoke_client.py <image_path> <out_dir>
Saves overview.jpg, zoom_legend.jpg and zoom_grid.jpg into out_dir.
"""

from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]


def _dump(result, out: Path) -> None:
    for block in result.content:
        if block.type == "text":
            print(block.text)
        elif block.type == "image":
            out.write_bytes(base64.b64decode(block.data))
            print(f"-> wrote {out} ({out.stat().st_size // 1024} KB, {block.mime_type})")
    if result.is_error:
        print("TOOL REPORTED is_error=True")


async def main(image: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    params = StdioServerParameters(command="uv", args=["run", "--directory", str(ROOT), "zoom-mcp"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])
            zoom_schema = next(t for t in tools.tools if t.name == "zoom").input_schema
            props = zoom_schema["properties"]
            print("region enum:", (props["region"].get("enum") or [a.get("enum") for a in props["region"].get("anyOf", [])]))
            print("coords enum:", props["coords"].get("enum"))

            print("\n== image_info ==")
            r = await session.call_tool("image_info", {"image_path": image})
            _dump(r, out_dir / "overview.jpg")

            print("\n== zoom region=legend_right ==")
            r = await session.call_tool("zoom", {"image_path": image, "region": "legend_right", "label": "colourbar"})
            _dump(r, out_dir / "zoom_legend.jpg")

            print("\n== zoom fraction box with grid ==")
            r = await session.call_tool(
                "zoom",
                {"image_path": image, "x1": 0.0, "y1": 0.6, "x2": 0.5, "y2": 1.0, "coords": "fraction", "grid": True},
            )
            _dump(r, out_dir / "zoom_grid.jpg")

            print("\n== zoom_many: 3 row bands ==")
            r = await session.call_tool(
                "zoom_many",
                {
                    "image_path": image,
                    "boxes": [[0, 0.13, 0.53, 0.35], [0, 0.35, 0.53, 0.6], [0, 0.6, 0.53, 0.97]],
                    "labels": ["rows top", "rows middle", "rows bottom"],
                    "coords": "fraction",
                },
            )
            texts = [b for b in r.content if b.type == "text"]
            imgs = [b for b in r.content if b.type == "image"]
            for i, (t, im) in enumerate(zip(texts, imgs), 1):
                print(t.text)
                out = out_dir / f"many_{i}.jpg"
                out.write_bytes(base64.b64decode(im.data))
                print(f"-> wrote {out} ({out.stat().st_size // 1024} KB)")

            print("\n== error cases ==")
            r = await session.call_tool("zoom", {"image_path": image, "region": "nowhere"})
            _dump(r, out_dir / "unused.jpg")
            r = await session.call_tool("zoom", {"image_path": "/nope.png", "x1": 0, "y1": 0, "x2": 10, "y2": 10})
            _dump(r, out_dir / "unused.jpg")
            r = await session.call_tool("zoom", {"image_path": image, "x1": 50, "y1": 50, "x2": 40, "y2": 60})
            _dump(r, out_dir / "unused.jpg")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], Path(sys.argv[2])))
