#!/usr/bin/env python3
"""Round 11: do the two fixture bundles ask for the same amount of work?

The arms ran different EEST bundles (6142626aac06abc4 vs 3cf555c593bcb136).
Both tests burn the same gas, but if their benchmark loops differ - a
different salt range, a different per-iteration cost, different code - then
state-actor performs more account accesses for the same gas, and every
resource counter scales together. That is exactly the flat, opcode- and
mode-independent multiplier rounds 2 and 10 measured.
"""
import glob
import json
import os
import re

BUNDLES = {
    "jochemnet": "/root/.cache/benchmarkoor/eest-url/6142626aac06abc4",
    "state-actor": "/root/.cache/benchmarkoor/eest-url/3cf555c593bcb136",
}
WANT = "opcode_BALANCE-value_sent_0-account_mode_AccountMode.EXISTING_CONTRACT_MINIMAL"


def find_json(root, gas="0160M"):
    pats = [
        f"{root}/**/for_amsterdam_at_{gas}/**/account_query/account_access.json",
        f"{root}/**/for_amsterdam_at_{gas}/**/account_access*.json",
    ]
    for p in pats:
        hits = glob.glob(p, recursive=True)
        if hits:
            return hits[0]
    return None


def rlp_fields(raw):
    """Crude RLP tx decoder: returns (to_hex, data_hex, gas_limit) if typed."""
    b = bytes.fromhex(raw[2:] if raw.startswith("0x") else raw)
    return b


def main():
    for label, root in BUNDLES.items():
        path = find_json(root)
        print(f"=== {label} ===")
        print(f"  file: {path}")
        if not path:
            hits = glob.glob(f"{root}/**/*.json", recursive=True)
            print(f"  (no match; {len(hits)} json files, sample: {hits[:2]})")
            continue
        d = json.load(open(path))
        names = [k for k in d if WANT in k]
        print(f"  cases in file: {len(d)}   matching '{WANT[:40]}...': {len(names)}")
        if not names:
            names = list(d)[:1]
        name = sorted(names)[0]
        c = d[name]
        print(f"  case: {name[:120]}")
        pls = c.get("engineNewPayloads") or []
        print(f"  payloads: {len(pls)}")
        for i, pl in enumerate(pls):
            params = pl.get("params") or [{}]
            txs = params[0].get("transactions") or []
            gu = params[0].get("gasUsed")
            print(f"    payload {i}: txs={len(txs)} gasUsed={gu}")
            for j, t in enumerate(txs[:3]):
                b = rlp_fields(t)
                # calldata of these fixtures is the 64-byte tail before the
                # signature; print the last 96 bytes so the words are visible
                print(f"      tx{j}: {len(b)} bytes  tail={b[-100:].hex()[:160]}")
        pre = c.get("pre") or {}
        big = sorted(((len(v.get("code", "0x")), k) for k, v in pre.items()),
                     reverse=True)[:3]
        print(f"  pre accounts: {len(pre)}  largest code: "
              + ", ".join(f"{k[:12]}..={n}" for n, k in big))
        for n, k in big[:1]:
            print(f"  loop code: {pre[k]['code'][:200]}")


if __name__ == "__main__":
    main()
