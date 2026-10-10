"""Headless driver for the runner's TCP protocol with savestates (used by the coverage fuzzers)."""
import json, socket, subprocess, time, zlib, struct, hashlib, os
from pathlib import Path


def png(path, w, h, rgb):
    raw = b"".join(b"\x00" + rgb[y*w*3:(y+1)*w*3] for y in range(h))
    def ch(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + ch(b"IDAT", zlib.compress(raw, 6)) + ch(b"IEND", b""))


class Session:
    def __init__(self, runner, rom, work, save=None, manifest=None, extra=()):
        self.work = Path(work); self.work.mkdir(parents=True, exist_ok=True)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]
        cmd = [str(runner), ".", "--serve", "--port", str(self.port), "--freebios", "--generated-firmware",
               "--boot", "direct", "--rom", str(rom), "--diagnostics", "off"]
        cmd += ["--save-path", str(save)] if save else ["--no-save"]
        cmd += ["--coverage-manifest", str(manifest)] if manifest else ["--no-coverage-manifest"]
        env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        self.p = subprocess.Popen(cmd + list(extra), cwd=self.work, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(300):
            try:
                self.sk = socket.create_connection(("127.0.0.1", self.port)); break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("runner did not open its debug port")
        self.f = self.sk.makefile("rw", newline="\n")
        self.vb = 0

    def call(self, **r):
        self.f.write(json.dumps(r) + "\n"); self.f.flush()
        return json.loads(self.f.readline())

    def run_to(self, n):
        r = self.call(cmd="run_to_event", event="vblank9", count=n)
        self.vb = n
        return r

    def run(self, frames):
        return self.run_to(self.vb + frames)

    def frame(self):
        return self.call(cmd="event_counts").get("vblank9", self.vb)

    def touch(self, x, y, hold=3):
        self.call(cmd="touch", x=x, y=y, down=True); self.run(hold)
        self.call(cmd="touch", x=x, y=y, down=False)

    def down(self, x, y, hold=1):
        self.call(cmd="touch", x=x, y=y, down=True); self.run(hold)

    def up(self, hold=1):
        self.call(cmd="touch", x=0, y=0, down=False); self.run(hold)

    def flick(self, x0, y0, x1, y1, frames=4):
        for k in range(frames + 1):
            self.call(cmd="touch", x=round(x0 + (x1 - x0) * k / frames),
                      y=round(y0 + (y1 - y0) * k / frames), down=True)
            self.run(1)
        self.call(cmd="touch", x=x1, y=y1, down=False)

    def keys(self, mask, hold=3):
        self.call(cmd="keys", mask=mask); self.run(hold); self.call(cmd="keys", mask=0)

    def save_state(self, path):
        r = self.call(cmd="state_save", path=str(path)); assert r.get("ok"), r

    def load_state(self, path):
        r = self.call(cmd="state_load", path=str(path)); assert r.get("ok"), r
        self.vb = self.frame()

    def shot(self, name, out):
        out = Path(out); out.mkdir(parents=True, exist_ok=True); h = []
        for eng in "AB":
            r = self.call(cmd="framebuffer", engine=eng); rgb = bytes.fromhex(r["rgb"])
            png(out / f"{name}_{eng}.png", r["w"], r["h"], rgb); h.append(hashlib.sha1(rgb).hexdigest()[:10])
        return h

    def grab(self):
        """(w, h, rgb) of both screens stacked: A over B."""
        parts = []
        for eng in "AB":
            r = self.call(cmd="framebuffer", engine=eng)
            parts.append((r["w"], r["h"], bytes.fromhex(r["rgb"])))
        return parts

    def digest(self):
        out = []
        for eng in "AB":
            r = self.call(cmd="framebuffer", engine=eng); out.append(hashlib.sha1(bytes.fromhex(r["rgb"])).hexdigest()[:10])
        return out

    def tier3(self):
        return self.call(cmd="static_coverage")

    def manifest(self, path):
        return self.call(cmd="coverage_manifest", path=str(path))

    def close(self):
        try: self.p.terminate(); self.p.wait(10)
        except Exception: self.p.kill()


def sheet(frames, path, cols=4, labels=None):
    """Contact sheet: each frame is [(w,h,rgb)A,(w,h,rgb)B], drawn A over B."""
    w, h = 256, 192
    rows = (len(frames) + cols - 1) // cols
    W, H = cols * (w + 4), rows * (2 * h + 4)
    buf = bytearray(b"\x20" * (W * H * 3))
    for i, fr in enumerate(frames):
        ox, oy = (i % cols) * (w + 4), (i // cols) * (2 * h + 4)
        for k, (fw, fh, rgb) in enumerate(fr):
            for y in range(min(fh, h)):
                src = rgb[y * fw * 3:(y * fw + min(fw, w)) * 3]
                dst = ((oy + k * h + y) * W + ox) * 3
                buf[dst:dst + len(src)] = src
    png(path, W, H, bytes(buf))


def find_tiles(w, h, rgb):
    """Tile centres on the game-select map: 34x34 frames with a fff700 left border."""
    Y = b"\xff\xf7\x00"
    def px(x, y): return rgb[(y * w + x) * 3:(y * w + x) * 3 + 3]
    out = []
    for x in range(1, w - 36):
        y = 0
        while y < h:
            if px(x, y) == Y and px(x - 1, y) == b"\x00\x00\x00":
                y0 = y
                while y < h and px(x, y) == Y: y += 1
                if 24 <= y - y0 <= 40:
                    out.append((x, y0, y - y0))
            else:
                y += 1
    # collapse duplicates (adjacent x for double-wide border)
    tiles = []
    for x, y0, n in out:
        if not any(abs(x - tx) <= 3 and abs(y0 - ty) <= 3 for tx, ty, _ in tiles):
            tiles.append((x, y0, n))
    return [(x + 17, y0 + n // 2) for x, y0, n in sorted(tiles, key=lambda t: (t[1], t[0]))]


def tile_hash(w, h, rgb, cx, cy):
    """Hash of the tile's inner picture (ignores the PERFECT/rank ribbon at the edges)."""
    x0, y0 = max(0, cx - 15), max(0, cy - 15)
    data = b"".join(rgb[((y0 + j) * w + x0) * 3:((y0 + j) * w + min(w, x0 + 30)) * 3] for j in range(30) if y0 + j < h)
    return hashlib.sha1(data).hexdigest()[:10]


def boot_to_map(s):
    """Boot with the (left-handed) 100% save to the game-select map, no savestates."""
    s.run_to(600); s.touch(14, 14, 6)          # "Change to right-handed?" prompt button
    s.run_to(800); s.touch(150, 45, 6)         # No
    s.run_to(1000)
    s.down(128, 96, 6); s.down(100, 96, 2); s.down(60, 96, 2); s.down(10, 96, 1); s.up(1)  # start flick
    s.run_to(1250); s.touch(60, 96, 6)         # file slot 1
    s.run_to(1550); s.touch(128, 96, 6)        # START
    s.run(360)


def pan(s, hx, hy, dx, dy):
    x1 = max(8, min(247, hx + dx)); y1 = max(8, min(184, hy + dy))
    s.flick(hx, hy, x1, y1, 22); s.run(80)


def tap_game_tile(s, game, hold=6):
    """Find the game's tile by picture in the current map view and tap it. False if absent."""
    w, h, rgb = s.grab()[1]
    want = set(game.get("hashes", []))
    for cx, cy in find_tiles(w, h, rgb):
        if cx < 20 or cx > w - 20 or cy < 18 or cy > h - 18:
            continue
        if tile_hash(w, h, rgb, cx, cy) in want:
            s.touch(cx, cy, hold)
            return True
    s.touch(game["x"], game["y"], hold)
    return False
