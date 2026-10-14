#!/usr/bin/env python3
"""Storage-shape gate for a --storage-model=mainnet store against jochemnet.
usage: distgate.py <jwalk json of the new store> <jwalk json of J> <state-actor manifest>
Both walks include the spec-planted bloated contract, so the histograms are compared as is.
Prints J vs new for each metric; exits 1 if any bounded metric is out of range."""
import json
import sys

J_ACCOUNTS = 354_792_873  # J HashedAccounts entries (probe/joc-stats.txt)


def summ(path):
    w = json.load(open(path))
    h = {int(k): v for k, v in w["hist"].items()}
    n = sum(h.values())
    s = sum(k * v for k, v in h.items())
    ks = sorted(h)

    def q(p):
        a = 0
        for k in ks:
            a += h[k]
            if a >= p * n:
                return k

    def share(lo, hi):
        return sum(v for k, v in h.items() if lo <= k <= hi) / n

    vl = {int(k): v for k, v in w["value_len_hist"].items()}
    tv = sum(vl.values()) or 1
    return {"storage_accounts": n, "slots": s, "p50": q(.5), "p90": q(.9), "p99": q(.99), "p999": q(.999),
            "one_slot": share(1, 1), "le28": share(1, 28), "mid_29_4000": share(29, 4000),
            "main_leaves_per_account": w["leaves"] / n, "value20": vl.get(20, 0) / tv, "value32": vl.get(32, 0) / tv,
            # Scale-free tail: contracts above 1M slots per million storage accounts (J: 116 incl. the bloated one).
            "over_1m_per_m": sum(v for k, v in h.items() if k >= 10**6) / n * 1e6,
            "over_2_24": sum(v for k, v in h.items() if k > 2**24), "max_slots": ks[-1]}


new, j = summ(sys.argv[1]), summ(sys.argv[2])
r = json.load(open(sys.argv[3]))["result"]
accounts = r["accounts_created"] + r["contracts_created"]
bounds = {  # (lo, hi) on the new store; None = informational
    "p50": (1, 1), "p90": (8, 12), "p99": (120, 190),
    "one_slot": (0.53, 0.57), "le28": (0.96, 0.98), "mid_29_4000": (0.024, 0.032),
    "value20": (0.47, 0.52), "over_1m_per_m": (3.7, 5.5),
    "over_2_24": (4, 9),  # J 5; the alpha=1 tail at ~120 giants gives 6, plus the bloated contract
}
bad = 0
for k in new:
    lo_hi = bounds.get(k)
    ok = lo_hi is None or lo_hi[0] <= new[k] <= lo_hi[1]
    bad += not ok
    tag = "info" if lo_hi is None else ("ok  " if ok else "FAIL")
    print(f"{tag} {k:24} J {j[k]!s:>16}  new {new[k]!s:>16}  {lo_hi or ''}")
ok = abs(accounts / J_ACCOUNTS - 1) <= 0.001
bad += not ok
print(f"{'ok  ' if ok else 'FAIL'} accounts                 J {J_ACCOUNTS:>16}  new {accounts:>16}  (±0.1%)")
sys.exit(1 if bad else 0)
