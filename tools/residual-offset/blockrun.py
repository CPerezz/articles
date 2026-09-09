#!/usr/bin/env python3
"""Execute the benchmark's real block on a store, and measure it.

Round 15 sent only the measured payload and got SYNCING: the fixture's test
block is head+2, because the setup block sits between them. Sending the setup
payload first - exactly what the harness does - closes the gap, and then the
measured block runs through the genuine execution path: trie prefetcher,
state-root computation, commit. That is the path every earlier probe missed.

usage: blockrun.py <bundle_dir> <label> [mode]
"""
import glob
import hashlib
import subprocess as sp
import hmac
import base64
import json
import sys
import time
import urllib.request

AUTH = "http://127.0.0.1:8551"
MET = "http://127.0.0.1:6060/debug/metrics"
SECRET = bytes.fromhex("00" * 31 + "2a")
KEEP = ("pathdb/clean/node/hit", "pathdb/clean/node/miss",
        "pathdb/clean/state/hit", "pathdb/clean/state/miss",
        "pathdb/dirty/node/hit", "pathdb/dirty/node/miss",
        "pathdb/state/account/exist/total", "pathdb/state/account/exist/disk",
        "pathdb/state/account/inex/total", "pathdb/state/account/inex/disk",
        "eth/db/chaindata/cache/block/hit", "eth/db/chaindata/cache/block/miss",
        "eth/db/chaindata/cache/table/hit", "eth/db/chaindata/cache/table/miss")


def jwt():
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")
    hdr = b64(b'{"alg":"HS256","typ":"JWT"}')
    pay = b64(json.dumps({"iat": int(time.time())}).encode())
    sig = b64(hmac.new(SECRET, hdr + b"." + pay, hashlib.sha256).digest())
    return (hdr + b"." + pay + b"." + sig).decode()


def call(method, params, url=AUTH, timeout=3600):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                       "params": params}).encode()
    hdrs = {"Content-Type": "application/json"}
    if url == AUTH:
        hdrs["Authorization"] = "Bearer " + jwt()
    req = urllib.request.Request(url, body, hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return json.load(fh)


def geth_io():
    """Bytes the geth process has pulled from the block layer. Comparable now
    that both stores live on the same device and the same loop/ext4 stack."""
    try:
        pid = sp.run(["pgrep", "-f", "geth --datadir=/data"],
                     capture_output=True, text=True).stdout.split()[0]
        for line in open(f"/proc/{pid}/io"):
            if line.startswith("read_bytes:"):
                return int(line.split()[1])
    except Exception:
        return 0
    return 0


def metrics():
    with urllib.request.urlopen(MET, timeout=60) as fh:
        raw = json.load(fh)
    return {k: raw.get(k + ".count", raw.get(k + ".value", 0)) or 0 for k in KEEP}


def send_payload(pl):
    """Try the newest engine API first; fall back one version."""
    params = pl["params"]
    for m in ("engine_newPayloadV5", "engine_newPayloadV4", "engine_newPayloadV3"):
        r = call(m, params)
        if "error" not in r:
            return m, r["result"]
        if "Unsupported" not in str(r["error"]) and "not found" not in str(r["error"]).lower():
            return m, r["error"]
    return None, {"error": "no accepted newPayload version"}


def main():
    bundle, label = sys.argv[1], sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "EXISTING_CONTRACT_MINIMAL"
    hits = glob.glob(f"{bundle}/**/for_amsterdam_at_0160M/**/account_access.json",
                     recursive=True)
    d = json.load(open(hits[0]))
    name = sorted(k for k in d if f"AccountMode.{mode}" in k
                  and "opcode_BALANCE" in k and "baseline_False" in k)[0]
    case = d[name]

    out = {"label": label, "mode": mode}

    # A node whose store carries no head marker starts in sync mode and
    # answers every newPayload with SYNCING ("forced head needed for
    # startup"). Tell it where its own head is first.
    head = call("eth_getBlockByNumber", ["latest", False],
                url="http://127.0.0.1:8545")["result"]["hash"]
    fc0 = call("engine_forkchoiceUpdatedV3",
               [{"headBlockHash": head, "safeBlockHash": head,
                 "finalizedBlockHash": head}, None])
    out["startup_fcu"] = ((fc0.get("result") or {}).get("payloadStatus")
                          or {}).get("status") or fc0.get("error")

    # 0. the arm's chain may sit below the fixture's anchor: state-actor's store
    #    is at genesis while its fixtures start at block 1. That block lives in
    #    the pre-run bundle, named for the hash it produces.
    pre = glob.glob(f"{bundle}/**/pre_run/{case['startBlockHash']}.json", recursive=True)
    if pre:
        pd = json.load(open(pre[0]))
        for pl in pd.get("engineNewPayloads", []):
            m, res = send_payload(pl)
            out["prerun_status"] = res.get("status") if isinstance(res, dict) else res
            blk = pl["params"][0]["blockHash"]
            fc = call("engine_forkchoiceUpdatedV3",
                      [{"headBlockHash": blk, "safeBlockHash": blk,
                        "finalizedBlockHash": blk}, None])
            out["prerun_fcu"] = ((fc.get("result") or {}).get("payloadStatus")
                                 or {}).get("status") or fc.get("error")

    # 1. setup block, then make it the head
    for pl in case["setupEngineNewPayloads"]:
        m, res = send_payload(pl)
        out["setup_status"] = res.get("status") if isinstance(res, dict) else res
        blk = pl["params"][0]["blockHash"]
        fc = call("engine_forkchoiceUpdatedV3",
                  [{"headBlockHash": blk, "safeBlockHash": blk,
                    "finalizedBlockHash": blk}, None])
        out["setup_fcu"] = ((fc.get("result") or {}).get("payloadStatus") or {}).get("status") \
            or fc.get("error")

    # 2. cold caches, exactly as the harness does between tests
    import subprocess
    subprocess.run(["sync"], check=False)
    subprocess.run(["bash", "-c", "echo 3 > /proc/sys/vm/drop_caches"], check=False)
    time.sleep(3)

    # 3. the measured block
    time.sleep(30)
    before = metrics()
    io0 = geth_io()
    t0 = time.time()
    m, res = send_payload(case["engineNewPayloads"][0])
    wall = time.time() - t0
    io1 = geth_io()
    time.sleep(30)
    after = metrics()

    delta = {k: after[k] - before[k] for k in KEEP}
    accounts = (delta["pathdb/state/account/exist/total"]
                + delta["pathdb/state/account/inex/total"])
    nodes = (delta["pathdb/clean/node/hit"] + delta["pathdb/clean/node/miss"]
             + delta["pathdb/dirty/node/hit"])
    blocks = (delta["eth/db/chaindata/cache/block/hit"]
              + delta["eth/db/chaindata/cache/block/miss"])
    out.update({
        "method": m,
        "status": res.get("status") if isinstance(res, dict) else res,
        "wall_s": round(wall, 2),
        "disk_read_bytes": io1 - io0,
        "accounts_read": accounts,
        "trie_nodes": nodes,
        "nodes_per_account": round(nodes / max(accounts, 1), 3),
        "block_lookups": blocks,
        "block_misses": delta["eth/db/chaindata/cache/block/miss"],
        "blocks_per_account": round(blocks / max(accounts, 1), 3),
        "misses_per_account": round(delta["eth/db/chaindata/cache/block/miss"]
                                    / max(accounts, 1), 3),
        "table_misses": delta["eth/db/chaindata/cache/table/miss"],
        "raw": delta,
    })
    json.dump(out, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
