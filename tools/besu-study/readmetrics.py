#!/usr/bin/env python3
"""Per-account-mode read counters from a joined metrics file.

`miss/total` is the answer to gap B: the fraction of account lookups that found nothing in the
flat database. If the NON_EXISTING probe addresses really are absent from a store, that store's
NON_EXISTING rows should sit near 1.0; if the generated store has filled those addresses, its
rows should sit near 0.
"""
import collections
import json
import statistics as st
import sys

a = json.load(open(sys.argv[1]))
label = sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]

g = collections.defaultdict(list)
for r in a:
    if "mode" in r and r.get("reads"):
        g[r["mode"]].append(r)

print(f"--- {label} ---")
print(f'{"account_mode":<28}{"n":>4}{"reads":>12}{"missing":>12}{"miss/tot":>10}'
      f'{"bytes":>14}{"B/read":>9}')
for k, v in sorted(g.items()):
    rd = st.median([x["reads"] for x in v])
    ms = st.median([x["reads_missing"] for x in v])
    by = st.median([x["disk_read_bytes"] for x in v])
    print(f"{k:<28}{len(v):>4}{rd:>12.0f}{ms:>12.0f}{(ms/rd if rd else 0):>10.3f}"
          f"{by:>14.0f}{(by/rd if rd else 0):>9.0f}")
