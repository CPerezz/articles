#!/usr/bin/env python3
"""Per-test reproducibility: the same store, the same config, measured twice.

Every per-test claim in the article assumed a test's throughput is repeatable. It is, for long
tests, and it is not for short ones. This is the control that says which is which, so captions
can state the floor instead of implying the dispersion is a store property.
"""
import glob
import json
import os
import re
import sys
from collections import defaultdict
from statistics import median

R = "/bench/results/"


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


def secs(e):
    return (agg(e).get("gas_used_time_total") or 0) / 1e9


def category(t):
    if "overhead_baseline_True" in t:
        return "CONTROL"
    if "test_ext_account_query_warm" in t:
        return "warm query"
    if "ether_transfers" in t:
        return "ether transfer"
    if "sload" in t or "sstore" in t:
        return "storage slot"
    if re.search(r"EXISTING_EOA", t):
        return "existing EOA"
    if re.search(r"NON_EXISTING_ACCOUNT", t):
        return "non-existing"
    if re.search(r"EXISTING_CONTRACT", t):
        return "existing contract"
    return "other"


def bucket(s):
    return "lt0.2s" if s < 0.2 else "0.2to1s" if s < 1 else "1to5s" if s < 5 else "ge5s"


def summarise(pairs):
    rs = [r for r, _ in pairs]
    if not rs:
        return None
    return {"n": len(rs), "within10": sum(1 for r in rs if 0.9 <= r <= 1.1),
            "median": round(median(rs), 4), "min": round(min(rs), 3), "max": round(max(rs), 3)}


A, B = load(R + "nm-joc-r1"), load(R + "nm-joc-r2")
per, buck, allp = defaultdict(list), defaultdict(list), []
for t in set(A) & set(B):
    x, y = mgas(A[t]), mgas(B[t])
    if not x or not y:
        continue
    item = (y / x, secs(A[t]))
    allp.append(item)
    per[category(t)].append(item)
    buck[bucket(secs(A[t]))].append(item)

# Cross-store agreement in the same duration buckets, for the honest side-by-side.
JF, SA = load(R + "nm-joc-full"), load(R + "nm-state-actor")
xbuck = defaultdict(list)
for t in set(JF) & set(SA):
    x, y = mgas(JF[t]), mgas(SA[t])
    if x and y:
        xbuck[bucket(secs(JF[t]))].append((y / x, secs(JF[t])))

json.dump({"replica": {"all": summarise(allp),
                       "by_category": {k: summarise(v) for k, v in sorted(per.items())},
                       "by_duration": {k: summarise(v) for k, v in buck.items()}},
           "cross_by_duration": {k: summarise(v) for k, v in xbuck.items()}},
          sys.stdout, indent=1, sort_keys=True)
