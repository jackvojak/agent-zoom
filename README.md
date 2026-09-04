# zoom-mcp

An MCP server that lets Claude read fine detail in plot and figure images. Claude
sees images downscaled to a token budget, so small tick labels, legend entries and
heatmap cell values are often illegible. `zoom` crops from the full-resolution
original and upscales the crop to fill the budget. `image_info` returns the
original size plus a gridded overview so every coordinate Claude reasons about
is an original pixel coordinate.

## Tools

- `image_info(image_path, grid=True, grid_step=None)`: original width, height,
  mode and file size, the recommended maximum zoom box width for 3x, plus a
  downscaled overview with ruler margins labelled in original pixels.
- `zoom(image_path, x1, y1, x2, y2, label=None, region=None, coords="pixel", grid=False)`:
  crop and magnify one box. `region` presets: `top_left, top_right, bottom_left,
  bottom_right, center, left_half, right_half, top_half, bottom_half, x_axis,
  y_axis, legend_right, title`. `coords="fraction"` takes 0..1 values. Boxes
  that look fractional in pixel mode are rejected with a hint. Tiny boxes are
  padded to a minimum side so the result is not a blur.
- `zoom_many(image_path, boxes, labels=None, coords="pixel", grid=False)`: up to
  6 boxes in one call, each at the full budget, returned in order.

`ZOOM_MCP_TIER` selects the budget: `claude-code` (default, 2000 px long edge,
matches what Claude Code displays), `high` (2576 px) or `standard` (1568 px).

## Install

`uv` must be on PATH for the plugin-style `.mcp.json` entry. Otherwise use the
absolute path as in the personal entry below.

```bash
uv sync
uv run pytest
uv run python tests/smoke_client.py path/to/plot.png /tmp/zoom_out
```

Personal Claude Code `~/.claude.json` entry:

```json
"zoom": {
  "type": "stdio",
  "command": "/Users/jack.vojak/.local/bin/uv",
  "args": ["run", "--frozen", "--directory", "/Users/jack.vojak/Projects/zoom-mcp", "zoom-mcp"],
  "env": { "ZOOM_MCP_TIER": "claude-code" }
}
```

Skill: `ln -s ~/Projects/zoom-mcp/skills/zoom ~/.claude/skills/zoom`, then `/zoom <image> [claim]`.

The repo is laid out as a Claude Code plugin (`.claude-plugin/plugin.json`,
`.mcp.json`, `skills/`) so it can be installed as one later.
