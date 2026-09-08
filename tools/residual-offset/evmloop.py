#!/usr/bin/env python3
"""Round 16: run the benchmark's own EVM loop against each store.

The fixture block cannot simply be replayed - it is anchored two blocks past
the promoted head. But the loop itself can: extract the receiver-walking
runtime bytecode straight out of the fixture's setup initcode, install it with
an eth_call state override, and hand it the same (start, end) calldata. That
executes the identical opcode sequence over that arm's real CREATE2 receivers,
reading real accounts out of the real store, with no chain surgery.

Counters, not milliseconds - the stores sit on different media.
"""
import glob
import json
import sys
import time
import urllib.request

RPC = "http://127.0.0.1:8545"
MET = "http://127.0.0.1:6060/debug/metrics"
KEEP = ("pathdb/clean/node/hit", "pathdb/clean/node/miss",
        "pathdb/clean/state/hit", "pathdb/clean/state/miss",
        "pathdb/dirty/node/hit", "pathdb/dirty/node/miss",
        "pathdb/state/account/exist/total", "pathdb/state/account/exist/disk",
        "pathdb/state/account/inex/total", "pathdb/state/account/inex/disk",
        "eth/db/chaindata/cache/block/hit", "eth/db/chaindata/cache/block/miss")
LOOP_ADDR = "0x00000000000000000000000000000000cafe0001"


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params}).encode()
    req = urllib.request.Request(RPC, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as fh:
        return json.load(fh)


def metrics():
    with urllib.request.urlopen(MET, timeout=60) as fh:
        raw = json.load(fh)
    return {k: raw.get(k + ".count", raw.get(k + ".value", 0)) or 0 for k in KEEP}


def runtime_code(bundle, mode):
    """The receiver-walking runtime, lifted out of the setup deploy initcode."""
    hits = glob.glob(f"{bundle}/**/for_amsterdam_at_0160M/**/account_access.json",
                     recursive=True)
    d = json.load(open(hits[0]))
    name = sorted(k for k in d
                  if f"account_mode_AccountMode.{mode}" in k and "opcode_BALANCE" in k)[0]
    case = d[name]
    # the deploy sits in the SETUP payload, not the measured one
    for pl in case.get("setupEngineNewPayloads", []) + case.get("engineNewPayloads", []):
        for raw in pl["params"][0].get("transactions", []):
            h = raw[2:] if raw.startswith("0x") else raw
            i = h.find("600081600b8239f3")
            if i > 0:
                start = i + len("600081600b8239f3")
                return h[start:start + 0x6f * 2], name
    return None, name


def main():
    bundle, label, iters, mode = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    code, name = runtime_code(bundle, mode)
    if not code:
        print(json.dumps({"label": label, "error": "no loop code found", "case": name}))
        return
    calldata = "0x" + f"{0:064x}" + f"{iters - 1:064x}"

    time.sleep(12)
    before = metrics()
    t0 = time.time()
    r = rpc("eth_call", [
        {"to": LOOP_ADDR, "data": calldata, "gas": hex(45_000_000)},
        "latest",
        {LOOP_ADDR: {"code": "0x" + code}},
    ])
    wall = time.time() - t0
    time.sleep(12)
    after = metrics()
    delta = {k: after[k] - before[k] for k in KEEP}

    nodes = (delta["pathdb/clean/node/hit"] + delta["pathdb/clean/node/miss"]
             + delta["pathdb/dirty/node/hit"])
    accounts = (delta["pathdb/state/account/exist/total"]
                + delta["pathdb/state/account/inex/total"])
    blocks = (delta["eth/db/chaindata/cache/block/hit"]
              + delta["eth/db/chaindata/cache/block/miss"])
    json.dump({
        "label": label, "mode": mode, "iterations": iters,
        "ok": "result" in r, "err": (r.get("error") or {}).get("message"),
        "wall_s": round(wall, 1),
        "code_len": len(code) // 2,
        "accounts_read": accounts,
        "accounts_existing": delta["pathdb/state/account/exist/total"],
        "accounts_absent": delta["pathdb/state/account/inex/total"],
        "from_disk": delta["pathdb/state/account/exist/disk"]
                     + delta["pathdb/state/account/inex/disk"],
        "trie_nodes": nodes,
        "nodes_per_account": round(nodes / max(accounts, 1), 3),
        "block_lookups": blocks,
        "block_misses": delta["eth/db/chaindata/cache/block/miss"],
        "blocks_per_account": round(blocks / max(accounts, 1), 3),
        "misses_per_account": round(delta["eth/db/chaindata/cache/block/miss"]
                                    / max(accounts, 1), 3),
        "raw": delta,
    }, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
