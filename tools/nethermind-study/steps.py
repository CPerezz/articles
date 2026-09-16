#!/usr/bin/env python3
"""Setup step vs measured step, per arm and category.

The fixed ~179 MB excess was measured on the 'test' step only. Every test also runs a 'setup'
step, and comparing the two per arm says whether the generated store pays its penalty while
executing the setup payload, while executing the measured payload, or both. That distinguishes
"we created this by running pre-bench setup fixtures" from "the store itself costs more".
"""
import glob
import json
import os
import re
import sys
from statistics import median

ARMS = {"jochemnet (treated)": "/bench/results/nm-joc-full",
        "state-actor": "/bench/results/nm-state-actor"}


def load(root):
    best, bn = None, -1
    for rj in glob.glob(os.path.join(root, "runs", "*", "result.json")):
        try:
            n = len(json.load(open(rj)).get("tests", {}))
        except Exception:
            continue
        if n > bn:
            best, bn = rj, n
    return json.load(open(best))["tests"]


def step_mb(entry, step):
    s = (entry.get("steps") or {}).get(step)
    if not s:
        return None
    r = (s.get("aggregated") or {}).get("resource_totals") or {}
    return r.get("disk_read_bytes", 0) / 1e6


def is_control(tid):
    return bool(re.search(r"overhead_baseline_True", tid))


data = {k: load(v) for k, v in ARMS.items()}
common = set.intersection(*(set(v) for v in data.values()))
print(f"matched tests: {len(common)}")
print("%-22s%10s%12s%12s%12s" % ("arm", "tests", "setup MB", "test MB", "setup+test"))
for group, pred in (("CONTROL (no account work)", is_control),
                    ("MEASURED", lambda t: not is_control(t))):
    print(f"\n### {group}")
    for label, tests in data.items():
        sel = [t for t in common if pred(t)]
        su = [step_mb(tests[t], "setup") for t in sel]
        te = [step_mb(tests[t], "test") for t in sel]
        su = [x for x in su if x is not None]
        te = [x for x in te if x is not None]
        if not te:
            continue
        print("%-22s%10d%12.1f%12.1f%12.1f" % (
            label, len(sel), median(su) if su else 0, median(te),
            (median(su) if su else 0) + median(te)))
