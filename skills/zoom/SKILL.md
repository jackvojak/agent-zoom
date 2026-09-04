---
name: zoom
description: "Review a figure or plot image carefully: read it, describe it, zoom into unclear regions with the zoom MCP tool, and report whether the figure supports the stated claim. Use when the user types /zoom <image_path> [claim], or asks to check, read, or verify a chart, heatmap, or plot."
argument-hint: "<image_path> [claim]"
---

# Zoom: careful figure review

Arguments: `$ARGUMENTS` = `<image_path> [claim text]`. The image path is required. Everything after it is the claim to check. If no claim is given, the verdict is NO CLAIM GIVEN.

## Procedure

1. **Parse args.** First token is the image path. The rest is the claim.
2. **Overview.** Call `image_info` on the path. Note the original width and height and the recommended maximum box width. Describe the figure at a high level: chart type, axes, legend or colourbar, and what each visual channel encodes.
3. **Zoom what you cannot read.** Zoom only regions that are not legible in the overview. Use original pixel boxes at most the recommended width (max_edge / 3) so text comes back at 3x or more. Use `zoom_many` to batch up to 6 boxes. Use a preset (`title`, `x_axis`, `y_axis`, `legend_right`) only when the target really sits in that band. For dense unlabelled panels, such as a heatmap strip with hundreds of rows, use `grid=True` so a stripe's y position maps to a row index. For outlier hunting, zoom the rows or columns with extreme colours and read their labels. Zoom again on a sub-region while text is still unclear.
4. **Never report a number or label you have not seen legibly in the overview or a zoom.** If something stays unreadable after two zooms, say it is unreadable.
5. **Report** in plain language, short sentences, no em dashes:
   - What the figure shows.
   - Exact values and labels read, each tied to where it was read.
   - Notable outliers or anomalies with their original pixel coordinates.
   - Verdict: SUPPORTS / PARTIALLY SUPPORTS / DOES NOT SUPPORT / NO CLAIM GIVEN, followed by the evidence.
