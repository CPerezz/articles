#!/usr/bin/env python3
"""Per-test I/O accounting for matched tests, normalised to estimated cold account accesses.

gas_used is identical per test across arms, and EIP-2929 charges 2600 gas for a cold account
access, so gas/2600 is a usable proxy for the number of account touches. Dividing physical I/O
by it gives bytes and I/O-ops per account access — directly comparable to the isolated
per-lookup cost measured with probe-flat (~2 blocks / ~8 KB / ~1 op).
"""
import json, glob, os, re, sys
from statistics import median

COLD_ACCOUNT_GAS = 2600


def load(root):
    best, bn = None, -1
    for rj in glob.glob(os.path.join(root, "runs", "*", "result.json")):
        try:
            n = len(json.load(open(rj)).get("tests", {}))
        except Exception:
            continue
        if n > bn:
            best, bn = rj, n
    out = {}
    for tid, meta in json.load(open(best))["tests"].items():
        a = ((meta.get("steps") or {}).get("test") or {}).get("aggregated") or {}
        g = a.get("gas_used_total", 0)
        if a.get("fail") or not g:
            continue
        r = a.get("resource_totals", {})
        out[tid] = {
            "gas": g,
            "wall": a.get("gas_used_time_total", 0) / 1e9,
            "read": r.get("disk_read_bytes", 0),
            "iops": r.get("disk_read_iops", 0),
            "cpu": r.get("cpu_usec", 0) / 1e6,
        }
    return out


def sel(tid):
    m = re.search(r"account_mode_AccountMode\.([A-Z_]+)", tid)
    b = re.search(r"overhead_baseline_(True|False)", tid)
    return (m.group(1) if m else None), (b.group(1) if b else None)


def main():
    joc, sa = load(sys.argv[1]), load(sys.argv[2])
    groups = {}
    for tid in set(joc) & set(sa):
        mode, base = sel(tid)
        if base != "False" or not mode:
            continue
        groups.setdefault(mode, []).append(tid)

    print(f"{'account_mode':<28}{'arm':<6}{'accesses':>10}{'KB/access':>11}"
          f"{'ops/access':>12}{'bytes/op':>10}{'us/access':>11}")
    print("-" * 88)
    for mode in sorted(groups):
        for name, src in (("joc", joc), ("sa", sa)):
            accs, kb, ops, bpo, us = [], [], [], [], []
            for tid in groups[mode]:
                d = src[tid]
                n = d["gas"] / COLD_ACCOUNT_GAS
                if n <= 0:
                    continue
                accs.append(n)
                kb.append(d["read"] / n / 1024)
                ops.append(d["iops"] / n)
                bpo.append(d["read"] / d["iops"] if d["iops"] else 0)
                us.append(d["wall"] * 1e6 / n)
            if accs:
                print(f"{mode:<28}{name:<6}{median(accs):>10.0f}{median(kb):>11.1f}"
                      f"{median(ops):>12.2f}{median(bpo):>10.0f}{median(us):>11.1f}")
        print()


if __name__ == "__main__":
    main()
