#!/usr/bin/env python3
"""Emit the B1 cache experiment as a JSON block for report_data.json.

B1 re-ran the 266-test subset on both arms with the flat DB block cache cut from 1 GiB to
8 MiB. Same stores, same tests, same treatment - only the cache changed. The article needs the
per-category throughput ratio before and after, plus the setup/measured step split, so the prose
can state exactly what the cache reduction moved.

Accessors mirror the existing host scripts: `tests` is a dict keyed by test id, throughput comes
from the test step's aggregated gas counters, and read bytes from its resource totals.
"""
import glob
import json
import os
import re
import sys
from collections import defaultdict
from statistics import median

CATS = {"EXISTING_EOA": "existing EOA",
        "EXISTING_CONTRACT_MINIMAL": "existing contract",
        "EXISTING_CONTRACT_SAME_MAX": "existing contract",
        "EXISTING_CONTRACT_JUMPDEST": "existing contract",
        "EXISTING_CONTRACT_DIFF_MAX": "existing contract",
        "NON_EXISTING_ACCOUNT": "absent account"}


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


def step_io(entry, step):
    """(read MB, write MB) for a step. Writes matter: anything setup wrote would sit in the
    client's memtables, a carry-over channel that sync + drop_caches cannot clear."""
    s = (entry.get("steps") or {}).get(step)
    r = ((s or {}).get("aggregated") or {}).get("resource_totals") or {}
    return ((r.get("disk_read_bytes", 0) / 1e6, r.get("disk_write_bytes", 0) / 1e6)
            if s else (None, None))


def mgas(entry):
    a = ((entry.get("steps") or {}).get("test") or {}).get("aggregated") or {}
    g, t = a.get("gas_used_total"), a.get("gas_used_time_total")
    return (g / 1e6) / (t / 1e9) if g and t else None


def category(tid):
    if re.search(r"overhead_baseline_True", tid):
        return "CONTROL"
    m = re.search(r"account_mode_(?:AccountMode\.)?([A-Z_]+)", tid)
    return CATS.get(m.group(1)) if m else None


def pair(joc_root, sa_root, only=None):
    joc, sa = load(joc_root), load(sa_root)
    if only is not None:
        joc = {k: v for k, v in joc.items() if k in only}
        sa = {k: v for k, v in sa.items() if k in only}
    thr = defaultdict(list)
    for tid in set(joc) & set(sa):
        a, b = mgas(joc[tid]), mgas(sa[tid])
        c = category(tid)
        if a and b and c:
            thr[c].append(b / a)
    steps = {}
    for label, src in (("joc", joc), ("sa", sa)):
        grp = defaultdict(list)
        for tid, e in src.items():
            c = category(tid)
            if c:
                grp["control" if c == "CONTROL" else "measured"].append(e)
        steps[label] = {
            k: {"n": len(v),
                "setup_mb": round(median([step_io(e, "setup")[0] for e in v]), 1),
                "setup_write_mb": round(median([step_io(e, "setup")[1] for e in v]), 1),
                "test_mb": round(median([step_io(e, "test")[0] for e in v]), 1),
                "test_write_mb": round(median([step_io(e, "test")[1] for e in v]), 1)}
            for k, v in grp.items()}
    return {"n": len(set(joc) & set(sa)),
            "thr": {k: round(median(v), 4) for k, v in sorted(thr.items())},
            "steps": steps}


if __name__ == "__main__":
    small = pair("/bench/results/nm-joc-b1", "/bench/results/nm-sa-b1")
    # same test ids on both sides, so the cache is the only difference between big and small
    ids = set(load("/bench/results/nm-joc-b1")) & set(load("/bench/results/nm-sa-b1"))
    big = pair("/bench/results/nm-joc-full", "/bench/results/nm-state-actor", only=ids)
    json.dump({"cache_bytes": {"big": 1073741824, "small": 8388608},
               "big": big, "small": small},
              sys.stdout, indent=1, sort_keys=True)
