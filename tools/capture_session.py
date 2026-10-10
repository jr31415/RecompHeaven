#!/usr/bin/env python3
"""Scripted headless session over the runner's TCP protocol.

Script items (JSON list via --script file or inline):
  {"run": 700}                         run to ARM9 VBlank count
  {"touch": [x, y], "hold": 6}         press the stylus for `hold` VBlanks, release
  {"swipe": [[x0,y0],[x1,y1]], "frames": 4}   stylus drag then release
  {"keys": 0x0001, "hold": 6}          DS key mask (A=1,B=2,Sel=4,Start=8,R=0x10..)
  {"shot": "name"}                     save both screens as PNG
  {"manifest": "path.json"}            write the Tier-3 coverage manifest now
  {"digest": true}                     print frame digests (deterministic compare)
"""
import argparse, json, socket, subprocess, time, zlib, struct, hashlib
from pathlib import Path

def png(path, w, h, rgb):
    raw = b"".join(b"\x00" + rgb[y*w*3:(y+1)*w*3] for y in range(h))
    def ch(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + ch(b"IDAT", zlib.compress(raw, 6)) + ch(b"IEND", b""))

ap = argparse.ArgumentParser()
ap.add_argument("--runner", required=True); ap.add_argument("--rom", required=True)
ap.add_argument("--work", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--script", required=True); ap.add_argument("--port", type=int, default=19842)
ap.add_argument("--extra", nargs="*", default=[])
a = ap.parse_args()
Path(a.work).mkdir(parents=True, exist_ok=True); Path(a.out).mkdir(parents=True, exist_ok=True)
script = json.loads(a.script) if a.script.lstrip().startswith("[") else json.loads(Path(a.script).read_text())
p = subprocess.Popen([a.runner, ".", "--serve", "--port", str(a.port), "--freebios",
                      "--generated-firmware", "--boot", "direct", "--rom", a.rom, "--no-save",
                      "--diagnostics", "off", *a.extra], cwd=a.work,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(200):
        try: sk = socket.create_connection(("127.0.0.1", a.port)); break
        except OSError: time.sleep(0.1)
    f = sk.makefile("rw", newline="\n")
    def call(**r):
        f.write(json.dumps(r) + "\n"); f.flush(); return json.loads(f.readline())
    vb = 0
    def run_to(n):
        global vb
        r = call(cmd="run_to_event", event="vblank9", count=n)
        if not r.get("reached"): print("WARN run_to", n, r)
        vb = n
    for it in script:
        if "run" in it: run_to(it["run"])
        elif "touch" in it:
            call(cmd="touch", x=it["touch"][0], y=it["touch"][1], down=True)
            run_to(vb + it.get("hold", 6)); call(cmd="touch", x=it["touch"][0], y=it["touch"][1], down=False)
        elif "down" in it:
            call(cmd="touch", x=it["down"][0], y=it["down"][1], down=True); run_to(vb + it.get("hold", 1))
        elif "up" in it:
            call(cmd="touch", x=0, y=0, down=False); run_to(vb + it.get("hold", 1))
        elif "swipe" in it:
            (x0, y0), (x1, y1) = it["swipe"]; n = max(2, it.get("frames", 4))
            for k in range(n + 1):
                x = round(x0 + (x1 - x0) * k / n); y = round(y0 + (y1 - y0) * k / n)
                call(cmd="touch", x=x, y=y, down=True); run_to(vb + 1)
            call(cmd="touch", x=x1, y=y1, down=False)
        elif "keys" in it:
            call(cmd="keys", mask=it["keys"]); run_to(vb + it.get("hold", 6)); call(cmd="keys", mask=0)
        elif "shot" in it:
            for eng in "AB":
                r = call(cmd="framebuffer", engine=eng); rgb = bytes.fromhex(r["rgb"])
                png(Path(a.out) / f"{it['shot']}_{eng}.png", r["w"], r["h"], rgb)
                print("shot", it["shot"], eng, hashlib.sha1(rgb).hexdigest()[:12])
        elif "manifest" in it:
            print("manifest", call(cmd="coverage_manifest", path=it["manifest"]))
        elif "digest" in it:
            ev = call(cmd="event_counts"); print("events", {k: ev[k] for k in ("vblank9","vblank7","insn9","insn7") if k in ev})
        elif "tier3" in it:
            r = call(cmd="tier3_coverage", max=it.get("max", 4000))
            Path(it["tier3"]).write_text(json.dumps(r)); print("tier3 entries", len(r.get("entries", [])))
        elif "cov" in it:
            print("static_coverage", json.dumps(call(cmd="static_coverage"))[:600])
finally:
    p.terminate()
