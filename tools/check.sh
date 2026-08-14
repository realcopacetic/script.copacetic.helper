#!/bin/sh
python3 "$(dirname "$0")/golden_diff.py" \
  "/Users/arash/Library/Application Support/Kodi/addons/skin.copacetic2/16x9" \
  "$(dirname "$0")/golden" "$@"
