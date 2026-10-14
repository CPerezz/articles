#!/usr/bin/env python3
"""Per family: measured-step time, disk read bytes and IOPS, CPU, for two runs (default J1 vs S1).
usage: perfam.py [runA runB]"""
import glob
import json
import re
import sys
from collections import defaultdict
from statistics import median

R = "/root/bench/reth/results/"
A, B = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("j1", "s1")


def load(rid):
    p = max(glob.glob(R + rid + "/runs/*/result.json"), key=lambda p: len(json.load(open(p))["tests"]))
    return json.load(open(p))["tests"]


def cat(t):
    fam = re.search(r"::(test_[a-z_]+)\[", t).group(1).replace("test_", "")
    op = re.search(r"opcode_([A-Z0-9]+)", t)
    mode = re.search(r"AccountMode\.([A-Z_]+)", t)
    val = re.search(r"value_sent_(\d)", t)
    if fam == "account_access":
        return "%s %s v%s" % (op.group(1), mode.group(1), val.group(1) if val else "-")
    return fam


def m(e):
    a = e["steps"]["test"]["aggregated"]
    r = a.get("resource_totals") or {}
    return {"s": a["gas_used_time_total"] / 1e9, "mgas": a["gas_used_total"] / 1e6 / (a["gas_used_time_total"] / 1e9),
            "rb": r.get("disk_read_bytes", 0), "riops": r.get("disk_read_iops", 0), "cpu": r.get("cpu_usec", 0) / 1e6}


a, b = load(A), load(B)
by = defaultdict(list)
for t in a:
    if t in b:
        by[cat(t)].append((m(a[t]), m(b[t])))
print(f"{'family':42} {'n':>3} {'ratio':>6} {A+' s':>7} {B+' s':>7} {A+' MB':>8} {B+' MB':>8} {A+' kIO':>7} {B+' kIO':>7} {A+' cpu':>7} {B+' cpu':>7}")
for k, v in sorted(by.items(), key=lambda kv: median(y["mgas"] / x["mgas"] for x, y in kv[1])):
    f = lambda i, key: median(p[i][key] for p in v)
    print(f"{k:42} {len(v):3} {median(y['mgas'] / x['mgas'] for x, y in v):6.3f} {f(0,'s'):7.2f} {f(1,'s'):7.2f} "
          f"{f(0,'rb')/1e6:8.0f} {f(1,'rb')/1e6:8.0f} {f(0,'riops')/1e3:7.1f} {f(1,'riops')/1e3:7.1f} {f(0,'cpu'):7.1f} {f(1,'cpu'):7.1f}")
