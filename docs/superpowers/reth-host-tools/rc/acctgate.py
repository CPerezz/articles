#!/usr/bin/env python3
"""Account-shape gate for a --account-model=mainnet store against jochemnet.
usage: acctgate.py <acctsize new> <acctsize J> <acctkind new> <acctkind J>
Inputs are rc/acctsize.py (200k uniform account samples) and rc/acctkind.py (20k code-bearing rows).
Prints J vs new for each metric; exits 1 if any is out of range."""
import json
import sys

sn, sj, kn, kj = (json.load(open(p)) for p in sys.argv[1:5])


def tvd(a, b, na, nb):
    keys = set(a) | set(b)
    return sum(abs(a.get(k, 0) / na - b.get(k, 0) / nb) for k in keys) / 2


def share(s, k, kind):
    """Share of all accounts in one code-bearing kind: acctkind's share of coded rows x acctsize's coded share."""
    return k["kinds"].get(kind, 0) * s["code_hash_share"]


rows = [  # (metric, J, new, allowed |new - J|)
    ("value bytes, mean", sj["value_len_mean"], sn["value_len_mean"], 0.03 * sj["value_len_mean"]),
    ("rows with a code hash", sj["code_hash_share"], sn["code_hash_share"], 0.02),
    ("storage-less contracts", share(sj, kj, "contract"), share(sn, kn, "contract"), 0.01),
    ("delegations without storage", share(sj, kj, "delegation"), share(sn, kn, "delegation"), 0.0015),
    # Storage accounts follow the slot budget and the storage model, not the account model: the
    # 20/10/70 split gives J's account count with ~4% more slots, hence ~8% more storage accounts.
    ("contracts with storage", share(sj, kj, "contract +storage"), share(sn, kn, "contract +storage"), 0.015),
    ("nonce length TVD", 0, tvd(sn["nonce_len_hist"], sj["nonce_len_hist"], sn["n"], sj["n"]), 0.03),
    ("balance length TVD", 0, tvd(sn["balance_len_hist"], sj["balance_len_hist"], sn["n"], sj["n"]), 0.03),
]
bad = 0
for name, j, n, tol in rows:
    ok = abs(n - j) <= tol
    bad += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name:30} J {j:>9.4f}  new {n:>9.4f}  (±{tol:.4f})")
sys.exit(1 if bad else 0)
