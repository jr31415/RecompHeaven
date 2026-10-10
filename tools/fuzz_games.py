#!/usr/bin/env python3
"""Coverage fuzzer: launch each rhythm game from the 100% save and play randomized input.

  python3 tools/fuzz_games.py --runner R --rom ROM --save SAVE --tiles tiles.json \
      --out DIR [--runs 6] [--frames 9000] [--jobs 4] [--only gid,gid]

tiles.json maps tile-hash -> {gid: {x, y, chain}} (the map of the 50 game tiles). Each run
boots from the saved map state (fast), launches the game (tap tile twice), then
plays random taps / flicks / drags / holds for --frames VBlanks with a throw-away
copy of the save. Per-run Tier-3 coverage manifests land in DIR for
tools/ingest_coverage_manifests.py.
"""
import argparse, json, os, random, shutil, sys, time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rhplay import Session, boot_to_map, pan, tap_game_tile  # noqa: E402


def fuzz_run(job):
    runner, rom, save, game, seed, frames, out, work = job
    rnd = random.Random(seed)
    tag = f"{game['gid']}-{seed}"
    mf = Path(out) / f"{tag}.json"
    if mf.exists():
        return tag, None, "skip"
    w = Path(work) / tag; w.mkdir(parents=True, exist_ok=True)
    sv = w / "save.sav"; shutil.copyfile(save, sv)
    s = Session(runner, rom, w, save=sv)
    try:
        boot_to_map(s); s.run(5)
        for hx, hy, dx, dy in game["chain"]:
            pan(s, hx, hy, dx, dy)
        tap_game_tile(s, game); s.run(40); s.touch(game["x"], game["y"], 6); s.run(120)
        mode = seed % 3          # 0 sparse, 1 dense, 2 beat-locked
        period = rnd.choice([20, 24, 26, 28, 30, 32, 36, 40])
        phase = rnd.randrange(period)
        t0 = s.vb; end = t0 + frames
        while s.vb < end:
            if mode == 2:
                # tap on a fixed grid with jitter: sweeps hit/near-miss/miss offsets over the run
                nxt = ((s.vb - t0 - phase) // period + 1) * period + phase + t0
                s.run(max(1, min(nxt - s.vb + rnd.randrange(-3, 4), end - s.vb)))
                kind = rnd.random()
            else:
                s.run(rnd.randrange(2, 14 if mode else 40))
                kind = rnd.random()
            x, y = rnd.randrange(8, 248), rnd.randrange(8, 184)
            if kind < 0.62:
                s.touch(x, y, rnd.randrange(1, 5))
            elif kind < 0.82:
                s.flick(x, y, rnd.randrange(8, 248), rnd.randrange(8, 184), rnd.randrange(2, 8))
            elif kind < 0.92:
                s.down(x, y, rnd.randrange(10, 50)); s.up(1)
            else:
                s.keys(rnd.choice([1, 2, 0x40, 0x80, 0x10, 0x20, 0x100, 0x200]), rnd.randrange(1, 5))
        cov = s.tier3()
        s.manifest(mf)
        return tag, cov, "ok"
    finally:
        s.close()
        shutil.rmtree(w, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runner", required=True); ap.add_argument("--rom", required=True)
    ap.add_argument("--save", required=True); ap.add_argument("--tiles", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--work", default="/tmp/rh-fuzz")
    ap.add_argument("--runs", type=int, default=6); ap.add_argument("--frames", type=int, default=9000)
    ap.add_argument("--jobs", type=int, default=4); ap.add_argument("--only", default="")
    ap.add_argument("--seed0", type=int, default=0)
    a = ap.parse_args()
    Path(a.out).mkdir(parents=True, exist_ok=True)
    games = json.load(open(a.tiles))
    only = set(filter(None, a.only.split(",")))
    jobs = [(a.runner, a.rom, a.save, g, a.seed0 + k, a.frames, a.out, a.work)
            for k in range(a.runs) for gid, g in games.items() if not only or gid in only]
    print(len(games), "games,", len(jobs), "runs", flush=True)
    t = time.time()
    with Pool(a.jobs) as p:
        for tag, cov, st in p.imap_unordered(fuzz_run, jobs):
            c = (cov or {}).get("tier3_insns9")
            print(f"{time.time()-t:7.0f}s {tag} {st} tier3_insns9={c}", flush=True)


if __name__ == "__main__":
    main()
