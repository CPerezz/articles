#!/usr/bin/env python3
"""Full-suite ratios restricted to the 72 workloads the filtered arms share.

The filtered bucket medians disagreed with the full-suite ones (code-reading 1.009 vs 0.702).
Cross-checking identical test ids showed the runs agree within 11-13%, so the disagreement is
bucket COMPOSITION: the 1,463-test selection's leaf-only bucket is dominated by EXISTING_EOA
across 8 opcodes, while the 129-test selection's is mostly BALANCE into contracts.

Restricting the full suite to the same workloads makes the two directly comparable and shows
whether the filtered runs reproduce the effect or not.
"""
import collections
import glob
import json
import os
import re
import statistics as st

CODE = {"EXTCODECOPY", "EXTCODEHASH", "EXTCODESIZE", "CALL", "CALLCODE",
        "DELEGATECALL", "STATICCALL"}


def bucket(op, mode):
    if mode == "NON_EXISTING_ACCOUNT":
        return "absent"
    if mode == "EXISTING_EOA" or op == "BALANCE":
        return "leaf-only"
    return "code-reading" if op in CODE else "leaf-only"


FIELDS = re.compile(
    r"opcode_(?P<opcode>[A-Z0-9]+)"
    r"|value_sent_(?P<value_sent>\d+)"
    r"|account_mode_AccountMode\.(?P<mode>[A-Z_]+)"
    r"|overhead_baseline_(?P<baseline>True|False)"
    r"|gas-value_(?P<gas>\d+)M"
)


def keyof(tid):
    f = {}
    for m in FIELDS.finditer(tid):
        for k, v in m.groupdict().items():
            if v is not None:
                f[k] = v
    if not all(k in f for k in ("opcode", "mode", "gas")):
        return None
    return (f["opcode"], f["mode"], f["gas"], f.get("value_sent"), f.get("baseline"))


def load(results_dir):
    runs = sorted(d for d in glob.glob(os.path.join(results_dir, "runs", "*")) if os.path.isdir(d))
    index = json.load(open(os.path.join(runs[-1], "result.json")))["tests"]
    out = {}
    for tid, meta in index.items():
        agg = (meta.get("steps", {}).get("test") or {}).get("aggregated")
        if not agg:
            continue
        ns = agg.get("gas_used_time_total") or agg.get("time_total")
        if not ns or not agg.get("gas_used_total"):
            continue
        k = keyof(tid)
        if k:
            out[k] = agg["gas_used_total"] / (ns / 1e9) / 1e6
    return out


filt_plain = load("/data/bench-results/s3-plain")
filt_comp = load("/data/bench-results/s4-drained")
shared = sorted(set(filt_plain) & set(filt_comp))

full = json.load(open("/root/bench/arms-three.json"))
fidx = {}
for arm, rows in full.items():
    fidx[arm] = {}
    for r in rows:
        k = keyof(r["test_id"])
        if k:
            fidx[arm][k] = r["mgas_s"]

keys = [k for k in shared if k in fidx["untreated"] and k in fidx["treated"]]
print(f"workloads in both the filtered and full runs: {len(keys)}")

by = collections.defaultdict(lambda: ([], []))
for k in keys:
    b = bucket(k[0], k[1])
    by[b][0].append(fidx["treated"][k] / fidx["untreated"][k])   # full suite
    by[b][1].append(filt_comp[k] / filt_plain[k])                # filtered

print(f'\n{"bucket":<14}{"n":>4}{"full compacted/plain":>22}{"filtered compacted/plain":>26}')
for b in ("absent", "leaf-only", "code-reading"):
    f, l = by[b]
    if f:
        print(f"{b:<14}{len(f):>4}{st.median(f):>22.3f}{st.median(l):>26.3f}")
