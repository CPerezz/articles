#!/usr/bin/env python3
"""Is state-actor's extra read volume additive (fixed MB per test) or multiplicative?

This decides how to read the residual. The category table hints at additive: state-actor reads
+95 MB where a test reads 1.8 MB, and +183 MB where it reads 3587 MB. If the excess is roughly
constant, the throughput ratio must approach parity as a test's own volume grows and collapse
toward 0.7 when a test reads almost nothing - which is exactly the observed pattern, and would
mean the remaining divergence is one fixed overhead rather than a per-lookup penalty.
"""
import glob
import json
import os
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
    return (g / 1e6) / (t / 1e9), r.get("disk_read_bytes", 0) / 1e6


joc, sa = load(sys.argv[1]), load(sys.argv[2])
rows = []
for tid in set(joc) & set(sa):
    a, b = metrics(joc[tid]), metrics(sa[tid])
    if a and b:
        rows.append((a[1], b[1], b[0] / a[0]))
rows.sort()

hdr = ("jocMB bucket", "n", "med jocMB", "med saMB", "med DIFF", "med saMB/jocMB", "thr sa/joc")
print("%-16s%5s%12s%11s%11s%17s%13s" % hdr)
for lo, hi in ((0, 10), (10, 100), (100, 1000), (1000, 4000), (4000, 1e9)):
    g = [r for r in rows if lo <= r[0] < hi]
    if not g:
        continue
    label = "%g-%g" % (lo, hi) if hi < 1e9 else "%g+" % lo
    print("%-16s%5d%12.1f%11.1f%11.1f%17.1f%13.3f" % (
        label, len(g),
        median([x[0] for x in g]), median([x[1] for x in g]),
        median([x[1] - x[0] for x in g]),
        median([x[1] / max(x[0], 0.01) for x in g]),
        median([x[2] for x in g])))

d = sorted(x[1] - x[0] for x in rows)
print()
print("excess bytes over all %d tests: median %.0f MB   p10 %.0f   p90 %.0f"
      % (len(d), median(d), d[len(d) // 10], d[9 * len(d) // 10]))
