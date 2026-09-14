#!/usr/bin/env python3
"""Absolute medians per bucket per arm, to diagnose a ratio that disagrees with the full suite.

The filtered arms produced code-reading ratios near 1.0 where the full 1,463-test suites gave
0.702, and a bytes ratio of 0.067 where the suites gave 6.95. Ratios cannot say which arm moved,
so print the underlying numbers.
"""
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
        out[(f["opcode"], f["mode"], f["gas"], f.get("value_sent"))] = dict(
            mgas_s=gas / (ns / 1e9) / 1e6,
            bytes=agg.get("resource_totals", {}).get("disk_read_bytes", 0),
            bucket=bucket(f["opcode"], f["mode"]),
        )
    return out


arms = {}
for arg in sys.argv[1:]:
    label, _, path = arg.partition("=")
    arms[label] = load(path)

common = sorted(set.intersection(*(set(v) for v in arms.values())))
print(f"common: {len(common)}")
print(f'{"bucket":<14}{"arm":<16}{"MGas/s":>10}{"bytes(med)":>16}')
for b in ("absent", "leaf-only", "code-reading"):
    keys = [c for c in common if arms[next(iter(arms))][c]["bucket"] == b]
    if not keys:
        continue
    for label, v in arms.items():
        print(f"{b:<14}{label:<16}"
              f"{st.median([v[c]['mgas_s'] for c in keys]):>10.2f}"
              f"{st.median([v[c]['bytes'] for c in keys]):>16.0f}")
    print()
