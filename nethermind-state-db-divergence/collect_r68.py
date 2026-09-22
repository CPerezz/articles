#!/usr/bin/env python3
"""Round 68: the tests still outside +-10%, re-measured against a same-session denominator.

The v2 pair measured state-actor twice against *one* jochemnet run, so a single slow jochemnet
measurement makes an outlier "reproduce" in both. R68 re-ran the reproducible outliers on both
arms back to back with per-column pread accounting. This block carries, per test: throughput on
all five runs, and the per-column read counts, bytes and mean latency from the fresh pair.
Prints JSON to stdout; merged into data/report_data.json under `outliers`.
"""
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

P = "/bench/logs/r68"
R = "/bench/results/"
CFS = ("flat/Account", "flat/StateTopNodes", "flat/StateNodes", "flat/Storage", "flat/StorageNodes", "code")


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


def mg(e):
    a = ((e.get("steps") or {}).get("test") or {}).get("aggregated") or {}
    g, t = a.get("gas_used_total"), a.get("gas_used_time_total")
    return (g / 1e6) / (t / 1e9) if g and t else None


def short(t):
    m = re.search(r"transfer_amount_(\d)-case_id_(\w+?)-benchmark-gas-value_(\d+M)", t)
    if m:
        return "amt%s %s %s" % m.groups()
    m = re.search(r"test_sstore_bloated\[.*?existing_slots_(\w+)-write_new_value_(\w+).*gas-value_(\d+M)", t)
    return "sstore slots=%s new=%s %s" % m.groups() if m else None


def cfmap(p):
    m = {}
    for line in open(p, errors="replace"):
        q = line.split()
        if len(q) == 4:
            m[q[0]] = q[1]
    return m


def fds(p):
    out = {}
    for line in open(p, errors="replace"):
        q = line.split()
        if len(q) == 3 and q[1].isdigit():
            out[(int(q[0]), int(q[1]))] = q[2]
    return out


def bucket(path, cfs):
    if "/code/" in path:
        return "code"
    m = re.search(r"/flat/([^/]+)$", path)
    return "flat/" + cfs.get(m.group(1), "unmapped") if m else "other"


def windows(log):
    out, a, name = [], None, None
    for line in open(log, errors="replace"):
        mm = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
        if not mm:
            continue
        t = int(datetime.strptime(mm.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        if "Running test step" in line:
            a, name = t, short(line)
        elif "Test completed" in line and a is not None and name:
            out.append((name, a, t + 1))
            a = None
    return out


def cut(arm):
    cfs, fdmap = cfmap("%s/files-%s.txt" % (P, arm)), fds("%s/fds-%s.txt" % (P, arm))
    pids = {p for p, _ in fdmap}
    wins = windows("%s/run-%s.log" % (P, arm))
    per = {w[0]: defaultdict(lambda: [0, 0, 0]) for w in wins}
    cur = None
    for line in open("%s/trace-%s.txt" % (P, arm), errors="replace"):
        mm = re.match(r"SEC (\d+)", line)
        if mm:
            t = int(mm.group(1))
            hit = [w for w in wins if w[1] <= t <= w[2]]
            cur = hit[0][0] if hit else None
            continue
        if cur is None:
            continue
        mm = re.match(r"@(lat|cnt|byt)\[(\d+), (\d+)\]: (\d+)", line)
        if mm and int(mm.group(2)) in pids:
            k = bucket(fdmap.get((int(mm.group(2)), int(mm.group(3))), "?"), cfs)
            per[cur][k][{"cnt": 0, "byt": 1, "lat": 2}[mm.group(1)]] += int(mm.group(4))
    return per


def levels(arm):
    d = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for line in open("%s/files-%s.txt" % (P, arm), errors="replace"):
        q = line.split()
        if len(q) == 4 and q[0].endswith(".sst"):
            d[q[1]][int(q[2])][0] += 1
            d[q[1]][int(q[2])][1] += int(q[3])
    return {cf: {"levels": sorted(v), "files": sum(x[0] for x in v.values()),
                 "gb": round(sum(x[1] for x in v.values()) / 1e9, 2)} for cf, v in d.items()}


A, B = cut("sa"), cut("joc")
runs = {k: load(R + k) for k in ("nm-sa-v2r1", "nm-sa-v2r2", "nm-joc-v2r1", "nm-sa-out68", "nm-joc-out68")}
thr = defaultdict(dict)
for k, v in runs.items():
    for t, e in v.items():
        n = short(t)
        if n and mg(e):
            thr[n][k] = round(mg(e), 2)

tests = {}
for name in sorted(set(A) & set(B)):
    d = thr.get(name, {})
    if "nm-sa-out68" not in d or "nm-joc-out68" not in d:
        continue
    cols = {}
    for k in CFS:
        a, b = A[name].get(k, [0, 0, 0]), B[name].get(k, [0, 0, 0])
        if a[0] + b[0] < 200:
            continue
        cols[k] = {"sa_n": a[0], "joc_n": b[0], "sa_mb": round(a[1] / 1e6, 1), "joc_mb": round(b[1] / 1e6, 1),
                   "sa_us": round(a[2] / max(a[0], 1)), "joc_us": round(b[2] / max(b[0], 1))}
    tests[name] = {
        "thr": d,
        "r_v2r1": round(d["nm-sa-v2r1"] / d["nm-joc-v2r1"], 3) if "nm-sa-v2r1" in d and "nm-joc-v2r1" in d else None,
        "r_v2r2": round(d["nm-sa-v2r2"] / d["nm-joc-v2r1"], 3) if "nm-sa-v2r2" in d and "nm-joc-v2r1" in d else None,
        "r_r68": round(d["nm-sa-out68"] / d["nm-joc-out68"], 3),
        "cols": cols,
    }

out = {
    "src": "R68: the reproducible >10% outliers re-run on both arms back to back, per-column pread accounting",
    "tests": tests,
    "levels": {"sa": levels("sa"), "joc": levels("joc")},
}
# the denominator effect, quantified: same test, jochemnet measured twice
sh = [(n, t["thr"]["nm-joc-v2r1"], t["thr"]["nm-joc-out68"]) for n, t in tests.items() if "nm-joc-v2r1" in t["thr"]]
sa = [(n, t["thr"]["nm-sa-v2r1"], t["thr"]["nm-sa-out68"]) for n, t in tests.items() if "nm-sa-v2r1" in t["thr"]]
out["denominator"] = {
    "joc_spread": round(max(abs(b / a - 1) for _, a, b in sh), 3),
    "sa_spread": round(max(abs(b / a - 1) for _, a, b in sa), 3),
    "joc_worst": max(sh, key=lambda x: abs(x[2] / x[1] - 1))[0],
    "sa_worst": max(sa, key=lambda x: abs(x[2] / x[1] - 1))[0],
    "n": len(sh),
}
json.dump(out, sys.stdout, indent=1, sort_keys=True)
