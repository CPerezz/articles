#!/usr/bin/env python3
"""What one unknown block-hash lookup costs each store: the study's probe-hash.sh output.

Per arm, /bench/erigon/probe-hash/<arm>/ holds calls.tsv (label, hash, curl seconds), trace.txt
(page-cache adds on the arm's device, with "WALL <label> start|end" markers around each call) and
files.txt (inode, size, path). Each call's pages are the events between its two markers, by file
category as in collect_trace.py.

Usage on the box: collect_probe_hash.py > probe-hash.json
"""
import json
import os
import re
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_trace import EVENT, category  # noqa: E402

ROOT = "/bench/erigon/probe-hash"
MARK = re.compile(r"\s(\d+\.\d+): tracing_mark_write: WALL (\S+) (start|end) ")


def kind(path):
    """Finer than collect_trace's categories: the lookup's reads are headers indexes and MDBX."""
    name = os.path.basename(path)
    if "-headers." in name:
        return "headers index" if name.endswith(".idx") else "headers data"
    return category(path)


def arm(name):
    d = os.path.join(ROOT, name)
    files = {}
    for line in open(os.path.join(d, "files.txt")):
        ino, _, path = line.rstrip("\n").split(" ", 2)
        files[int(ino)] = path
    calls = [l.rstrip("\n").split("\t") for l in open(os.path.join(d, "calls.tsv"))]
    marks, events = {}, []
    for line in open(os.path.join(d, "trace.txt"), errors="replace"):
        m = MARK.search(line)
        if m:
            marks[(m.group(2), m.group(3))] = float(m.group(1))
            continue
        m = EVENT.search(line)
        if m:
            events.append((float(m.group(1)), files.get(int(m.group(2), 16), ""), 4096 << int(m.group(3) or 0)))
    out = {}
    for label, _, secs in calls:
        t0, t1 = marks[(label, "start")], marks[(label, "end")]
        b, touched = defaultdict(int), set()
        for t, path, n in events:
            if t0 <= t <= t1:
                b[kind(path) if path else "unmapped"] += n
                if "-headers." in path:
                    touched.add(path)
        out[label] = {"ms": 1e3 * float(secs), "bytes": dict(b), "headers_files_touched": len(touched)}
    summ = {"headers_files": sum(1 for p in files.values() if p.endswith("-headers.seg"))}
    for k in ("cold", "warm"):
        vs = [v for label, v in out.items() if label.startswith(k + "-")]
        cats = {c for v in vs for c in v["bytes"]}
        summ[k] = {"n": len(vs), "ms_median": statistics.median(v["ms"] for v in vs),
                   "bytes_median": statistics.median(sum(v["bytes"].values()) for v in vs),
                   "bytes_by_kind_median": {c: statistics.median(v["bytes"].get(c, 0) for v in vs) for c in cats},
                   "headers_files_touched_median": statistics.median(v["headers_files_touched"] for v in vs)}
    return {"summary": summ, "calls": out}


if __name__ == "__main__":
    json.dump({a: arm(a) for a in ("joc", "sa")}, sys.stdout, indent=1, sort_keys=True)
