#!/usr/bin/env python3
"""Build a playable Rhythm Heaven app from YOUR ROM (nothing game-derived ships).

  python3 tools/build_app.py --rom game.nds --work ~/rh-app --framework ~/ndsrecomp \
      --target macos|ios-sim|ios-device [--recomp-ui DIR] [--bundle-id ID] [--sign "Apple Development: ..."]

Stages (each skipped when its output exists; delete the work dir entry to redo):
  1 verify ROM SHA-1          2 module images (prepare_images)
  3 recompiler (framework)    4 FreeBIOS banks
  5 title banks from the ROM + data/ingest seeds (no captured pages needed)
  6 SDL3 (macOS: Homebrew; iOS: source build, static)
  7 runner build              8 package (.app / .ipa)

The result contains code derived from Nintendo's ROM: build it for yourself,
do not redistribute it. iOS-device output is an UNSIGNED .ipa unless --sign is
given; install it with your own Apple ID (Xcode/Sideloadly/AltStore).
"""
import argparse, hashlib, os, shutil, subprocess, sys, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SHA1 = "601b92b1603f1822543e264df55ab4152ded356c"
SDL_TAG = "release-3.4.18"


def run(cmd, **kw):
    cmd = [str(c) for c in cmd]
    print("  $", " ".join(cmd)[:200], flush=True)
    r = subprocess.run(cmd, **kw)
    if r.returncode:
        sys.exit(f"command failed ({r.returncode}): {' '.join(cmd)[:160]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--work", required=True, help="build dir (keep OUTSIDE iCloud/Dropbox)")
    ap.add_argument("--framework", required=True, help="ndsrecomp checkout (port branch)")
    ap.add_argument("--recomp-ui", default=os.environ.get("RECOMP_UI_ROOT"),
                    help="github.com/mstan/recomp-ui checkout")
    ap.add_argument("--target", choices=("macos", "ios-sim", "ios-device"), default="macos")
    ap.add_argument("--bundle-id", default="com.example.rhythmheavenrecomp")
    ap.add_argument("--app-name", default="Rhythm Heaven")
    ap.add_argument("--sdl-src", help="SDL3 source tree (iOS targets; cloned if absent)")
    ap.add_argument("--sign", help="codesign identity for iOS output (optional)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()

    rom, work, fw = Path(a.rom).resolve(), Path(a.work).expanduser().resolve(), Path(a.framework).resolve()
    if "Mobile Documents" in str(work) or "iCloud" in str(work):
        sys.exit("work dir is inside iCloud Drive; pick a local path (hundreds of MB of C)")
    work.mkdir(parents=True, exist_ok=True)

    print("[1] ROM")
    h = hashlib.sha1(rom.read_bytes()).hexdigest()
    if h != SHA1:
        sys.exit(f"ROM SHA-1 {h} is not Rhythm Heaven (US) {SHA1}")
    local_rom = work / "game.nds"          # simctl/TCC-friendly local copy
    if not local_rom.exists():
        shutil.copyfile(rom, local_rom)

    print("[2] module images")
    images = work / "images"
    if not (images / "arm9.bin").exists():
        run([sys.executable, "-I", HERE / "prepare_images.py", "--rom", local_rom, "--out", images])

    print("[3] recompiler")
    rc_dir = work / "recompiler"
    exe = rc_dir / "nds_recompile"
    if not exe.exists():
        run(["cmake", "-G", "Ninja", "-S", fw / "recompiler", "-B", rc_dir, "-DCMAKE_BUILD_TYPE=Release"])
        run(["cmake", "--build", rc_dir, "--parallel", a.jobs])

    print("[4] FreeBIOS banks")
    gen = work / "generated"
    gen.mkdir(exist_ok=True)
    for bank, cfg, binf in (("freebios_arm9", "freebios9", "drastic_bios_arm9.bin"),
                            ("freebios_arm7", "freebios7", "drastic_bios_arm7.bin")):
        if not (gen / f"{bank}.c").exists():
            run([exe, "--config", fw / "bios" / (cfg + ".toml"),
                 "--bin", fw / "third_party/freebios" / binf, "--out", gen, "--bank", bank])

    print("[5] title banks")
    banks = work / "titlebanks"
    if not list(banks.glob("*_dispatch.c")):
        run([sys.executable, "-I", HERE / "gen_banks.py", "--recompiler", exe, "--images", images,
             "--ingest", REPO / "data/ingest", "--out", banks, "--all-overlays", "--no-page-banks"])

    ios = a.target.startswith("ios")
    sysroot = {"macos": None, "ios-sim": "iphonesimulator", "ios-device": "iphoneos"}[a.target]
    plat = []
    sdl_dir = None
    print("[6] SDL3")
    if ios:
        plat = ["-DCMAKE_SYSTEM_NAME=iOS", f"-DCMAKE_OSX_SYSROOT={sysroot}",
                "-DCMAKE_OSX_ARCHITECTURES=arm64", "-DCMAKE_OSX_DEPLOYMENT_TARGET=17.0"]
        src = Path(a.sdl_src) if a.sdl_src else work / "SDL-src"
        if not src.exists():
            run(["git", "clone", "-q", "--depth", "1", "--branch", SDL_TAG,
                 "https://github.com/libsdl-org/SDL", src])
        sdl_b, sdl_i = work / f"sdl-{a.target}", work / f"sdl-{a.target}-install"
        if not (sdl_i / "lib/cmake/SDL3").exists():
            run(["cmake", "-G", "Ninja", "-S", src, "-B", sdl_b, *plat, "-DCMAKE_BUILD_TYPE=Release",
                 "-DSDL_STATIC=ON", "-DSDL_SHARED=OFF", "-DSDL_TEST_LIBRARY=OFF", "-DSDL_TESTS=OFF",
                 f"-DCMAKE_INSTALL_PREFIX={sdl_i}"])
            run(["cmake", "--build", sdl_b, "--parallel", a.jobs])
            run(["cmake", "--install", sdl_b])
        sdl_dir = sdl_i / "lib/cmake/SDL3"
    else:
        for c in ("/opt/homebrew/lib/cmake/SDL3", "/usr/local/lib/cmake/SDL3"):
            if Path(c).exists():
                sdl_dir = Path(c)
        if not sdl_dir:
            sys.exit("SDL3 not found: brew install sdl3")

    print("[7] runner")
    if not a.recomp_ui or not Path(a.recomp_ui).exists():
        sys.exit("--recomp-ui (or RECOMP_UI_ROOT) must point at a recomp-ui checkout: "
                 "git clone https://github.com/mstan/recomp-ui")
    rb = work / f"runner-{a.target}"
    cfg = ["cmake", "-G", "Ninja", "-S", fw / "runner", "-B", rb, *plat,
           "-DCMAKE_BUILD_TYPE=Release", "-DNDS_SDL_BACKEND=SDL3", f"-DSDL3_DIR={sdl_dir}",
           "-DNDS_BOOTSTRAP_FIRMWARE=ON", "-DNDS_ENABLE_COMPUTE_RENDERER=OFF",
           "-DNDS_ENABLE_PCAP_BACKEND=OFF", "-DNDS_RETAIL_BIOS_BANKS=OFF",
           f"-DNDS_GENERATED_DIR={gen}", f"-DNDS_RECOMP_UI_ROOT={a.recomp_ui}",
           f"-DNDS_TITLE_BANK_DIR={banks}", f"-DNDS_TITLE_ROM_SHA1={SHA1}"]
    game_toml = REPO / ("game-ios.toml" if ios and (REPO / "game-ios.toml").exists() else "game.toml")
    if ios:
        cfg += [f"-DNDS_IOS_GAME_CONFIG={game_toml}", f"-DNDS_IOS_BUNDLE_ID={a.bundle_id}",
                f"-DNDS_IOS_APP_NAME={a.app_name}"]
    run(cfg)
    run(["cmake", "--build", rb, "--target", "nds_runner", "--parallel", a.jobs])

    print("[8] package")
    out = work / "out" / a.target
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    if not ios:
        shutil.copy2(rb / "nds_runner", out / "nds_runner")
        shutil.copy2(game_toml, out / "game.toml")
        (out / "play.sh").write_text(
            '#!/bin/sh\nD="$(cd "$(dirname "$0")" && pwd)"\n'
            'ROM="${1:?usage: play.sh game.nds [rotation]}"\n'
            'S="$HOME/Library/Application Support/RhythmHeavenRecomp"; mkdir -p "$S"\n'
            'cd "$S"; export NDS_THREADED_PRESENT=1 NDS_PRESENT_THREAD=1\n'
            'exec "$D/nds_runner" . --interactive --freebios --generated-firmware --boot direct '
            '--rom "$ROM" --config "$D/game.toml" --save-path "$S/rhythmheaven.sav" '
            '--coverage-manifest "$S/coverage-$(date +%Y%m%d-%H%M%S).json" ${2:+--screen-rotation $2}\n')
        (out / "play.sh").chmod(0o755)
        print("done:", out)
        return
    app = rb / "nds_runner.app"
    dest = out / f"{a.app_name}.app"
    shutil.copytree(app, dest, symlinks=True)
    if a.target == "ios-sim" or a.sign:
        run(["codesign", "-s", a.sign or "-", "--force", dest])
    if a.target == "ios-device":
        payload = out / "Payload"
        payload.mkdir()
        shutil.copytree(dest, payload / dest.name, symlinks=True)
        ipa = out / f"{a.app_name.replace(' ', '')}.ipa"
        with zipfile.ZipFile(ipa, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(payload.rglob("*")):
                z.write(p, p.relative_to(out))
        shutil.rmtree(payload)
        print("done:", ipa, "(signed)" if a.sign else "(UNSIGNED: sign/install with your Apple ID)")
    else:
        print("done:", dest)
    print("Copy your .nds into the app's Documents folder (Files app) as game.nds, then open the app.")


if __name__ == "__main__":
    main()
