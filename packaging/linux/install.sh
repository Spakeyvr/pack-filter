#!/bin/sh
# Adds Pack Filter to your application menu. Run from the extracted PackFilter folder.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
mkdir -p "$APPS" "$ICONS"
cp "$HERE/packfilter.png" "$ICONS/packfilter.png"
cat > "$APPS/packfilter.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Pack Filter
Comment=Censor lewd cover art in rhythm game song packs
Exec="$HERE/PackFilter" %F
Icon=packfilter
Terminal=false
Categories=Utility;Game;
DESKTOP
echo "Installed. Pack Filter is now in your application menu."
