#!/usr/bin/env python3
"""Split each test's forkchoiceUpdated time the way Erigon's own log does.

Erigon logs `Timings: Forkchoice flush+commit=<d> prune=<d>` once per FCU. benchmarkoor
recreates the container for every test, so each test's FCUs are the timing lines between its
start and the next test's. The last one belongs to the measured block.

Usage on the box: collect_fcu.py <series-tag>... > fcu.json   (e.g. joc-D1 joc-E1 sa-E1)
"""
import bisect
import collections
import datetime as dt
import glob
import json
import re
import sys

R = "/bench/results/"
TIMING = re.compile(r"\[(\d\d)-(\d\d)\|([\d:.]+)\] Timings: Forkchoice\s+flush\+commit=(\S+) prune=(\S+)")
UNIT = {"µs": 1e-6, "ms": 1e-3, "s": 1.0, "m": 60.0}


def secs(s):
    # Erigon rounds anything over a second to whole seconds ("4s"), so those values are coarse.
    m = re.match(r"([\d.]+)(µs|ms|s|m)", s)
    return float(m.group(1)) * UNIT[m.group(2)]


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def split(tag):
    run = sorted(glob.glob(f"{R}er-{tag}-*/runs/*/"))[-1]
    first = {}
    for line in open(run + "benchmarkoor.log", errors="replace"):
        m = re.search(r"(\d{4}-\d\d-\d\dT[\d:.]+)Z.*? index=\d+/\d+ .*?test=(\S+)", line)
        if m and m.group(2) not in first:
            first[m.group(2)] = dt.datetime.fromisoformat(m.group(1))
    starts = sorted((t, name) for name, t in first.items())
    times = [t for t, _ in starts]
    year = times[0].year
    per = collections.defaultdict(list)
    for line in open(run + "container.log", errors="replace"):
        m = TIMING.search(line)
        if not m:
            continue
        t = dt.datetime.fromisoformat(f"{year}-{m.group(1)}-{m.group(2)}T{m.group(3)}")
        i = bisect.bisect_right(times, t) - 1
        if i >= 0:
            per[starts[i][1]].append((secs(m.group(4)), secs(m.group(5))))
    tests = {name: {"fcus": len(seq), "commit_s": seq[-1][0], "prune_s": seq[-1][1],
                    "first_prune_s": seq[0][1]} for name, seq in per.items()}
    return {"run": run, "n_tests": len(starts), "tests": tests}


def main():
    out = {tag: split(tag) for tag in sys.argv[1:]}
    for tag, r in out.items():
        assert len(r["tests"]) == r["n_tests"], f"{tag}: {r['n_tests'] - len(r['tests'])} tests have no FCU timing"
        ts = r["tests"].values()
        print(f"{tag}: {len(r['tests'])} tests, measured-FCU commit median {median(t['commit_s'] for t in ts):.3f} s, "
              f"first-FCU prune median {median(t['first_prune_s'] for t in ts):.3f} s", file=sys.stderr)
    json.dump(out, sys.stdout, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
