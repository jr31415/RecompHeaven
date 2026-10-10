#!/bin/sh
# Drag a downloaded .sav onto the Terminal window after typing:  scripts/install_save.sh
# (a dropped file pastes its path). Backs up the current save first.
HERE="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 -I "$HERE/tools/install_save.py" "$@"
