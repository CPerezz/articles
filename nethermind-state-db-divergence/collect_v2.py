#!/usr/bin/env python3
"""Collect rounds 66-67 into two JSON blocks: `topnodes` (the StateTopNodes packing finding and its
two-direction intervention) and `v2` (the regenerated store and the class-2 re-measurement).

Throughput cells are recomputed from the run results, like the rest of the page. Pread counts and
store geometry come from the dive's traces and table-property dumps (bpftrace/RocksDB leave no
result.json). Run on the bench host; prints JSON to stdout.
"""
import glob
import json
import os
import re
import sys
from collections import defaultdict
from statistics import median

DV = "/bench/logs/dive"
V2 = "/bench/logs/v2"
R = "/bench/results/"


def txt(p):
    try:
        return open(p, errors="replace").read()
    except OSError:
        return ""


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
    a = agg(e)
    t = a.get("gas_used_time_total")
    return t / 1e9 if t else None


def cell(t):
    fam = t.split("::", 1)[1].split("[")[0]
    if fam == "test_account_access":
        m = re.search(r"opcode_([A-Z]+)-.*account_mode_AccountMode\.(\w+?)-overhead", t)
        op, mode = m.group(1), m.group(2).replace("EXISTING_CONTRACT_", "")
        return "%s %s" % (mode, "BAL/HASH" if op in ("BALANCE", "EXTCODEHASH") else "code-exec")
    if fam.startswith("test_sload") or fam.startswith("test_sstore"):
        return "storage slot"
    if fam.startswith("test_ether_transfers"):
        return "ether transfer"
    return fam


def ratios(A, B, ids):
    return [mgas(A[t]) / mgas(B[t]) for t in ids if t in A and t in B and mgas(A[t]) and mgas(B[t])]


# ---------------------------------------------------------------- topnodes: shape and packing
def shape(path):
    s = txt(path)
    m = re.search(r"StateTopNodes: (\d+) nodes", s)
    m2 = re.search(r"(\d+) level-6 subtrees sampled: ([\d.]+) nodes and ([\d.]+) leaves per subtree.*?=> ~([\d.]+)M accounts, deepest node at path length (\d+)", s)
    m3 = re.search(r"mean leaf path length ([\d.]+) => a cold account walk touches ([\d.]+) nodes", s)
    return {"top_nodes": int(m.group(1)), "subtrees_sampled": int(m2.group(1)), "nodes_per_subtree": float(m2.group(2)),
            "leaves_per_subtree": float(m2.group(3)), "accounts_est_M": float(m2.group(4)), "deepest_len": int(m2.group(5)),
            "mean_leaf_len": float(m3.group(1)), "walk_nodes": float(m3.group(2))}


def geom(line):
    m = re.search(r"entries=(\d+) blocks=(\d+) ondisk/block=(\d+)B entries/block=([\d.]+) filter=([\d.]+)MB", line)
    return {"entries": int(m.group(1)), "blocks": int(m.group(2)), "bytes_per_block": int(m.group(3)),
            "entries_per_block": float(m.group(4)), "filter_mb": float(m.group(5))}


dive = txt(DV + "/dive.log")
tn = {
    "shape": {"joc": shape(DV + "/shape-joc.txt"), "sa_v1": shape(DV + "/shape-sa.txt"), "sa_v2": shape(V2 + "/shape-v2.txt")},
    "packing": {
        "joc_before": geom(re.search(r"before  joc: (.*)", dive).group(1)),
        "sa_before": geom(re.search(r"before  sa : (.*)", dive).group(1)),
        "sa_after": geom(re.search(r"after   sa : (.*)", dive).group(1)),
        "joc_after": geom(re.search(r"after   joc: (.*)", dive).group(1)),
    },
    "client_option": {"block_size": 16000, "filter": "ribbonfilter:10:3 policy; no bottommost filter (optimize_filters_for_hits=true)"},
}
v = txt(DV + "/verdict-topnodes.txt")
m = re.search(r"median sa/joc: settled layouts ([\d.]+) -> swapped layouts ([\d.]+) \(n=(\d+)\)", v)
m2 = re.search(r"sa x([\d.]+) .*?joc x([\d.]+)", v)
tn["swap"] = {"ratio_settled": float(m.group(1)), "ratio_swapped": float(m.group(2)), "n_pairs": int(m.group(3)),
              "sa_change": float(m2.group(1)), "joc_change": float(m2.group(2))}
for arm in ("joc", "sa"):
    mm = re.search(arm + r" totals: Account (\d+) -> (\d+) \| StateTopNodes (\d+) -> (\d+) \| StateNodes (\d+) -> (\d+) \| top preads per account read ([\d.]+) -> ([\d.]+)", v)
    m240 = re.search(arm + r" totals:.*?\n\s+restricted to the 240M half.*?top preads (\d+) -> (\d+) per (\d+) account reads \(([\d.]+) -> ([\d.]+) per account\); bytes/pread on top now (\d+) B", v)
    tn["swap"][arm] = {"account_before": int(mm.group(1)), "top_before": int(mm.group(3)), "statenodes_before": int(mm.group(5)),
                       "top_per_account_before": float(mm.group(7)), "top_per_account_after_all": float(mm.group(8)),
                       "top_per_account_after_240M": float(m240.group(5)), "top_bytes_per_pread_after": int(m240.group(6)),
                       "account_after_240M": int(m240.group(3)), "top_after_240M": int(m240.group(2))}
tn["swap"]["tests_completed"] = {"sa": len([1 for l in txt(DV + "/run-sa-top4k.log").splitlines() if "Test completed" in l]),
                                 "joc": len([1 for l in txt(DV + "/run-joc-top16k.log").splitlines() if "Test completed" in l])}
# provenance of the 4 KB layout: file numbers from the pre-rebuild map
nums = defaultdict(list)
for line in txt("/bench/logs/night/r59-files-joc.txt").splitlines():
    p = line.split()
    if len(p) == 4 and p[0].endswith(".sst"):
        nums[p[1]].append(int(p[0][:-4]))
tn["provenance"] = {cf: {"min": min(v_), "max": max(v_), "n": len(v_)} for cf, v_ in nums.items()}
# per-variant R62 top/account before the swap, for the "uniform across variants" claim
per = []
for line in v.splitlines():
    mm = re.match(r"(amt\d \S+ 240M?)\s*\|\s+\d+>\d+\s+\d+>\d+\s+\d+>\d+ ([\d.]+)>([\d.]+) \|\s+\d+>\d+\s+\d+>\d+\s+\d+>\d+ ([\d.]+)>([\d.]+)", line)
    if mm and float(mm.group(2)) > 0 and float(mm.group(4)) > 0:
        per.append({"variant": mm.group(1), "joc_before": float(mm.group(2)), "joc_after": float(mm.group(3)),
                    "sa_before": float(mm.group(4)), "sa_after": float(mm.group(5))})
tn["swap"]["per_variant_240M"] = per
tn["src"] = "R66: probe-flat -mode shape / -mode props / -mode rebuild; runs nm-sa-top4k, nm-joc-top16k with per-fd pread tracing"

# ---------------------------------------------------------------- v2: identity and cells
ident = txt(V2 + "/v2-identity.txt").strip()
gen = txt(V2 + "/gen.log")
plog = txt(V2 + "/pipeline.log")
mg = re.search(r"generated: (\S+); genesis=(0x[0-9a-f]+) root=(0x[0-9a-f]+)", plog)
mt = re.search(r"real\s+(\d+)m([\d.]+)s", gen)
v2 = {
    "image": re.search(r"image=(\S+)", ident).group(1),
    "revision": (re.search(r"revision=(\S+)", plog) or [None, None])[1] if re.search(r"revision=(\S+)", plog) else None,
    "genesis": mg.group(2), "state_root": mg.group(3), "size": mg.group(1),
    "gen_minutes": round(int(mt.group(1)) + float(mt.group(2)) / 60) if mt else None,
    "v1_genesis": "0xa9e61c12051aeda72581c40b1718fa76b80c0b5cc5f7b7ebe96e0b6d9669491b",
    "topnodes_packing": geom(re.search(r"v2 top-node packing: (.*)", plog).group(1)),
    "fixtures": {"eest_ref": "benchmarks/amsterdam", "eest_commit": (re.search(r"commit=([0-9a-f]+)", txt(V2 + "/fill.log")) or [None, "?"])[1],
                 "filler": "nethermind", "gas": [160, 240],
                 "filled": int(re.search(r"fixtures filled: (\d+)", txt(V2 + "/fill-coverage.txt")).group(1)),
                 "class2_covered": [int(x) for x in re.search(r"class-2 ids covered: (\d+) of (\d+)", txt(V2 + "/fill-coverage.txt")).groups()]},
}
runs = {k: load(R + k) for k in ("nm-sa-v2r1", "nm-sa-v2r2", "nm-joc-v2r1", "nm-sa-t1", "nm-joc-t1")}
S1, S2, J, S0, J0 = (runs[k] for k in ("nm-sa-v2r1", "nm-sa-v2r2", "nm-joc-v2r1", "nm-sa-t1", "nm-joc-t1"))
v2["runs"] = {k: len(v_) for k, v_ in runs.items()}
ids = sorted(t for t in S1 if t in J and mgas(S1[t]) and mgas(J[t]))
by = defaultdict(list)
for t in ids:
    by[cell(t)].append(t)
cells = {}
for c, ts in by.items():
    cells[c] = {"n": len(ts)}
    for name, A, B in (("v2r1", S1, J), ("v2r2", S2, J), ("v2r1_joc_t1", S1, J0), ("v1_t1", S0, J0), ("v2r2_v2r1", S2, S1), ("joc_joc_t1", J, J0)):
        rs = ratios(A, B, ts)
        cells[c][name] = round(median(rs), 4) if rs else None
        cells[c][name + "_n"] = len(rs)
v2["cells"] = cells
long = [(mgas(S1[t]) / mgas(J[t]), t) for t in ids if (secs(S1[t]) or 0) >= 1 and (secs(J[t]) or 0) >= 1]
long2 = [(mgas(S2[t]) / mgas(J[t]), t) for t in ids if t in S2 and mgas(S2[t]) and (secs(S2[t]) or 0) >= 1 and (secs(J[t]) or 0) >= 1]


def split(rs):
    return {"n": len(rs), "within10": sum(1 for r, _ in rs if 0.9 <= r <= 1.1), "slower": sum(1 for r, _ in rs if r < 0.9),
            "faster": sum(1 for r, _ in rs if r > 1.1), "median": round(median(r for r, _ in rs), 4) if rs else None,
            "min": round(min(r for r, _ in rs), 4) if rs else None, "max": round(max(r for r, _ in rs), 4) if rs else None,
            "extremes": [(round(r, 3), t.split("::", 1)[1][:150]) for r, t in sorted(rs)[:3] + sorted(rs)[-3:]]}


v2["per_test"] = {"v2r1": split(long), "v2r2": split(long2)}
# same split for v1 settled, on the same ids, for the before/after sentence
v1ids = [t for t in ids if t in S0 and t in J0 and mgas(S0[t]) and mgas(J0[t]) and (secs(S0[t]) or 0) >= 1 and (secs(J0[t]) or 0) >= 1]
v2["per_test"]["v1_t1"] = split([(mgas(S0[t]) / mgas(J0[t]), t) for t in v1ids])
tr = {}
for t in ids:
    if "ether_transfers" not in t:
        continue
    mm = re.search(r"transfer_amount_(\d)-case_id_(\w+?)-benchmark-gas-value_(\d+M)", t)
    k = "amt%s %s %s" % mm.groups()
    tr[k] = {"v2r1": round(mgas(S1[t]) / mgas(J[t]), 4),
             "v2r2": round(mgas(S2[t]) / mgas(J[t]), 4) if t in S2 and mgas(S2.get(t, {})) else None,
             "v1_t1": round(mgas(S0[t]) / mgas(J0[t]), 4) if t in S0 and t in J0 and mgas(S0[t]) and mgas(J0[t]) else None}
v2["transfers"] = tr
v2["src"] = "R67: nm-sa-v2r1, nm-joc-v2r1, nm-sa-v2r2 on the 148 class-2 fixtures filled against v2; settled t1 runs for reference"

json.dump({"topnodes": tn, "v2": v2}, sys.stdout, indent=1, sort_keys=True)
