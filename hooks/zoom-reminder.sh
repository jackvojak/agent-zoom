#!/bin/bash
# PostToolUse hook on Read. When the file read was an image, remind the model
# that the zoom tools exist so fine detail is zoomed rather than guessed.
# Reads the hook payload on stdin; emits additionalContext only for image paths.
input=$(cat)
if command -v jq >/dev/null 2>&1; then
  path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""' 2>/dev/null)
else
  path=$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null)
fi
lower=$(printf '%s' "$path" | tr '[:upper:]' '[:lower:]')
case "$lower" in
  *.png|*.jpg|*.jpeg|*.gif|*.webp|*.bmp|*.tiff|*.tif)
    printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"This was an image. Before reporting any small text, tick label, legend entry, cell value, data point, line crossing or other fine detail from it, call the zoom MCP server: image_info first, then zoom or zoom_many on the relevant region. Do not guess from the downscaled view."}}'
    ;;
esac
exit 0
