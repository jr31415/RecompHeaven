#!/bin/sh
# Play Rhythm Heaven in a window. Mouse on the bottom screen = stylus.
# Usage: scripts/play_window.sh [rotation: 0|90|180|270, default 270]
# Needs the SDL3 build at ~/dev/rh-build/runner-play (see docs/RUNNING.md).
ROM="${ROM:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents/GitHub/ndsrecomp/3588 - Rhythm Heaven (US)(XenoPhobia).nds}"
RUNNER="${RUNNER:-$HOME/dev/rh-build/runner-play/nds_runner}"
ROT="${1:-270}"
mkdir -p "$HOME/dev/rh-build/play" && cd "$HOME/dev/rh-build/play"
exec "$RUNNER" . --interactive --freebios --generated-firmware --boot direct \
  --rom "$ROM" --no-save --no-coverage-manifest --screen-rotation "$ROT"
