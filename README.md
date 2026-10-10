# rhythmheavenrecomp

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
