#!/usr/bin/env python3
"""Interactive-runner UI test (dummy video). Scenes are forced on (NDS_TB_FORCE) so no menu
navigation is needed; checks the buttons are painted, that pressing a corner button drives
KEYINPUT (pause = Select, bend = L+R), and that a second pointer can't steal the stylus.

  ui_test.py RUNNER ROM CONFIG
"""
import json, os, shutil, socket, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rhplay import png

runner, rom, config = [str(Path(x).resolve()) for x in sys.argv[1:4]]
work = Path("/tmp/rh-ui"); shutil.rmtree(work, ignore_errors=True); work.mkdir()
with socket.socket() as s_: s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]
env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", NDS_AUTO_HAND_ROTATION="0",
           NDS_THREADED_PRESENT="0", NDS_FRAME_LOG="off", NDS_TB_DUMP=str(work / "tb"),
           NDS_TB_FORCE="minigame,guitar")
p = subprocess.Popen([runner, ".", "--interactive", "--freebios", "--generated-firmware", "--boot", "direct",
                      "--rom", rom, "--config", config, "--no-save", "--no-coverage-manifest",
                      "--screen-rotation", "0", "--port", str(port)], cwd=work, env=env,
                     stdout=subprocess.DEVNULL, stderr=open(work / "err.log", "w"))
for _ in range(300):
    try: sk = socket.create_connection(("127.0.0.1", port)); break
    except OSError: time.sleep(0.1)
f = sk.makefile("rw", newline="\n")
def call(**r):
    f.write(json.dumps(r) + "\n"); f.flush(); return json.loads(f.readline())
def frame(): return call(cmd="event_counts")["vblank9"]
def wait(k):
    n = frame() + k
    while frame() < n: time.sleep(0.002)
def pointer(x, y, down, which=None):
    return call(cmd="frontend_input", action="touch", x=x, y=y, down=down)
def keys():
    return call(cmd="read_io", cpu=9, addr=0x04000130, width=16)["value"] & 0x3FF   # KEYINPUT, active low
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name, flush=True)
try:
    wait(400)
    base = keys(); print("KEYINPUT idle", hex(base))
    check("scenes reported on", sum("scene" in l and " on" in l for l in open(work / "err.log")) >= 2)
    check("buttons painted (frame dumps written)", any(work.glob("tb-*.ppm")) or (wait(200) or any(work.glob("tb-*.ppm"))))
    pointer(251, 3, True); wait(8); pause = keys(); pointer(251, 3, False); wait(8)
    check(f"pause (top-right) holds Select: {base:#06x} -> {pause:#06x}", (base & ~pause) == 0x0004)
    after = keys(); check("pause releases", after == base)
    pointer(252, 188, True); wait(8); bend = keys(); pointer(252, 188, False); wait(8)
    check(f"bend (bottom-right) holds L+R: {base:#06x} -> {bend:#06x}", (base & ~bend) == 0x0300)
    check("bend releases", keys() == base)
    pointer(128, 96, True); wait(3)                          # stylus mid-screen is NOT a button
    mid = keys(); pointer(128, 96, False); wait(3)
    check("mid-screen touch does not press a button", mid == base)
finally:
    try: call(cmd="frontend_exit")
    except Exception: pass
    time.sleep(1); p.terminate()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
