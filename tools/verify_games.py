#!/usr/bin/env python3
"""Replay every games.json recipe and check the launch splash matches its id."""
import hashlib, json, os, shutil, sys
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rhplay import Session, boot_to_map, pan, tap_game_tile

def one(a):
    runner, rom, save, gid, g, work = a
    w = Path(work) / gid; w.mkdir(parents=True, exist_ok=True)
    sv = w / "s.sav"; shutil.copyfile(save, sv)
    s = Session(runner, rom, w, save=sv)
    try:
        boot_to_map(s); s.run(5)
        for hx, hy, dx, dy in g["chain"]: pan(s, hx, hy, dx, dy)
        tap_game_tile(s, g); s.run(40); s.touch(g["x"], g["y"], 6); s.run(170)
        got = hashlib.sha1(s.grab()[0][2]).hexdigest()[:10]
        return gid, got == gid
    finally:
        s.close(); shutil.rmtree(w, ignore_errors=True)

if __name__ == "__main__":
    runner, rom, save, games = sys.argv[1:5]
    games = json.load(open(games))
    with Pool(4) as p:
        res = p.map(one, [(runner, rom, save, k, v, "/tmp/rh-verify") for k, v in games.items()])
    bad = [g for g, ok in res if not ok]
    print(len(res) - len(bad), "ok;", "mismatch:", bad)
