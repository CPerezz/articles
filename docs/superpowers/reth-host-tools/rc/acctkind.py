#!/usr/bin/env python3
"""What the code-bearing accounts of a reth store are, read-only (pread). Random-key descents into
HashedAccounts land on accounts uniformly; for each row with a code hash, look the code up in Bytecodes
(EIP-7702 designator = 23-byte code starting 0xef0100) and the account up in HashedStorages (has
storage or not). Also records code-hash reuse (how many sampled accounts share a code hash).
usage: acctkind.py <mdbx.dat> <coded rows wanted> <out.json>"""
import bisect
import json
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/root/bench/reth/rc")
import lib  # noqa: E402

db = lib.DB(sys.argv[1])
WANT = int(sys.argv[2])
T = db.tables()


def find(tree, key):
    """(node data size, node flags, page, data offset) of the exact key, or None."""
    _, _, _, path = db.search(tree, key)
    p = db.page(path[-1])
    for d, f, k, o in lib.nodes(p):
        if p[o:o + k] == key:
            return d, f, p, o + k
    return None


def sample(seed):
    key = random.Random(seed).randbytes(32)
    _, _, _, path = db.search(T["HashedAccounts"], key)
    p = db.page(path[-1])
    ns = list(lib.nodes(p))
    keys = [p[o:o + k] for d, f, k, o in ns]
    d, f, k, o = ns[min(bisect.bisect_left(keys, key), len(ns) - 1)]
    b = p[o + k:o + k + d]
    hdr = b[0] | b[1] << 8
    nn, bn = hdr & 0xF, (hdr >> 4) & 0x3F
    if d - 2 - nn - bn != 32:
        return None
    acct_key, code_hash = p[o:o + k], bytes(b[2 + nn + bn:])
    code = find(T["Bytecodes"], code_hash)
    has_storage = find(T["HashedStorages"], acct_key) is not None
    if code is None:
        return ("code-missing", has_storage, 0, code_hash)
    cd, cf, cp, co = code
    head = bytes(cp[co:co + min(cd, 40)]) if not (cf & 1) else b""  # flag 1 = N_BIG (overflow page)
    kind = "delegation" if b"\xef\x01\x00" in head[:8] and cd <= 40 else "contract"
    return (kind, has_storage, cd, code_hash)


rows, seed = [], 9_000_000
with ThreadPoolExecutor(32) as pool:
    while len(rows) < WANT:
        batch = list(pool.map(sample, range(seed, seed + 20000)))
        seed += 20000
        rows += [r for r in batch if r]
rows = rows[:WANT]
kinds = Counter((r[0], r[1]) for r in rows)
reuse = Counter(r[3] for r in rows)
out = {
    "coded_rows": len(rows),
    "kinds": {f"{k}{' +storage' if s else ''}": v / len(rows) for (k, s), v in sorted(kinds.items())},
    "contract_code_bytes_quantiles": {q: sorted(r[2] for r in rows if r[0] == "contract")[int(q * (sum(1 for r in rows if r[0] == "contract") - 1))]
                                      for q in (0.1, 0.5, 0.9, 0.99)},
    "distinct_code_hashes": len(reuse),
    "accounts_per_distinct_code": len(rows) / len(reuse),
    "top_code_shares": [round(v / len(rows), 4) for _, v in reuse.most_common(5)],
}
json.dump(out, open(sys.argv[3], "w"), indent=1)
print(json.dumps(out, indent=1))
