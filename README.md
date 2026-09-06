# zoom-mcp

An MCP server that lets Claude resolve fine detail in any image: plots, charts,
screenshots, diagrams, scans. Claude sees images downscaled to a token budget, so
small text, individual data points, line crossings and small features are often
unresolvable. `zoom` crops from the full-resolution
original and upscales the crop to fill the budget. `image_info` returns the
original size plus a gridded overview so every coordinate Claude reasons about
is an original pixel coordinate.

The approach follows Anthropic's crop-tool cookbook notebook, adapted for the
Claude Code harness and packaged as a plugin:
https://github.com/anthropics/claude-cookbooks/blob/main/multimodal/crop_tool.ipynb

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

## Install as a Claude Code plugin (recommended)

Requires [uv](https://docs.astral.sh/uv/) on PATH. The plugin bundles three things:
the MCP server, the `/zoom:zoom` skill, and a hook that reminds Claude to zoom
whenever it reads an image file.

Push this repo to your git host, then in Claude Code:

```
/plugin marketplace add <org>/zoom-mcp            # GitHub shorthand
/plugin marketplace add https://<host>/<org>/zoom-mcp.git   # GitLab or any git URL
/plugin install zoom@zoom-mcp
```

From a local checkout instead:

```
/plugin marketplace add /path/to/zoom-mcp
/plugin install zoom@zoom-mcp
```

The first launch creates a virtual environment inside the plugin cache from
`uv.lock`, so it takes a few seconds; later launches are instant.

Plugins cannot grant tool permissions, so to avoid a prompt on every call add an
allow rule to `~/.claude/settings.json`. Run `/mcp` once to see the server's
exact tool prefix, then:

```json
"permissions": { "allow": ["mcp__<prefix>__image_info", "mcp__<prefix>__zoom", "mcp__<prefix>__zoom_many"] }
```

To recommend the plugin to everyone working in a repo, add to that repo's
`.claude/settings.json`:

```json
"extraKnownMarketplaces": ["<org>/zoom-mcp"],
"enabledPlugins": { "zoom@zoom-mcp": true }
```

## Manual install (no plugin)

```bash
git clone <remote> ~/Projects/zoom-mcp
claude mcp add-json --scope user zoom '{"type":"stdio","command":"uv","args":["run","--frozen","--directory","'"$HOME"'/Projects/zoom-mcp","zoom-mcp"],"env":{"ZOOM_MCP_TIER":"claude-code"}}'
ln -s ~/Projects/zoom-mcp/skills/zoom ~/.claude/skills/zoom
```

If `uv` is not on the PATH Claude Code sees, use its absolute path as `command`.
The tools then appear as `mcp__zoom__image_info`, `mcp__zoom__zoom` and
`mcp__zoom__zoom_many`, and the skill as `/zoom`. To get the image-read
reminder as well, copy `hooks/zoom-reminder.sh` somewhere stable and wire it
as a `PostToolUse` hook with matcher `Read` in `~/.claude/settings.json`.

## Making the zoom automatic

The plugin nudges Claude to zoom without being asked, through three layers:
tool docstrings and server instructions, the `/zoom:zoom` skill description,
and the Read hook. For the strongest effect add a standing rule to your
`~/.claude/CLAUDE.md`:

```
Whenever a conclusion rests on fine detail in an image (small text, tick labels,
legend entries, cell values, individual data points, line crossings), call
image_info first for size and a gridded overview, then zoom on the relevant
regions. Never report a value or label that was not seen clearly in a zoom.
```

## Development

```bash
uv sync
uv run pytest
uv run python tests/smoke_client.py path/to/plot.png /tmp/zoom_out
claude plugin validate .
```
