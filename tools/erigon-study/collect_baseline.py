#!/usr/bin/env python3
"""Erigon baseline: two independent pairs (B1, B2) of the 160M/240M subset, with each arm's replica
floor, on the population the Nethermind final pairs used.

A test's class is fixed once, at one second of measured step time on the jochemnet arm (median of
B1 and B2), so it never changes population between views. A ratio counts as a store difference only
where the between-arm gap exceeds the larger of the two arms' own run-to-run deltas for that test
(plan section 5); otherwise it is "within replica floor".

Runs on the bench host; prints JSON to stdout. Usage: collect_baseline.py [YYYYMMDD]
"""
import glob
import json
import os
import re
import sys
from collections import defaultdict
from statistics import median

R = "/bench/results/"
DAY = sys.argv[1] if len(sys.argv) > 1 else "*"


def run_of(tag):
    roots = sorted(glob.glob(os.path.join(R, f"er-{tag}-{DAY}")))
    if not roots:
        return {}, None
    best, bn = None, -1
    for p in glob.glob(os.path.join(roots[-1], "runs", "*", "result.json")):
        n = len(json.load(open(p)).get("tests", {}))
        if n > bn:
            best, bn = p, n
    if not best:
        return {}, None
    return json.load(open(best))["tests"], os.path.relpath(os.path.dirname(best), R)


def agg(e):
    return ((e.get("steps") or {}).get("test") or {}).get("aggregated") or {}


def mg(e):
    a = agg(e)
    g, t = a.get("gas_used_total"), a.get("gas_used_time_total")
    return (g / 1e6) / (t / 1e9) if g and t else None


def fcu_ms(e):
    """Erigon commits the block's state in forkchoiceUpdated, which newPayload throughput never sees."""
    times = (agg(e).get("method_stats") or {}).get("times") or {}
    v = [m.get("last") for k, m in times.items() if k.startswith("engine_forkchoiceUpdated")]
    return sum(x for x in v if x) / 1e6 if v else None


def secs(e):
    t = agg(e).get("gas_used_time_total")
    return t / 1e9 if t else None


def category(t):
    fam = t.split("::", 1)[1].split("[")[0]
    if fam == "test_account_access":
        m = re.search(r"opcode_([A-Z]+)-value_sent_\d.*account_mode_AccountMode\.(\w+?)-overhead_baseline_(\w+)", t)
        op, mode, ctl = m.group(1), m.group(2), m.group(3)
        if ctl == "True":
            return "control (no state work)"
        if mode == "NON_EXISTING_ACCOUNT":
            return "absent account"
        mode = mode.replace("EXISTING_CONTRACT_", "")
        return "%s %s" % ("account row" if op in ("BALANCE", "EXTCODEHASH") else "code-exec", mode)
    if fam == "test_ext_account_query_warm":
        return "warm query"
    if fam.startswith("test_sload_same_key"):
        return "sload same key"
    if fam.startswith("test_sload") or fam.startswith("test_sstore"):
        return "storage slot"
    if fam.startswith("test_ether_transfers"):
        return "ether transfer"
    return fam


def summary(rs):
    rs = [r for r in rs if r is not None]
    if not rs:
        return None
    return {"n": len(rs), "median": round(median(rs), 4), "within10": sum(1 for r in rs if 0.9 <= r <= 1.1),
            "min": round(min(rs), 4), "max": round(max(rs), 4)}


def ratio(A, B, t):
    return mg(A[t]) / mg(B[t]) if t in A and t in B and mg(A[t]) and mg(B[t]) else None


runs, ids_ = {}, {}
for tag in ("joc-B1", "sa-B1", "joc-B2", "sa-B2"):
    runs[tag], ids_[tag] = run_of(tag)
J1, S1, J2, S2 = runs["joc-B1"], runs["sa-B1"], runs["joc-B2"], runs["sa-B2"]
complete = all(len(runs[k]) >= 260 for k in ("joc-B1", "sa-B1", "joc-B2", "sa-B2"))

ids = sorted(t for t in J1 if t in S1 and mg(J1[t]) and mg(S1[t]))
tests, rows = {}, defaultdict(lambda: defaultdict(list))
for t in ids:
    js = [secs(J1[t])] + ([secs(J2[t])] if t in J2 and secs(J2[t]) else [])
    cls = "ge1s" if median(js) >= 1.0 else "lt1s"
    a, b = ratio(S1, J1, t), ratio(S2, J2, t)
    fj, fs = ratio(J2, J1, t), ratio(S2, S1, t)
    gas_match = (agg(J1[t]).get("gas_used_total") == agg(S1[t]).get("gas_used_total"))
    reportable = None
    if a is not None and fj is not None and fs is not None:
        reportable = abs(a - 1) > max(abs(fj - 1), abs(fs - 1))
    rec = {"cls": cls, "cat": category(t), "joc_secs": round(median(js), 3), "a": a, "b": b,
           "floor_joc": fj, "floor_sa": fs, "gas_match": gas_match, "reportable": reportable,
           "joc_mgas": mg(J1[t]), "sa_mgas": mg(S1[t]),
           "joc_fcu_ms": fcu_ms(J1[t]), "sa_fcu_ms": fcu_ms(S1[t])}
    rec = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in rec.items()}
    tests[t] = rec
    for k in ("a", "b", "floor_joc", "floor_sa"):
        rows[(rec["cls"], rec["cat"])][k].append(rec[k])
        rows[(rec["cls"], "__all__")][k].append(rec[k])
    rows[(rec["cls"], rec["cat"])]["_rep"].append(reportable)
    rows[(rec["cls"], "__all__")]["_rep"].append(reportable)

out = {
    "src": "collect_baseline.py: Erigon B1/B2 pairs, 160M/240M; class at 1 s on the jochemnet arm",
    "runs": ids_,
    "complete": complete,
    "n": len(ids),
    "gas_mismatches": sum(1 for r in tests.values() if not r["gas_match"]),
    "tests": tests,
    "rows": [{"cls": cls, "cat": c, "reportable": sum(1 for x in d["_rep"] if x),
              **{k: summary(v) for k, v in d.items() if k != "_rep"}}
             for (cls, c), d in sorted(rows.items(), key=lambda kv: (kv[0][0] != "ge1s", kv[0][1] != "__all__", kv[0][1]))],
}
json.dump(out, sys.stdout, indent=1, sort_keys=True)
