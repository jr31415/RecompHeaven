# Running and examining the recomp yourself (macOS arm64)

Everything below already exists under `~/dev/rh-build/`. FW = the framework checkout
(`.../GitHub/ndsrecomp`, branch `port/rhythm-heaven-macos`), ROM = your .nds.

## 1. Headless run, print what happened
```
cd ~/dev/rh-build/run
~/dev/rh-build/runner-title2/nds_runner . 200000000 --freebios --generated-firmware \
  --boot direct --rom "$ROM" --no-save --diagnostics off --no-coverage-manifest
```
Prints both CPUs' registers, dispatch stats, and (at exit) a trace tail.
`runner/` = no title banks (everything interpreted, Tier 3).
`runner-title2/` = static banks (best so far; Tier 3 ~0.0035%).

## 2. Drive it and look at the screens (what I used)
```
python3 -I tools/capture_session.py --runner ~/dev/rh-build/runner-title2/nds_runner \
  --rom "$ROM" --work /tmp/rh-w --out /tmp/rh-frames \
  --script '[{"run":600},{"shot":"title"}]'
```
Open /tmp/rh-frames/title_A.png (top) and _B.png (bottom). Script actions: run, touch,
down/up, swipe, keys, shot, manifest, tier3, cov, digest.
Flick that advances the title (needs speed):
`{"down":[110,96],"hold":12},{"down":[130,70],"hold":8},{"down":[150,60],"hold":6},{"down":[252,76],"hold":1},{"up":true,"hold":1}`
Then slot 1 `{"touch":[64,96]}`, label Me `[170,30]`, Yes `[50,45]`.
Run it with `scripts/play.sh [script.json] [outdir]` (defaults: play1.json -> /tmp/rh-frames).
Full 3,840-VBlank play script: `scripts/play1.json` (edit the manifest path inside).

## 2b. Play in a window
`scripts/play_window.sh [rotation]` (default 270). Saves go to
`~/Library/Application Support/RhythmHeavenRecomp/rhythmheaven.sav` (8 KiB EEPROM,
raw, melonDS-compatible). Every session also writes
`~/dev/rh-build/play/frame_times-<stamp>.csv` (per-frame timing) and a Tier-3 coverage
manifest to `~/dev/rh-build/coverage/` (feed it to ingest to close coverage gaps).
`python3 tools/analyze_frames.py <csv>` explains slow frames.
Env: `NDS_AUDIO_QUEUE_FRAMES` (256..4096, default 1024), `NDS_VSYNC=0`.

## 3. Live debug over TCP (any time, any ring)
```
nds_runner . --serve --port 19842 --freebios --generated-firmware --boot direct --rom "$ROM" --no-save
printf '{"cmd":"regs","cpu":9}\n' | nc 127.0.0.1 19842
```
Useful cmds (FW/TCP.md): regs, read_mem, framebuffer, event_counts, static_coverage,
tier3_coverage, run_to_event, pc_hot, dispatch_stats, coverage_manifest.

## 4. Look at the generated C
- `~/dev/rh-build/titlebanks2/*.c` is the recompiled game (one bank per module/overlay,
  `*_dispatch.c` has the PC->function + content-validation rows).
- Recompile one module by hand:
```
nds_recompile --config ~/dev/rh-build/images/arm9.toml --bin ~/dev/rh-build/images/arm9.bin --audit
nds_recompile --config X.toml --bin X.bin --out OUT --bank NAME --shards 2 --validate-live-bytes
```
  `--audit` prints function count, undecoded words and per-op histogram without emitting.

## 5. Rebuild the whole thing
Framework recompiler: `cmake -G Ninja -B B FW/recompiler && cmake --build B`.
Then prepare_images -> capture (interpreted runner) -> FW/tools/ingest_coverage_manifests.py
-> gen_banks.py --all-overlays -> cmake with -DNDS_TITLE_BANK_DIR/-DNDS_TITLE_ROM_SHA1
(see README.md). ~90 s to rebuild banks.

## Not available yet
- A window: SDL3 is not installed (`brew install sdl3`, then configure with
  -DNDS_SDL_BACKEND=SDL3). Until then it is headless + PNGs.
- Note: the third ingest (adding a banked-runner manifest) *regressed* Tier 3
  (13.6K -> 1.1M ARM9 insns). Use titlebanks2 / runner-title2 as the baseline.
