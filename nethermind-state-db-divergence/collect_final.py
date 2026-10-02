#!/usr/bin/env python3
"""The before and after views of the page: one population, one class membership, three pairs.

Population: the 266 tests the final pair ran (160M and 240M gas). Before is the untreated published
pair, pinned by run id. After is two independent pairs of the fully settled stores, R74 + R75, each
state-actor run divided by its own jochemnet run. Every test is classed once, at one second of
measured step time on the jochemnet arm of the final pair, so no test changes population between
the two views. Runs on the bench host; prints JSON to stdout, merged under `final`.
"""
import json
import os
import re
import sys
from collections import defaultdict
from statistics import median

R = "/bench/results/"
BASELINE = {"sa": ("nm-state-actor", "1789207753_887c4915_nm-sa"),
            "joc": ("nm-jochemnet", "1789101020_23e0ca97_nm-jochemnet")}
FINAL = {"sa1": "nm-sa-fin1", "joc1": "nm-joc-fin1", "sa2": "nm-sa-fin2", "joc2": "nm-joc-fin2"}


def pinned(root, run):
    return json.load(open(os.path.join(R, root, "runs", run, "result.json")))["tests"]


def largest(root):
    best, bn = None, -1
    d = os.path.join(R, root, "runs")
    for run in os.listdir(d):
        p = os.path.join(d, run, "result.json")
        if not os.path.exists(p):
            continue
        n = len(json.load(open(p)).get("tests", {}))
        if n > bn:
            best, bn = p, n
    return json.load(open(best))["tests"], os.path.basename(os.path.dirname(best))


def agg(e):
    return ((e.get("steps") or {}).get("test") or {}).get("aggregated") or {}


def mg(e):
    a = agg(e)
    g, t = a.get("gas_used_total"), a.get("gas_used_time_total")
    return (g / 1e6) / (t / 1e9) if g and t else None


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


def tiered(root, run):
    """The finding-2 lever as the run recorded it; absent means the .NET default (tiered on)."""
    cfg = json.load(open(os.path.join(R, root, "runs", run, "config.json")))
    return (cfg.get("instance", {}).get("environment") or {}).get("DOTNET_TieredCompilation", "default")


SB, JB = (pinned(*BASELINE[k]) for k in ("sa", "joc"))
runs, run_ids = {}, {}
for k, root in FINAL.items():
    if os.path.isdir(os.path.join(R, root)):
        runs[k], run_ids[k] = largest(root)
S1, J1, S2 = runs["sa1"], runs["joc1"], runs["sa2"]
J2 = runs.get("joc2", {})
have_joc2 = len(J2) >= 260

ids = sorted(t for t in J1 if t in S1 and t in S2 and t in SB and t in JB and mg(J1[t]))
tests, rows = {}, defaultdict(lambda: defaultdict(list))
for t in ids:
    js = [secs(J1[t])] + ([secs(J2[t])] if have_joc2 and t in J2 and secs(J2[t]) else [])
    cls = "ge1s" if median(js) >= 1.0 else "lt1s"
    c = category(t)
    rec = {"cls": cls, "cat": c, "joc_secs": round(median(js), 3),
           "base": ratio(SB, JB, t), "a": ratio(S1, J1, t),
           "b": ratio(S2, J2, t) if have_joc2 else None,
           "floor_sa": ratio(S2, S1, t), "floor_joc": ratio(J2, J1, t) if have_joc2 else None}
    rec = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in rec.items()}
    tests[t] = rec
    for k in ("base", "a", "b", "floor_sa", "floor_joc"):
        rows[(cls, c)][k].append(rec[k])
        rows[(cls, "__all__")][k].append(rec[k])

out = {
    "src": "collect_final.py: untreated pair pinned by run id; final pairs R74 (sa-fin1/joc-fin1) and "
           "R75 (sa-fin2/joc-fin2); class at 1 s of measured step time on the final jochemnet arm",
    "runs": {"baseline": {k: v[1] for k, v in BASELINE.items()}, "final": run_ids},
    "tiered_compilation": {**{k: tiered(*v) for k, v in BASELINE.items()},
                           **{k: tiered(FINAL[k], run_ids[k]) for k in run_ids}},
    "complete": have_joc2,
    "n": len(ids),
    "tests": tests,
    "rows": [{"cls": cls, "cat": c, **{k: summary(v) for k, v in d.items()}}
             for (cls, c), d in sorted(rows.items(), key=lambda kv: (kv[0][0] != "ge1s", kv[0][1] != "__all__", kv[0][1]))],
}
json.dump(out, sys.stdout, indent=1, sort_keys=True)
