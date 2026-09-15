#!/usr/bin/env python3
"""Collect every number the Nethermind state-DB article states, into data/report_data.json.

Two kinds of input:
  - run-derived: computed here from benchmarkoor's result.json trees (four arms).
  - probe-derived: measurements taken against the raw RocksDB stores with scripts/probe-flat and
    recorded in the study ledger. These are embedded as literals with a `src` note, because they
    cannot be recovered from the result trees. They are data, not prose: the article interpolates
    them, it never restates them.

Usage: python3 collect_nethermind.py > report_data.json
"""
import glob
import json
import os
import re
import sys
from statistics import median

RESULTS = "/bench/results"
ARMS = {
    "sa": "nm-state-actor",        # generated state, flat backend, symmetric config
    "joc": "nm-jochemnet",         # mainnet shadowfork + promoted pre-run (the confound)
    "fix": "nm-joc-full",          # same store, placement equalised, pre-run stripped
    "rep": "nm-joc-replication",   # accidental independent replication of the uncorrected arm
}


def load(name):
    root = os.path.join(RESULTS, name)
    best, bn = None, -1
    for rj in glob.glob(os.path.join(root, "runs", "*", "result.json")):
        try:
            n = len(json.load(open(rj)).get("tests", {}))
        except Exception:
            continue
        if n > bn:
            best, bn = rj, n
    if not best:
        return {}, None
    return json.load(open(best))["tests"], os.path.basename(os.path.dirname(best))


def metrics(entry):
    """MGas/s, MB read, CPU seconds and MGas from the measured step only.

    The 'setup' step is excluded: comparing a setup step on one arm against the test step on the
    other manufactures 5-8x ratios out of data whose category medians are ~0.97.
    """
    s = (entry.get("steps") or {}).get("test")
    if not s:
        return None
    a = s.get("aggregated") or {}
    g, t = a.get("gas_used_total"), a.get("gas_used_time_total")
    if not g or not t:
        return None
    r = a.get("resource_totals") or {}
    return {
        "mgas_s": (g / 1e6) / (t / 1e9),
        "mb": r.get("disk_read_bytes", 0) / 1e6,
        "cpu": r.get("cpu_usec", 0) / 1e6,
        "mgas": g / 1e6,
    }


def mode_of(tid):
    m = re.search(r"account_mode_(?:AccountMode\.)?([A-Z_]+)", tid)
    return m.group(1) if m else None


def gas_of(tid):
    m = re.findall(r"(\d+)M", tid)
    return int(m[-1]) if m else None


def family_of(tid):
    return tid.split("::")[1].split("[")[0] if "::" in tid else "?"


def category_of(tid):
    """Same partition the study used throughout, so the article's tables line up with the ledger."""
    fam = family_of(tid)
    if re.search(r"overhead_baseline_True", tid):
        return "CONTROL overhead_baseline"
    if fam == "test_ether_transfers_onchain_receivers":
        return "ETHER transfer receivers"
    if fam == "test_ext_account_query_warm":
        return "ACCOUNT warm query"
    if fam.startswith("test_sload") or fam.startswith("test_sstore"):
        return "STORAGE slot access"
    mode = mode_of(tid) or ""
    if mode == "NON_EXISTING_ACCOUNT":
        return "ACCOUNT cold non-existing"
    if mode == "EXISTING_EOA":
        return "ACCOUNT cold existing EOA"
    if mode.startswith("EXISTING_CONTRACT"):
        return "ACCOUNT cold existing contract"
    return "other"


def pair(a_tests, b_tests):
    """Exact-test-id pairs with matching gas. Identical gas is what makes a pair comparable."""
    out = []
    for tid in set(a_tests) & set(b_tests):
        a, b = metrics(a_tests[tid]), metrics(b_tests[tid])
        if not a or not b:
            continue
        if a["mgas"] and abs(a["mgas"] - b["mgas"]) / a["mgas"] > 0.01:
            continue
        out.append((tid, a, b))
    return out


def by_category(pairs):
    """Per-category medians. Ratios are state-actor / jochemnet, so 1.00 is parity."""
    buckets = {}
    for tid, j, s in pairs:
        buckets.setdefault(category_of(tid), []).append((j, s))
    out = {}
    for cat, v in buckets.items():
        thr = [s["mgas_s"] / j["mgas_s"] for j, s in v]
        out[cat] = {
            "n": len(v),
            "agree": sum(1 for r in thr if 0.9 <= r <= 1.1),
            "thr": median(thr),
            "read": median([s["mb"] / max(j["mb"], 0.01) for j, s in v]),
            "cpu": median([s["cpu"] / max(j["cpu"], 1e-6) for j, s in v]),
            "jocMB": median([j["mb"] for j, s in v]),
            "saMB": median([s["mb"] for j, s in v]),
        }
    return out


def by_mode(pairs, control):
    out = {}
    for tid, j, s in pairs:
        if bool(re.search(r"overhead_baseline_True", tid)) != control:
            continue
        m = mode_of(tid)
        if not m:
            continue
        out.setdefault(m, []).append((j, s))
    return {
        m: {
            "n": len(v),
            "jocMB": median([j["mb"] for j, s in v]),
            "saMB": median([s["mb"] for j, s in v]),
            "readX": median([s["mb"] / max(j["mb"], 0.01) for j, s in v]),
            "thrX": median([s["mgas_s"] / j["mgas_s"] for j, s in v]),
        }
        for m, v in out.items()
    }


def agreement(pairs):
    thr = [s["mgas_s"] / j["mgas_s"] for _, j, s in pairs]
    ok = [r for r in thr if 0.9 <= r <= 1.1]
    return {
        "n": len(thr),
        "agree": len(ok),
        "agree_pct": len(ok) / len(thr) * 100 if thr else 0,
        "median": median(thr),
        "min": min(thr) if thr else None,
        "max": max(thr) if thr else None,
    }


def cost_curve(pairs):
    """Read volume against gas, per arm. A store with a bounded working set is flat in gas."""
    g = {}
    for tid, j, s in pairs:
        gas = gas_of(tid)
        if gas is None or category_of(tid) != "ACCOUNT cold existing contract":
            continue
        g.setdefault(gas, []).append((j["mb"], s["mb"]))
    return [
        {"gas": k, "n": len(v), "jocMB": median([x[0] for x in v]),
         "saMB": median([x[1] for x in v])}
        for k, v in sorted(g.items())
    ]


def additive(pairs):
    """Is the leftover excess a fixed number of megabytes, or proportional to the work?"""
    rows = [(j["mb"], s["mb"], s["mgas_s"] / j["mgas_s"]) for _, j, s in pairs]
    out = []
    for lo, hi in ((0, 10), (10, 100), (100, 1000), (1000, 4000), (4000, float("inf"))):
        v = [r for r in rows if lo <= r[0] < hi]
        if not v:
            continue
        out.append({
            "lo": lo, "hi": None if hi == float("inf") else hi, "n": len(v),
            "jocMB": median([x[0] for x in v]),
            "saMB": median([x[1] for x in v]),
            "excess": median([x[1] - x[0] for x in v]),
            "thr": median([x[2] for x in v]),
        })
    excess = sorted(x[1] - x[0] for x in rows)
    return {
        "buckets": out,
        "median_excess": median(excess),
        "p10": excess[len(excess) // 10],
        "p90": excess[9 * len(excess) // 10],
    }


# --------------------------------------------------------------------------- #
# Probe-derived measurements: taken against the raw stores, not recoverable from result.json.
# --------------------------------------------------------------------------- #
MEASURED = {
    # The comparison only exists once both arms read through the flat backend. Recorded so the
    # generator can refuse to build from a run predating the flat-state rebuild.
    "preconditions": {
        "src": "both arms' Nethermind startup lines; the generated store was rebuilt from a state-actor revision that writes the flat layout before any run quoted here",
        "backend_both": "flat (existing flat DB detected)",
        "sa_run_flat_backed": "1789207753_887c4915_nm-sa",
        "joc_run": "1789101020_23e0ca97_nm-jochemnet"
    },
    "amortisation": {
        "src": "probe-flat -mode seq, Account CF, cold caches + fresh process per point, "
               "fill_cache=false, 100% hits, the EEST fixtures' own key population",
        "points": [
            {"n": 500,   "sa_blk": 2.00, "sa_mb": 4.1,   "sa_us": 183.6,
             "joc_blk": 1.88, "joc_mb": 3.9,  "joc_us": 164.0},
            {"n": 2000,  "sa_blk": 1.99, "sa_mb": 16.3,  "sa_us": 184.9,
             "joc_blk": 1.65, "joc_mb": 13.5, "joc_us": 107.7},
            {"n": 8000,  "sa_blk": 1.99, "sa_mb": 65.2,  "sa_us": 183.0,
             "joc_blk": 1.06, "joc_mb": 34.8, "joc_us": 39.2},
            {"n": 20000, "sa_blk": 1.99, "sa_mb": 162.6, "sa_us": 183.9,
             "joc_blk": 0.55, "joc_mb": 45.0, "joc_us": 31.4},
            {"n": 50000, "sa_blk": 1.97, "sa_mb": 404.4, "sa_us": 179.1,
             "joc_blk": 0.23, "joc_mb": 47.2, "joc_us": 10.6},
        ],
    },
    "random_keys": {
        "src": "probe-flat -mode sample/probe: keys sampled from the CF itself, so both arms are "
               "measured on their own contents rather than on a shared synthetic range",
        "Account":    {"sa_blk": 1.99, "joc_blk": 2.51, "sa_us": 188, "joc_us": 219},
        "StateNodes": {"sa_blk": 3.44, "joc_blk": 10.26, "sa_us": 208, "joc_us": 434},
        "Storage":    {"sa_blk": 2.52, "joc_blk": 2.21, "sa_us": 200, "joc_us": 198},
    },
    "intervention": {
        "src": "probe-flat -mode rebuild: CompactRangeCFOpt with bottommost=kForce, per-CF options "
               "transcribed from state-actor's OPTIONS and verified by an OPTIONS diff",
        "account_before":    {"levels": {"3": 4, "4": 36, "5": 304, "6": 20}, "gb": 16.25},
        "account_after":     {"levels": {"6": 37}, "gb": 17.38, "seconds": 185.1},
        "statenodes_before": {"levels": {"0": 3, "3": 1, "4": 4, "5": 60, "6": 487}, "gb": 39.10},
        "statenodes_after":  {"levels": {"6": 158}, "gb": 38.98, "seconds": 708.2},
        "code_before":       {"levels": {"0": 3, "5": 6, "6": 117}, "gb": 7.6},
        "code_after":        {"levels": {"6": 115}, "seconds": 61.6},
        "compacted_blk": 1.76, "compacted_us": 186.0,
        "compacted_mb_20k": 146.1, "compacted_mb_50k": 361.4,
    },
    "footprint": {
        "src": "du -sh on each promoted volume",
        "sa": {"state": "160 KB", "flat": "478 GB", "code": "45 GB", "total_gib": 409},
        "joc": {"state": "341 GB", "flat": "314 GB", "code": "7.6 GB"},
        "boot_read_gb": {"sa": 4.81, "joc": 6.53},
    },
    "prerun": {
        "src": "the pre-run bundle shipped with the jochemnet fixtures release",
        "bytes": 10062313486, "blocks": 7736, "txs_per_block": 64,
        "first_block": 24402728, "last_block": 24410463,
    },
    "eip_trap": {
        "nine": [2780, 7708, 7778, 7843, 7928, 7954, 7976, 7981, 8024],
        "fourteen": [2780, 7708, 7778, 7843, 7928, 7954, 7976, 7981, 7997,
                     8024, 8037, 8038, 8246, 8282],
        "src": "benchmarkoor ships two Amsterdam EIP sets; only the existing-snapshot family's "
               "list reproduces what geth and Besu get by activating Amsterdam by name",
    },
    "options_per_cf": {
        "src": "OPTIONS files of both stores, compared knob by knob",
        "rows": [
            ["Account",       4096,  4,  "kNoCompression", "ribbon 10:3"],
            ["Storage",       8000,  4,  "kLZ4Compression", "ribbon 10:3"],
            ["StateNodes",    16000, 8,  "kLZ4Compression", "ribbon 10:3"],
            ["StateTopNodes", 16000, 8,  "kLZ4Compression", "ribbon 10:3"],
            ["StorageNodes",  16000, 8,  "kLZ4Compression", "ribbon 10:3"],
            ["FallbackNodes", 16000, 8,  "kLZ4Compression", "ribbon 10:3"],
            ["Metadata",      16000, 4,  "kLZ4Compression", "ribbon 10:3"],
            ["default",       4096,  16, "kSnappyCompression", "none"],
        ],
    },
    "three_client": {
        "src": "geth and Besu figures from the two sibling reports in this repo",
        "state_gib": {"geth": 674, "besu": 532, "nethermind": 409},
        "geth_sa_over_compacted": {"lo": 1.031, "hi": 1.117, "median": 1.091},
        "geth_sa_over_uncompacted": {"EOA": 2.01, "MINIMAL": 4.80, "SAME_MAX": 5.81,
                                     "JUMPDEST": 4.94, "NON_EXISTING": 0.91},
        "geth_diffmax_sa_over_compacted": 7.71,
        "besu_sa_over_plain": 0.288,
        "besu_sa_over_compacted": 0.962,
        "besu_bytes_plain": 2.916,
        "besu_bytes_compacted": 1.124,
        "besu_cells": 108,
        "besu_src": "computed from besu-state-db-divergence/data/report_data.json on main, the same way as this study's own ratios: median of per-cell mgas_s ratios over the account-reading cells, with gas matched exactly",
    },
}


def main():
    tests, runs = {}, {}
    for key, name in ARMS.items():
        tests[key], runs[key] = load(name)

    before = pair(tests["joc"], tests["sa"])
    after = pair(tests["fix"], tests["sa"])
    repl = pair(tests["rep"], tests["sa"]) if tests["rep"] else []

    data = {
        "provenance": {
            "arms": {k: {"results": ARMS[k], "run": runs[k], "tests": len(tests[k])}
                     for k in ARMS if tests[k]},
            "image": "docker.io/ethpandaops/nethermind:glamsterdam-devnet-7",
            "flags": ["--FlatDb.Enabled=true", "--Blocks.ParallelExecution=true",
                      "--Blocks.ParallelExecutionBatchRead=true"],
            "harness": {"rollback_strategy": "container-recreate",
                        "drop_memory_caches": "steps"},
            "snapshot_block": 24402727,
            "host": "48 cores, 125 GB RAM, 7 TB NVMe RAID",
        },
        "before": {"categories": by_category(before), "agreement": agreement(before),
                   "cost_curve": cost_curve(before)},
        "after": {"categories": by_category(after), "agreement": agreement(after),
                  "by_mode": by_mode(after, control=False),
                  "by_mode_control": by_mode(after, control=True),
                  "additive": additive(after)},
        "replication": {"agreement": agreement(repl),
                        "categories": by_category(repl)} if repl else None,
        "measured": MEASURED,
    }
    json.dump(data, sys.stdout, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
