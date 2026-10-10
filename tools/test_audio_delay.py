#!/usr/bin/env python3
"""Measure and minimise audio delay end to end (software side + OS report).

What it does
  Launches the interactive runner with a REAL audio device and NDS_AUDIO_TEST=1.
  In that mode game audio is muted and a short click is injected every ~300 ms
  into the exact path game audio takes (push_audio -> SDL audio stream ->
  device). Each click is timestamped when it is handed to the stream and again
  when it appears in the device mix (SDL's postmix callback: the last place
  software can see it). The OS/hardware part (CoreAudio device latency, safety
  offset, IO buffer) is read from the system. Reported:

      total ~= push->mix  (host pipeline: queue + resample + SDL buffer)
             + (IO buffer + device latency + safety offset + stream latency)

  It then sweeps the two knobs that matter and recommends the lowest setting
  that produced zero underruns:

      NDS_AUDIO_QUEUE_FRAMES   pacing floor / host queue depth (32.7 kHz frames)
      NDS_AUDIO_OS_BUFFER_FRAMES  CoreAudio IO buffer for the output device (device frames)

You WILL hear short clicks while this runs (game audio is muted).

  python tools/test_audio_delay.py --rom ROM [--runner R] [--seconds 8]
  python tools/test_audio_delay.py --rom ROM --quick
  python tools/test_audio_delay.py --rom ROM --queue 512 --device 128   # one run

Exit status is 0 when a zero-underrun configuration was found.
"""
import argparse, json, os, socket, subprocess, sys, time
from pathlib import Path

HOME = Path.home()
DEFAULT_RUNNER = HOME / "dev/rh-build/runner-play4/nds_runner"
STREAM_RATE = 32728.0


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Client:
    def __init__(self, port, timeout=30.0):
        t0 = time.time()
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
                break
            except OSError:
                if time.time() - t0 > timeout:
                    raise RuntimeError("runner debug port never opened")
                time.sleep(0.1)
        self.f = self.sock.makefile("rw", newline="\n")

    def call(self, **req):
        self.f.write(json.dumps(req) + "\n")
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise RuntimeError("runner closed the debug connection")
        return json.loads(line)


def run_once(runner, rom, queue, device, seconds, workdir, chunks=16):
    """Boot, wait for the queue to settle, then measure for `seconds`.

    Startup deliberately prebuffers ~1.75 s of audio and glides it down, so
    only clicks pushed once the queue is back near its target are real
    steady-state latency. Underruns are counted inside the window only.
    """
    env = dict(os.environ)
    env.update({
        "NDS_AUDIO_TEST": "1",
        "NDS_AUDIO_QUEUE_FRAMES": str(queue),
        "NDS_AUDIO_DEVICE_FRAMES": str(min(device, 256)),
        "NDS_AUDIO_OS_BUFFER_FRAMES": str(device),
        "NDS_AUDIO_CHUNKS": str(chunks),
        "NDS_THREADED_PRESENT": "1",
        "SDL_VIDEODRIVER": "dummy",        # no window; audio is the real device
        "NDS_FRAME_LOG": "off",
    })
    port = free_port()
    workdir.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(
        [str(runner), ".", "--interactive", "--freebios", "--generated-firmware",
         "--boot", "direct", "--rom", str(rom), "--no-save", "--no-coverage-manifest",
         "--port", str(port)],
        cwd=workdir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        c = Client(port)
        deadline = time.time() + 40
        steady = 0
        while time.time() < deadline:
            time.sleep(0.4)
            pr = c.call(cmd="audio_latency")
            rec = pr.get("recent") or []
            if rec and rec[-1][1] <= queue * 2 + 400:
                steady += 1
            else:
                steady = 0
            if steady >= 4:
                break
        else:
            raise RuntimeError("queue never settled (audio device stalled?)")
        n0 = pr["samples"]
        u0 = c.call(cmd="frontend_stats").get("underruns", 0)
        time.sleep(seconds)
        probe = c.call(cmd="audio_latency")
        u1 = c.call(cmd="frontend_stats").get("underruns", 0)
        c.call(cmd="frontend_exit")
    finally:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    new = probe["samples"] - n0
    rec = (probe.get("recent") or [])[-new:] if new > 0 else []
    # A click pushed during the boot prebuffer surfaces ~1.7 s later, i.e. inside
    # the window; its push-time queue depth gives it away.
    rec = [r for r in rec if r[1] <= queue * 2 + 400]
    if rec:
        ms = [r[0] for r in rec]
        probe["push_to_mix_ms"] = {"mean": sum(ms) / len(ms), "min": min(ms), "max": max(ms)}
        probe["queued_frames_mean"] = sum(r[1] for r in rec) / len(rec)
        probe["samples"] = len(rec)
    else:
        probe["samples"] = 0
    return probe, {"underruns": max(0, u1 - u0)}


def total_ms(probe):
    sysi = probe.get("system", {})
    rate = sysi.get("rate") or probe.get("sdl_device_freq") or 48000
    os_frames = (sysi.get("buffer_frames", 0) + sysi.get("device_latency", 0) +
                 sysi.get("safety_offset", 0) + sysi.get("stream_latency", 0))
    os_ms = os_frames / rate * 1000.0 if rate else 0.0
    return probe["push_to_mix_ms"]["mean"], os_ms


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--runner", default=str(DEFAULT_RUNNER))
    ap.add_argument("--seconds", type=float, default=9.0,
                    help="measurement time per configuration (after boot settles)")
    ap.add_argument("--quick", action="store_true", help="small sweep")
    ap.add_argument("--queue", type=int, help="single run: NDS_AUDIO_QUEUE_FRAMES")
    ap.add_argument("--device", type=int, help="single run: NDS_AUDIO_DEVICE_FRAMES")
    ap.add_argument("--json", help="write full results here")
    a = ap.parse_args()

    runner = Path(a.runner)
    if not runner.is_file():
        sys.exit(f"runner not found: {runner}")
    work = HOME / "dev/rh-build/audio-test"

    if a.queue or a.device:
        grid = [(a.queue or 1024, a.device if a.device is not None else 256)]
    elif a.quick:
        grid = [(1024, 512), (384, 128), (384, 64), (256, 64), (256, 32)]
    else:
        grid = [(q, d) for q in (1024, 512, 384, 256, 192) for d in (256, 128, 64, 32)]

    print("Running with the real audio device. Short clicks are expected.\n")
    print(f"{'queue':>6} {'dev':>5} | {'push->mix':>9} {'(min..max)':>13} | "
          f"{'OS buf+lat':>10} | {'TOTAL':>7} | {'queued':>6} {'underruns':>9} {'clicks':>6}")
    results = []
    for q, d in grid:
        try:
            probe, stats = run_once(runner, a.rom, q, d, a.seconds, work)
        except Exception as e:  # noqa: BLE001
            print(f"{q:>6} {d:>5} | FAILED: {e}")
            continue
        if probe.get("samples", 0) == 0:
            print(f"{q:>6} {d:>5} | no clicks seen (device unavailable / muted?)")
            continue
        host_ms, os_ms = total_ms(probe)
        under = stats.get("underruns", 0)
        pm = probe["push_to_mix_ms"]
        rec = dict(queue=q, device=d, host_ms=host_ms, os_ms=os_ms,
                   total_ms=host_ms + os_ms, min_ms=pm["min"], max_ms=pm["max"],
                   queued=probe["queued_frames_mean"], underruns=under,
                   clicks=probe["samples"], probe=probe)
        results.append(rec)
        print(f"{q:>6} {d:>5} | {host_ms:>7.2f}ms {pm['min']:>5.1f}..{pm['max']:<5.1f} | "
              f"{os_ms:>8.2f}ms | {host_ms + os_ms:>5.1f}ms | "
              f"{probe['queued_frames_mean']:>6.0f} {under:>9} {probe['samples']:>6}")

    if not results:
        sys.exit("no usable measurements")
    sysi = results[0]["probe"].get("system", {})
    print("\nOutput device:", sysi.get("name") or "(unknown)",
          f"@ {sysi.get('rate', 0):.0f} Hz; SDL device buffer "
          f"{results[0]['probe'].get('sdl_device_frames')} frames")
    print(f"OS floor for this device: IO buffer min {sysi.get('min_buffer_frames')} frames, "
          f"device latency {sysi.get('device_latency')}, safety offset "
          f"{sysi.get('safety_offset')}, stream latency {sysi.get('stream_latency')}")

    clean = [r for r in results if r["underruns"] == 0]
    best = min(clean or results, key=lambda r: r["total_ms"])
    print("\nRecommended" if clean else "\nBest available (all configs underran!)",
          f"-> NDS_AUDIO_QUEUE_FRAMES={best['queue']} NDS_AUDIO_OS_BUFFER_FRAMES={best['device']}"
          f"  (~{best['total_ms']:.1f} ms total, {best['underruns']} underruns)")
    base = next((r for r in results if r["queue"] == 1024 and r["device"] in (256, 512)), None)
    if base and base is not best:
        print(f"vs 1024/{base['device']}: {base['total_ms'] - best['total_ms']:+.1f} ms saved")
    if a.json:
        slim = [{k: v for k, v in r.items() if k != "probe"} for r in results]
        Path(a.json).write_text(json.dumps(slim, indent=2))
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
