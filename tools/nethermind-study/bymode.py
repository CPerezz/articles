#!/usr/bin/env python3
"""Per-account_mode read volume, to test whether the residual tracks code-boundness.

state-actor's `code/` DB is 45 GB against jochemnet's 7.6 GB (6x). If the remaining divergence is
driven by code reads, the ordering of the per-mode ratios should follow how code-heavy each mode
is: DIFF_MAX (a different max-size contract per access) worst, JUMPDEST (code scanned for valid
jump destinations) next, and the modes that only touch an account record at parity.
"""
import glob
import json
import os
import re
import sys
from statistics import median


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


def metrics(entry):
    s = (entry.get("steps") or {}).get("test")
    if not s:
        return None
    a = s.get("aggregated") or {}
    g, t = a.get("gas_used_total"), a.get("gas_used_time_total")
    if not g or not t:
        return None
    r = a.get("resource_totals") or {}
    return ((g / 1e6) / (t / 1e9), r.get("disk_read_bytes", 0) / 1e6,
            r.get("cpu_usec", 0) / 1e6, g / 1e6)


joc, sa = load(sys.argv[1]), load(sys.argv[2])
by = {}
for tid in set(joc) & set(sa):
    a, b = metrics(joc[tid]), metrics(sa[tid])
    if not a or not b:
        continue
    m = re.search(r"account_mode_(?:AccountMode\.)?([A-Z_]+)", tid)
    mode = m.group(1) if m else "(none)"
    if re.search(r"overhead_baseline_True", tid):
        mode += " [control]"
    by.setdefault(mode, []).append((a, b))

print("%-34s%5s%10s%10s%9s%9s%11s" % (
    "account_mode", "n", "jocMB", "saMB", "readX", "thrX", "MB/Mgas sa"))
rows = []
for mode, v in by.items():
    jm = median([x[0][1] for x in v])
    sm = median([x[1][1] for x in v])
    thr = median([x[1][0] / x[0][0] for x in v])
    gas = median([x[1][3] for x in v])
    rows.append((thr, mode, len(v), jm, sm, sm / max(jm, 0.01), gas))
for thr, mode, n, jm, sm, rx, gas in sorted(rows):
    print("%-34s%5d%10.1f%10.1f%9.2f%9.3f%11.1f" % (mode, n, jm, sm, rx, thr, sm / gas))
