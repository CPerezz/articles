#!/usr/bin/env python3
"""Verify a filled payload set before anything is measured against it.

The orchestrator's inline version of this crashed on the pre_run fixture, whose top level is a
single object rather than a mapping of test ids, and because the reordered script dropped the
`|| exit 1` after the heredoc the campaign marked fill-ok regardless. This is the check that
should have run.
"""
import collections
import glob
import json
import sys

root = sys.argv[1] if len(sys.argv) > 1 else \
    "/data/fixtures/v3-95e5a10/geth/blockchain_tests_stateful_engine"
fx = sorted(glob.glob(root + "/**/*.json", recursive=True))
pre = [p for p in fx if "/pre_run/" in p]
tst = [p for p in fx if "/pre_run/" not in p]
print(f"files: {len(fx)}  (pre_run {len(pre)}, test {len(tst)})")

ids, anchors, budgets, gas = set(), collections.Counter(), set(), {}
for p in tst:
    if "for_amsterdam_at_" in p:
        budgets.add(p.split("for_amsterdam_at_")[1].split("/")[0])
    for k, t in json.load(open(p)).items():
        if not isinstance(t, dict):
            continue
        ids.add(k)
        anchors[t.get("snapshotBlockHash")] += 1
        if "benchmarkGasUsed" in t:
            gas[k] = int(t["benchmarkGasUsed"], 16)

acc = [i for i in ids if "test_account_access" in i]
print(f"gas budgets       : {len(budgets)} -> {sorted(budgets)}")
print(f"test ids          : {len(ids)}")
print(f"test_account_access: {len(acc)}")
print(f"distinct anchors  : {len(anchors)}")
for a, n in anchors.most_common():
    print(f"   {a} x{n}")
for p in pre:
    d = json.load(open(p))
    keys = list(d)[:8]
    print(f"pre_run {p.split('/')[-1]}: keys={keys}")

checks = [
    ("11 gas budgets", len(budgets) == 11),
    ("exactly one anchor", len(anchors) == 1),
    (">=300 account_access ids", len(acc) >= 300),
    ("gas recorded per test", len(gas) >= len(ids) * 0.9),
]
print()
for name, ok in checks:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
bad = [n for n, ok in checks if not ok]
print("\nORACLE: " + ("PASS" if not bad else "FAIL on " + ", ".join(bad)))
sys.exit(1 if bad else 0)
