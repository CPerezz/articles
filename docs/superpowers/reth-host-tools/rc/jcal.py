#!/usr/bin/env python3
"""Calibration sample of a reth store's storage population, read-only (pread).
usage: jcal.py <mdbx.dat> <n descents> <out.json>
Random-key descents land on accounts uniformly (keccak keys are uniform), so:
- HashedStorages: slots per storage-bearing account, exact for every node kind (single value, inline
  dup subpage, nested tree), and slot value lengths (compact, leading zeros stripped).
- HashedAccounts: share of accounts carrying a bytecode hash (contracts and 7702 EOAs)."""
import bisect
import json
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/root/bench/reth/rc")
import lib  # noqa: E402

db = lib.DB(sys.argv[1])
N = int(sys.argv[2])
T = db.tables()


def land(tree, key):
    _, _, _, path = db.search(tree, key)
    p = db.page(path[-1])
    ns = list(lib.nodes(p))
    keys = [p[o:o + k] for d, f, k, o in ns]
    i = min(bisect.bisect_left(keys, key), len(ns) - 1)
    return p, ns[i]


def storage(seed):
    p, (d, f, k, o) = land(T["HashedStorages"], random.Random(seed).randbytes(32))
    if f & lib.N_TREE:
        nt = lib.tree(p, o + k)
        lens = []
        if nt["height"] == 1:  # a single nested leaf: read its items' value lengths too
            q = db.page(nt["root"])
            lens = [kk - 32 for dd, ff, kk, oo in lib.nodes(q)]
        return "nested", nt["items"], lens
    if f & lib.N_DUP:  # inline subpage: items are stored as keys, data empty
        sub = list(lib.nodes(p, o + k))
        return "inline", len(sub), [kk - 32 for dd, ff, kk, oo in sub]
    return "single", 1, [d - 32]


def account(seed):
    p, (d, f, k, o) = land(T["HashedAccounts"], random.Random(seed).randbytes(32))
    b = p[o + k:o + k + d]
    hdr = b[0] | b[1] << 8
    nonce_n, bal_n = hdr & 0xF, (hdr >> 4) & 0x3F
    rest = d - 2 - nonce_n - bal_n
    return rest  # 0 = no code hash, 32 = code hash, anything else = header decoded wrongly


with ThreadPoolExecutor(32) as pool:
    st = list(pool.map(storage, range(1, N + 1)))
    ac = list(pool.map(account, range(10**6, 10**6 + N)))

items = sorted(n for _, n, _ in st)
q = lambda p: items[min(len(items) - 1, int(p * len(items)))]
lens = Counter(x for _, _, ls in st for x in ls)
tot = sum(items)
buckets = {"1": (1, 1), "2-28": (2, 28), "29-4000": (29, 4000), ">4000": (4001, 10**12)}
out = {
    "n": N,
    "kinds": dict(Counter(kind for kind, _, _ in st)),
    "slots_per_account": {"mean": tot / len(items), **{f"p{int(p*1000)/10:g}": q(p) for p in (0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 0.999)}, "max": items[-1]},
    "buckets": {name: {"accounts": sum(lo <= n <= hi for n in items) / len(items),
                       "slots": sum(n for n in items if lo <= n <= hi) / tot} for name, (lo, hi) in buckets.items()},
    "quantiles_1000": [q(i / 1000) for i in range(1000)],
    "value_len_hist": dict(sorted(lens.items())),
    "value_len_mean": sum(k * v for k, v in lens.items()) / sum(lens.values()),
    "accounts": {"code_hash_share": sum(r == 32 for r in ac) / N, "bad_header": sum(r not in (0, 32) for r in ac)},
}
json.dump(out, open(sys.argv[3], "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "quantiles_1000"}, indent=1))
