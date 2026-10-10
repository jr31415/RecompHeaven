#!/bin/sh
# Play Rhythm Heaven in a window. Mouse on the bottom screen = stylus.
# Usage: scripts/play_window.sh [rotation: 0|90|180|270, default 270]
#
# Keys: arrows=D-pad  Z=A  X=B  A=Y  S=X  Q=L  W=R  Enter/P=Start
#       Backspace=Select  Esc=settings  (hold Tab = virtual stylus)
#       Space = tap the touchscreen at the mouse cursor (aim with the mouse,
#               tap with the spacebar; drag by moving the mouse while held)
# Tuning (env): NDS_AUDIO_QUEUE_FRAMES (min floor, default 192 ~ 6 ms, adaptive)
#               NDS_VSYNC=0 to present immediately (tearing, lowest video lag)
# Emulation + audio run on a worker thread; the main thread only presents
# (vsync) so a late frame never starves the audio clock. NDS_THREADED_PRESENT=0
# goes back to the single-thread loop.
# Needs the SDL3 build at ~/dev/rh-build/runner-play (see docs/RUNNING.md).
HERE="$(cd "$(dirname "$0")/.." && pwd)"
ROM="${ROM:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents/GitHub/ndsrecomp/3588 - Rhythm Heaven (US)(XenoPhobia).nds}"
RUNNER="${RUNNER:-$HOME/dev/rh-build/runner-play/nds_runner}"
ROT="${1:-270}"
SAVEDIR="$HOME/Library/Application Support/RhythmHeavenRecomp"
mkdir -p "$SAVEDIR" "$HOME/dev/rh-build/play" "$HOME/dev/rh-build/coverage"
cd "$HOME/dev/rh-build/play"
STAMP="$(date +%Y%m%d-%H%M%S)"
export NDS_THREADED_PRESENT="${NDS_THREADED_PRESENT:-1}"
export NDS_FRAME_LOG="$HOME/dev/rh-build/play/frame_times-$STAMP.csv"
exec "$RUNNER" . --interactive --freebios --generated-firmware --boot direct \
  --rom "$ROM" --config "$HERE/game.toml" \
  --save-path "$SAVEDIR/rhythmheaven.sav" \
  --coverage-manifest "$HOME/dev/rh-build/coverage/session-$STAMP.json" \
  --screen-rotation "$ROT"
