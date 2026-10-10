# RecompHeaven

Title repo for a static recompilation of Rhythm Heaven (US, `YLZE`) on the
[ndsrecomp](../GitHub/ndsrecomp) framework. Contains no ROM, BIOS, firmware,
or generated code; each user builds from their own dump.

- ROM SHA-1: `601b92b1603f1822543e264df55ab4152ded356c`
- Framework checkout: set `NDSRECOMP` (default `~/Library/Mobile Documents/com~apple~CloudDocs/Documents/GitHub/ndsrecomp`)
- Port plan: `$NDSRECOMP/docs/rhythm-heaven-plan.md`
- Readiness suite: `python $NDSRECOMP/tools/rh_suite.py --rom <rom>`

Layout: `config/` recompiler TOMLs (ARM9, ARM7, overlays, ITCM/DTCM
autoload), `tools/` capture and overlay-manifest generators, `game.toml`
host settings, `docs/` title notes. `generated/` is ignored.

Not yet pinned to the framework as a submodule: that happens once the
framework's portability changes are pushed.

## Pipeline (macOS arm64 verified 2026-10-09)

```
# 0. framework recompiler + dump-free runner (see framework docs/rhythm-heaven-plan.md Phase 1)
python tools/prepare_images.py --rom ROM --out images/             # arm9/arm7/overlays/autoload
python tools/capture_session.py --runner R --rom ROM --work W --out frames/ \
       --script session.json                                       # headless scripted session
#    ... include {"manifest": "coverage/title.json"} in the script
python $NDSRECOMP/tools/ingest_coverage_manifests.py coverage/*.json \
       --images images/ --out ingest/ --bank-prefix rh             # aliases, seeds, page banks
python tools/gen_banks.py --recompiler nds_recompile --images images/ \
       --ingest ingest/ --out titlebanks/ [--all-overlays]         # content-validated banks
cmake ... -DNDS_TITLE_BANK_DIR=titlebanks -DNDS_TITLE_ROM_SHA1=601b92b1...
```

Differential used as the correctness gate here: run the same script on the
all-interpreted runner and the banked runner; frame hashes and `insn9/insn7`
at the same VBlank counts must match, and `static_coverage` Tier-3 counters
should fall to ~0.

## Framework patches

`framework-patches/` holds the commits made to the ndsrecomp framework for this
port, as `git format-patch` output against upstream
`3a57236` (RetroPortingToolKit/ndsrecomp, "Merge pull request #26"):

```
git clone https://github.com/RetroPortingToolKit/ndsrecomp && cd ndsrecomp
git checkout 3a57236 && git am /path/to/framework-patches/*.patch
```

They add the port plan and readiness suite, a dump-free runner build option,
a `live_overlay_platform.cpp` fix for Apple targets, `--screen-rotation`, the
audio/vsync reordering with a per-frame timing ring, and the opt-in threaded
presenter (`NDS_THREADED_PRESENT=1`).

## Legal

No ROM, BIOS, firmware, or generated recompiled code is committed here, and none
should be (see `.gitignore`). Build from your own dump.
