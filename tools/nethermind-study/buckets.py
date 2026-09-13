#!/usr/bin/env python3
"""Bucket every comparable Nethermind benchmark into agree (<=10%) vs divergent, then
characterise the divergent set.

Matching is on the EXACT test identity (file::func[params]) so the two arms are compared
test-for-test, not via category medians. Earlier passes keyed on (opcode, account_mode, gas)
and silently dropped whole families (sload/sstore/storage-pattern) that lack those tokens.

Usage: buckets.py <jochemnet_root> <state_actor_root>
"""
import json, glob, os, re, sys
from statistics import median
from collections import defaultdict

BAND = 0.10  # "same/similar" = ratio within +/-10%


def load(root):
    best, bn = None, -1
    for rj in glob.glob(os.path.join(root, "runs", "*", "result.json")):
        try:
            n = len(json.load(open(rj)).get("tests", {}))
        except Exception:
            continue
        if n > bn:
            best, bn = rj, n
    tests = json.load(open(best))["tests"]
    out = {}
    for tid, meta in tests.items():
        a = ((meta.get("steps") or {}).get("test") or {}).get("aggregated") or {}
        gas, t = a.get("gas_used_total", 0), a.get("gas_used_time_total", 0)
        if a.get("fail") or not gas or not t:
            continue
        r = a.get("resource_totals", {})
        out[tid] = {"mgas": gas / (t / 1e9) / 1e6, "gas": gas, "wall": t / 1e9,
                    "read": r.get("disk_read_bytes", 0), "cpu": r.get("cpu_usec", 0)}
    return out


def family(tid):
    head = tid.split("[")[0]
    return head.split("::")[-1] if "::" in head else head


def params(tid):
    m = re.search(r"\[(.*)\]$", tid)
    return m.group(1).split("-") if m else []


def tok(tid, prefix):
    for p in params(tid):
        if p.startswith(prefix):
            return p[len(prefix):]
    return None


def main():
    joc, sa = load(sys.argv[1]), load(sys.argv[2])
    common = sorted(set(joc) & set(sa))
    print(f"jochemnet usable {len(joc)} | state-actor usable {len(sa)} | exact-id matches {len(common)}")
    if not common:
        print("NO EXACT MATCHES — ids differ between bundles; falling back is required")
        return

    rows = []
    for tid in common:
        j, s = joc[tid], sa[tid]
        if not j["mgas"]:
            continue
        # gas must match for the ratio to mean anything
        gasdiff = abs(j["gas"] - s["gas"]) / max(j["gas"], 1)
        rows.append({
            "tid": tid, "fam": family(tid),
            "ratio": s["mgas"] / j["mgas"],
            "readratio": (s["read"] / j["read"]) if j["read"] else 0,
            "gasdiff": gasdiff,
            "jm": j["mgas"], "sm": s["mgas"], "jr": j["read"], "sr": s["read"],
        })

    bad_gas = [r for r in rows if r["gasdiff"] > 0.01]
    rows = [r for r in rows if r["gasdiff"] <= 0.01]
    print(f"dropped for gas mismatch >1%: {len(bad_gas)}")
    print(f"comparable tests: {len(rows)}\n")

    agree = [r for r in rows if abs(r["ratio"] - 1) <= BAND]
    diverge = [r for r in rows if abs(r["ratio"] - 1) > BAND]
    print(f"=== BUCKET 1: AGREE (within +/-{int(BAND*100)}%) : {len(agree)} "
          f"({100*len(agree)/len(rows):.1f}%)")
    if agree:
        rr = [r["ratio"] for r in agree]
        print(f"    ratio min {min(rr):.3f} median {median(rr):.3f} max {max(rr):.3f}")
    print(f"=== BUCKET 2: DIVERGENT                      : {len(diverge)} "
          f"({100*len(diverge)/len(rows):.1f}%)")
    if diverge:
        rr = [r["ratio"] for r in diverge]
        print(f"    ratio min {min(rr):.3f} median {median(rr):.3f} max {max(rr):.3f}")
        slow = [r for r in diverge if r["ratio"] < 1]
        fast = [r for r in diverge if r["ratio"] > 1]
        print(f"    state-actor slower: {len(slow)}   state-actor faster: {len(fast)}")

    def crosstab(label, keyfn, sel=None):
        sel = rows if sel is None else sel
        agg = defaultdict(lambda: [0, 0, []])
        for r in sel:
            k = keyfn(r["tid"])
            if k is None:
                k = "(absent)"
            agg[k][0] += 1
            if abs(r["ratio"] - 1) <= BAND:
                agg[k][1] += 1
            agg[k][2].append(r["ratio"])
        print(f"\n--- by {label} ---")
        print(f"{'value':<40}{'n':>6}{'agree':>7}{'agree%':>8}{'medRatio':>10}")
        for k in sorted(agg, key=lambda k: median(agg[k][2])):
            n, a, rr = agg[k]
            print(f"{str(k):<40}{n:>6}{a:>7}{100*a/n:>7.0f}%{median(rr):>10.3f}")

    crosstab("test family", family)
    crosstab("account_mode", lambda t: tok(t, "account_mode_AccountMode."))
    crosstab("opcode", lambda t: tok(t, "opcode_"))
    crosstab("overhead_baseline", lambda t: tok(t, "overhead_baseline_"))
    crosstab("value_sent", lambda t: tok(t, "value_sent_"))
    crosstab("existing_slots", lambda t: tok(t, "existing_slots_"))
    crosstab("cache_strategy", lambda t: tok(t, "cache_strategy_CacheStrategy."))


if __name__ == "__main__":
    main()
