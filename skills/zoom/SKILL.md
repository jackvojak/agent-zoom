---
name: zoom
description: "Review a figure or plot image carefully: read it, describe it, zoom into unclear regions with the zoom MCP tool, and report whether the figure supports the stated claim. Use when the user types /zoom <image_path> [claim], or asks to check, read, or verify a chart, heatmap, or plot."
---

# Zoom: careful figure review

Arguments: `$ARGUMENTS` = `<image_path> [claim text]`. The image path is required. Everything after it is the claim to check. If no claim is given, the verdict is NO CLAIM GIVEN.

## Procedure

1. **Parse args.** Take the first token as the image path. Treat the rest as the claim.
2. **Overview.** Call `image_info` on the path. Note the original width and height. Describe the figure at a high level: chart type, axes, legend or colourbar, and what each visual channel encodes.
3. **Zoom systematically.** Use `zoom` with boxes in original pixels, or the named presets. Cover in order:
   - title (`region="title"`)
   - x axis labels and ticks (`region="x_axis"`)
   - y axis labels and ticks (`region="y_axis"`)
   - legend or colourbar (`region="legend_right"` or a pixel box)
   - any region where values or labels are small, dense, or where an outlier or anomaly is suspected.
   For heatmaps: zoom rows and columns with extreme colours to read the exact row and column labels and any cell values. Check the colourbar scale so colours map to numbers.
   Use `grid=True` when you need exact coordinates for the next, tighter zoom. Zoom again on a sub-region whenever text is still not clearly legible.
4. **Never report a number or label you have not seen legibly in a zoom.** If something stays unreadable after two zooms, say it is unreadable.
5. **Report** in plain language, short sentences, no em dashes:
   - What the figure shows.
   - Exact values and labels read, each tied to where it was read.
   - Notable outliers or anomalies with their original-pixel coordinates.
   - Verdict: SUPPORTS / PARTIALLY SUPPORTS / DOES NOT SUPPORT / NO CLAIM GIVEN, followed by the evidence.
