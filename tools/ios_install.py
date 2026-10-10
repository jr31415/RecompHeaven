#!/usr/bin/env python3
"""Sign a built Rhythm Heaven .app with your own Apple team and install it on a plugged-in iPad.

  python3 tools/ios_install.py --app ~/dev/rh-app/out/ios-device/"Rhythm Heaven.app" \
      --team 34SPG72VVT --udid 00008112-... --rom game.nds [--save rhythmheaven.sav] \
      [--coredevice-id 5062F6C6-...]

How it works: a throw-away Xcode project with the same bundle id is built with
-allowProvisioningUpdates so Xcode creates/downloads the development profile for
(team, bundle id, device). That profile and its entitlements are then applied to
the prebuilt app, which is re-signed, installed with devicectl, and the ROM (+ save)
are copied into the app's Documents folder BEFORE first launch.

Needs: Xcode signed in to the Apple ID (Settings > Accounts), iPad unlocked, trusted,
Developer Mode on. Find ids with `xcodebuild -showdestinations` (UDID) and
`xcrun devicectl list devices` (CoreDevice id).
"""
import argparse, plistlib, shutil, subprocess, sys, tempfile
from pathlib import Path


def run(cmd, **kw):
    cmd = [str(c) for c in cmd]
    print("  $", " ".join(cmd)[:180], flush=True)
    r = subprocess.run(cmd, **kw)
    if r.returncode:
        sys.exit(f"failed ({r.returncode}): {cmd[0]}")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", required=True)
    ap.add_argument("--team", required=True, help="Apple team id (certificate OU)")
    ap.add_argument("--udid", required=True, help="device UDID as shown by xcodebuild -showdestinations")
    ap.add_argument("--coredevice-id", help="devicectl identifier (defaults to --udid)")
    ap.add_argument("--rom", help="copied to Documents/game.nds when given")
    ap.add_argument("--save", help="raw 8 KiB EEPROM save to install as game.sav")
    ap.add_argument("--identity", default="Apple Development")
    a = ap.parse_args()
    app = Path(a.app).resolve()
    info = plistlib.loads((app / "Info.plist").read_bytes())
    bundle = info["CFBundleIdentifier"]
    dev = a.coredevice_id or a.udid

    tmp = Path(tempfile.mkdtemp(prefix="rh-prov-"))
    (tmp / "plain.m").write_text(
        '#import <UIKit/UIKit.h>\nint main(int c,char**v){@autoreleasepool{return 0;}}\n')
    (tmp / "CMakeLists.txt").write_text(f'''cmake_minimum_required(VERSION 3.20)
project(prov LANGUAGES C OBJC)
add_executable(prov MACOSX_BUNDLE plain.m)
target_link_libraries(prov PRIVATE "-framework UIKit" "-framework Foundation")
set_target_properties(prov PROPERTIES MACOSX_BUNDLE_GUI_IDENTIFIER {bundle}
  XCODE_ATTRIBUTE_DEVELOPMENT_TEAM {a.team} XCODE_ATTRIBUTE_CODE_SIGN_STYLE Automatic
  XCODE_ATTRIBUTE_CODE_SIGN_IDENTITY "Apple Development" XCODE_ATTRIBUTE_TARGETED_DEVICE_FAMILY "1,2")
''')
    run(["cmake", "-G", "Xcode", "-S", tmp, "-B", tmp / "b", "-DCMAKE_SYSTEM_NAME=iOS",
         "-DCMAKE_OSX_SYSROOT=iphoneos", "-DCMAKE_OSX_DEPLOYMENT_TARGET=17.0"], stdout=subprocess.DEVNULL)
    run(["xcodebuild", "-project", tmp / "b/prov.xcodeproj", "-scheme", "prov", "-configuration", "Release",
         "-destination", f"id={a.udid}", "-allowProvisioningUpdates",
         "-allowProvisioningDeviceRegistration"], stdout=subprocess.DEVNULL)
    prov_app = next((tmp / "b").rglob("prov.app"))
    profile = prov_app / "embedded.mobileprovision"
    if not profile.exists():
        sys.exit("no provisioning profile was produced")

    shutil.copy2(profile, app / "embedded.mobileprovision")
    ent = subprocess.run(["codesign", "-d", "--entitlements", "-", "--xml", prov_app],
                         capture_output=True, text=True).stdout
    ent_path = tmp / "ent.plist"
    ent_path.write_text(ent[ent.index("<?xml"):] if "<?xml" in ent else ent)
    # Pick the keychain identity whose certificate the profile actually lists
    # ("Apple Development" alone is ambiguous with several certs).
    import hashlib
    prof = plistlib.loads(subprocess.run(["security", "cms", "-D", "-i", profile],
                                         capture_output=True).stdout)
    ident = a.identity
    have = subprocess.run(["security", "find-identity", "-v", "-p", "codesigning"],
                          capture_output=True, text=True).stdout.upper()
    for der in prof.get("DeveloperCertificates", []):
        h = hashlib.sha1(der).hexdigest().upper()
        if h in have:
            ident = h
            break
    run(["codesign", "-f", "-s", ident, "--entitlements", ent_path, "--timestamp=none", app])
    run(["xcrun", "devicectl", "device", "install", "app", "--device", dev, app])
    for src, dst in ((a.rom, "Documents/game.nds"), (a.save, "Documents/game.sav")):
        if src:
            run(["xcrun", "devicectl", "device", "copy", "to", "--device", dev,
                 "--domain-type", "appDataContainer", "--domain-identifier", bundle,
                 "--source", src, "--destination", dst])
    print("installed. On the iPad: Settings > General > VPN & Device Management > trust your developer "
          "profile if prompted, then open the app.")


if __name__ == "__main__":
    main()
