#!/usr/bin/env bash
# Sync generated JSON from data/ into web/public/data/ so the Vite dev server
# and the production build both serve the latest collector output.
#
# Run after `python -m collector.main --once` and before `npm run build`.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/data"
DST="$ROOT/web/public/data"

mkdir -p "$DST"

for f in latest.json dids.json kibble.json tclk.json reputation.json; do
  if [ -f "$SRC/$f" ]; then
    cp "$SRC/$f" "$DST/$f"
    echo "synced $f"
  fi
done

# Always keep the directory present even if no files exist yet
touch "$DST/.gitkeep"
