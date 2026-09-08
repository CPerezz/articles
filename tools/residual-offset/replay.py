#!/usr/bin/env python3
"""Round 15: replay one real benchmark block against each store and count what
geth actually fetches.

Every probe so far used synthetic addresses. This sends the fixture's own
engine_newPayload - the exact block the benchmark measured - and diffs geth's
pathdb meters around it. Counters, not milliseconds: the two stores are on
different media.

usage: replay.py <bundle_dir> <label>
"""
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

AUTH = "http://127.0.0.1:8551"
MET = "http://127.0.0.1:6060/debug/metrics"
WANT = "opcode_BALANCE-value_sent_0-account_mode_AccountMode.EXISTING_CONTRACT_MINIMAL"
KEEP = ("pathdb/clean/node/hit", "pathdb/clean/node/miss",
        "pathdb/clean/state/hit", "pathdb/clean/state/miss",
        "pathdb/dirty/node/hit", "pathdb/dirty/node/miss",
        "pathdb/dirty/state/hit", "pathdb/dirty/state/miss",
        "pathdb/state/account/exist/total", "pathdb/state/account/exist/disk",
        "pathdb/state/account/inex/total", "pathdb/state/account/inex/disk",
        "eth/db/chaindata/cache/block/hit", "eth/db/chaindata/cache/block/miss")

SECRET = bytes.fromhex("00" * 31 + "2a")


def jwt():
    import hmac
    import base64

    def b64(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=")
    hdr = b64(b'{"alg":"HS256","typ":"JWT"}')
    pay = b64(json.dumps({"iat": int(time.time())}).encode())
    sig = b64(hmac.new(SECRET, hdr + b"." + pay, hashlib.sha256).digest())
    return (hdr + b"." + pay + b"." + sig).decode()


def call(method, params, url=AUTH):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params}).encode()
    req = urllib.request.Request(url, body, {
        "Content-Type": "application/json", "Authorization": "Bearer " + jwt()})
    with urllib.request.urlopen(req, timeout=1800) as fh:
        return json.load(fh)


def metrics():
    with urllib.request.urlopen(MET, timeout=60) as fh:
        raw = json.load(fh)
    return {k: raw.get(k + ".count", raw.get(k + ".value", 0)) or 0 for k in KEEP}


def main():
    bundle, label = sys.argv[1], sys.argv[2]
    hits = glob.glob(f"{bundle}/**/for_amsterdam_at_0160M/**/account_access.json",
                     recursive=True)
    d = json.load(open(hits[0]))
    name = sorted(k for k in d if WANT in k)[0]
    case = d[name]
    pl = case["engineNewPayloads"][0]
    params = pl["params"]
    method = pl.get("method", "engine_newPayloadV5")

    time.sleep(12)
    before = metrics()
    t0 = time.time()
    r = call(method, params)
    wall = time.time() - t0
    time.sleep(12)
    after = metrics()

    delta = {k: after[k] - before[k] for k in KEEP}
    status = (r.get("result") or {}).get("status", r.get("error"))
    nodes = (delta["pathdb/clean/node/hit"] + delta["pathdb/clean/node/miss"]
             + delta["pathdb/dirty/node/hit"])
    states = (delta["pathdb/clean/state/hit"] + delta["pathdb/clean/state/miss"]
              + delta["pathdb/dirty/state/hit"])
    blocks = (delta["eth/db/chaindata/cache/block/hit"]
              + delta["eth/db/chaindata/cache/block/miss"])
    json.dump({
        "label": label, "status": status, "wall_s": round(wall, 1),
        "trie_node_fetches": nodes,
        "flat_state_reads": states,
        "account_exist_total": delta["pathdb/state/account/exist/total"],
        "account_exist_from_disk": delta["pathdb/state/account/exist/disk"],
        "account_inex_total": delta["pathdb/state/account/inex/total"],
        "pebble_block_lookups": blocks,
        "pebble_block_misses": delta["eth/db/chaindata/cache/block/miss"],
        "nodes_per_account": round(nodes / max(delta["pathdb/state/account/exist/total"]
                                               + delta["pathdb/state/account/inex/total"], 1), 3),
        "blocks_per_node": round(blocks / max(nodes, 1), 3),
        "raw": delta,
    }, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
