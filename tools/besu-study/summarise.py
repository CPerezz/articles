#!/usr/bin/env python3
"""Summary statistics for the three Besu arms, split by account-class family.

The geth study's headline separated one anomalous class (DIFF_MAX) from the rest, because
mixing them produces a median that describes neither. The Besu data splits the same way but on
a different class, so the split is made explicit rather than assumed.
"""
import collections
import json
import statistics as st
import sys

arms = json.load(open(sys.argv[1]))


def index(rows):
    return {
        (r["opcode"], r["mode"], r["gas"], r.get("value_sent"), r.get("baseline")): r
        for r in rows
        if all(k in r for k in ("opcode", "mode", "gas"))
    }


idx = {k: index(v) for k, v in arms.items()}
common = sorted(set.intersection(*(set(v) for v in idx.values())))
print(f"workloads common to all three arms: {len(common)}")

gas = {k: sum(idx[k][c]["gas_used"] for c in common) for k in idx}
print("gas identity:", " ".join(f"{k}={v:.6g}" for k, v in gas.items()))


def cat_medians(a, b):
    by = collections.defaultdict(list)
    for c in common:
        by[(c[0], c[1])].append(idx[b][c]["mgas_s"] / idx[a][c]["mgas_s"])
    return {k: st.median(v) for k, v in by.items()}


def report(a, b):
    m = cat_medians(a, b)
    non = {k: v for k, v in m.items() if k[1] == "NON_EXISTING_ACCOUNT"}
    ex = {k: v for k, v in m.items() if k[1] != "NON_EXISTING_ACCOUNT"}
    print(f"\n=== {b} / {a} ===")
    for label, d in (("all", m), ("EXISTING_* only", ex), ("NON_EXISTING only", non)):
        if d:
            vs = list(d.values())
            print(
                f"  {label:<18} n={len(vs):<3} min {min(vs):.3f}  median {st.median(vs):.3f}  max {max(vs):.3f}"
            )
    da = sum(idx[a][c]["disk_read_bytes"] for c in common)
    db = sum(idx[b][c]["disk_read_bytes"] for c in common)
    print(f"  bytes/gas ratio ({b}/{a}): {db/da:.4f}")


report("treated", "state_actor")
report("untreated", "treated")
report("untreated", "state_actor")
