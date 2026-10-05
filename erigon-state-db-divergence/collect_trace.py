#!/usr/bin/env python3
"""Step 0: which file every page a traced test step reads comes from, and what each store holds.

Input per arm, written by the study's trace-tests.sh on the bench host into /bench/erigon/trace/<arm>-<tag>/:
trace.txt (kernel filemap:mm_filemap_add_to_page_cache events for the arm's device, plus WALL
markers), files.txt (inode, size, path of every file on the store) and run_dir.txt (benchmarkoor's
run directory). The page cache is dropped before every test step, so the pages a step adds are the
bytes it read from disk. Each engine call's window is [end - duration, end], from benchmarkoor's
"RPC call completed" line for that call in the test step.

Prints JSON to stdout; the page reads it as data/report_data.json's "step0".
Usage: collect_trace.py <tag>        e.g. collect_trace.py T0
"""
import bisect
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
CALL = re.compile(r"RPC call completed .*?full_duration=(\S+) method=(engine_\w+?)V\d")
GO_DUR = re.compile(r"(\d+(?:\.\d+)?)(h|ms|µs|us|ns|m|s)")
UNIT = {"h": 3600, "m": 60, "s": 1, "ms": 1e-3, "µs": 1e-6, "us": 1e-6, "ns": 1e-9}
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


def go_duration(s):
    return sum(float(v) * UNIT[u] for v, u in GO_DUR.findall(s))


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
    windows = []
    for i, line in enumerate(log):
        if "Running test step" not in line:
            continue
        test = next(t for t in result if t.split("::")[-1] in line or t in line)
        for l in log[i + 1:]:
            if "Test completed" in l or "Running test step" in l:
                break
            m = CALL.search(l)
            if m:
                end = epoch(STAMP.search(l).group(1))
                windows.append((test, m.group(2), end - go_duration(m.group(1)), end))

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

    tests = defaultdict(lambda: {"secs": {}, "bytes": {}})
    for test, method, t0, t1 in windows:
        b = defaultdict(int)
        for j in range(bisect.bisect_left(ts, t0), bisect.bisect_left(ts, t1)):
            b[files.get(events[j][1], "unmapped")] += events[j][2]
        tests[test]["secs"][method] = round(t1 - t0, 3)
        tests[test]["bytes"][method] = dict(b)
    return {"inventory_bytes": dict(inventory), "events": len(events),
            "domain_steps": {k: sorted(v) for k, v in domain_steps.items()}, "tests": tests}


json.dump({"src": f"collect_trace.py {TAG}", "joc": arm("joc"), "sa": arm("sa")},
          sys.stdout, indent=1, sort_keys=True)
