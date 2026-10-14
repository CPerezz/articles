#!/usr/bin/env python3
"""Reth baseline: two independent pairs (J1,S1), (J2,S2) and each store against itself (J2/J1, S2/S1),
over the tests both arms ran, split at one second of measured time with the class fixed from J1.
Prints JSON to stdout."""
import glob
import json
import os
import re
import sys
from collections import defaultdict
from statistics import median

R = "/root/bench/reth/results/"
P = sys.argv[1] if len(sys.argv) > 1 else ""  # run-id prefix: "d" reduces dj1 ds1 dj2 ds2


def load(rid):
    best, bn = None, -1
    for rj in glob.glob(os.path.join(R, rid, "runs", "*", "result.json")):
        n = len(json.load(open(rj)).get("tests", {}))
        if n > bn:
            best, bn = rj, n
    return json.load(open(best))["tests"] if best else {}


def agg(e):
    return ((e.get("steps") or {}).get("test") or {}).get("aggregated") or {}


def mg(e):
    a = agg(e)
    g, t = a.get("gas_used_total"), a.get("gas_used_time_total")
    return (g / 1e6) / (t / 1e9) if g and t and not a.get("fail") else None


def secs(e):
    t = agg(e).get("gas_used_time_total")
    return t / 1e9 if t else None


def key(t):
    # the two fixture sets name the same test differently in their prefix; match on the pytest id
    m = re.search(r"(test_[a-z_]+\[.*\])", t)
    return m.group(1).replace("blockchain_test_engine", "BTE").replace("blockchain_test_stateful_engine", "BTE") if m else t


def category(t):
    fam = re.search(r"::(test_[a-z_]+)\[", t)
    fam = fam.group(1) if fam else t
    mode = re.search(r"account_mode_AccountMode\.([A-Z_]+)", t)
    op = re.search(r"opcode_([A-Z0-9]+)", t)
    if fam == "test_account_access" and mode:
        return "%s %s" % (op.group(1) if op else "?", mode.group(1))
    return fam.replace("test_", "")


runs = {r: {key(t): (t, e) for t, e in load(P + r).items()} for r in ("j1", "s1", "j2", "s2")}
ids = sorted(k for k in runs["j1"] if all(k in runs[r] for r in runs) and all(mg(runs[r][k][1]) for r in runs))
cls = {k: "ge1s" if secs(runs["j1"][k][1]) >= 1.0 else "lt1s" for k in ids}


def ratio(a, b, k):
    return mg(runs[a][k][1]) / mg(runs[b][k][1])


def stats(xs):
    return {"n": len(xs), "median": round(median(xs), 4), "within10": sum(1 for x in xs if abs(x - 1) <= 0.10),
            "min": round(min(xs), 4), "max": round(max(xs), 4)} if xs else None


out = {"runs": {r: len(v) for r, v in runs.items()}, "common": len(ids),
       "classes": {c: sum(1 for k in ids if cls[k] == c) for c in ("ge1s", "lt1s")}, "by_class": {}, "categories": {}}
for c in ("ge1s", "lt1s"):
    sel = [k for k in ids if cls[k] == c]
    out["by_class"][c] = {"pair_a": stats([ratio("s1", "j1", k) for k in sel]),
                          "pair_b": stats([ratio("s2", "j2", k) for k in sel]),
                          "floor_sa": stats([ratio("s2", "s1", k) for k in sel]),
                          "floor_joc": stats([ratio("j2", "j1", k) for k in sel])}
by = defaultdict(list)
for k in ids:
    by[(cls[k], category(runs["j1"][k][0]))].append(k)
for (c, cat), ks in sorted(by.items()):
    out["categories"]["%s | %s" % (c, cat)] = {
        "n": len(ks), "pair_a": round(median([ratio("s1", "j1", k) for k in ks]), 4),
        "pair_b": round(median([ratio("s2", "j2", k) for k in ks]), 4),
        "j1_secs": round(median([secs(runs["j1"][k][1]) for k in ks]), 3),
        "s1_secs": round(median([secs(runs["s1"][k][1]) for k in ks]), 3)}
json.dump(out, sys.stdout, indent=1, sort_keys=True)
