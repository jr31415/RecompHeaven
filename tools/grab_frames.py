#!/usr/bin/env python3
"""Run the runner headless (--serve), advance to a VBlank count, save both
screens as PNG. Uses only the documented TCP protocol (TCP.md).

  python tools/grab_frames.py --runner RUNNER --rom ROM --work DIR --vblank 600 --out DIR
"""
import argparse, json, socket, subprocess, sys, time, zlib, struct
from pathlib import Path

def png(path, w, h, rgb):
    raw = b"".join(b"\x00" + rgb[y*w*3:(y+1)*w*3] for y in range(h))
    def ch(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + ch(b"IDAT", zlib.compress(raw, 6)) + ch(b"IEND", b""))

class Client:
    def __init__(s, port, tries=100):
        for _ in range(tries):
            try:
                s.sock = socket.create_connection(("127.0.0.1", port)); break
            except OSError:
                time.sleep(0.1)
        else:
            raise SystemExit("could not connect to runner debug port")
        s.f = s.sock.makefile("rw", newline="\n")
    def call(s, **req):
        s.f.write(json.dumps(req) + "\n"); s.f.flush()
        return json.loads(s.f.readline())

ap = argparse.ArgumentParser()
ap.add_argument("--runner", required=True); ap.add_argument("--rom", required=True)
ap.add_argument("--work", required=True); ap.add_argument("--vblank", type=int, default=300)
ap.add_argument("--out", required=True); ap.add_argument("--port", type=int, default=19842)
ap.add_argument("--extra", nargs="*", default=[])
a = ap.parse_args()
Path(a.work).mkdir(parents=True, exist_ok=True); Path(a.out).mkdir(parents=True, exist_ok=True)
p = subprocess.Popen([a.runner, ".", "--serve", "--port", str(a.port), "--freebios",
                      "--generated-firmware", "--boot", "direct", "--rom", a.rom, "--no-save",
                      "--diagnostics", "off", "--no-coverage-manifest", *a.extra],
                     cwd=a.work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    c = Client(a.port)
    print("ping", c.call(cmd="ping"))
    r = c.call(cmd="run_to_event", event="vblank9", count=a.vblank)
    print("run_to_event", {k: r[k] for k in r if k != "counts"} , r.get("counts"))
    for eng in "AB":
        r = c.call(cmd="framebuffer", engine=eng)
        rgb = bytes.fromhex(r["rgb"])
        png(Path(a.out) / f"screen_{eng}_vb{a.vblank}.png", r["w"], r["h"], rgb)
        print("saved", eng, r["w"], r["h"], "nonzero bytes:", sum(1 for b in rgb if b))
    print("io_state", c.call(cmd="io_state"))
finally:
    p.terminate()
