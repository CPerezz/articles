#!/usr/bin/env python3
"""Erigon baseline: two independent pairs (B1, B2) of the 160M/240M subset, with each arm's replica
floor, on the population the Nethermind final pairs used.

A test's class is fixed once, at one second of measured step time on the jochemnet arm (median of
B1 and B2), so it never changes population between views. A ratio counts as a store difference only
where the between-arm gap exceeds the larger of the two arms' own run-to-run deltas for that test;
otherwise it is "within replica floor".

Runs on the bench host and prints JSON to stdout; the page reads it as data/report_data.json's
"baseline". Usage: collect_erigon.py [YYYYMMDD] [series]    series B (buffered loops, default) or D
(the same suites with the scratch loops on direct I/O).
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
SERIES = sys.argv[2] if len(sys.argv) > 2 else "B"
TAGS = [f"{arm}-{SERIES}{n}" for n in (1, 2) for arm in ("joc", "sa")]


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


def np_read_mb(e):
    """Bytes the client read from disk inside newPayload, from benchmarkoor's per-method cgroup counters."""
    r = ((agg(e).get("method_stats") or {}).get("resources") or {})
    v = [m["disk_read_bytes"]["last"] for k, m in r.items()
         if k.startswith("engine_newPayload") and "disk_read_bytes" in m]
    return sum(v) / 1e6 if v else None


def total_s(e):
    """newPayload plus forkchoiceUpdated: the whole block, execution and commit."""
    s, f = secs(e), fcu_ms(e)
    return s + f / 1e3 if s and f is not None else None


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


def summary(rs, ratios=True):
    rs = [r for r in rs if r is not None]
    if not rs:
        return None
    s = {"n": len(rs), "median": round(median(rs), 4), "min": round(min(rs), 4), "max": round(max(rs), 4)}
    if ratios:
        s["within10"] = sum(1 for r in rs if 0.9 <= r <= 1.1)
    return s


def ratio(A, B, t, f=None):
    """Throughput ratio A/B. Both arms run the same gas, so it is B's time over A's."""
    f = f or secs
    ta, tb = (f(A[t]), f(B[t])) if t in A and t in B else (None, None)
    return tb / ta if ta and tb else None


runs, ids_ = {}, {}
for tag in TAGS:
    runs[tag], ids_[tag] = run_of(tag)
J1, S1, J2, S2 = (runs[f"{arm}-{SERIES}{n}"] for n, arm in ((1, "joc"), (1, "sa"), (2, "joc"), (2, "sa")))
complete = all(len(runs[k]) >= 260 for k in TAGS)

ids = sorted(t for t in J1 if t in S1 and mg(J1[t]) and mg(S1[t]))
tests, rows = {}, defaultdict(lambda: defaultdict(list))
for t in ids:
    js = [secs(J1[t])] + ([secs(J2[t])] if t in J2 and secs(J2[t]) else [])
    cls = "ge1s" if median(js) >= 1.0 else "lt1s"
    a, b = ratio(S1, J1, t), ratio(S2, J2, t)
    fj, fs = ratio(J2, J1, t), ratio(S2, S1, t)
    at, bt = ratio(S1, J1, t, total_s), ratio(S2, J2, t, total_s)
    fjt, fst = ratio(J2, J1, t, total_s), ratio(S2, S1, t, total_s)
    gas_match = (agg(J1[t]).get("gas_used_total") == agg(S1[t]).get("gas_used_total"))

    def beyond_floor(r, f1, f2):
        return abs(r - 1) > max(abs(f1 - 1), abs(f2 - 1)) if None not in (r, f1, f2) else None

    reportable, reportable_total = beyond_floor(a, fj, fs), beyond_floor(at, fjt, fst)
    rec = {"cls": cls, "cat": category(t), "joc_secs": round(median(js), 3), "a": a, "b": b,
           "floor_joc": fj, "floor_sa": fs, "gas_match": gas_match, "reportable": reportable,
           "a_total": at, "b_total": bt, "floor_joc_total": fjt, "floor_sa_total": fst,
           "reportable_total": reportable_total,
           "joc_mgas": mg(J1[t]), "sa_mgas": mg(S1[t]),
           "joc_fcu_ms": fcu_ms(J1[t]), "sa_fcu_ms": fcu_ms(S1[t]),
           "joc_np_read_mb": np_read_mb(J1[t]), "sa_np_read_mb": np_read_mb(S1[t])}
    rec = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in rec.items()}
    tests[t] = rec
    for key in ((rec["cls"], rec["cat"]), (rec["cls"], "__all__")):
        for k in ("a", "b", "floor_joc", "floor_sa", "a_total", "b_total", "floor_joc_total",
                  "floor_sa_total", "joc_fcu_ms", "sa_fcu_ms"):
            rows[key][k].append(rec[k])
        rows[key]["_rep"].append(reportable)
        rows[key]["_rep_total"].append(reportable_total)

out = {
    "src": f"collect_erigon.py: Erigon {SERIES}1/{SERIES}2 pairs, 160M/240M; class at 1 s on the jochemnet arm",
    "runs": ids_,
    "complete": complete,
    "n": len(ids),
    "gas_mismatches": sum(1 for r in tests.values() if not r["gas_match"]),
    "tests": tests,
    "rows": [{"cls": cls, "cat": c, "reportable": sum(1 for x in d["_rep"] if x),
              "reportable_total": sum(1 for x in d["_rep_total"] if x),
              **{k: summary(v, ratios=not k.endswith("_ms")) for k, v in d.items() if not k.startswith("_")}}
             for (cls, c), d in sorted(rows.items(), key=lambda kv: (kv[0][0] != "ge1s", kv[0][1] != "__all__", kv[0][1]))],
}
json.dump(out, sys.stdout, indent=1, sort_keys=True)
