#!/usr/bin/env python3
"""Collect the bottommost-compaction findings (rounds 46-56) into one JSON block.

The throughput cells are recomputed from the run results rather than parsed out of a verdict
file, the same way the rest of the page's numbers are built. The I/O figures come from the probe
verdicts because their source is bpftrace and /proc, which leave no result.json behind.
"""
import glob
import json
import os
import re
import sys
from statistics import median

ND = "/bench/logs/night"
R = "/bench/results/"


def txt(p):
    try:
        return open(os.path.join(ND, p)).read()
    except OSError:
        return ""


def num(pattern, s, default=None, group=1):
    m = re.search(pattern, s)
    return float(m.group(group)) if m else default


# ---------------------------------------------------------------- throughput cells
def load(root):
    best, bn = None, -1
    for rj in glob.glob(os.path.join(root, "runs", "*", "result.json")):
        try:
            n = len(json.load(open(rj)).get("tests", {}))
        except Exception:
            continue
        if n > bn:
            best, bn = rj, n
    return json.load(open(best))["tests"] if best else {}


def agg(e):
    return ((e.get("steps") or {}).get("test") or {}).get("aggregated") or {}


def mgas(e):
    a = agg(e)
    g, t = a.get("gas_used_total"), a.get("gas_used_time_total")
    return (g / 1e6) / (t / 1e9) if g and t else None


def cell(t):
    if "overhead_baseline_True" in t:
        return "CONTROL"
    if "test_ext_account_query_warm" in t:
        return "warm query"
    if "ether_transfers" in t:
        return "ether transfer"
    if "sload_same_key" in t:
        return "sload_same_key"
    if "sload" in t or "sstore" in t:
        return "storage slot"
    m = re.search(r"opcode_([A-Z]+)-value_sent_[01].*?"
                  r"(EXISTING_EOA|MINIMAL|SAME_MAX|JUMPDEST|DIFF_MAX|NON_EXISTING_ACCOUNT)", t)
    if not m:
        return "other"
    op, mode = m.groups()
    loads_code = op in ("CALL", "CALLCODE", "DELEGATECALL", "STATICCALL",
                        "EXTCODESIZE", "EXTCODECOPY")
    return "%s %s" % (mode, "code-exec" if loads_code else "BAL/HASH")


runs = {k: load(R + v) for k, v in (("j1", "nm-joc-c1"), ("s1", "nm-sa-c1"),
                                    ("j2", "nm-joc-c2"), ("s2", "nm-sa-c2"),
                                    ("jt", "nm-joc-t1"), ("st", "nm-sa-t1"))}
ids = [t for t in set.intersection(*(set(v) for v in runs.values()))
       if all(mgas(runs[k][t]) for k in runs)]
by = {}
for t in ids:
    by.setdefault(cell(t), []).append(t)
cells = {}
for c, ts in by.items():
    cells[c] = {
        "n": len(ts),
        "r1": median(mgas(runs["s1"][t]) / mgas(runs["j1"][t]) for t in ts),
        "r2": median(mgas(runs["s2"][t]) / mgas(runs["j2"][t]) for t in ts),
        "settled": median(mgas(runs["st"][t]) / mgas(runs["jt"][t]) for t in ts),
    }

# ---------------------------------------------------------------- per-CF attribution
def attribution(fname):
    """Parse a verdict table into {arm: {cf: {dm, sm, marg}}} plus the window counts."""
    out, arm = {}, None
    for line in txt(fname).splitlines():
        m = re.match(r"=== (joc|sa): MB read inside the measured step \((\d+) DIFF_MAX", line)
        if m:
            arm = m.group(1)
            out[arm] = {"_windows": int(m.group(2)), "cf": {}}
            continue
        m = re.match(r"\s*(\S+)\s+(-?\d+\.\d)\s+(-?\d+\.\d)\s+(-?\d+\.\d)\s*$", line)
        if m and arm:
            out[arm]["cf"][m.group(1)] = {"dm": float(m.group(2)), "sm": float(m.group(3)),
                                          "marg": float(m.group(4))}
        m = re.match(r"\s+total marginal (\d+\.\d) MB", line)
        if m and arm:
            out[arm]["total_marg"] = float(m.group(1))
    return out


# ---------------------------------------------------------------- probe verdicts
r50, r51, r52, r53, r46 = (txt(f) for f in ("r50-verdict.txt", "r51-verdict.txt",
                                            "r52-verdict.txt", "r53-verdict.txt",
                                            "r46-verdict.txt"))
r53log = txt("r53.log")

idle = {"window_s": 60}
for arm, key in (("sa", "sa_mb"), ("joc", "joc_mb")):
    m = re.search(r"=== %s: client pid \d+.*?client block-layer reads over 60 s: (\d+) MB"
                  % arm, r50, re.S)
    if m:
        idle[key] = int(m.group(1))
idle["sa_settled_mb"] = int(num(r"idle, zero queries: (\d+) MB", r53, 0))

boot = {"sa": {}, "joc": {}, "sa_settled": {}}
for arm in ("sa", "joc"):
    block = re.search(r"=== %s ===(.*?)(?====|\Z)" % arm, r52, re.S)
    if block:
        m = re.search(r"(\d+)\s+(\w+) (\w+)\s*$", block.group(1), re.M)
        if m:
            boot[arm] = {"jobs": int(m.group(1)), "cf": m.group(2), "reason": m.group(3)}
boot["sa_settled"] = {"jobs": int(num(r"compaction jobs this boot: (\d+)", r53, 0))}

rpc = {"calls": 2000, "joc": {}, "sa": {}}
for arm in ("joc", "sa"):
    block = re.search(r"=== %s: MB read while serving plain eth_getBalance calls ===(.*?)"
                      r"(?====|\Z)" % arm, r46, re.S)
    if block:
        b = block.group(1)
        rpc[arm] = {"account_mb": num(r"flat/Account\s+(\d+\.\d)", b, 0.0),
                    "trie_mb": num(r"flat/StateNodes\s+(\d+\.\d)", b, 0.0),
                    "trie_share_pct": num(r"trie-node share (\d+)%", b, 0.0)}

settle = {}
for cf in ("StateNodes", "StateTopNodes", "StorageNodes"):
    m = re.search(r"%s\s+before: map\[6:(\d+)\]\s+([\d.]+) GB.*?"
                  r"%s\s+after : map\[6:(\d+)\]\s+([\d.]+) GB\s+\(([\d.]+) s\)" % (cf, cf),
                  r53log, re.S)
    if m:
        settle[cf] = {"files_before": int(m.group(1)), "gb_before": float(m.group(2)),
                      "files_after": int(m.group(3)), "gb_after": float(m.group(4)),
                      "secs": float(m.group(5))}

threads = {"window_s": 45,
           "rocksdb_low_mb": num(r"rocksdb:low\s+(\d+\.\d) MB", r51, 0.0)}

out = {
    "idle": idle,
    "boot": boot,
    "rpc": rpc,
    "settle": settle,
    "threads": threads,
    "cells": cells,
    "attribution": {
        "code": {"before": attribution("r44b-verdict-presettle.txt"),
                 "after": attribution("r44b-verdict.txt")},
        "noncode": {"before": attribution("r45-verdict-presettle.txt"),
                    "after": attribution("r45-verdict.txt")},
    },
    "pr": 139,
}
wide = attribution("r56-verdict.txt")
if wide:
    out["attribution"]["code_wide"] = wide

json.dump(out, sys.stdout, indent=1, sort_keys=True)
