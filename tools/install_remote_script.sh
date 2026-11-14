#!/bin/bash
# Install (or with --uninstall, remove) the Faderhand control script. It never touches other control scripts.
# Live loads Remote Scripts only at startup (measured 2026-11-10: re-picking the Control Surface slot doesn't reload code).
# --ext copies only ext.py: then call reload_extensions (lt.call or the MCP tool) and Live needs no restart.
#
# Migration: if an older install folder named WavReadBridge already exists, it is updated with the same code so a
# Control Surface slot still set to WavReadBridge keeps listening on 9878. It is never created, and --uninstall never
# removes it. Do not enable Faderhand and WavReadBridge in Live at the same time (both bind port 9878).
set -euo pipefail
RS="$HOME/Music/Ableton/User Library/Remote Scripts"
DEST="$RS/Faderhand"
OLD="$RS/WavReadBridge"
SRC="$(cd "$(dirname "$0")/.." && pwd)/remote_script/Faderhand"
STAMP=$(date +%Y%m%d-%H%M%S)
BK="${FADERHAND_BACKUP_DIR:-$(dirname "$0")/../backups/installed}"
if [ -d "$DEST" ]; then
  mkdir -p "$BK"
  cp -Rp "$DEST" "$BK/Faderhand-$STAMP"
fi
if [ "${1:-}" = "--uninstall" ]; then
  rm -rf "$DEST"; echo "removed $DEST (backup in backups/installed/Faderhand-$STAMP)"
  if [ -d "$OLD" ]; then
    echo "note: the older folder $OLD still exists. Remove it yourself once no Control Surface slot uses it."
  fi
  exit 0
fi
if [ -d "$OLD" ]; then
  mkdir -p "$BK"
  cp -Rp "$OLD" "$BK/WavReadBridge-$STAMP"
fi
if [ "${1:-}" = "--ext" ]; then
  mkdir -p "$DEST"
  cp -p "$SRC/ext.py" "$DEST/ext.py"; rm -rf "$DEST/__pycache__"
  if [ -d "$OLD" ]; then cp -p "$SRC/ext.py" "$OLD/ext.py"; rm -rf "$OLD/__pycache__"; fi
  shasum -a 256 "$DEST/ext.py"
  echo "installed ext.py; now call reload_extensions"; exit 0
fi
mkdir -p "$DEST"
cp -p "$SRC"/*.py "$DEST/"
rm -rf "$DEST/__pycache__"
shasum -a 256 "$DEST"/*.py
echo "installed to $DEST; restart Live to load the core (__init__.py)"
if [ -d "$OLD" ]; then
  cp -p "$SRC"/*.py "$OLD/"
  rm -rf "$OLD/__pycache__"
  echo "also updated the existing older folder $OLD, so a slot still set to WavReadBridge keeps listening on 9878."
  echo "Enable only one of Faderhand or WavReadBridge in Live, not both."
fi
