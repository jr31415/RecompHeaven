#!/usr/bin/env python3
"""Measure input latency: OS-delivered event -> applied to the guest.

SDL stamps every event when it is delivered; the worker records how long it was
until the event was applied. Key presses are injected at jittered times (so
their phase against the frame/vsync varies) in three modes:

  per-frame one thread, input applied once per frame (the old behaviour)
  legacy   one thread: input applied every audio chunk (~1 ms)
  threaded worker applies input between scheduler rounds; main thread pumps
           events between presents (blocked up to a display period in vsync)
  present  main thread only pumps input; vsync present on its own thread

A real window appears for ~15 s per mode (vsync needs one). Presses are
injected by an independent thread inside the runner (NDS_INPUT_TEST_PRESSES),
not over the debug socket, whose handlers run on the emulation thread.

  python tools/test_input_delay.py --rom ROM [--runner R] [--presses 80]
"""
import argparse, json, os, random, socket, subprocess, sys, time
from pathlib import Path

DEFAULT_RUNNER = Path.home() / "dev/rh-build/runner-play/nds_runner"
MODES = {
    # The previous behaviour: input applied once per frame, on one thread.
    "per-frame": {"NDS_THREADED_PRESENT": "0", "NDS_PRESENT_THREAD": "0",
                  "NDS_AUDIO_CHUNKS": "1"},
    "legacy":   {"NDS_THREADED_PRESENT": "0", "NDS_PRESENT_THREAD": "0"},
    "threaded": {"NDS_THREADED_PRESENT": "1", "NDS_PRESENT_THREAD": "0"},
    "present":  {"NDS_THREADED_PRESENT": "1", "NDS_PRESENT_THREAD": "1"},
}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def run_mode(runner, rom, env_extra, presses, work):
    env = dict(os.environ, NDS_FRAME_LOG="off", NDS_AUDIO_TEST="1",
               NDS_INPUT_TEST_PRESSES=str(presses), **env_extra)
    port = free_port()
    work.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen([str(runner), ".", "--interactive", "--freebios", "--generated-firmware",
                          "--boot", "direct", "--rom", str(rom), "--no-save", "--no-coverage-manifest",
                          "--port", str(port)], cwd=work, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        t0 = time.time()
        while True:
            try:
                sk = socket.create_connection(("127.0.0.1", port), timeout=5); break
            except OSError:
                if time.time() - t0 > 30: raise RuntimeError("runner debug port never opened")
                time.sleep(0.1)
        f = sk.makefile("rw", newline="\n")
        def call(**r):
            f.write(json.dumps(r) + "\n"); f.flush(); return json.loads(f.readline())
        # The runner injects the presses itself from an independent thread
        # (starting 8 s after launch), like asynchronous OS delivery.
        time.sleep(8 + presses * 0.1 + 1.5)
        after = call(cmd="input_latency")
        before = {"events": 0}
        call(cmd="frontend_exit")
    finally:
        try: p.wait(timeout=10)
        except subprocess.TimeoutExpired: p.kill()
    n = after["events"] - before["events"]
    return n, after


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--runner", default=str(DEFAULT_RUNNER))
    ap.add_argument("--presses", type=int, default=80)
    ap.add_argument("--modes", default="per-frame,legacy,threaded,present")
    a = ap.parse_args()
    work = Path.home() / "dev/rh-build/input-test"
    print(f"{'mode':10} {'events':>7} {'mean ms':>9} {'max ms':>8} {'>8 ms':>6}")
    for m in a.modes.split(","):
        try:
            n, st = run_mode(a.runner, a.rom, MODES[m], a.presses, work)
        except Exception as e:  # noqa: BLE001
            print(f"{m:10} FAILED: {e}"); continue
        print(f"{m:10} {n:>7} {st['mean_ms']:>9.2f} {st['max_ms']:>8.2f} {st['over_8ms']:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
