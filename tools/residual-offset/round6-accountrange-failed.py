#!/usr/bin/env python3
"""Round 6: are state-actor's account records fatter than jochemnet's?

A snapshot account is slim-encoded: an EOA with an empty storage root and
empty code hash drops both fields, a contract carries 32 bytes of each. If a
generated bloatnet is mostly contracts and a mainnet snapshot mostly EOAs,
state-actor moves more bytes for the same number of account reads - which is
what the EVM actually does, and what round 2 measured.

Samples accounts through debug_accountRange from several start points so the
sample is not biased to one corner of the keyspace.
"""
import hashlib
import json
import sys
import urllib.request

RPC = "http://127.0.0.1:8545"
EMPTY_ROOT = "0x56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
EMPTY_CODE = "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
PAGES = 8
PER_PAGE = 256


def rpc(method, params):
    req = urllib.request.Request(
        RPC, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                         "params": params}).encode(),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as fh:
        return json.load(fh)


def slim_size(acc):
    """Bytes the slim snapshot encoding needs for this account."""
    n = int(acc.get("nonce", 0) or 0)
    bal = int(acc.get("balance", "0") or 0)
    size = 3                                     # rlp list header + small fields
    size += max((n.bit_length() + 7) // 8, 0)
    size += max((bal.bit_length() + 7) // 8, 0)
    if (acc.get("root") or "").lower() not in ("", EMPTY_ROOT):
        size += 33
    if (acc.get("codeHash") or "").lower() not in ("", EMPTY_CODE):
        size += 33
    return size


def main():
    label = sys.argv[1]
    seen, with_storage, with_code, sizes = 0, 0, 0, []
    for p in range(PAGES):
        start = "0x" + hashlib.sha256(f"range-{p}".encode()).hexdigest()
        try:
            r = rpc("debug_accountRange", ["latest", start, PER_PAGE, True, True, False])
        except Exception as exc:                  # noqa: BLE001 - reported, not hidden
            print(json.dumps({"label": label, "error": str(exc)}))
            return
        if "result" not in r:
            print(json.dumps({"label": label, "error": r.get("error")}))
            return
        accs = r["result"].get("accounts") or {}
        for _, a in accs.items():
            seen += 1
            root = (a.get("root") or "").lower()
            code = (a.get("codeHash") or "").lower()
            if root and root != EMPTY_ROOT:
                with_storage += 1
            if code and code != EMPTY_CODE:
                with_code += 1
            sizes.append(slim_size(a))
    json.dump({
        "label": label,
        "sampled": seen,
        "with_storage_pct": round(100 * with_storage / max(seen, 1), 1),
        "with_code_pct": round(100 * with_code / max(seen, 1), 1),
        "mean_slim_bytes": round(sum(sizes) / max(len(sizes), 1), 1),
        "sample_account": next(iter((r["result"].get("accounts") or {}).values()), None),
    }, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
