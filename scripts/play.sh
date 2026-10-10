#!/bin/sh
# Usage: scripts/play.sh [script.json] [outdir]
# Runs the banked runner headless through a scripted session and saves PNGs.
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
ROM="${ROM:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents/GitHub/ndsrecomp/3588 - Rhythm Heaven (US)(XenoPhobia).nds}"
RUNNER="${RUNNER:-$HOME/dev/rh-build/runner-title2/nds_runner}"
SCRIPT="${1:-$HERE/scripts/play1.json}"
OUT="${2:-/tmp/rh-frames}"
mkdir -p "$OUT"
python3 -I "$HERE/tools/capture_session.py" --runner "$RUNNER" --rom "$ROM" \
  --work /tmp/rh-w --out "$OUT" --script "$SCRIPT"
echo "frames in $OUT"; open "$OUT" 2>/dev/null || true
