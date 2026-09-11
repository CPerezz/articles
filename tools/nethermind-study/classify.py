#!/usr/bin/env python3
"""Classify Nethermind baseline results by category and compare the two arms.

Mirrors the geth study's headline table: per (opcode, account_mode) category, the median
throughput of each arm and the state-actor / jochemnet ratio.

Usage: classify.py <jochemnet_results_dir> <state_actor_results_dir>
"""
import json, glob, os, re, sys
from statistics import median
from collections import defaultdict

# benchmarkoor encodes the parameters in the test id, e.g.
#   ...test_account_access[fork_Amsterdam-blockchain_test_stateful_engine-opcode_BALANCE-
#   value_sent_0-account_mode_AccountMode.EXISTING_CONTRACT_DIFF_MAX-...-value_160M]
RE_OPCODE = re.compile(r"opcode_([A-Z0-9]+)")
RE_MODE   = re.compile(r"account_mode_AccountMode\.([A-Z_]+)")
RE_GAS    = re.compile(r"value_(\d+)M")
RE_SENT   = re.compile(r"value_sent_(\d+)")


def collect(root):
    """test-id -> measurement, from every aggregated result under a results dir."""
    out = {}
    for f in glob.glob(os.path.join(root, "runs", "**", "test.result-aggregated.json"),
                       recursive=True):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if d.get("fail"):                      # only successful executions are comparable
            continue
        gas, t = d.get("gas_used_total", 0), d.get("gas_used_time_total", 0)
        if not gas or not t:
            continue
        # the test id is the directory name two levels up (…/<test-id-hash>/test.result-*)
        tid = os.path.basename(os.path.dirname(f))
        r = d.get("resource_totals", {})
        out[tid] = {
            "mgas_s": gas / (t / 1e9) / 1e6,
            "gas": gas,
            "secs": t / 1e9,
            "disk_read_bytes": r.get("disk_read_bytes", 0),
            "cpu_usec": r.get("cpu_usec", 0),
        }
    return out


def key_of(tid):
    o, m, g = RE_OPCODE.search(tid), RE_MODE.search(tid), RE_GAS.search(tid)
    if not (o and m):
        return None
    return o.group(1), m.group(1), (g.group(1) + "M" if g else "?")


def main():
    joc_dir, sa_dir = sys.argv[1], sys.argv[2]
    joc, sa = collect(joc_dir), collect(sa_dir)
    print(f"jochemnet measurements : {len(joc)}")
    print(f"state-actor measurements: {len(sa)}")

    # Match on the parameter tuple, not the raw id: the two arms hash ids differently.
    def bucket(rows):
        b = defaultdict(list)
        for tid, v in rows.items():
            k = key_of(tid)
            if k:
                b[k].append(v)
        return b

    bj, bs = bucket(joc), bucket(sa)
    common = sorted(set(bj) & set(bs))
    print(f"common categories       : {len(common)}\n")

    rows = []
    for k in common:
        mj = median(v["mgas_s"] for v in bj[k])
        ms = median(v["mgas_s"] for v in bs[k])
        rj = median(v["disk_read_bytes"] for v in bj[k])
        rs = median(v["disk_read_bytes"] for v in bs[k])
        rows.append((k, mj, ms, ms / mj if mj else 0, rj, rs))

    rows.sort(key=lambda r: r[3])
    print(f"{'opcode':<16}{'account_mode':<28}{'gas':<7}"
          f"{'joc MGas/s':>11}{'sa MGas/s':>11}{'sa/joc':>9}{'joc MB/rd':>11}{'sa MB/rd':>10}")
    print("-" * 103)
    for (op, mode, gas), mj, ms, ratio, rj, rs in rows:
        print(f"{op:<16}{mode:<28}{gas:<7}{mj:>11.2f}{ms:>11.2f}{ratio:>9.3f}"
              f"{rj/1e6:>11.1f}{rs/1e6:>10.1f}")

    if rows:
        rr = [r[3] for r in rows]
        print("-" * 103)
        print(f"ratio sa/joc: min {min(rr):.3f}  median {median(rr):.3f}  max {max(rr):.3f}")
        # A ratio far from 1 in only a few categories is the DIFF_MAX-style signature the
        # geth study found; a flat offset across all categories is the residual signature.
        flat = [r for r in rows if 0.9 <= r[3] <= 1.1]
        print(f"categories within +/-10%: {len(flat)} of {len(rows)}")


if __name__ == "__main__":
    main()
