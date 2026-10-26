#!/usr/bin/env python3
"""Boot headless with NDS_STRICT_STATIC=1 and report every interpreter entry (should be none).
  strict_check.py RUNNER ROM [frames]"""
import os, subprocess, sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rhplay import Session
runner, rom = sys.argv[1:3]; frames = int(sys.argv[3]) if len(sys.argv) > 3 else 3000
log = "/tmp/strict-check.log"
orig = subprocess.Popen
subprocess.Popen = lambda *a, **k: orig(*a, **{**k, "stderr": open(log, "w")})
os.environ["NDS_STRICT_STATIC"] = "1"
s = Session(runner, rom, "/tmp/rh-strict-work", save=None)
s.run_to(frames); cov = s.tier3(); s.close()
c = collections.Counter(l.split("pc=")[1].split()[0] for l in open(log) if "strict-static" in l)
print("tier3:", cov["tier3_insns9"], "insns;", sum(c.values()), "entries at", len(c), "addresses")
for a, n in c.most_common(12): print("  ", a, n)
