# zoom-mcp

An MCP server that lets Claude read fine detail in plot and figure images. Claude
sees images downscaled to a token budget, so small tick labels, legend entries and
heatmap cell values are often illegible. `zoom` crops from the full-resolution
original and upscales the crop to fill the budget. `image_info` returns the
original size plus a gridded overview so every coordinate Claude reasons about
is an original pixel coordinate.

## Tools

- `image_info(image_path, grid=True, grid_step=None)`: original width, height,
  mode and file size, plus a downscaled overview with a grid labelled in original
  pixels.
- `zoom(image_path, x1, y1, x2, y2, label=None, region=None, coords="pixel", grid=False)`:
  crop and magnify a box. `region` presets: `top_left, top_right, bottom_left,
  bottom_right, center, left_half, right_half, top_half, bottom_half, x_axis,
  y_axis, legend_right, title`. `coords="fraction"` takes 0..1 values. Tiny boxes
  are padded to a minimum side so the result is not a blur.

Set `ZOOM_MCP_TIER=standard` for the 1568 px / 1568 token budget. Default is
`high` (2576 px / 4784 tokens).

## Install

```bash
uv sync
uv run pytest
uv run python tests/smoke_client.py path/to/plot.png /tmp/zoom_out
```

Claude Code `~/.claude.json` entry:

```json
"zoom": {
  "type": "stdio",
  "command": "uv",
  "args": ["run", "--directory", "/Users/jack.vojak/Projects/zoom-mcp", "zoom-mcp"]
}
```

Skill: `ln -s ~/Projects/zoom-mcp/skills/zoom ~/.claude/skills/zoom`, then `/zoom <image> [claim]`.

The repo is laid out as a Claude Code plugin (`.claude-plugin/plugin.json`,
`.mcp.json`, `skills/`) so it can be installed as one later.
