#!/usr/bin/env python3
"""Locate a game-state flag in main RAM by differential snapshots.

Boots headless, takes snapshots at fixed VBlanks to learn which bytes churn on
their own (noise), performs a scripted UI toggle, snapshots again, and reports
bytes that changed across the toggle, were stable before it, and (with
--revert) flip back when the toggle is undone.

  python tools/find_flag.py --runner R --rom ROM --work W --script FILE.json
Script: {"boot":[...actions to reach the screen...], "toggle":[...], "revert":[...]}
Actions are capture_session actions (run/touch/down/up/swipe).
"""
import argparse, json, socket, subprocess, time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--runner", required=True); ap.add_argument("--rom", required=True)
ap.add_argument("--work", required=True); ap.add_argument("--script", required=True)
ap.add_argument("--extra", default="")
a = ap.parse_args()
import shlex
sc = json.loads(Path(a.script).read_text())
with socket.socket() as t:
    t.bind(("127.0.0.1", 0)); port = t.getsockname()[1]
Path(a.work).mkdir(parents=True, exist_ok=True)
p = subprocess.Popen([a.runner, ".", "--serve", "--port", str(port), "--freebios",
                      "--generated-firmware", "--boot", "direct", "--rom", a.rom, "--no-save",
                      "--diagnostics", "off", "--no-coverage-manifest", *shlex.split(a.extra)],
                     cwd=a.work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(200):
        try: sk = socket.create_connection(("127.0.0.1", port)); break
        except OSError: time.sleep(0.1)
    f = sk.makefile("rw", newline="\n")
    def call(**r):
        f.write(json.dumps(r) + "\n"); f.flush(); return json.loads(f.readline())
    vb = [0]
    def run_to(n):
        r = call(cmd="run_to_event", event="vblank9", count=n); vb[0] = n; return r
    def do(items):
        for it in items:
            if "run" in it: run_to(it["run"])
            elif "wait" in it: run_to(vb[0] + it["wait"])
            elif "down" in it:
                call(cmd="touch", x=it["down"][0], y=it["down"][1], down=True); run_to(vb[0] + it.get("hold", 1))
            elif "up" in it:
                call(cmd="touch", x=0, y=0, down=False); run_to(vb[0] + it.get("hold", 1))
            elif "touch" in it:
                call(cmd="touch", x=it["touch"][0], y=it["touch"][1], down=True); run_to(vb[0] + it.get("hold", 6))
                call(cmd="touch", x=it["touch"][0], y=it["touch"][1], down=False)
    def snap():
        out = bytearray()
        for off in range(0, 0x400000, 0x1000):
            r = call(cmd="read_mem", cpu=9, addr=0x02000000 + off, len=0x1000)
            out += bytes.fromhex(r["hex"])
        return bytes(out)
    do(sc["boot"])
    s1 = snap(); do([{"wait": 3}]); s2 = snap(); do([{"wait": 17}]); s3 = snap()
    do(sc["toggle"]); do([{"wait": sc.get("settle", 40)}])
    s4 = snap(); do([{"wait": 3}]); s5 = snap()
    noise = {i for i in range(len(s1)) if s1[i] != s2[i] or s2[i] != s3[i] or s4[i] != s5[i]}
    chg = [i for i in range(len(s3)) if s3[i] != s4[i] and i not in noise]
    print(f"noise bytes: {len(noise)}; stable-before/after toggle changes: {len(chg)}")
    res = {"toggle_changes": [(0x02000000 + i, s3[i], s4[i]) for i in chg]}
    if sc.get("revert"):
        do(sc["revert"]); do([{"wait": sc.get("settle", 40)}]); s6 = snap()
        back = [i for i in chg if s6[i] == s3[i]]
        res["flips_back"] = [(0x02000000 + i, s3[i], s4[i]) for i in back]
        print("of those, flip back after revert:", len(back))
    show = res.get("flips_back", res["toggle_changes"])
    for addr, before, after in show[:40]:
        print(f"  {addr:#010x}: {before:#04x} -> {after:#04x}")
    Path(a.work, "flag_candidates.json").write_text(json.dumps(res))
finally:
    p.terminate()
