#!/usr/bin/env python3
"""Rounds 69-73: the storage class closed by intervention, and the absent-account transfer localised.

R69 compacted jochemnet's Flat/Storage (807 files over six levels -> 108 at L6); R72 compacted
Flat/StorageNodes (1,961 over five -> 801 at L6) - the two columns no earlier round ever settled.
R71 profiled the absent-account transfer per thread; R73 ablated the two warming paths on it.
Prints JSON to stdout; merged into data/report_data.json under `storage`.
"""
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

R = "/bench/results/"


def levels(path, cf):
    lv = defaultdict(lambda: [0, 0])
    for line in open(path, errors="replace"):
        q = line.split()
        if len(q) == 4 and q[1] == cf:
            lv[int(q[2])][0] += 1
            lv[int(q[2])][1] += int(q[3])
    return {"levels": sorted(lv), "files": sum(v[0] for v in lv.values()),
            "gb": round(sum(v[1] for v in lv.values()) / 1e9, 1),
            "per_level": {str(l): lv[l][0] for l in sorted(lv)}}


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


def sstore(t):
    m = re.search(r"test_sstore_bloated\[.*?existing_slots_(\w+)-write_new_value_(\w+).*gas-value_(\d+M)", t)
    return "slots=%s new=%s %s" % m.groups() if m else None


# ---------------------------------------------------------------- per-column traces (R72 pair)
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


def cut(P, arm, namer):
    cfs, fdmap = cfmap("%s/files-%s.txt" % (P, arm)), fds("%s/fds-%s.txt" % (P, arm))
    pids = {p for p, _ in fdmap}
    wins, a, name = [], None, None
    for line in open("%s/run-%s.log" % (P, arm), errors="replace"):
        mm = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
        if not mm:
            continue
        t = int(datetime.strptime(mm.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
        if "Running test step" in line:
            a, name = t, namer(line)
        elif "Test completed" in line and a is not None and name:
            wins.append((name, a, t + 1))
            a = None
    per = {w[0]: defaultdict(int) for w in wins}
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
        mm = re.match(r"@cnt\[(\d+), (\d+)\]: (\d+)", line)
        if mm and int(mm.group(1)) in pids:
            per[cur][bucket(fdmap.get((int(mm.group(1)), int(mm.group(2))), "?"), cfs)] += int(mm.group(3))
    return per


out = {"src": "R69 (Flat/Storage) and R72 (Flat/StorageNodes) compactions with pre-registered predictions; "
              "R71 per-thread CPU and R73 ablation on the absent-account transfer"}

out["columns"] = {
    "joc_storage_before": levels("/bench/logs/r69/files-joc-before.txt", "Storage"),
    "joc_storage_after": levels("/bench/logs/r69/files-joc.txt", "Storage"),
    "joc_storagenodes_before": levels("/bench/logs/r72/files-joc-before.txt", "StorageNodes"),
    "joc_storagenodes_after": levels("/bench/logs/r72/files-joc.txt", "StorageNodes"),
    "sa_storage": levels("/bench/logs/r72/files-sa.txt", "Storage"),
    "sa_storagenodes": levels("/bench/logs/r72/files-sa.txt", "StorageNodes"),
    "settled_earlier": {"Account": "round 14", "StateNodes": "round 14", "StateTopNodes": "round 66"},
}

# ---------------------------------------------------------------- the storage cells, three stages
stages = {"v2": ("nm-sa-v2r1", "nm-joc-v2r1"), "r68": ("nm-sa-out68", "nm-joc-out68"),
          "r69": ("nm-sa-st69", "nm-joc-st69"), "r72": ("nm-sa-sn72", "nm-joc-sn72")}
runs = {k: (load(R + a), load(R + b)) for k, (a, b) in stages.items()}
cells = defaultdict(dict)
for stage, (S, J) in runs.items():
    for t in S:
        n = sstore(t)
        if n and t in J and mg(S[t]) and mg(J[t]):
            cells[n][stage] = round(mg(S[t]) / mg(J[t]), 3)
            cells[n][stage + "_sa"] = round(mg(S[t]), 1)
            cells[n][stage + "_joc"] = round(mg(J[t]), 1)
out["cells"] = dict(cells)

A, B = cut("/bench/logs/r72", "sa", sstore), cut("/bench/logs/r72", "joc", sstore)
A9, B9 = cut("/bench/logs/r69", "sa", sstore), cut("/bench/logs/r69", "joc", sstore)
out["reads"] = {}
for n in sorted(set(A) & set(B)):
    out["reads"][n] = {
        "after_r72": {"sa_rows": A[n].get("flat/Storage", 0), "joc_rows": B[n].get("flat/Storage", 0),
                      "sa_nodes": A[n].get("flat/StorageNodes", 0), "joc_nodes": B[n].get("flat/StorageNodes", 0)},
        "after_r69": {"sa_rows": A9.get(n, {}).get("flat/Storage", 0), "joc_rows": B9.get(n, {}).get("flat/Storage", 0),
                      "sa_nodes": A9.get(n, {}).get("flat/StorageNodes", 0), "joc_nodes": B9.get(n, {}).get("flat/StorageNodes", 0)},
    }

# ---------------------------------------------------------------- the absent-account transfer
def gasof(line):
    m = re.search(r"gas-value_(\d+M)", line)
    return m.group(1) if m else None


HZ = 100.0
cpu = {}
for arm in ("sa", "joc"):
    series, comms = defaultdict(list), {}
    for line in open("/bench/logs/r71/threads-%s.txt" % arm, errors="replace"):
        q = line.split()
        if len(q) == 5 and q[2].isdigit():
            comms[(q[0], q[2])] = q[3]
            series[(q[0], q[2])].append((float(q[1]), int(q[4])))
    per = defaultdict(lambda: defaultdict(list))
    for rep in (1, 2, 3):
        log = "/bench/logs/r71/run-%s-%d.log" % (arm, rep)
        if not os.path.exists(log):
            continue
        a = name = None
        for line in open(log, errors="replace"):
            mm = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
            if not mm:
                continue
            t = datetime.strptime(mm.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
            if "Running test step" in line:
                a, name = t, gasof(line)
            elif "Test completed" in line and a is not None and name:
                acc = defaultdict(float)
                for k, pts in series.items():
                    ins = [(x, v) for x, v in pts if a <= x <= t + 1]
                    if len(ins) >= 2:
                        c = comms[k].lower()
                        b = "rocksdb" if c.startswith("rocksdb") else (
                            ".net thread pool" if c.startswith(".net_tp") else (
                                ".net gc" if "gc" in c else (".net other" if c.startswith(".net") else "client main")))
                        acc[b] += (ins[-1][1] - ins[0][1]) / HZ
                for kk, vv in acc.items():
                    per[name][kk].append(round(vv, 2))
                a = None
    cpu[arm] = {g: {k: round(sum(v) / len(v), 2) for k, v in d.items() if sum(v) / len(v) >= 0.05}
                for g, d in per.items()}
thr71 = defaultdict(lambda: defaultdict(list))
for arm in ("sa", "joc"):
    for rep in (1, 2, 3):
        root = "/bench/logs/r71/res-%s-%d" % (arm, rep)
        t = load(root)
        for k, e in t.items():
            g = gasof(k)
            if g and mg(e):
                thr71[g][arm].append(round(mg(e), 1))
out["absent_account"] = {"cpu_seconds": cpu, "throughput": {g: dict(v) for g, v in thr71.items()}}

abl = defaultdict(lambda: defaultdict(list))
for line in open("/bench/logs/r73/r73.log", errors="replace"):
    m = re.search(r"(A baseline|B prewarming off|C trie warmer off)\s+(\w+) rep\d: (.*)", line)
    if m:
        for g, v in re.findall(r"(\d+M) ([\d.]+) MGas/s", m.group(3)):
            abl[m.group(1).strip()]["%s %s" % (m.group(2), g)].append(float(v))
out["ablation"] = {k: {kk: [round(x, 1) for x in vv] for kk, vv in v.items()} for k, v in abl.items()}

json.dump(out, sys.stdout, indent=1, sort_keys=True)
