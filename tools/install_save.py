#!/usr/bin/env python3
"""Install a downloaded Rhythm Heaven (DS) save as the game's save file.

  python3 tools/install_save.py PATH_TO_SAVE [--dest FILE] [--dry-run]

Accepts a raw 8192-byte .sav, an Action Replay .duc (8 KiB EEPROM in a
256 KB image), a DeSmuME .dsv (8192 bytes + a 122-byte footer),
or an .sav with trailing padding. Anything else is refused with the reason
rather than guessed at. The current save is backed up first, and the file is
checked for being not-blank and not all 0xFF. Never overwrites without a backup.
"""
import argparse, shutil, sys, time
from pathlib import Path

SIZE = 8192
DUC_HEADER = 0x1F4
FOOTER_MARK = b"|<--Snip above here to create a raw sav"
default_dest = Path.home() / "Library/Application Support/RhythmHeavenRecomp/rhythmheaven.sav"

ap = argparse.ArgumentParser()
ap.add_argument("save"); ap.add_argument("--dest", default=str(default_dest))
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()
src = Path(a.save.strip().strip("'\"")).expanduser()
if not src.is_file():
    sys.exit(f"not a file: {src}")
d = src.read_bytes()
note = ""
if len(d) == SIZE:
    raw = d; note = "raw 8 KiB"
elif FOOTER_MARK in d and d.index(FOOTER_MARK) >= SIZE:
    raw = d[:SIZE]; note = "DeSmuME footer stripped"
elif len(d) > SIZE and len(d) <= SIZE + 4096 and set(d[SIZE:]) <= {0, 0xFF}:
    raw = d[:SIZE]; note = f"trailing padding ({len(d) - SIZE} bytes) trimmed"
elif d[:5] == b"ARDS0" and len(d) > DUC_HEADER + SIZE:
    # Action Replay DS "Converted Savegame": a 500-byte header, then the card's
    # save padded out to a 256 KB image. The real EEPROM is the leading 8 KiB and
    # everything after it must be erased flash (0xFF), otherwise this is some
    # other game's / chip's save and we refuse.
    payload = d[DUC_HEADER:]
    if len(payload) < SIZE or set(payload[SIZE:]) - {0xFF}:
        sys.exit(".duc payload does not look like an 8 KiB EEPROM save padded with 0xFF "
                 "(wrong game or chip?); refusing")
    raw = payload[:SIZE]; note = f"Action Replay .duc, {len(payload)}-byte image -> leading 8 KiB"
elif src.suffix.lower() == ".duc":
    sys.exit("unrecognized .duc container; refusing")
else:
    sys.exit(f"unexpected size {len(d)} bytes; Rhythm Heaven (US) uses an 8192-byte EEPROM. "
             "Is this the right game/region (YLZE, US)?")
if set(raw) <= {0} or set(raw) <= {0xFF}:
    sys.exit("save is blank (all 0x00 or all 0xFF); refusing")
used = sum(1 for b in raw if b not in (0, 0xFF))
print(f"source: {src.name} -> {note}; {used} non-blank bytes")
dest = Path(a.dest)
if a.dry_run:
    print("dry run; would install to", dest); sys.exit(0)
dest.parent.mkdir(parents=True, exist_ok=True)
if dest.exists():
    bk = dest.with_name(f"{dest.stem}.backup-{time.strftime('%Y%m%d-%H%M%S')}{dest.suffix}")
    shutil.copy2(dest, bk); print("backed up current save ->", bk)
tmp = dest.with_suffix(".tmp"); tmp.write_bytes(raw); tmp.replace(dest)
print("installed ->", dest, "\nstart the game and choose the file slot.")
