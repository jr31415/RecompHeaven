# Rhythm Heaven title notes

See README.md. Facts about the ROM live in the framework CLAUDE.md.

## iOS / iPadOS status (2026-10-10)
- Framework commit "iOS: runner builds for iPhoneOS/Simulator" (framework-patches/0012): CMake
  `-DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_SYSROOT=iphonesimulator|iphoneos` with SDL3 built as a static iOS
  library (`SDL-ios-src`, release-3.4.8, `-DSDL_STATIC=ON`). The runner links to a `.app` bundle
  (`runner/ios/Info.plist.in`, `src/ios_launch.mm`: SDL_RunApp entry, ROM = `game.nds` or first `*.nds`
  in the app's Documents folder via the Files app, save = Documents/game.sav).
- Verified: the headless iOS-simulator arm64 binary (`simctl spawn`) runs the title flow with frame
  digests, instruction counts and Tier-3 counts identical to the macOS build (306 banks).
- NOT verified: UIKit launch. On this machine every third-party UIKit app (a 10-line plain
  UIApplicationMain app too) traps in IOHIDEventSystemClientSetDispatchQueue under the iOS 27.0 beta
  simulator runtime (24A5390f vs host macOS 26A5425a), so the SDL window path has not run. Needs a
  real device or a matching runtime. A signing identity exists but no provisioning/registration was done.
- Note: a process launched through `simctl spawn` hangs in fopen() on a ROM under iCloud Drive; use a
  local copy outside iCloud.

## App builder (2026-10-10)
`tools/build_app.py --rom ROM --work DIR --framework FW --recomp-ui UI --target macos|ios-sim|ios-device`
rebuilds everything from the user's ROM (images -> recompiler -> FreeBIOS banks -> title banks from
`data/ingest/seeds` (address lists only) -> SDL3 -> runner -> `.app`/`.ipa`). Verified end to end for
`macos` from an empty work dir (587 build steps). ios-sim/ios-device targets compile and link
(device Mach-O platform IOS); UIKit launch untested (see iOS section).
Without captured-page banks (`--no-page-banks`, needed because those pages are ROM+runtime bytes that
cannot be shipped) a minigame launch interprets ~3.0M ARM9 insns vs 0.48M with them (both vs 54.6M
before the close-out). Next step if wanted: have the builder run a scripted capture to materialise
the page banks itself.
