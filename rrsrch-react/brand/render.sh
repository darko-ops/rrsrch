#!/bin/sh
# Regenerates the brand images in public/: the share card (og.png) and the icons.
set -e
cd "$(dirname "$0")/.."
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --virtual-time-budget=5000 \
  --window-size=1200,630 --screenshot=public/og.png "file://$PWD/brand/og.html"
python3 brand/icons.py public
