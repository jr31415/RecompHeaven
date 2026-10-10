#!/usr/bin/env python3
"""Turn prepared images + ingest output into content-validated title banks.

  python tools/gen_banks.py --recompiler nds_recompile --images IMAGES \
      --ingest INGEST --out BANKDIR [--all-overlays]

Every bank is emitted with --validate-live-bytes: dispatch rows hash the live
guest bytes, so the 165 overlays that share three RAM addresses are told apart
by content, never by PC. Bank ids contain _arm9_/_arm7_ (the runner's CMake
classifies title banks by that substring).
"""
import argparse, hashlib, json, re, shutil, subprocess, sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--recompiler", required=True); ap.add_argument("--images", required=True)
ap.add_argument("--ingest", required=True, nargs="+",
                help="one or more ingest dirs; seeds are unioned per module (monotonic)"); ap.add_argument("--out", required=True)
ap.add_argument("--no-page-banks", action="store_true",
                help="skip banks built from runtime-captured pages (needs only the ROM + seed lists)")
ap.add_argument("--all-overlays", action="store_true",
                help="also emit every ROM overlay at its table address (entry-only discovery)")
a = ap.parse_args()
img, out = Path(a.images), Path(a.out)
ingests = [Path(p) for p in a.ingest]
shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
work = out.parent / (out.name + "-work"); shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True)

def entries_of(path):
    return re.findall(r'addr\s*=\s*(0x[0-9A-Fa-f]+)\s*\nmode\s*=\s*"(arm|thumb)"', Path(path).read_text())

def header(bid, cpu, isa, base, blob):
    return (f'[program]\nname = "{bid}"\nid = "{bid}"\ncpu = "{cpu}"\nisa = "{isa}"\n'
            f'load_address = {base:#010x}\nsize = {len(blob):#010x}\nentry_pc = {base:#010x}\n\n'
            f'[identity]\nsha1 = "{hashlib.sha1(blob).hexdigest()}"\n\n')

jobs = []  # (bank id, config text, blob)
def add(bid, cpu, isa, base, blob, seeds):
    seen, body = set(), ""
    for addr, mode in seeds:
        v = int(addr, 16)
        if not (base <= v < base + len(blob)) or (v, mode) in seen: continue
        seen.add((v, mode)); body += f'[[entry_point]]\naddr = {v:#010x}\nmode = "{mode}"\n\n'
    jobs.append((bid, header(bid, cpu, isa, base, blob) + body, blob))

mods = {"arm9": img / "arm9.bin", "arm7": img / "arm7.bin"}
for p in sorted((img / "overlays").glob("ov*.bin")): mods[p.stem] = p
seed_files = {}
for ing in ingests:
    for sf in sorted((ing / "seeds").glob("*.toml")):
        seed_files.setdefault(sf.stem, []).append(sf)
for stem, sfs in sorted(seed_files.items()):
    m = re.match(r"(arm9|arm7)_([a-z0-9]+)_([0-9a-f]+)$", stem)
    if not m or m.group(2) == "unresolved": continue
    sf = sfs[0]
    cpu, mod, base = m.group(1), m.group(2), int(m.group(3), 16)
    if mod not in mods: print("skip (no image):", stem); continue
    blob = mods[mod].read_bytes()
    add(f"rh_{cpu}_{mod}_{base:08x}", cpu, "armv5te" if cpu == "arm9" else "armv4t",
        base, blob,
        [e for f in sfs for e in entries_of(f)])

# Runtime-materialised pages that exist nowhere in the ROM (ingest wrote bin+toml).
page_ids = set()
for ing in ([] if a.no_page_banks else ingests):
    for t in sorted((ing / "images").glob("rh_*.toml")):
        b = t.with_suffix(".bin")
        if not b.exists(): continue
        txt = t.read_text(); bid = re.search(r'id\s*=\s*"([^"]+)"', txt).group(1)
        if bid in page_ids: continue
        page_ids.add(bid); jobs.append((bid, txt, b.read_bytes()))

if a.all_overlays:
    ov = json.loads((img / "overlays.json").read_text())
    for r in ov:
        stem = Path(r["file"]).stem; base = int(r["load_address"], 16)
        bid = f"rh_arm9_{stem}_{base:08x}"
        if any(j[0] == bid for j in jobs): continue
        blob = (img / "overlays" / r["file"]).read_bytes()
        add(bid, "arm9", "armv5te", base, blob, [(r["load_address"], "arm")])

ok = 0
for bid, cfg, blob in jobs:
    c, b = work / f"{bid}.toml", work / f"{bid}.bin"
    c.write_text(cfg); b.write_bytes(blob)
    r = subprocess.run([a.recompiler, "--config", str(c), "--bin", str(b), "--out", str(out),
                        "--bank", bid, "--shards", "2", "--validate-live-bytes"],
                       capture_output=True, text=True)
    last = (r.stdout.strip().splitlines() or [""])[-2:] if r.returncode == 0 else r.stderr.strip().splitlines()[-2:]
    print(("ok  " if r.returncode == 0 else "FAIL"), bid, "|", " ".join(last)[:140])
    ok += r.returncode == 0
print(f"{ok}/{len(jobs)} banks -> {out}")
sys.exit(0 if ok == len(jobs) else 1)
