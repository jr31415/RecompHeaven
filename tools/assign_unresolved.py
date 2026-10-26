#!/usr/bin/env python3
"""File 'unresolved' seeds (pages straddling two modules) under the overlays they really belong to.

Overlays share three RAM slots, so a captured 4 KB page at a slot boundary cannot be tied to one
ROM module by hash. For each unresolved address this tries every overlay whose image covers it and
keeps the ones where a function decoded at that address is clean (valid instructions to a return,
no SVC/coprocessor oddities). Needs capstone.   assign_unresolved.py --images I --seeds data/ingest/seeds
"""
import argparse, json, re
from pathlib import Path
import capstone as cs

ARM = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_ARM); THUMB = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB)
for m in (ARM, THUMB): m.detail = True
BAD = {"svc", "swi", "bkpt", "udf", "cdp", "cdp2", "mcr2", "mrc2", "ldc", "stc", "ldc2", "stc2"}


def is_end(ins):
    m = ins.mnemonic
    if ins.cc not in (cs.arm.ARM_CC_AL, cs.arm.ARM_CC_INVALID): return False
    if m in ("b", "bx"): return True
    pc = lambda op: op.type == cs.arm.ARM_OP_REG and op.reg == cs.arm.ARM_REG_PC
    if m.startswith(("pop", "ldm")) and any(pc(o) for o in ins.operands): return True
    if m in ("mov", "movs", "ldr") and ins.operands and pc(ins.operands[0]): return True
    return False


def clean(blob, base, off, th):
    size = len(blob); seen = {}; work = [off]; md = THUMB if th else ARM
    while work:
        o = work.pop()
        while True:
            if o < 0 or o + 2 > size: return False
            if o in seen: break
            try: ins = next(md.disasm(blob[o:o + 4], base + o, 1))
            except StopIteration: return False
            if ins.mnemonic in BAD or len(seen) > 4000: return False
            seen[o] = ins.size
            if ins.group(cs.CS_GRP_JUMP) or ins.group(cs.CS_GRP_CALL):
                for op in ins.operands:
                    if op.type == cs.arm.ARM_OP_IMM and 0 <= op.imm - base < size: work.append(op.imm - base)
            if is_end(ins): break
            o += ins.size
    return len(seen) >= 1


def main():
    ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("--images", required=True)
    ap.add_argument("--seeds", required=True, help="seed dir(s) to read and update", nargs="+")
    ap.add_argument("--extra", nargs="*", default=[], help="extra seed dirs to read unresolved entries from")
    ap.add_argument("--pages", nargs="*", default=[], help="ingest dirs whose images/ hold the captured 4 KB pages (exact matching)")
    a = ap.parse_args()
    img = Path(a.images); ov = json.loads((img / "overlays.json").read_text())
    mods = [(r["file"][:-4], int(r["load_address"], 16), (img / "overlays" / r["file"]).read_bytes()) for r in ov]
    ent = set()
    for d in list(a.seeds) + list(a.extra):
        f = Path(d) / "arm9_unresolved.toml"
        if f.exists():
            for ad, m in re.findall(r'addr\s*=\s*(0x[0-9A-Fa-f]+)\s*\nmode\s*=\s*"(arm|thumb)"', f.read_text()):
                ent.add((int(ad, 16), m == "thumb"))
    out = Path(a.seeds[0]); added = {}
    # Captured pages: the live bytes at the time the address was executed. An overlay
    # owns the seed iff its ROM bytes equal the live bytes around the address.
    pages = {}
    for d in a.pages:
        for t in Path(d).glob("images/rh_*.toml"):
            b = t.with_suffix(".bin")
            m = re.search(r'load_address\s*=\s*(0x[0-9A-Fa-f]+)', t.read_text())
            if b.exists() and m:
                pages.setdefault(int(m.group(1), 16), set()).add(b.read_bytes())
    W = 16
    for ad, th in sorted(ent):
        lives = []
        for pbase, versions in pages.items():
            for v in versions:
                if pbase <= ad and ad + W <= pbase + len(v):
                    lives.append(v[ad - pbase:ad - pbase + W])
        for name, base, blob in mods:
            if not (base <= ad < base + len(blob)):
                continue
            ok = (any(blob[ad - base:ad - base + W] == lv for lv in lives) if lives
                  else clean(blob, base, ad - base, th))
            if ok:
                added.setdefault(f"arm9_{name}_{base:08x}", set()).add((ad, "thumb" if th else "arm"))
    # Overlays link the same helper code at the same addresses, so a seed resolved to one
    # module is needed by every sibling overlay whose bytes there are identical.
    by_stem = {f"arm9_{n}_{b:08x}": (n, b, bl) for n, b, bl in mods}
    for d in list(a.seeds) + list(a.extra):
        for f in Path(d).glob("arm9_ov*_*.toml"):
            if f.stem not in by_stem: continue
            _, base, blob = by_stem[f.stem]
            for ad, m in re.findall(r'addr\s*=\s*(0x[0-9A-Fa-f]+)\s*\nmode\s*=\s*"(arm|thumb)"', f.read_text()):
                ad = int(ad, 16)
                if not (base <= ad < base + len(blob)): continue
                ref = blob[ad - base:ad - base + W]
                for n2, b2, bl2 in mods:
                    if b2 == base and base <= ad < base + len(bl2) and bl2[ad - base:ad - base + W] == ref:
                        added.setdefault(f"arm9_{n2}_{b2:08x}", set()).add((ad, m))
    for stem, es in added.items():
        f = out / f"{stem}.toml"
        old = set()
        if f.exists():
            for ad, m in re.findall(r'addr\s*=\s*(0x[0-9A-Fa-f]+)\s*\nmode\s*=\s*"(arm|thumb)"', f.read_text()):
                old.add((int(ad, 16), m))
        allv = sorted(old | es)
        f.write_text("# Entry points: observed in Tier-3 manifests plus recovered candidates (addresses only).\n" +
                     "".join(f'[[entry_point]]\naddr = {x:#010x}\nmode = "{m}"\n\n' for x, m in allv))
    print(len(ent), "unresolved ->", sum(len(v) for v in added.values()), "assignments over", len(added), "overlays")


if __name__ == "__main__":
    main()
