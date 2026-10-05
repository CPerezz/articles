#!/usr/bin/env python3
"""Step 0: which file every page a traced test step reads comes from, and what each store holds.

Input per arm, written by the study's trace-tests.sh on the bench host into /bench/erigon/trace/<arm>-<tag>/:
trace.txt (kernel filemap:mm_filemap_add_to_page_cache events for the arm's device, plus WALL
markers), files.txt (inode, size, path of every file on the store) and run_dir.txt (benchmarkoor's
run directory). The page cache is dropped before every test step, so the pages a step adds are the
bytes it read from disk. A step's window opens at benchmarkoor's "Running test step" line; its
first newPayload-time seconds are newPayload, the rest until the next harness line is
forkchoiceUpdated.

Prints JSON to stdout; the page reads it as data/report_data.json's "step0".
Usage: collect_trace.py <tag>        e.g. collect_trace.py T0
"""
import bisect
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

TAG = sys.argv[1]
ROOT = "/bench/erigon/trace"
EVENT = re.compile(r"\s(\d+\.\d+): mm_filemap_add_to_page_cache: dev \d+:\d+ ino ([0-9a-f]+) "
                   r"pfn=\S+ ofs=\d+(?: order=(\d+))?")
MARK = re.compile(r"\s(\d+\.\d+): tracing_mark_write: WALL (\d+\.\d+)")
STAMP = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)")
DOMAINS = ("accounts", "storage", "code", "commitment")


def category(path):
    if path.endswith("/chaindata/mdbx.dat"):
        return "database"
    name = os.path.basename(path)
    if "/snapshots/domain/" in path:
        for d in DOMAINS:
            if f"-{d}." in name:
                return f"{d} files" if name.endswith(".kv") else f"{d} indexes"
        return "other domain files"
    if "/snapshots/" in path:
        if "/history/" in path or "/idx/" in path or "/accessor/" in path:
            return "history"
        return "block files"
    return "other"


def steps(name):
    m = re.search(r"\.(\d+)-(\d+)\.\w+$", name)
    return (int(m.group(1)), int(m.group(2))) if m else None


def epoch(s):
    return datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S.%f%z").timestamp() \
        if "." in s else datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z").timestamp()


def arm(name):
    d = os.path.join(ROOT, f"{name}-{TAG}")
    files = {}
    inventory = defaultdict(int)
    domain_steps = defaultdict(set)
    for line in open(os.path.join(d, "files.txt")):
        ino, size, path = line.rstrip("\n").split(" ", 2)
        cat = category(path)
        files[int(ino)] = cat
        inventory[cat] += int(size)
        if cat.endswith(" files"):
            s = steps(os.path.basename(path))
            if s:
                domain_steps[cat.split()[0]].add(s)

    run = open(os.path.join(d, "run_dir.txt")).read().split()[0]
    result = json.load(open(os.path.join(run, "result.json")))["tests"]
    log = open(os.path.join(run, "benchmarkoor.log"), errors="replace").read().splitlines()
    starts = []
    for i, line in enumerate(log):
        if "Running test step" not in line:
            continue
        test = next(t for t in result if t.split("::")[-1] in line or t in line)
        nxt = next(l for l in log[i + 1:] if STAMP.search(l) and "CLIE" not in l)
        times = result[test]["steps"]["test"]["aggregated"]["method_stats"]["times"]
        np_s = sum(m["last"] for k, m in times.items() if k.startswith("engine_newPayload")) / 1e9
        t0 = epoch(STAMP.search(line).group(1))
        starts.append((test, t0, t0 + np_s, epoch(STAMP.search(nxt).group(1))))

    offset, events = None, []
    for line in open(os.path.join(d, "trace.txt"), errors="replace"):
        m = MARK.search(line)
        if m and offset is None:
            offset = float(m.group(2)) - float(m.group(1))
            continue
        m = EVENT.search(line)
        if m:
            events.append((float(m.group(1)), int(m.group(2), 16), 4096 << int(m.group(3) or 0)))
    assert offset is not None, "no WALL marker in the trace"
    events.sort()
    ts = [e[0] + offset for e in events]

    tests = {}
    for test, t0, t_np, t_end in starts:
        win = {"newPayload": defaultdict(int), "forkchoiceUpdated": defaultdict(int)}
        for j in range(bisect.bisect_left(ts, t0), bisect.bisect_left(ts, t_end)):
            part = "newPayload" if ts[j] < t_np else "forkchoiceUpdated"
            win[part][files.get(events[j][1], "unmapped")] += events[j][2]
        tests[test] = {"np_secs": round(t_np - t0, 3), "window_secs": round(t_end - t0, 3),
                       **{k: dict(v) for k, v in win.items()}}
    return {"inventory_bytes": dict(inventory), "events": len(events),
            "domain_steps": {k: sorted(v) for k, v in domain_steps.items()}, "tests": tests}


json.dump({"src": f"collect_trace.py {TAG}", "joc": arm("joc"), "sa": arm("sa")},
          sys.stdout, indent=1, sort_keys=True)
