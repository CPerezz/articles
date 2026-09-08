#!/usr/bin/env python3
"""Round-1 workload: identical logical reads against whichever datadir the
node was booted on, measured with geth's pathdb meters.

The addresses are a fixed pseudorandom set, so they exist in neither store.
That is deliberate: it needs no trie preimages (state-actor has none), it is
byte-identical work on both arms, and it exercises the absence path - the
NON_EXISTING category, where the residual offset is just as large (1.247x)
as everywhere else.
"""
import hashlib
import json
import sys
import time
import urllib.request

RPC = "http://127.0.0.1:8545"
MET = "http://127.0.0.1:6060/debug/metrics"
N = 300
KEEP = ("pathdb/state/account/inex/total", "pathdb/state/account/inex/disk",
        "pathdb/state/account/exist/total", "pathdb/state/account/exist/disk",
        "pathdb/clean/node/hit", "pathdb/clean/node/miss",
        "pathdb/clean/state/hit", "pathdb/clean/state/miss",
        "pathdb/dirty/node/hit", "pathdb/dirty/node/miss",
        "pathdb/dirty/state/hit", "pathdb/dirty/state/miss")


def rpc(method, params):
    req = urllib.request.Request(
        RPC, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                         "params": params}).encode(),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as fh:
        return json.load(fh)


def metrics():
    with urllib.request.urlopen(MET, timeout=30) as fh:
        raw = json.load(fh)
    out = {}
    for k in KEEP:
        v = raw.get(k + ".count", raw.get(k))
        if isinstance(v, dict):
            out[k] = v.get("count", v.get("Count", v.get("value")))
        elif v is not None:
            out[k] = v
    return out


def addrs(n):
    return ["0x" + hashlib.sha256(f"residual-offset-probe-{i}".encode())
            .hexdigest()[:40] for i in range(n)]


def main():
    label = sys.argv[1]
    a = addrs(N)
    before = metrics()
    depths, t0 = [], time.time()
    for addr in a:
        r = rpc("eth_getProof", [addr, [], "latest"])
        if "result" in r:
            depths.append(len(r["result"]["accountProof"]))
    wall = time.time() - t0
    after = metrics()
    delta = {k: (after.get(k, 0) or 0) - (before.get(k, 0) or 0) for k in KEEP}
    inex_t = delta.get("pathdb/state/account/inex/total", 0)
    inex_d = delta.get("pathdb/state/account/inex/disk", 0)
    nodes = (delta.get("pathdb/clean/node/hit", 0)
             + delta.get("pathdb/clean/node/miss", 0)
             + delta.get("pathdb/dirty/node/hit", 0))
    json.dump({
        "label": label, "n_reads": len(depths), "wall_s": round(wall, 2),
        "ms_per_read": round(1000 * wall / max(len(depths), 1), 3),
        "proof_depth_min": min(depths) if depths else None,
        "proof_depth_median": sorted(depths)[len(depths) // 2] if depths else None,
        "proof_depth_max": max(depths) if depths else None,
        "absence_reads_total": inex_t,
        "absence_reads_from_disk": inex_d,
        "absence_disk_fraction": round(inex_d / inex_t, 4) if inex_t else None,
        "trie_nodes_fetched": nodes,
        "nodes_per_read": round(nodes / max(len(depths), 1), 2),
        "clean_node_hit": delta.get("pathdb/clean/node/hit", 0),
        "clean_node_miss": delta.get("pathdb/clean/node/miss", 0),
        "raw_delta": delta,
    }, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
