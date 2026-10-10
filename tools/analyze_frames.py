#!/usr/bin/env python3
"""Summarise a runner frame_times CSV: where did the slow frames go?

  python tools/analyze_frames.py FRAME_LOG.csv [--skip 150] [--slow-ms 20]

A frame is "slow" when its wall time exceeds --slow-ms (display period is
16.7 ms). Each slow frame is attributed to the largest single component:
  emu       the emulator took too long (look at tier3_insns on those frames)
  swap      SDL_RenderPresent blocked (vsync wait or driver stall)
  throttle  audio pacing sleep (usually harmless: the loop was ahead)
  other     time outside the measured phases (event pump, OS scheduling)
Also reports audio underruns and the minimum audio queue.
"""
import argparse, csv, collections
ap = argparse.ArgumentParser()
ap.add_argument("csv"); ap.add_argument("--skip", type=int, default=150)
ap.add_argument("--slow-ms", type=float, default=20.0)
a = ap.parse_args()
rows = [{k: int(v) for k, v in r.items()} for r in csv.DictReader(open(a.csv))]
rows = [r for r in rows if r["frame"] >= a.skip]
if not rows: raise SystemExit("no frames after --skip")
def pct(v, p): v = sorted(v); return v[min(len(v) - 1, int(len(v) * p))]
tot = [r["total_us"] for r in rows]
print(f"frames={len(rows)}  total_ms p50={pct(tot,.5)/1000:.1f} p99={pct(tot,.99)/1000:.1f} max={max(tot)/1000:.1f}")
for k in ("emu_us", "present_us", "swap_us", "throttle_us"):
    v = [r[k] for r in rows]; print(f"  {k:12s} p50={pct(v,.5)/1000:6.2f} p99={pct(v,.99)/1000:6.2f} max={max(v)/1000:6.2f} ms")
q = [r["queued"] for r in rows]
print(f"audio queue min={min(q)} frames ({min(q)*1000/32768:.1f} ms), underruns at end={rows[-1]['underruns']}")
slow = [r for r in rows if r["total_us"] > a.slow_ms * 1000]
print(f"slow frames (> {a.slow_ms:.0f} ms): {len(slow)} ({100*len(slow)/len(rows):.2f}%)")
cause = collections.Counter(); t3 = 0
for r in slow:
    parts = {"emu": r["emu_us"] + r["push_us"], "swap": r["swap_us"],
             "throttle": r["throttle_us"]}
    other = r["total_us"] - sum(parts.values()) - (r["present_us"] - r["swap_us"])
    parts["other"] = other
    cause[max(parts, key=parts.get)] += 1
    t3 += r["tier3_insns"] > 0
print("  attributed to:", dict(cause), f"| with interpreter activity: {t3}")
print("worst 8:")
for r in sorted(slow, key=lambda r: -r["total_us"])[:8]:
    print(f"  f{r['frame']:6d} total={r['total_us']/1000:6.1f} emu={r['emu_us']/1000:5.1f} "
          f"swap={r['swap_us']/1000:5.1f} thr={r['throttle_us']/1000:5.1f} q={r['queued']:5d} t3={r['tier3_insns']}")
