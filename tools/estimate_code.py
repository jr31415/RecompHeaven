#!/usr/bin/env python3
"""Estimate how much of the ROM's code-module bytes is code, and how much of that is recompiled.

  python3 tools/estimate_code.py --images IMAGES --banks BANKDIR [--json out.json]

Needs capstone (pip install capstone; use a venv outside the repo).

Method (an estimate, not a proof):
  covered   bytes inside functions the banks contain (union of validation ranges)
  pool      words reached by pc-relative loads/adr from covered code (literal pools = data)
  gaps      everything else
  recovered gap bytes reachable by recursive descent from
              A. words anywhere in the module that point into a gap (function tables, vtables)
              B. direct branch/call targets out of covered code that land in a gap
              C. function prologues (STMFD sp!,{..lr} / PUSH {..lr}) inside a gap
            A and B are strong evidence of code; C alone is weaker.
  leftover  gap bytes no seed reaches: data (tables, graphics, strings) or dead code
"""
import argparse, json, os, re, struct, sys
from pathlib import Path
import capstone as cs

ARM = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_ARM); ARM.detail = True
THUMB = cs.Cs(cs.CS_ARCH_ARM, cs.CS_MODE_THUMB); THUMB.detail = True


def covered_map(bank_dir, bank, base, size):
    f = Path(bank_dir) / f"{bank}_dispatch.c"
    if not f.exists():
        return None
    t = f.read_text()
    lens = {int(k): len(re.findall(r"0x[0-9A-Fa-f]{2}u", b))
            for k, b in re.findall(r"g_validation_\w+?__(\d+)_bytes\[\] = \{(.*?)\};", t, re.S)}
    funcs = []
    for k, a, fl in re.findall(r"g_validation_\w+?__(\d+) = \{0x([0-9A-Fa-f]+)u, (\d+)u", t):
        a = int(a, 16) - base
        n = lens.get(int(k), 0)
        if n and 0 <= a < size:
            funcs.append((a, min(n, size - a), bool(int(fl) & 2)))
    return funcs


def decode(md, blob, off, n, base):
    return list(md.disasm(blob[off:off + n], base + off))


def is_end_early(ins):
    if ins.cc not in (cs.arm.ARM_CC_AL, cs.arm.ARM_CC_INVALID):
        return False
    m = ins.mnemonic
    if m in ("b", "bx"):
        return True
    pc = lambda op: op.type == cs.arm.ARM_OP_REG and op.reg == cs.arm.ARM_REG_PC
    if m.startswith(("pop", "ldm")) and any(pc(o) for o in ins.operands):
        return True
    return m in ("mov", "movs", "ldr") and bool(ins.operands) and pc(ins.operands[0])


def estimate_module(blob, base, funcs):
    size = len(blob)
    cov = bytearray(size)
    for a, n, _ in funcs:
        cov[a:a + n] = b"\x01" * n
    pool = bytearray(size)
    direct = set()          # branch targets from covered code (offsets, thumb flag)
    jt_slots = set()        # computed-branch table slots (ARM `add pc,pc,..` + run of `b`)
    after_end = set()       # address right after an unconditional return/branch (adjacent stubs)
    for a, n, thumb in funcs:
        md = THUMB if thumb else ARM
        for ins in decode(md, blob, a, n, base):
            if ins.mnemonic.startswith(("ldr", "adr", "add")) and any(
                    op.type == cs.arm.ARM_OP_MEM and op.mem.base == cs.arm.ARM_REG_PC for op in ins.operands):
                for op in ins.operands:
                    if op.type == cs.arm.ARM_OP_MEM and op.mem.base == cs.arm.ARM_REG_PC:
                        pc = (ins.address + (4 if thumb else 8)) & ~3
                        tgt = pc + op.mem.disp - base
                        if 0 <= tgt + 4 <= size:
                            pool[tgt:tgt + 4] = b"\x01" * 4
            if ins.group(cs.CS_GRP_JUMP) or ins.group(cs.CS_GRP_CALL):
                for op in ins.operands:
                    if op.type == cs.arm.ARM_OP_IMM:
                        direct.add((op.imm - base, thumb))
            if is_end_early(ins):
                after_end.add((ins.address - base + ins.size, thumb))
            if not thumb and ins.operands and ins.operands[0].type == cs.arm.ARM_OP_REG \
                    and ins.operands[0].reg == cs.arm.ARM_REG_PC and ins.mnemonic[:3] in ("add", "ldr") \
                    and len(ins.operands) >= 2:
                tbl = ins.address - base + 8
                while 0 <= tbl + 4 <= size:
                    nxt = next(ARM.disasm(blob[tbl:tbl + 4], base + tbl, 1), None)
                    if nxt is None or nxt.mnemonic != "b":
                        break
                    jt_slots.add((tbl, False))
                    tbl += 4
    entry_offsets = {a for a, _, _ in funcs}
    gap = [i for i in range(size) if not cov[i] and not pool[i]]
    gapset = bytearray(size)
    for i in gap:
        gapset[i] = 1
    in_gap = lambda o: 0 <= o < size and gapset[o]

    seedsA, seedsB, seedsC = set(), set(), set()
    seedsE = set()          # pointers to the middle of compiled code (case labels, callbacks)
    # A: pointers anywhere
    for o in range(0, size - 3, 4):
        w = struct.unpack_from("<I", blob, o)[0]
        t = w & ~1
        if base <= t < base + size and in_gap(t - base):
            seedsA.add((t - base, bool(w & 1)))
        elif base <= t < base + size and cov[t - base] and (t & (1 if (w & 1) else 3)) == 0 \
                and not pool[o] and (t - base) not in entry_offsets:
            seedsE.add((t - base, bool(w & 1)))
    # B: direct targets out of covered code
    for t, th in direct:
        if in_gap(t):
            seedsB.add((t, th))
    # C: prologues
    for o in range(0, size - 3, 4):
        w = struct.unpack_from("<I", blob, o)[0]
        if in_gap(o) and (w & 0xFFFFC000) == 0xE92D4000:
            seedsC.add((o, False))
    for o in range(0, size - 1, 2):
        h = struct.unpack_from("<H", blob, o)[0]
        if in_gap(o) and (h & 0xFF00) == 0xB500:
            seedsC.add((o, True))

    seedsD = {(o, th) for o, th in after_end if in_gap(o)}
    claimed = {"A": bytearray(size), "B": bytearray(size), "C": bytearray(size), "D": bytearray(size)}
    any_claim = bytearray(size)
    BAD = {"svc", "swi", "bkpt", "udf", "cdp", "cdp2", "mcr2", "mrc2", "ldc", "stc", "ldc2", "stc2"}

    def is_end(ins):
        m = ins.mnemonic
        cond_always = ins.cc in (cs.arm.ARM_CC_AL, cs.arm.ARM_CC_INVALID)
        if not cond_always:
            return False
        if m in ("b", "bx"):
            return True
        if m.startswith(("pop", "ldm")) and any(
                op.type == cs.arm.ARM_OP_REG and op.reg == cs.arm.ARM_REG_PC for op in ins.operands):
            return True
        if m in ("mov", "movs", "ldr") and ins.operands and ins.operands[0].type == cs.arm.ARM_OP_REG \
                and ins.operands[0].reg == cs.arm.ARM_REG_PC:
            return True
        return False

    def trace(seed, minlen=3):
        """Decode everything reachable from `seed`; None if it is not a clean function."""
        seen = {}
        work = [seed]
        while work:
            o, th = work.pop()
            md = THUMB if th else ARM
            while True:
                if o < 0 or o + 2 > size:
                    return None
                if not gapset[o]:
                    break                       # flows into compiled code / a pool: fine
                if o in seen:
                    break
                try:
                    ins = next(md.disasm(blob[o:o + 4], base + o, 1))
                except StopIteration:
                    return None
                if ins.mnemonic in BAD or len(seen) > 4000:
                    return None
                seen[o] = ins.size
                if ins.group(cs.CS_GRP_JUMP) or ins.group(cs.CS_GRP_CALL):
                    for op in ins.operands:
                        if op.type == cs.arm.ARM_OP_IMM:
                            t = op.imm - base
                            if 0 <= t < size and gapset[t]:
                                work.append((t, th))
                if is_end(ins):
                    break
                o += ins.size
        return seen if len(seen) >= minlen else None

    def run(seeds, tag, minlen=3):
        for o, th in sorted(seeds):
            if any_claim[o]:
                continue
            seen = trace((o, th), minlen)
            if not seen:
                continue
            for a0, n in seen.items():
                claimed[tag][a0:a0 + n] = b"\x01" * n
                any_claim[a0:a0 + n] = b"\x01" * n

    run(seedsB, "B")      # strongest first so provenance is credited to the best evidence
    run(seedsA, "A")
    run(seedsC, "C")
    run(seedsD, "D", 1)
    valid_seeds = sorted(jt_slots | seedsE | {(o, th) for tag, ss in (('B', seedsB), ('A', seedsA), ('C', seedsC), ('D', seedsD)) for o, th in ss if claimed[tag][o]})
    return dict(size=size, covered=sum(cov), pool=sum(pool),
                A=sum(claimed["A"]), B=sum(claimed["B"]), C=sum(claimed["C"]) + sum(claimed["D"]),
                gap=len(gap), seeds=valid_seeds)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", required=True); ap.add_argument("--banks", required=True)
    ap.add_argument("--json")
    ap.add_argument("--emit-seeds", help="write gen_banks-style seed files for every clean candidate function")
    a = ap.parse_args()
    img = Path(a.images)
    mods = []
    ov = json.loads((img / "overlays.json").read_text())
    mods.append(("arm9", (img / "arm9.bin").read_bytes(), 0x02000000, ["rh_arm9_arm9_02000000"], False))
    mods.append(("arm7", (img / "arm7.bin").read_bytes(), None, [("rh_arm7_arm7_02380000", 0x02380000),
                ("rh_arm7_arm7_027d0968", 0x027d0968), ("rh_arm7_arm7_037f7e18", 0x037f7e18)], True))
    al = json.loads((img / "autoload.json").read_text())
    mods.append(("itcm", (img / "autoload0.bin").read_bytes(), 0x01FF8000, ["rh_arm9_itcm_01ff8000"], False))
    for r in ov:
        st = r["file"][:-4]; b = int(r["load_address"], 16)
        mods.append((st, (img / "overlays" / r["file"]).read_bytes(), b, [f"rh_arm9_{st}_{b:08x}"], False))
    tot = dict(size=0, covered=0, pool=0, A=0, B=0, C=0, gap=0)
    per = {}
    for name, blob, base, banks, multi in mods:
        funcs = []
        if multi:
            # arm7 runs from aliases: merge all alias banks onto image offsets
            seen = set()
            for bank, bb in banks:
                fs = covered_map(a.banks, bank, bb, len(blob)) or []
                for off, n, th in fs:
                    if (off, th) not in seen:
                        seen.add((off, th)); funcs.append((off, n, th))
            base = 0x02380000
        else:
            funcs = covered_map(a.banks, banks[0], base, len(blob)) or []
        r = estimate_module(blob, base, funcs)
        per[name] = r
        if a.emit_seeds:
            out = Path(a.emit_seeds) / "seeds"; out.mkdir(parents=True, exist_ok=True)
            if name == "arm7":
                targets = [(f"arm7_arm7_{bb:08x}", bb) for bb in (0x02380000, 0x027d0968, 0x037f7e18)]
            elif name == "arm9":
                targets = [("arm9_arm9_02000000", 0x02000000)]
            elif name == "itcm":
                targets = [("arm9_itcm_01ff8000", 0x01FF8000)]
            else:
                targets = [(f"arm9_{name}_{base:08x}", base)]
            for stem, bb in targets:
                (out / f"{stem}.toml").write_text("".join(
                    f'[[entry_point]]\naddr = {bb + o:#010x}\nmode = "{"thumb" if th else "arm"}"\n\n' for o, th in r["seeds"]))
        r = {k: v for k, v in r.items() if k != "seeds"}
        per[name] = r
        for k in tot: tot[k] += r[k]
        print(f"{name:7s} size {r['size']:7d} covered {r['covered']:7d} pool {r['pool']:6d} "
              f"A {r['A']:6d} B {r['B']:6d} C {r['C']:6d} gap {r['gap']:7d}", flush=True)
    code_strong = tot["covered"] + tot["A"] + tot["B"]
    code_all = code_strong + tot["C"]
    print(json.dumps(tot))
    print(f"covered functions : {tot['covered']:8d} B  ({100*tot['covered']/tot['size']:.1f}% of images)")
    print(f"literal pools     : {tot['pool']:8d} B  ({100*tot['pool']/tot['size']:.1f}%)")
    print(f"uncompiled, strong: {tot['A']+tot['B']:8d} B  (pointer/branch-referenced code)")
    print(f"uncompiled, weak  : {tot['C']:8d} B  (prologue-only)")
    left = tot['size'] - code_all - tot['pool']
    print(f"leftover (data?)  : {left:8d} B  ({100*left/tot['size']:.1f}%)")
    print(f"=> recompiled / estimated code = {100*tot['covered']/code_all:.1f}% "
          f"(strong-only {100*tot['covered']/code_strong:.1f}%)")
    if a.json:
        Path(a.json).write_text(json.dumps(dict(total=tot, modules=per), indent=1))


if __name__ == "__main__":
    main()
