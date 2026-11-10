#!/bin/bash
# Install (or with --uninstall, remove) the WavReadBridge control script (WavRead MCP Bridge). It never touches other
# control scripts.
# Live loads Remote Scripts only at startup (measured 2026-11-10: re-picking the Control Surface slot doesn't reload code).
# --ext copies only ext.py: then call reload_extensions (lt.call or the MCP tool) and Live needs no restart.
set -euo pipefail
DEST="$HOME/Music/Ableton/User Library/Remote Scripts/WavReadBridge"
SRC="$(cd "$(dirname "$0")/.." && pwd)/remote_script/WavReadBridge"
STAMP=$(date +%Y%m%d-%H%M%S)
if [ -d "$DEST" ]; then
  mkdir -p "$(dirname "$0")/../backups/installed"
  cp -Rp "$DEST" "$(dirname "$0")/../backups/installed/WavReadBridge-$STAMP"
fi
if [ "${1:-}" = "--uninstall" ]; then
  rm -rf "$DEST"; echo "removed $DEST (backup in backups/installed/WavReadBridge-$STAMP)"; exit 0
fi
mkdir -p "$DEST"
if [ "${1:-}" = "--ext" ]; then
  cp -p "$SRC/ext.py" "$DEST/ext.py"; rm -rf "$DEST/__pycache__"; shasum -a 256 "$DEST/ext.py"
  echo "installed ext.py; now call reload_extensions"; exit 0
fi
cp -p "$SRC"/*.py "$DEST/"
rm -rf "$DEST/__pycache__"
shasum -a 256 "$DEST"/*.py
echo "installed to $DEST; restart Live to load the core (__init__.py)"
