#!/usr/bin/env python3
"""Answer every sampled key over JSON-RPC at the latest block, one JSON line per sample.

Run once on the untreated jochemnet and once on the rebuilt one; the two outputs must be equal
line for line. eth_getProof walks the commitment trie, so equal proofs mean equal trie paths, not
just equal values.

Usage: rpc-sample.py <port> <samples.txt> <out.jsonl>
samples.txt lines: "<all|db> <accounts|storage|code|commitment> <hexkey>"
"""
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PORT, SAMPLES, OUT = int(sys.argv[1]), sys.argv[2], sys.argv[3]
URL = f"http://127.0.0.1:{PORT}"


def batch(calls):
    body = json.dumps([{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)])
    req = urllib.request.Request(URL, data=body.encode(), headers={"content-type": "application/json"})
    res = {r["id"]: r for r in json.load(urllib.request.urlopen(req, timeout=300))}
    return [res[i].get("result", res[i].get("error")) for i in range(len(calls))]


def calls_for(domain, key):
    if domain == "accounts":
        a = "0x" + key[:40]
        return [("eth_getBalance", [a, "latest"]), ("eth_getTransactionCount", [a, "latest"]),
                ("eth_getProof", [a, [], "latest"])]
    if domain == "storage":
        a, s = "0x" + key[:40], "0x" + key[40:104]
        return [("eth_getStorageAt", [a, s, "latest"]), ("eth_getProof", [a, [s], "latest"])]
    if domain == "code":
        return [("eth_getCode", ["0x" + key[:40], "latest"])]
    return []


lines = [l.split() for l in open(SAMPLES) if l.strip()]
work = [(src, dom, key) for src, dom, key in lines if dom != "commitment"]
head = batch([("eth_getBlockByNumber", ["latest", False])])[0]


def run(item):
    src, dom, key = item
    return {"src": src, "domain": dom, "key": key, "answers": batch(calls_for(dom, key))}


with ThreadPoolExecutor(16) as ex, open(OUT, "w") as out:
    out.write(json.dumps({"head": {k: head[k] for k in ("number", "hash", "stateRoot")}}) + "\n")
    for r in ex.map(run, work):
        out.write(json.dumps(r, sort_keys=True) + "\n")
print(f"{len(work)} samples answered at block {int(head['number'], 16)}")
