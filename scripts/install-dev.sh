#!/usr/bin/env sh
# Link this checkout into IngeTrazo's per-user plugins folder (Flatpak if
# installed, else ~/.local/share). Restart IngeTrazo afterwards.
set -eu
SRC="$(cd "$(dirname "$0")/.." && pwd)/step_import"
if flatpak info com.ingetrazo.IngeTrazo >/dev/null 2>&1; then
    DIR="$HOME/.var/app/com.ingetrazo.IngeTrazo/data/ingetrazo/plugins"
else
    DIR="${XDG_DATA_HOME:-$HOME/.local/share}/ingetrazo/plugins"
fi
mkdir -p "$DIR"
ln -sfn "$SRC" "$DIR/step_import"
echo "Linked $DIR/step_import -> $SRC"
