#!/usr/bin/env python3
"""The waterfall: the same 266 test ids through every stage of the study, by family and duration
class. Membership in the two classes is fixed once, from the final jochemnet run, so no test
changes population between stages.

Stages and what changed going into each:
  baseline   the published pair: jochemnet with its pre-run promoted, state-actor v1
  placement  jochemnet compacted (Finding 1); state-actor unchanged
  warmup     DOTNET_TieredCompilation=0 on both arms (Finding 2) and the generated store's trie
             families settled (Finding 3, which moved nothing)
  codepool   state-actor regenerated with the mainnet-sliced code pool (Finding 4); a long-class
             run, so the few short tests it happens to cover are left out
  final      jochemnet's two storage columns compacted (Finding 5); whole suite, one session

Transfers and storage writes are reported at baseline and final only: their intermediate runs
were taken on a snapshot whose top-of-trie column this study's own tooling had repacked.
Prints JSON to stdout; merged into data/report_data.json under `waterfall`."""
import glob
import json
import os
import re
import sys
from collections import defaultdict
from statistics import median

R = "/bench/results/"
STAGES = [
    ("baseline", "nm-state-actor", "nm-jochemnet"),
    ("placement", "nm-state-actor", "nm-joc-full"),
    ("warmup", "nm-sa-t1", "nm-joc-t1"),
    ("codepool", "nm-sa-v2r1", "nm-joc-v2r1"),
    ("final", "nm-sa-fin1", "nm-joc-fin1"),
]
FAMILIES = ["account reads", "code, reused or small", "code, distinct large", "storage",
            "ether transfers", "absent accounts", "no state work"]
# families whose intermediate points were taken on a store our tooling had altered
WRITE_FAMILIES = {"ether transfers", "storage"}


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


def family(t):
    fam = t.split("::", 1)[1].split("[")[0]
    if fam == "test_account_access":
        m = re.search(r"opcode_([A-Z]+)-value_sent_\d.*account_mode_AccountMode\.(\w+?)-overhead_baseline_(\w+)", t)
        op, mode, ctl = m.group(1), m.group(2), m.group(3)
        if ctl == "True":
            return "no state work"
        if mode == "NON_EXISTING_ACCOUNT":
            return "absent accounts"
        if op in ("BALANCE", "EXTCODEHASH"):
            return "account reads"
        if mode in ("EXISTING_CONTRACT_DIFF_MAX", "EXISTING_CONTRACT_JUMPDEST"):
            return "code, distinct large"
        return "code, reused or small"
    if fam == "test_ext_account_query_warm":
        return "no state work"
    if fam.startswith("test_sload") or fam.startswith("test_sstore"):
        return "storage"
    if fam.startswith("test_ether_transfers"):
        return "ether transfers"
    return "other"


ids = [l.strip() for l in open("/bench/logs/r74/suite_ids.txt") if l.strip()]
runs = {name: (load(R + sa), load(R + joc)) for name, sa, joc in STAGES}
FJ = runs["final"][1]
LONG = {t for t in ids if (secs(FJ.get(t, {})) or 0) >= 1.0}
cls = {t: ("long" if t in LONG else "short") for t in ids}
fam = {t: family(t) for t in ids}

out = {"src": __doc__.split("\n\n")[0].strip(), "stages": [s[0] for s in STAGES],
       "stage_runs": {s[0]: {"sa": s[1], "joc": s[2]} for s in STAGES},
       "families": FAMILIES, "write_families": sorted(WRITE_FAMILIES),
       "membership": {c: {f: sum(1 for t in ids if cls[t] == c and fam[t] == f) for f in FAMILIES}
                      for c in ("long", "short")},
       "cells": {}, "coverage": {}}

for stage, (S, J) in runs.items():
    have = [t for t in ids if t in S and t in J and mg(S[t]) and mg(J[t])]
    out["coverage"][stage] = {"long": sum(1 for t in have if cls[t] == "long"),
                              "short": sum(1 for t in have if cls[t] == "short")}
    for c in ("long", "short"):
        for f in FAMILIES:
            sel = [t for t in have if cls[t] == c and fam[t] == f]
            if not sel:
                continue
            if f in WRITE_FAMILIES and stage not in ("baseline", "final"):
                continue
            if stage == "codepool" and c == "short":
                continue
            rs = [mg(S[t]) / mg(J[t]) for t in sel]
            out["cells"].setdefault(c, {}).setdefault(f, {})[stage] = {
                "n": len(rs), "median": round(median(rs), 4),
                "within10": sum(1 for r in rs if 0.9 <= r <= 1.1),
                "min": round(min(rs), 4), "max": round(max(rs), 4)}
    for c in ("long", "short"):
        sel = [t for t in have if cls[t] == c]
        if sel and not (stage == "codepool" and c == "short"):
            rs = [mg(S[t]) / mg(J[t]) for t in sel]
            out["cells"].setdefault(c, {}).setdefault("_all", {})[stage] = {
                "n": len(rs), "median": round(median(rs), 4),
                "within10": sum(1 for r in rs if 0.9 <= r <= 1.1)}

# the replica floor on the final pair, per class and family, for the overview charts
S1, S2 = load(R + "nm-sa-fin1"), load(R + "nm-sa-fin2")
out["floor"] = {}
for c in ("long", "short"):
    for f in FAMILIES + ["_all"]:
        sel = [t for t in ids if cls[t] == c and (f == "_all" or fam[t] == f)
               and t in S1 and t in S2 and mg(S1[t]) and mg(S2[t])]
        if sel:
            rs = [mg(S2[t]) / mg(S1[t]) for t in sel]
            out["floor"].setdefault(c, {})[f] = {"n": len(rs), "within10": sum(1 for r in rs if 0.9 <= r <= 1.1),
                                                 "median": round(median(rs), 4)}
json.dump(out, sys.stdout, indent=1, sort_keys=True)
