#!/usr/bin/env python3
"""List the tests that still diverge after the placement correction, with their physical evidence.

The aggregate says 124/266 sit outside +/-10%. The question that matters is whether those are
concentrated in the one known-unexplained cell (overhead_baseline, which does no account-state
work) or whether real state-reading tests are still diverging.
"""
import glob
import json
import os
import re
import sys
from collections import Counter
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
    """Throughput, bytes read and cpu from the MEASURED step only.

    Selecting by dict order silently compared a setup step on one arm against the test step on
    the other, which produced ratios of 5-8x out of data whose category medians are ~0.97.
    """
    s = (entry.get("steps") or {}).get("test")
    if not s:
        return None
    a = s.get("aggregated") or {}
    g, t = a.get("gas_used_total"), a.get("gas_used_time_total")
    if not g or not t:
        return None
    r = a.get("resource_totals") or {}
    return (g / 1e6) / (t / 1e9), r.get("disk_read_bytes", 0) / 1e6, r.get("cpu_usec", 0) / 1e6


def params(tid):
    p = {}
    for k in ("opcode", "account_mode", "overhead_baseline", "value_sent", "cache_strategy"):
        m = re.search(k + r"_([^\-\]]+)", tid)
        if m:
            p[k] = m.group(1).replace("AccountMode.", "")
    m = re.findall(r"(\d+)M", tid)
    p["gas"] = (m[-1] + "M") if m else "?"
    p["family"] = tid.split("::")[1].split("[")[0] if "::" in tid else "?"
    return p


joc, sa = load(sys.argv[1]), load(sys.argv[2])
rows = []
for tid in set(joc) & set(sa):
    a, b = metrics(joc[tid]), metrics(sa[tid])
    if not a or not b:
        continue
    rows.append((b[0] / a[0], tid, params(tid), a, b))

div = [r for r in rows if not (0.9 <= r[0] <= 1.1)]
ctrl = [r for r in div if r[2].get("overhead_baseline") == "True"]
real = [r for r in div if r[2].get("overhead_baseline") != "True"]

print(f"comparable {len(rows)} | divergent {len(div)} "
      f"({len(div)/len(rows)*100:.1f}%)  ->  overhead_baseline={len(ctrl)}, "
      f"real state-reading={len(real)}")
print()
print("=== divergent tests that ACTUALLY READ STATE (overhead_baseline != True) ===")
if not real:
    print("  none - every remaining divergence is in the no-account-work control")
else:
    print(f"  {'ratio':>6}  {'family':<38}{'opcode':<14}{'account_mode':<30}{'gas':<6}"
          f"{'jocMB':>8}{'saMB':>9}{'cpu s/j':>9}")
    for r, tid, p, a, b in sorted(real)[:25]:
        print(f"  {r:>6.3f}  {p['family']:<38}{p.get('opcode','-'):<14}"
              f"{p.get('account_mode','-'):<30}{p['gas']:<6}{a[1]:>8.0f}{b[1]:>9.0f}"
              f"{(b[2]/a[2] if a[2] else 0):>9.2f}")
    print()
    print("  breakdown of real divergent tests:")
    for key in ("family", "account_mode", "opcode", "gas"):
        c = Counter(p.get(key, "-") for _, _, p, _, _ in real)
        print(f"    by {key:<14} " + ", ".join(f"{k}={v}" for k, v in c.most_common()))
    print(f"    ratio range {min(r[0] for r in real):.3f} - {max(r[0] for r in real):.3f}, "
          f"median {median([r[0] for r in real]):.3f}")
print()
print("=== state-actor FASTER outliers (ratio > 1.10) ===")
fast = sorted([r for r in rows if r[0] > 1.10], reverse=True)
for r, tid, p, a, b in fast[:10]:
    print(f"  {r:>6.3f}  {p['family']:<34}{p.get('opcode','-'):<13}"
          f"{p.get('account_mode','-'):<28}{p['gas']:<6} ob={p.get('overhead_baseline','-')}")
