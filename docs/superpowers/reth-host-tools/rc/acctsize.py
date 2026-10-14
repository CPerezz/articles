#!/usr/bin/env python3
"""Account-row sizes of a reth store, read-only (pread): random-key descents into HashedAccounts land
on accounts uniformly (keccak keys are uniform). Per sampled row: value bytes, nonce bytes, balance
bytes, code-hash flag (reth's compact Account: 2-byte header with nonce length in bits 0-3 and balance
length in bits 4-9, then nonce, balance, optional 32-byte code hash), plus the nonce and balance
values themselves.
usage: acctsize.py <mdbx.dat> <n descents> <out.json>"""
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
T = db.tables()["HashedAccounts"]


def sample(seed):
    key = random.Random(seed).randbytes(32)
    _, _, _, path = db.search(T, key)
    p = db.page(path[-1])
    ns = list(lib.nodes(p))
    keys = [p[o:o + k] for d, f, k, o in ns]
    d, f, k, o = ns[min(bisect.bisect_left(keys, key), len(ns) - 1)]
    b = p[o + k:o + k + d]
    hdr = b[0] | b[1] << 8
    nn, bn = hdr & 0xF, (hdr >> 4) & 0x3F
    code = d - 2 - nn - bn
    nonce = int.from_bytes(b[2:2 + nn], "big") if nn else 0
    bal = int.from_bytes(b[2 + nn:2 + nn + bn], "big") if bn else 0
    return d, nn, bn, code, nonce, bal


with ThreadPoolExecutor(32) as pool:
    rows = list(pool.map(sample, range(7_000_000, 7_000_000 + N)))

H = lambda xs: dict(sorted(Counter(xs).items()))
eoa = [r for r in rows if r[3] == 0]
coded = [r for r in rows if r[3] == 32]
mean = lambda xs: sum(xs) / len(xs) if xs else None
out = {
    "n": N,
    "bad_header": sum(r[3] not in (0, 32) for r in rows),
    "code_hash_share": len(coded) / N,
    "value_len_mean": mean([r[0] for r in rows]),
    "value_len_hist": H(r[0] for r in rows),
    "nonce_len_hist": H(r[1] for r in rows),
    "balance_len_hist": H(r[2] for r in rows),
    "no_code": {"share": len(eoa) / N, "value_len_mean": mean([r[0] for r in eoa]),
                "nonce_len_mean": mean([r[1] for r in eoa]), "balance_len_mean": mean([r[2] for r in eoa]),
                "nonce_zero": mean([r[4] == 0 for r in eoa]), "balance_zero": mean([r[5] == 0 for r in eoa])},
    "with_code": {"share": len(coded) / N, "value_len_mean": mean([r[0] for r in coded]),
                  "nonce_len_mean": mean([r[1] for r in coded]), "balance_len_mean": mean([r[2] for r in coded]),
                  "nonce_zero": mean([r[4] == 0 for r in coded]), "balance_zero": mean([r[5] == 0 for r in coded])},
    "nonce_quantiles": {q: sorted(r[4] for r in rows)[int(q * (N - 1))] for q in (0.5, 0.9, 0.99, 0.999)},
    "balance_wei_quantiles": {q: str(sorted(r[5] for r in rows)[int(q * (N - 1))]) for q in (0.1, 0.5, 0.9, 0.99)},
}
json.dump(out, open(sys.argv[3], "w"), indent=1)
print(json.dumps(out, indent=1))
