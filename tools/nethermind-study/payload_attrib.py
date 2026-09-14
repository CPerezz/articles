#!/usr/bin/env python3
"""Where inside a test do the bytes get read?

The CONTROL tests do no account-state work, yet state-actor reads 96-240 MB on them while
jochemnet reads ~2 MB. Two very different explanations:
  - the first payload's resource delta swallows Nethermind's startup/warmup I/O, in which case
    the "control penalty" is a measurement-window artifact, not execution cost;
  - the bytes are spread across payloads, in which case it is genuine per-block I/O and the
    generated store really does more work per block.
Per-payload deltas are already recorded, so this needs no new runs.
"""
import glob
import json
import os
import sys
from statistics import median


def run_dir(root):
    best, bn = None, -1
    for d in glob.glob(os.path.join(root, "runs", "*")):
        n = len(glob.glob(os.path.join(d, "*", "test.result-details.json")))
        if n > bn:
            best, bn = d, n
    return best


def collect(root, want_control):
    d = run_dir(root)
    rows = []
    for f in glob.glob(os.path.join(d, "*", "test.result-details.json")):
        name = os.path.basename(os.path.dirname(f))
        is_ctrl = "overhead_baseline_True" in name or "overhead-baseline-True" in name
        if is_ctrl != want_control:
            continue
        try:
            j = json.load(open(f))
        except Exception:
            continue
        res = j.get("resources") or []
        reads = [r.get("disk_read_bytes", 0) for r in res if isinstance(r, dict)]
        if not reads:
            continue
        rows.append((name, reads))
    return rows


def report(label, rows):
    if not rows:
        print(f"  {label}: no matching tests")
        return
    tot = [sum(r) / 1e6 for _, r in rows]
    n_pl = [len(r) for _, r in rows]
    # share of the test's bytes carried by its first payload
    share0 = [(r[0] / sum(r) * 100 if sum(r) else 0) for _, r in rows]
    first = [r[0] / 1e6 for _, r in rows]
    rest = [(sum(r) - r[0]) / 1e6 for _, r in rows]
    print(f"  {label:<26} tests={len(rows):<5} payloads/test={median(n_pl):<5.0f} "
          f"totalMB={median(tot):>8.1f}  payload0MB={median(first):>8.1f}  "
          f"restMB={median(rest):>7.1f}  payload0share={median(share0):>5.1f}%")


for want, tag in ((True, "CONTROL (no account work)"), (False, "MEASURED")):
    print(f"### {tag}")
    for label, root in (("jochemnet-compacted", "/bench/results/nm-joc-compacted"),
                        ("state-actor", "/bench/results/nm-state-actor")):
        report(label, collect(root, want))
    print()
