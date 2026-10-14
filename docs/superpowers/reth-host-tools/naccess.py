#!/usr/bin/env python3
"""Accounts accessed per account_access test = sum over txs of (end - start + 1) from calldata.
Prints per family (160M, overhead_baseline_False) the access count and BAL size, for both fixture sets."""
import json
import re

SA = "/root/bench/reth/fixtures/sa-v2-full/nethermind/blockchain_tests_stateful_engine/for_amsterdam_at_0160M/stateful/bloatnet/account_query/account_access.json"
JO = "/root/.cache/benchmarkoor/eest-url/6142626aac06abc4/fixtures/benchmarkoor-build-artifacts/eest-payloads/geth/blockchain_tests_stateful_engine/for_amsterdam_at_0160M/stateful/bloatnet/account_query/account_access.json"


def rlp(b, i=0):
    """Decode one RLP item at b[i:]; return (item, next_index)."""
    p = b[i]
    if p < 0x80:
        return b[i:i + 1], i + 1
    if p < 0xb8:
        n = p - 0x80
        return b[i + 1:i + 1 + n], i + 1 + n
    if p < 0xc0:
        ln = p - 0xb7
        n = int.from_bytes(b[i + 1:i + 1 + ln], "big")
        return b[i + 1 + ln:i + 1 + ln + n], i + 1 + ln + n
    if p < 0xf8:
        n, s = p - 0xc0, i + 1
    else:
        ln = p - 0xf7
        n, s = int.from_bytes(b[i + 1:i + 1 + ln], "big"), i + 1 + ln
    out, j = [], s
    while j < s + n:
        x, j = rlp(b, j)
        out.append(x)
    return out, s + n


def accesses(test):
    tot = 0
    for tx in test["engineNewPayloads"][-1]["params"][0]["transactions"]:
        b = bytes.fromhex(tx[2:])
        f, _ = rlp(b, 1) if b[0] < 0x7f else rlp(b, 0)  # typed tx: skip type byte
        data = next((x for x in f if isinstance(x, bytes) and len(x) == 64), b"")
        if len(data) == 64:
            s, e = int.from_bytes(data[:32], "big"), int.from_bytes(data[32:], "big")
            tot += e - s + 1
    return tot


for name, path in (("S", SA), ("J", JO)):
    d = json.load(open(path))
    for k, t in sorted(d.items()):
        if "overhead_baseline_False" not in k:
            continue
        op = re.search(r"opcode_([A-Z0-9]+)", k).group(1)
        mode = re.search(r"AccountMode\.([A-Z_]+)", k).group(1)
        v = re.search(r"value_sent_(\d)", k).group(1)
        if op in ("BALANCE", "CALL") :
            print(name, f"{op} {mode} v{v}", accesses(t), "bal_len", len(t["engineNewPayloads"][-1]["params"][0]["blockAccessList"]))
