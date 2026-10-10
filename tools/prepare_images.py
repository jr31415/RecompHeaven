#!/usr/bin/env python3
"""Split the ROM into the module images the framework's coverage/ingest tools expect.

  python tools/prepare_images.py --rom ROM --out DIR

Writes DIR/arm9.bin, arm7.bin, itcm.bin (autoload block), overlays/ovNNN.bin,
overlays.json and arm9.toml/arm7.toml (declared load addresses). Output is
ROM-derived: keep it out of git (the title repo .gitignore covers images/).
"""
import argparse, hashlib, json, struct
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--rom", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
d = Path(a.rom).read_bytes()
out = Path(a.out); (out / "overlays").mkdir(parents=True, exist_ok=True)
sha = hashlib.sha1(d).hexdigest()
a9o, a9e, a9l, a9s = struct.unpack("<IIII", d[0x20:0x30])
a7o, a7e, a7l, a7s = struct.unpack("<IIII", d[0x30:0x40])
arm9 = d[a9o:a9o + a9s]; arm7 = d[a7o:a7o + a7s]
(out / "arm9.bin").write_bytes(arm9); (out / "arm7.bin").write_bytes(arm7)

def toml(name, cpu, isa, load, size, entry, blob):
    return (f'[program]\nname = "{name}"\nid = "{name}"\ncpu = "{cpu}"\nisa = "{isa}"\n'
            f'load_address = {load:#010x}\nsize = {size:#010x}\nentry_pc = {entry:#010x}\n\n'
            f'[identity]\nsha1 = "{hashlib.sha1(blob).hexdigest()}"\n\n'
            f'[[entry_point]]\naddr = {entry:#010x}\nmode = "arm"\nname = "_start"\n')
(out / "arm9.toml").write_text(toml("arm9", "arm9", "armv5te", a9l, a9s, a9e, arm9))
(out / "arm7.toml").write_text(toml("arm7", "arm7", "armv4t", a7l, a7s, a7e, arm7))

# ARM9 autoload blocks (ITCM/DTCM), located through the module params.
i = arm9.find(bytes.fromhex("2106c0de")); mp = struct.unpack("<9I", arm9[i - 0x1C:i + 8])
lo, hi, start = mp[0] - a9l, mp[1] - a9l, mp[2] - a9l
off, blocks = start, []
for k in range((hi - lo) // 12):
    addr, size, bss = struct.unpack("<III", arm9[lo + 12 * k:lo + 12 * k + 12])
    blocks.append(dict(addr=addr, size=size, bss=bss, image_offset=off))
    (out / f"autoload{k}.bin").write_bytes(arm9[off:off + size]); off += size

t, n = struct.unpack("<II", d[0x50:0x58]); fat = struct.unpack("<I", d[0x48:0x4C])[0]
recs = []
for k in range(n // 32):
    ovid, ram, size, bss, si0, si1, fid, flags = struct.unpack("<IIIIIIII", d[t + 32 * k:t + 32 * k + 32])
    if flags >> 24 & 1:
        raise SystemExit(f"overlay {ovid} is compressed; decompression not implemented")
    s, e = struct.unpack("<II", d[fat + 8 * fid:fat + 8 * fid + 8])
    name = f"ov{ovid:03d}.bin"
    (out / "overlays" / name).write_bytes(d[s:s + size])
    recs.append(dict(file=name, load_address=f"{ram:#x}", size=size, bss=bss, id=ovid))
(out / "overlays.json").write_text(json.dumps(recs, indent=1))
(out / "autoload.json").write_text(json.dumps(blocks, indent=1))
print(f"rom {sha}\narm9 {len(arm9):#x} arm7 {len(arm7):#x} overlays {len(recs)} autoload {len(blocks)} -> {out}")
