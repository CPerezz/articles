#!/usr/bin/env python3
"""Split every test by how long it runs, and report the two classes separately.

A test that finishes in 0.12 s and a test that runs for 10 s cannot carry the same claim: the
short one is mostly process warm-up, and the same store measured twice disagrees with itself on
it. The page had been reporting both on one list, which is what forced its hedging. This
collector recomputes per test - class medians cannot be derived from the per-bucket medians the
noise collector already emits - and produces the class split, the per-category membership, the
family x mode taxonomy inside the long class, and the same summary at three boundaries so the
page can show the conclusion does not depend on where the line is drawn.

Runs on the benchmark host; writes one JSON block to stdout.
"""
import glob
import json
import os
import re
import sys
from collections import defaultdict
from statistics import median

R = "/bench/results/"
BOUNDARY = 1.0
BOUNDARIES = (0.5, 1.0, 2.0)
LOADS_CODE = ("CALL", "CALLCODE", "DELEGATECALL", "STATICCALL", "EXTCODESIZE", "EXTCODECOPY")
ACCOUNT_ROW = ("BALANCE", "EXTCODEHASH")
MODES = ("EXISTING_EOA", "EXISTING_CONTRACT_MINIMAL", "EXISTING_CONTRACT_SAME_MAX",
         "EXISTING_CONTRACT_JUMPDEST", "EXISTING_CONTRACT_DIFF_MAX", "NON_EXISTING_ACCOUNT")
PAIRS = {"published": ("nm-jochemnet", "nm-state-actor"),
         "treated": ("nm-joc-full", "nm-state-actor"),
         "replica": ("nm-joc-r1", "nm-joc-r2"),
         "settled": ("nm-joc-t1", "nm-sa-t1")}


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


def read_mb(e):
    return ((agg(e).get("resource_totals") or {}).get("disk_read_bytes", 0)) / 1e6


def category(t):
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
    if "NON_EXISTING" in t:
        return "absent account"
    if "EXISTING_EOA" in t:
        return "existing EOA"
    if "EXISTING_CONTRACT" in t:
        return "existing contract"
    return "other"


def opcode(t):
    m = re.search(r"opcode_([A-Z]+)-value_sent_[01]", t)
    return m.group(1) if m else None


def mode(t):
    m = re.search(r"account_mode_AccountMode[.]([A-Z_]+)", t)
    return m.group(1) if m else None


def summarise(rs):
    if not rs:
        return None
    rs = sorted(rs)
    n = len(rs)
    return {"n": n,
            "within10": sum(1 for r in rs if 0.9 <= r <= 1.1),
            "median": round(median(rs), 4),
            "p25": round(rs[n // 4], 3),
            "p75": round(rs[(3 * n) // 4], 3),
            "min": round(rs[0], 3), "max": round(rs[-1], 3)}


def rows_for(pair):
    """(ratio, seconds, read-MB on each arm, test id) for every test both arms completed."""
    A, B = load(R + pair[0]), load(R + pair[1])
    out = []
    for t in set(A) & set(B):
        x, y = mgas(A[t]), mgas(B[t])
        if x and y:
            out.append((y / x, secs(A[t]), read_mb(A[t]), read_mb(B[t]), t))
    return out


data = {name: rows_for(p) for name, p in PAIRS.items()}

# Class membership is a property of the test, not of the configuration it was measured in, so it
# is fixed once from the reference arm of the treated pair and applied to every column. Deriving
# it per pair instead would move tests across the boundary between columns - the untreated
# jochemnet arm is the fast one, so it puts 1,021 tests under a second where the treated arm puts
# 676 - and a side-by-side whose rows change membership is not a side-by-side.
MEMBER = {t: s for _, s, _, _, t in data["treated"]}


def split(rows):
    known = [(r, MEMBER[t]) for r, _, _, _, t in rows if t in MEMBER]
    return ([r for r, s in known if s < BOUNDARY], [r for r, s in known if s >= BOUNDARY])


classes = {}
for name, rows in data.items():
    short, long_ = split(rows)
    classes[name] = {"lt1s": summarise(short), "ge1s": summarise(long_),
                     "unclassified": len(rows) - len(short) - len(long_)}

# Category membership, on the treated pair: which side of the line each category lives on, and
# what it reads there. A category that is wholly short cannot support a claim about a store.
by_category = {}
for cat in sorted({category(t) for _, _, _, _, t in data["treated"]}):
    rows = [r for r in data["treated"] if category(r[4]) == cat]
    short = [r for r in rows if MEMBER[r[4]] < BOUNDARY]
    long_ = [r for r in rows if MEMBER[r[4]] >= BOUNDARY]
    by_category[cat] = {
        "n": len(rows),
        "pct_lt1s": round(100 * len(short) / len(rows), 1),
        "median_secs": round(median([s for _, s, _, _, _ in rows]), 2),
        "lt1s": summarise([r[0] for r in short]),
        "ge1s": summarise([r[0] for r in long_]),
    }

# The taxonomy inside the long class: does the opcode load the callee's code, and is the contract
# distinct or reused. This is the split that localised the residual.
families = {"loads_code": defaultdict(list), "account_row": defaultdict(list)}
for r, s, ja, sa, t in data["treated"]:
    if MEMBER[t] < BOUNDARY:
        continue
    op, md = opcode(t), mode(t)
    if not op or md not in MODES:
        continue
    fam = "loads_code" if op in LOADS_CODE else "account_row" if op in ACCOUNT_ROW else None
    if fam:
        families[fam][md].append((r, ja, sa))
class2_families = {}
for fam, per_mode in families.items():
    class2_families[fam] = {}
    for md, vals in per_mode.items():
        class2_families[fam][md] = {
            "n": len(vals),
            "median": round(median([v[0] for v in vals]), 4),
            "jocMB": round(median([v[1] for v in vals]), 1),
            "saMB": round(median([v[2] for v in vals]), 1),
        }
# Modes whose tests are all short drop out of the long class entirely; record that rather than
# leaving a hole the reader has to infer.
dropped = sorted({md for md in MODES
                  if not any(md in class2_families[f] for f in class2_families)})

# The boundary is a choice, so show it is not a load-bearing one.
sensitivity = {}
for b in BOUNDARIES:
    rows = data["treated"]
    sensitivity[str(b)] = {
        "lt": summarise([r for r, s, _, _, _ in rows if s < b]),
        "ge": summarise([r for r, s, _, _, _ in rows if s >= b]),
        "n_lt": sum(1 for _, s, _, _, _ in rows if s < b),
    }

# Fine-grained buckets for the floor figure: the same store twice, against the two stores.
def bucket(s):
    return "lt0.2s" if s < 0.2 else "0.2to1s" if s < 1 else "1to5s" if s < 5 else "ge5s"


buckets = {}
for name in ("replica", "treated"):
    b = defaultdict(list)
    for r, s, _, _, t in data[name]:
        b[bucket(MEMBER.get(t, s))].append(r)
    buckets[name] = {k: summarise(v) for k, v in b.items()}

json.dump({"boundary_s": BOUNDARY,
           "classes": classes,
           "by_category": by_category,
           "class2_families": class2_families,
           "class2_modes_dropped": dropped,
           "boundary_sensitivity": sensitivity,
           "buckets": buckets},
          sys.stdout, indent=1, sort_keys=True)
