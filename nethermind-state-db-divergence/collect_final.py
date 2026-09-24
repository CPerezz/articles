#!/usr/bin/env python3
"""R74: the final pair. Both stores fully settled - state-actor v2 (generated with #139 and #141)
and jochemnet with every flat column compacted to L6 - measured in one session over the whole
suite, sub-second tests included, state-actor twice so the replica floor is measured beside the
comparison. Prints JSON to stdout; merged into data/report_data.json under `final`."""
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


def mg(e):
    a = agg(e)
    g, t = a.get("gas_used_total"), a.get("gas_used_time_total")
    return (g / 1e6) / (t / 1e9) if g and t else None


def secs(e):
    a = agg(e)
    t = a.get("gas_used_time_total")
    return t / 1e9 if t else None


def cat(t):
    fam = t.split("::", 1)[1].split("[")[0]
    if fam == "test_account_access":
        m = re.search(r"opcode_([A-Z]+)-value_sent_\d.*account_mode_AccountMode\.(\w+?)-overhead_baseline_(\w+)", t)
        if not m:
            return fam
        op, mode, ctl = m.group(1), m.group(2), m.group(3)
        if ctl == "True":
            return "control (no state work)"
        mode = mode.replace("EXISTING_CONTRACT_", "")
        kind = "BAL/HASH" if op in ("BALANCE", "EXTCODEHASH") else "code-exec"
        return "absent account %s" % kind if mode == "NON_EXISTING_ACCOUNT" else "%s %s" % (mode, kind)
    if fam == "test_ext_account_query_warm":
        return "warm query"
    if fam.startswith("test_sload_same_key"):
        return "sload same key"
    if fam.startswith("test_sload") or fam.startswith("test_sstore"):
        return "storage slot"
    if fam.startswith("test_ether_transfers"):
        return "ether transfer"
    return fam


def variant(t):
    v = t.split("::", 1)[1]
    g = re.search(r"gas-value_(\d+M)", v)
    m = (re.search(r"opcode_(\w+?)-value_sent_(\d)", v) or re.search(r"case_id_(\w+?)-benchmark", v) or
         re.search(r"existing_slots_(\w+)-write_new_value_(\w+)", v) or re.search(r"(storage_keys_\w+?)-", v))
    return "%s %s" % ("-".join(m.groups()) if m else v[:28], g.group(1) if g else "")


runs = {k: load(R + k) for k in ("nm-sa-fin1", "nm-sa-fin2", "nm-joc-fin1", "nm-sa-t1", "nm-joc-t1")}
S1, S2, J, S0, J0 = (runs[k] for k in ("nm-sa-fin1", "nm-sa-fin2", "nm-joc-fin1", "nm-sa-t1", "nm-joc-t1"))
ids = [t for t in S1 if t in J and t in S2 and mg(S1[t]) and mg(S2[t]) and mg(J[t])]
LONG = [t for t in ids if (secs(J[t]) or 0) >= 1.0]
SHORT = [t for t in ids if t not in set(LONG)]


def stats(A, B, sel):
    rs = [mg(A[t]) / mg(B[t]) for t in sel if t in A and t in B and mg(A[t]) and mg(B[t])]
    if not rs:
        return None
    return {"n": len(rs), "median": round(median(rs), 3),
            "within10": sum(1 for r in rs if 0.9 <= r <= 1.1),
            "min": round(min(rs), 3), "max": round(max(rs), 3)}


out = {
    "src": "R74: the whole suite at 160M/240M on the settled pair, one session, state-actor twice",
    "runs": {k: len(v) for k, v in runs.items()},
    "classes": {"long": len(LONG), "short": len(SHORT), "boundary_s": 1.0,
                "membership": "fixed from the jochemnet arm of this pair"},
    "by_class": {},
}
for name, sel in (("long", LONG), ("short", SHORT)):
    out["by_class"][name] = {
        "v1_pair": stats(S0, J0, sel), "run1": stats(S1, J, sel), "run2": stats(S2, J, sel),
        "replica": stats(S2, S1, sel),
    }

by = defaultdict(list)
for t in ids:
    by[cat(t)].append(t)
out["categories"] = {}
for c, ts in by.items():
    r1, r2 = stats(S1, J, ts), stats(S2, J, ts)
    out["categories"][c] = {
        "n": len(ts), "long": sum(1 for t in ts if t in set(LONG)),
        "v1_pair": (stats(S0, J0, ts) or {}).get("median"),
        "run1": r1["median"], "run2": r2["median"], "within10": r1["within10"],
        "replica": (stats(S2, S1, ts) or {}).get("median"),
    }

outl = []
for t in ids:
    a, b = mg(S1[t]) / mg(J[t]), mg(S2[t]) / mg(J[t])
    if abs(a - 1) > 0.1 and abs(b - 1) > 0.1 and (a - 1) * (b - 1) > 0:
        outl.append({"cat": cat(t), "variant": variant(t), "run1": round(a, 3), "run2": round(b, 3),
                     "sa_s": round(secs(S1[t]) or 0, 1), "joc_s": round(secs(J[t]) or 0, 1),
                     "long": t in set(LONG)})
outl.sort(key=lambda r: -max(r["run1"], r["run2"]))
out["outliers"] = {"all": len(outl), "long": sum(1 for r in outl if r["long"]),
                   "short": sum(1 for r in outl if not r["long"]), "long_rows": [r for r in outl if r["long"]]}
buckets = defaultdict(int)
for r in outl:
    if r["long"]:
        buckets["code pool (#141 overshoot)" if "code-exec" in r["cat"] and r["cat"].split()[0] in ("DIFF_MAX", "JUMPDEST")
                else ("absent-key work" if ("absent" in r["cat"] or "nonexistent" in r["variant"]) else r["cat"])] += 1
out["outliers"]["long_buckets"] = dict(buckets)
json.dump(out, sys.stdout, indent=1, sort_keys=True)
