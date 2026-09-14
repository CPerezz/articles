#!/usr/bin/env python3
"""Compare the filtered 129-test arms, bucketed, against a chosen reference.

Arms are given as label=results-dir. Only workloads present in every arm are used, and gas is
reported per arm so workload identity is verifiable rather than assumed.

Usage: compare_filtered.py <ref-label> <label>=<dir> ...
"""
import collections
import glob
import json
import os
import re
import statistics as st
import sys

CODE = {"EXTCODECOPY", "EXTCODEHASH", "EXTCODESIZE", "CALL", "CALLCODE",
        "DELEGATECALL", "STATICCALL"}
FIELDS = re.compile(
    r"opcode_(?P<opcode>[A-Z0-9]+)"
    r"|value_sent_(?P<value_sent>\d+)"
    r"|account_mode_AccountMode\.(?P<mode>[A-Z_]+)"
    r"|gas-value_(?P<gas>\d+)M"
)


def bucket(op, mode):
    if mode == "NON_EXISTING_ACCOUNT":
        return "absent"
    if mode == "EXISTING_EOA" or op == "BALANCE":
        return "leaf-only"
    return "code-reading" if op in CODE else "leaf-only"


def load(results_dir):
    # runs/ also contains index.json, so select directories explicitly
    runs = sorted(d for d in glob.glob(os.path.join(results_dir, "runs", "*")) if os.path.isdir(d))
    if not runs:
        return {}
    index = json.load(open(os.path.join(runs[-1], "result.json")))["tests"]
    out = {}
    for tid, meta in index.items():
        agg = (meta.get("steps", {}).get("test") or {}).get("aggregated")
        if not agg:
            continue
        ns = agg.get("gas_used_time_total") or agg.get("time_total")
        gas = agg.get("gas_used_total")
        if not ns or not gas:
            continue
        f = {}
        for m in FIELDS.finditer(tid):
            for k, v in m.groupdict().items():
                if v is not None:
                    f[k] = v
        if not all(k in f for k in ("opcode", "mode", "gas")):
            continue
        key = (f["opcode"], f["mode"], f["gas"], f.get("value_sent"))
        out[key] = dict(
            mgas_s=gas / (ns / 1e9) / 1e6,
            gas=gas,
            bytes=agg.get("resource_totals", {}).get("disk_read_bytes", 0),
            bucket=bucket(f["opcode"], f["mode"]),
        )
    return out


ref = sys.argv[1]
arms = {}
for arg in sys.argv[2:]:
    label, _, path = arg.partition("=")
    arms[label] = load(path)
    print(f"{label}: {len(arms[label])} tests", file=sys.stderr)

common = sorted(set.intersection(*(set(v) for v in arms.values())))
print(f"\ncommon workloads: {len(common)}")
print("gas per arm:", "  ".join(f"{k}={sum(v[c]['gas'] for c in common):.6g}" for k, v in arms.items()))

others = [k for k in arms if k != ref]
print(f"\nthroughput ratio vs {ref} (median per bucket)")
print(f'{"bucket":<14}{"n":>5}' + "".join(f"{o:>16}" for o in others))
for b in ("absent", "leaf-only", "code-reading"):
    keys = [c for c in common if arms[ref][c]["bucket"] == b]
    if not keys:
        continue
    row = f"{b:<14}{len(keys):>5}"
    for o in others:
        row += f"{st.median([arms[o][c]['mgas_s'] / arms[ref][c]['mgas_s'] for c in keys]):>16.3f}"
    print(row)

print(f"\nbytes ratio vs {ref} (aggregate per bucket)")
print(f'{"bucket":<14}{"n":>5}' + "".join(f"{o:>16}" for o in others))
for b in ("absent", "leaf-only", "code-reading"):
    keys = [c for c in common if arms[ref][c]["bucket"] == b]
    if not keys:
        continue
    base = sum(arms[ref][c]["bytes"] for c in keys)
    row = f"{b:<14}{len(keys):>5}"
    for o in others:
        row += f"{sum(arms[o][c]['bytes'] for c in keys) / base:>16.3f}"
    print(row)
