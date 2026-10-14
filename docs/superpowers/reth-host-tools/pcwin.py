#!/usr/bin/env python3
"""Per test step: pages inserted into the page cache for mdbx.dat and for the loop backing image.
usage: pcwin.py <rid>   (reads logs/<rid>.log, logs/<rid>.pc; writes probe/<rid>-<n>.pages per test)"""
import datetime
import re
import sys
from collections import Counter

rid = sys.argv[1]
D = "/root/bench/reth/"
first = open(D + f"logs/{rid}.pc").readline()
ino_m, ino_b = map(int, re.findall(r"=(\d+)", first))

wins, cur = [], None
for l in open(D + f"logs/{rid}.log", errors="ignore"):
    l = re.sub(r"\x1b\[[0-9;]*m", "", l)
    m = re.search(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+)Z\s+\w+\s+\|\s+(Running test step|Test completed successfully|Test failed).*?test=(\S+)", l)
    if not m:
        continue
    t = datetime.datetime.fromisoformat(m.group(1)).replace(tzinfo=datetime.timezone.utc).timestamp()
    if m.group(2) == "Running test step":
        cur = (t, m.group(3))
    elif cur:
        wins.append((cur[0], t, cur[1]))
        cur = None

ev = []
for l in open(D + f"logs/{rid}.pc"):
    p = l.split()
    if len(p) == 4 and p[0][0].isdigit():
        ev.append((float(p[0]), int(p[1]), int(p[2]), int(p[3])))

for n, (a, b, name) in enumerate(wins):
    pages_m, cnt_b = set(), 0
    for t, ino, idx, order in ev:
        if a - 0.5 <= t <= b + 0.5:
            if ino == ino_m:
                pages_m.update(range(idx, idx + (1 << order)))
            elif ino == ino_b:
                cnt_b += 1 << order
    short = re.sub(r".*::test_", "", name)
    short = re.sub(r"fork_Amsterdam-blockchain_test_stateful_engine-|cache_strategy_CacheStrategy.NO_CACHE-|benchmark-gas-value_", "", short)
    open(D + f"probe/{rid}-{n}.pages", "w").write("\n".join(map(str, sorted(pages_m))) + "\n")
    print(f"{rid}-{n} {b - a:6.2f}s mdbx_pages={len(pages_m):8d} ({len(pages_m) * 4 / 1024:7.0f} MB) backing_pages={cnt_b:8d}  {short}")
