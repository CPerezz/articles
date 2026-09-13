#!/usr/bin/env python3
"""Second pass: attach physical evidence to each bucket.

If readratio ~= timeratio the arm is moving more bytes; if readratio ~= 1 while time diverges
the cost is CPU-side. That distinction decides where to look next.
"""
import json, glob, os, re, sys
from statistics import median
from collections import defaultdict

BAND = 0.10


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
        g, t = a.get("gas_used_total", 0), a.get("gas_used_time_total", 0)
        if a.get("fail") or not g or not t:
            continue
        r = a.get("resource_totals", {})
        out[tid] = {"mgas": g / (t / 1e9) / 1e6, "gas": g, "wall": t / 1e9,
                    "read": r.get("disk_read_bytes", 0), "cpu": r.get("cpu_usec", 0) / 1e6}
    return out


def fam(t):
    return t.split("[")[0].split("::")[-1]


def tok(t, p):
    m = re.search(r"\[(.*)\]$", t)
    for x in (m.group(1).split("-") if m else []):
        if x.startswith(p):
            return x[len(p):]
    return None


def label(tid):
    """Assign each test to one analysis category."""
    if tok(tid, "overhead_baseline_") == "True":
        return "CONTROL overhead_baseline"
    f = fam(tid)
    if f in ("test_sload_bloated", "test_sstore_bloated", "test_sload_same_key_benchmark"):
        return "STORAGE slot access"
    if f == "test_ext_account_query_warm":
        return "ACCOUNT warm query"
    m = tok(tid, "account_mode_AccountMode.")
    if m == "NON_EXISTING_ACCOUNT":
        return "ACCOUNT cold non-existing"
    if m == "EXISTING_EOA":
        return "ACCOUNT cold existing EOA"
    if m and m.startswith("EXISTING_CONTRACT"):
        return "ACCOUNT cold existing contract"
    if f == "test_ether_transfers_onchain_receivers":
        return "ETHER transfer receivers"
    return "other (" + f + ")"


def main():
    joc, sa = load(sys.argv[1]), load(sys.argv[2])
    rows = []
    for tid in sorted(set(joc) & set(sa)):
        j, s = joc[tid], sa[tid]
        if not j["mgas"] or abs(j["gas"] - s["gas"]) / max(j["gas"], 1) > 0.01:
            continue
        rows.append({
            "cat": label(tid),
            "tr": s["mgas"] / j["mgas"],                       # throughput ratio sa/joc
            "rr": (s["read"] / j["read"]) if j["read"] else float("nan"),
            "cr": (s["cpu"] / j["cpu"]) if j["cpu"] else float("nan"),
            "jread": j["read"], "sread": s["read"],
            "jw": j["wall"], "sw": s["wall"],
        })

    agg = defaultdict(list)
    for r in rows:
        agg[r["cat"]].append(r)

    print(f"{'category':<34}{'n':>5}{'agree':>7}{'thr sa/joc':>12}"
          f"{'read sa/joc':>13}{'cpu sa/joc':>12}{'jocMB':>9}{'saMB':>9}")
    print("-" * 101)
    order = sorted(agg, key=lambda k: median(x["tr"] for x in agg[k]), reverse=True)
    for k in order:
        v = agg[k]
        a = sum(1 for x in v if abs(x["tr"] - 1) <= BAND)
        print(f"{k:<34}{len(v):>5}{a:>7}{median(x['tr'] for x in v):>12.3f}"
              f"{median(x['rr'] for x in v):>13.2f}{median(x['cr'] for x in v):>12.2f}"
              f"{median(x['jread'] for x in v)/1e6:>9.1f}{median(x['sread'] for x in v)/1e6:>9.1f}")

    print("\n=== the state-actor-FASTER outliers (ratio > 1.10) ===")
    fast = sorted([r for r in rows if r["tr"] > 1.10], key=lambda r: -r["tr"])
    fa = defaultdict(int)
    for r in fast:
        fa[r["cat"]] += 1
    print(f"count {len(fast)}; by category: " + ", ".join(f"{k}={v}" for k, v in
          sorted(fa.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
