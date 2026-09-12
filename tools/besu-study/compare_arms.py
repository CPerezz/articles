#!/usr/bin/env python3
"""Per-category comparison across Besu arms.

Mirrors the geth study's headline table: for each (opcode, account_mode) category, the median
throughput per arm and the ratio between them. Categories are compared only where BOTH arms
measured the same set of gas points, so a ratio can never be formed across different workloads.

Usage: compare_arms.py arms.json <baseline-label> <other-label>
"""
import collections
import json
import statistics as st
import sys

arms = json.load(open(sys.argv[1]))
base_label, other_label = sys.argv[2], sys.argv[3]


def index(rows):
    """key -> mgas/s, keyed by the full identity of the workload."""
    out = {}
    for r in rows:
        if not all(k in r for k in ("opcode", "mode", "gas")):
            continue
        out[(r["opcode"], r["mode"], r["gas"], r.get("value_sent"), r.get("baseline"))] = r
    return out


a, b = index(arms[base_label]), index(arms[other_label])
common = sorted(set(a) & set(b))
print(f"{base_label}: {len(a)}  {other_label}: {len(b)}  common: {len(common)}")
if not common:
    sys.exit("no common workloads")

by_cat = collections.defaultdict(list)
for k in common:
    ra, rb = a[k], b[k]
    by_cat[(k[0], k[1])].append((ra["mgas_s"], rb["mgas_s"], ra, rb))

print(f"\n{'opcode':<14}{'account_mode':<28}{'n':>4}{base_label:>12}{other_label:>12}{'ratio':>8}")
rows = []
for (op, mode), vals in by_cat.items():
    ma = st.median([v[0] for v in vals])
    mb = st.median([v[1] for v in vals])
    rows.append((mb / ma, op, mode, len(vals), ma, mb))
for ratio, op, mode, n, ma, mb in sorted(rows):
    print(f"{op:<14}{mode:<28}{n:>4}{ma:>12.2f}{mb:>12.2f}{ratio:>8.3f}")

ratios = [r[0] for r in rows]
print(f"\ncategories: {len(ratios)}  min {min(ratios):.3f}  median {st.median(ratios):.3f}  max {max(ratios):.3f}")

# Bytes moved per unit of gas: the engine-independent quantity the residual argument rests on.
da = sum(a[k]["disk_read_bytes"] for k in common)
db_ = sum(b[k]["disk_read_bytes"] for k in common)
ga = sum(a[k]["gas_used"] for k in common)
gb = sum(b[k]["gas_used"] for k in common)
print(f"\ngas on common workloads: {base_label} {ga:.4g}  {other_label} {gb:.4g}  (ratio {gb/ga:.6f})")
print(f"disk read bytes:         {base_label} {da:.4g}  {other_label} {db_:.4g}  (ratio {db_/da:.4f})")
print(f"bytes per gas:           {base_label} {da/ga:.4f}  {other_label} {db_/gb:.4f}  (ratio {(db_/gb)/(da/ga):.4f})")
