#!/usr/bin/env python3
"""Exact per-account slot counts of a reth store: walks every leaf of HashedStorages' main tree
(nested trees are counted from their tree record, not walked). Read-only, pread.
usage: jwalk.py <mdbx.dat> <out.json>
Also a value-length histogram from 1% of the leaves."""
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/root/bench/reth/rc")
import lib  # noqa: E402

db = lib.DB(sys.argv[1])
t = db.tables()["HashedStorages"]
leaves = db.levels(t)[-1]


def leaf(i_pg):
    i, pg = i_pg
    p = db.page(pg)
    counts, lens = [], []
    for d, f, k, o in lib.nodes(p):
        if f & lib.N_TREE:
            counts.append(lib.tree(p, o + k)["items"])
        elif f & lib.N_DUP:
            sub = list(lib.nodes(p, o + k))
            counts.append(len(sub))
            if i % 100 == 0:
                lens += [kk - 32 for dd, ff, kk, oo in sub]
        else:
            counts.append(1)
            if i % 100 == 0:
                lens.append(d - 32)
    return counts, lens


hist, vlen, n = Counter(), Counter(), 0
with ThreadPoolExecutor(32) as pool:
    for counts, lens in pool.map(leaf, enumerate(leaves), chunksize=256):
        hist.update(counts)
        vlen.update(lens)
accounts, slots = sum(hist.values()), sum(k * v for k, v in hist.items())
json.dump({"leaves": len(leaves), "accounts": accounts, "slots": slots, "catalog_items": t["items"],
           "hist": {str(k): v for k, v in sorted(hist.items())}, "value_len_hist": dict(sorted(vlen.items()))},
          open(sys.argv[2], "w"))
top = sorted(hist.items(), reverse=True)[:15]
print(json.dumps({"leaves": len(leaves), "accounts": accounts, "slots": slots, "catalog_items": t["items"],
                  "mean": slots / accounts, "top": top}))
