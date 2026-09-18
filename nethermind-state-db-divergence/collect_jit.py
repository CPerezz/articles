#!/usr/bin/env python3
"""Collect the JIT and settling experiments (rounds 28-40) into one JSON block for report_data.

Everything the rewritten article states about the second mechanism comes from here:
  profile      per-thread CPU inside the measured steps, both arms, before and after settling
  fixtures     per-payload structure of one control test per arm (the extra empty block)
  ab           round 36: control tests under three configurations
  slice        round 39: the regime-3 slice with TieredCompilation=0 on both arms
  subset       round 40: the 266 subset with both images settled and TieredCompilation=0
  settle       the level layouts before/after settling, from the ledger'd probe output
"""
import glob
import json
import os
import re
import sys
from collections import defaultdict
from statistics import median

R = "/bench/results/"
ND = "/bench/logs/night/"


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


def agg(e, step="test"):
    return ((e.get("steps") or {}).get(step) or {}).get("aggregated") or {}


def row(e):
    a = agg(e)
    g, t = a.get("gas_used_total"), a.get("gas_used_time_total")
    if not g or not t:
        return None
    r = a.get("resource_totals") or {}
    return {"mgas": (g / 1e6) / (t / 1e9), "secs": t / 1e9,
            "cpu": r.get("cpu_usec", 0) / 1e6, "rd": r.get("disk_read_bytes", 0) / 1e6}


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
    if re.search(r"EXISTING_EOA", t):
        return "existing EOA"
    if re.search(r"NON_EXISTING_ACCOUNT", t):
        return "non-existing"
    if re.search(r"EXISTING_CONTRACT", t):
        return "existing contract"
    return "other"


def cell(t):
    if "overhead_baseline_True" in t:
        return "CONTROL"
    if "ext_account_query_warm" in t:
        return "warm query"
    if "sload_same_key" in t:
        return "sload_same_key"
    m = re.search(r"opcode_([A-Z]+)-value_sent_([01]).*?(DIFF_MAX|SAME_MAX|NON_EXISTING_ACCOUNT)", t)
    if not m:
        return None
    op, vs, mode = m.groups()
    code = op in ("CALL", "CALLCODE", "DELEGATECALL", "STATICCALL", "EXTCODESIZE", "EXTCODECOPY")
    return "%s %s" % (mode, "code-exec" if code else "BAL/HASH")


def paired(jr, sr, keyfn):
    j, s = load(R + jr), load(R + sr)
    out = defaultdict(lambda: {"thr": [], "cpu": [], "joc_s": [], "sa_s": [], "sa_rd": [],
                               "joc_mgas": [], "sa_mgas": []})
    for t in set(j) & set(s):
        a, b = row(j[t]), row(s[t])
        k = keyfn(t)
        if not (a and b and k):
            continue
        d = out[k]
        d["thr"].append(b["mgas"] / a["mgas"])
        if a["cpu"]:
            d["cpu"].append(b["cpu"] / a["cpu"])
        d["joc_s"].append(a["secs"])
        d["sa_s"].append(b["secs"])
        d["sa_rd"].append(b["rd"])
        d["joc_mgas"].append(a["mgas"])
        d["sa_mgas"].append(b["mgas"])
    res = {}
    for k, d in out.items():
        rs = d["thr"]
        res[k] = {"n": len(rs), "thr": round(median(rs), 4),
                  "within10": sum(1 for r in rs if 0.9 <= r <= 1.1),
                  "cpu": round(median(d["cpu"]), 3) if d["cpu"] else None,
                  "joc_secs": round(median(d["joc_s"]), 3), "sa_secs": round(median(d["sa_s"]), 3),
                  "sa_read_mb": round(median(d["sa_rd"]), 1),
                  "joc_mgas": round(median(d["joc_mgas"]), 1), "sa_mgas": round(median(d["sa_mgas"]), 1)}
    allr = [r for d in out.values() for r in d["thr"]]
    res["_all"] = {"n": len(allr), "within10": sum(1 for r in allr if 0.9 <= r <= 1.1),
                   "median": round(median(allr), 4)} if allr else None
    return res


def threads(samples, log):
    """CPU by thread inside test-step windows, from the /proc sampler output."""
    from datetime import datetime, timezone
    win, start = [], None
    for line in open(log, errors="replace"):
        m = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
        if not m:
            continue
        t = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        if "Running test step" in line:
            start = t
        elif start and ("Test completed" in line or "Running cleanup step" in line):
            win.append((start, t + 1))
            start = None
    last, by = {}, defaultdict(float)
    for line in open(samples):
        ts, pid, tid, cpu, comm = line.rstrip("\n").split(" ", 4)
        ts, cpu = float(ts), float(cpu)
        prev = last.get((pid, tid))
        last[(pid, tid)] = (ts, cpu)
        if prev and any(s <= ts <= e for s, e in win):
            by[comm] += max(0.0, cpu - prev[1])
    wall = sum(e - s for s, e in win)
    return {"windows": len(win), "wall_s": round(wall, 1),
            "threads": {k: round(v, 2) for k, v in sorted(by.items(), key=lambda kv: -kv[1])[:6]}}


def payloads(root, pat):
    """Per-payload durations/gas of the first test matching pat: the fixture structure."""
    T = load(root)
    for t, e in T.items():
        if re.search(pat, t):
            out = {}
            for step in ("setup", "test"):
                a = agg(e, step)
                pl = a.get("payloads") or e.get("steps", {}).get(step, {}).get("payloads")
                out[step] = {"gas_m": (a.get("gas_used_total") or 0) / 1e6,
                             "secs": (a.get("gas_used_time_total") or 0) / 1e9}
            return {"test": t.split("::")[-1][:80], **out}
    return None


data = {
    "profile": {
        "joc_unsettled": threads(ND + "threads-joc.txt", ND + "prof-joc.log"),
        "sa_unsettled": threads(ND + "threads-sa.txt", ND + "prof-sa.log"),
        "sa_unsettled_rep": threads(ND + "threads-sa2.txt", ND + "prof2-sa.log"),
        "sa_settled": threads(ND + "threads-sa4.txt", ND + "r35-sa-ctl35.log"),
    },
    "ab": {
        "baseline": paired("nm-joc-prof", "nm-sa-ctl35", category)["CONTROL"],
        "no_parallel": paired("nm-joc-nopar", "nm-sa-nopar", category)["CONTROL"],
        "no_tiered_jit": paired("nm-joc-notc", "nm-sa-notc", category)["CONTROL"],
    },
    "slice": {
        "published": paired("nm-joc-full", "nm-state-actor", cell),
        "settled": paired("nm-joc-full", "nm-sa-slice38", cell),
        "jit_equalised": paired("nm-joc-slice39", "nm-sa-slice39", cell),
    },
    "subset": {
        "published": paired("nm-joc-full", "nm-state-actor", category),
        "corrected": paired("nm-joc-sub40", "nm-sa-sub40", category),
    },
    "settle": {
        "sa_account": {"before": "L3:92 (23.7 GB), compaction-pending", "after": "L6:92, pending 0"},
        "sa_code": {"before": "L4:734 (45.7 GB), compaction-pending", "after": "L6:729 (44.6 GB), pending 0"},
        "joc_code": {"before": "L0:3 L1:6 L3:117 (6.9 GB), compaction-pending", "after": "L6:113, pending 0"},
    },
}
json.dump(data, sys.stdout, indent=1, sort_keys=True)
