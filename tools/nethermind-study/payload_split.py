#!/usr/bin/env python3
"""Where inside a test do state-actor's extra bytes land?

The fixed ~150 MB excess has two possible homes:
  - payload 0 only  -> the measurement window is swallowing client warmup, so the excess is an
                       artifact of when benchmarkoor starts counting;
  - spread evenly   -> genuine per-block execution cost of the generated store.

Test identity is unrecoverable from the results tree (directory names are truncated and
hash-suffixed), so tests are bucketed by their own total read volume instead. The low-volume
bucket IS the control/warm-query population - those are exactly the tests that read ~1.8 MB on
jochemnet and ~96-230 MB on state-actor.
"""
import glob
import json
import os
import sys
from statistics import median


def collect(root):
    best, bn = None, -1
    for d in glob.glob(os.path.join(root, "runs", "*")):
        n = len(glob.glob(os.path.join(d, "**", "test.result-details.json"), recursive=True))
        if n > bn:
            best, bn = d, n
    out = []
    for f in glob.glob(os.path.join(best, "**", "test.result-details.json"), recursive=True):
        try:
            j = json.load(open(f))
        except Exception:
            continue
        # resources is a dict keyed by payload index ("0", "1", ...), not a list.
        res = j.get("resources") or {}
        if isinstance(res, list):
            items = list(enumerate(res))
        else:
            items = sorted(res.items(), key=lambda kv: int(kv[0]))
        reads = [v.get("disk_read_bytes", 0) / 1e6 for _, v in items if isinstance(v, dict)]
        if reads:
            out.append(reads)
    return out


for label, root in (("jochemnet (corrected)", "/bench/results/nm-joc-full"),
                    ("state-actor", "/bench/results/nm-state-actor")):
    rows = collect(root)
    print(f"### {label}: {len(rows)} tests")
    print("  %-14s%6s%12s%13s%14s%15s" % ("total bucket", "n", "med total", "med payloads",
                                          "med payload0", "payload0 share"))
    for lo, hi in ((0, 10), (10, 100), (100, 1000), (1000, 1e9)):
        g = [r for r in rows if lo <= sum(r) < hi]
        if not g:
            continue
        label2 = "%g-%g MB" % (lo, hi) if hi < 1e9 else "%g+ MB" % lo
        print("  %-14s%6d%12.1f%13.0f%14.1f%14.1f%%" % (
            label2, len(g),
            median([sum(r) for r in g]),
            median([len(r) for r in g]),
            median([r[0] for r in g]),
            median([r[0] / sum(r) * 100 if sum(r) else 0 for r in g])))
    print()
