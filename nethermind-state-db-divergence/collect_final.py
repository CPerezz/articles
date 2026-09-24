#!/usr/bin/env python3
"""R74 + R75: the final pairs. Both stores fully settled - state-actor v2 (generated with #139 and
#141) and jochemnet with every flat column compacted to L6 - over the whole suite, sub-second tests
included. Two independent pairs share no run (A = sa-fin1/joc-fin1, B = sa-fin2/joc-fin2), and each
store is also measured against itself. Prints JSON to stdout; merged into data/report_data.json
under `final`."""
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
    root = os.path.join(R, root)
    for rj in glob.glob(os.path.join(root, "runs", "*", "result.json")):
        try:
            n = len(json.load(open(rj)).get("tests", {}))
        except Exception:
            continue
        if n > bn:
            best, bn = rj, n
    if not best:
        return {}, None
    env = (json.load(open(os.path.join(os.path.dirname(best), "config.json"))).get("instance", {})
           .get("environment") or {})
    return json.load(open(best))["tests"], env.get("DOTNET_TieredCompilation", "default")


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


NAMES = ("nm-sa-fin1", "nm-sa-fin2", "nm-joc-fin1", "nm-joc-fin2", "nm-sa-t1", "nm-joc-t1")
loaded = {k: load(k) for k in NAMES}
runs = {k: v[0] for k, v in loaded.items()}
S1, S2, J, J2, S0, J0 = (runs[k] for k in NAMES)
ids = [t for t in S1 if t in J and t in S2 and t in J2 and mg(S1[t]) and mg(S2[t]) and mg(J[t]) and mg(J2[t])]
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
    "src": "R74 + R75: the whole suite at 160M/240M on the settled stores, two independent pairs",
    "runs": {k: len(v) for k, v in runs.items()},
    "tiered_compilation": {k: v[1] for k, v in loaded.items()},
    "classes": {"long": len(LONG), "short": len(SHORT), "boundary_s": 1.0,
                "membership": "fixed from the jochemnet arm of this pair"},
    "by_class": {},
}
for name, sel in (("long", LONG), ("short", SHORT)):
    out["by_class"][name] = {
        "v1_pair": stats(S0, J0, sel), "pair_a": stats(S1, J, sel), "pair_b": stats(S2, J2, sel),
        "floor_sa": stats(S2, S1, sel), "floor_joc": stats(J2, J, sel),
    }

by = defaultdict(list)
for t in ids:
    by[cat(t)].append(t)
out["categories"] = {}
for c, ts in by.items():
    r1, r2 = stats(S1, J, ts), stats(S2, J2, ts)
    out["categories"][c] = {
        "n": len(ts), "long": sum(1 for t in ts if t in set(LONG)),
        "v1_pair": (stats(S0, J0, ts) or {}).get("median"),
        "pair_a": r1["median"], "pair_b": r2["median"], "within10": r1["within10"],
        "floor_sa": (stats(S2, S1, ts) or {}).get("median"),
    }

outl = []
for t in ids:
    a, b = mg(S1[t]) / mg(J[t]), mg(S2[t]) / mg(J2[t])
    if abs(a - 1) > 0.1 and abs(b - 1) > 0.1 and (a - 1) * (b - 1) > 0:
        outl.append({"cat": cat(t), "variant": variant(t), "pair_a": round(a, 3), "pair_b": round(b, 3),
                     "sa_s": round(secs(S1[t]) or 0, 1), "joc_s": round(secs(J[t]) or 0, 1),
                     "long": t in set(LONG)})
outl.sort(key=lambda r: -max(r["pair_a"], r["pair_b"]))
out["outliers"] = {"all": len(outl), "long": sum(1 for r in outl if r["long"]),
                   "short": sum(1 for r in outl if not r["long"]), "long_rows": [r for r in outl if r["long"]]}
buckets = defaultdict(int)
for r in outl:
    if r["long"]:
        buckets["code pool (#141 overshoot)" if "code-exec" in r["cat"] and r["cat"].split()[0] in ("DIFF_MAX", "JUMPDEST")
                else ("absent-key work" if ("absent" in r["cat"] or "nonexistent" in r["variant"]) else r["cat"])] += 1
out["outliers"]["long_buckets"] = dict(buckets)
json.dump(out, sys.stdout, indent=1, sort_keys=True)
