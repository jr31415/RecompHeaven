#!/usr/bin/env python3
"""Which ROM overlays are resident (per RAM slot) while each game / tool is being played?

  identify_overlays.py RUNNER ROM SAVE GAMES.json IMAGES OUT.json [--hand right]

Used to decide, per game, which scene-dependent touch buttons to show (pause in minigames,
bend in guitar games). Output: {gid: {"slots": {"0x02287660": ovId, ...}}}, plus the menu baseline.
"""
import hashlib, json, os, shutil, sys
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rhplay import Session, boot_to_map, pan, tap_game_tile

SLOTS = {0x0227CB20: 0xAC00, 0x02287660: 0x8400, 0x0228FA60: 0xAC00}


def mem(s, a, n):
    out = b""
    while n > 0:
        k = min(n, 0x4000)
        out += bytes.fromhex(s.call(cmd="read_mem", cpu=9, addr=a, len=k)["hex"]); a += k; n -= k
    return out


def match(live_by_slot, overlays):
    res = {}
    for slot, live in live_by_slot.items():
        best = None
        for r in overlays:
            if r["base"] != slot: continue
            n = min(len(r["blob"]), 0x2000, len(live))
            d = sum(1 for i in range(0, n, 4) if r["blob"][i:i + 4] != live[i:i + 4])
            if best is None or d < best[0]: best = (d, r["id"], n // 4)
        res[f"0x{slot:08X}"] = None if best is None or best[0] > best[2] // 8 else best[1]
    return res


def one(a):
    runner, rom, save, gid, g, work, overlays, hand = a
    w = Path(work) / gid; w.mkdir(parents=True, exist_ok=True)
    sv = w / "s.sav"; shutil.copyfile(save, sv)
    s = Session(runner, rom, w, save=sv)
    try:
        boot_to_map(s, right=(hand == "right")); s.run(5)
        menu = match({k: mem(s, k, n) for k, n in SLOTS.items()}, overlays)
        if g.get("hub"):
            s.touch(22, 95, 6); s.run(240); s.touch(g["cat_x"], 95, 6); s.run(200)
            for _ in range(g["scrolls"]): s.touch(208, 95, 6); s.run(60)
            s.touch(g["item_x"], 95, 6); s.run(60); s.touch(238, 135, 6); s.run(120)
        else:
            for hx, hy, dx, dy in g["chain"]: pan(s, hx, hy, dx, dy)
            tap_game_tile(s, g); s.run(40); s.touch(g["x"], g["y"], 6); s.run(120)
        seen = []
        for i in range(8):                       # advance the intro, sample during it
            s.touch(128, 96, 4); s.run(110)
            seen.append(match({k: mem(s, k, n) for k, n in SLOTS.items()}, overlays))
        return gid, {"slots": seen[-1], "all": seen, "menu": menu}
    finally:
        s.close(); shutil.rmtree(w, ignore_errors=True)


if __name__ == "__main__":
    runner, rom, save, games, images, out = sys.argv[1:7]
    hand = "right" if "--hand" in sys.argv and sys.argv[sys.argv.index("--hand") + 1] == "right" else "left"
    img = Path(images)
    overlays = [dict(id=r["id"], base=int(r["load_address"], 16), blob=(img / "overlays" / r["file"]).read_bytes())
                for r in json.load(open(img / "overlays.json"))]
    games = json.load(open(games))
    with Pool(4) as p:
        res = dict(p.map(one, [(runner, rom, save, k, v, "/tmp/rh-ident", overlays, hand) for k, v in games.items()]))
    Path(out).write_text(json.dumps(res, indent=1))
    print(len(res), "games identified")
