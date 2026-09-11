#!/usr/bin/env python3
"""Classify Nethermind baseline results by category and compare the two arms.

Metrics live inline in each run's result.json under tests[<id>].steps.<step>.aggregated
("dir" is empty and there are no per-test files to read). The `test` step is the measurement;
`setup` is the preparation block and is reported separately for reference.

Usage: classify.py <jochemnet_results_root> <state_actor_results_root> [step]
"""
import json, glob, os, re, sys
from statistics import median
from collections import defaultdict

RE_OPCODE = re.compile(r"opcode_([A-Z0-9]+)")
RE_MODE = re.compile(r"account_mode_AccountMode\.([A-Z_]+)")
RE_GAS = re.compile(r"value_(\d+)M")
RE_BASE = re.compile(r"overhead_baseline_(True|False)")

STEP = sys.argv[3] if len(sys.argv) > 3 else "test"


def collect(root):
    """Pick the run with the most tests (ignores earlier pilot runs) and extract metrics."""
    best, best_n = None, -1
    for rj in glob.glob(os.path.join(root, "runs", "*", "result.json")):
        try:
            n = len(json.load(open(rj)).get("tests", {}))
        except Exception:
            continue
        if n > best_n:
            best, best_n = rj, n
    if not best:
        return {}, None, 0
    tests = json.load(open(best))["tests"]
    out = {}
    for tid, meta in tests.items():
        step = (meta.get("steps") or {}).get(STEP) or {}
        a = step.get("aggregated") or {}
        gas, t = a.get("gas_used_total", 0), a.get("gas_used_time_total", 0)
        if a.get("fail") or not gas or not t:
            continue
        r = a.get("resource_totals", {})
        out[tid] = {
            "mgas_s": gas / (t / 1e9) / 1e6,
            "secs": t / 1e9,
            "read": r.get("disk_read_bytes", 0),
            "cpu": r.get("cpu_usec", 0),
        }
    return out, os.path.basename(os.path.dirname(best)), best_n


def key_of(tid):
    o, m = RE_OPCODE.search(tid), RE_MODE.search(tid)
    if not (o and m):
        return None
    g, b = RE_GAS.search(tid), RE_BASE.search(tid)
    # overhead_baseline_True rows are the no-state-work control: keep them separate.
    return (o.group(1), m.group(1), (g.group(1) + "M" if g else "?"),
            ("ctl" if (b and b.group(1) == "True") else "work"))


def bucket(rows):
    b = defaultdict(list)
    for tid, v in rows.items():
        k = key_of(tid)
        if k:
            b[k].append(v)
    return b


def main():
    joc, jrun, jn = collect(sys.argv[1])
    sa, srun, sn = collect(sys.argv[2])
    print(f"step measured: {STEP}")
    print(f"jochemnet   run {jrun}  indexed={jn}  usable={len(joc)}")
    print(f"state-actor run {srun}  indexed={sn}  usable={len(sa)}")

    bj, bs = bucket(joc), bucket(sa)
    common = sorted(set(bj) & set(bs))
    print(f"common categories: {len(common)}  (joc {len(bj)}, sa {len(bs)})\n")
    if not common:
        return

    rows = []
    for k in common:
        mj = median(v["mgas_s"] for v in bj[k])
        ms = median(v["mgas_s"] for v in bs[k])
        rj = median(v["read"] for v in bj[k])
        rs = median(v["read"] for v in bs[k])
        rows.append((k, mj, ms, (ms / mj if mj else 0), rj, rs, len(bj[k]), len(bs[k])))

    work = [r for r in rows if r[0][3] == "work"]
    ctl = [r for r in rows if r[0][3] == "ctl"]

    def dump(sel, title):
        if not sel:
            return
        print(f"### {title} ({len(sel)} categories)")
        print(f"{'opcode':<14}{'account_mode':<28}{'gas':>5}"
              f"{'joc':>9}{'sa':>9}{'sa/joc':>8}{'jocMB':>9}{'saMB':>9}{'n':>8}")
        print("-" * 99)
        for (op, mode, gas, _), mj, ms, ratio, rj, rs, nj, ns in sorted(sel, key=lambda r: r[3]):
            print(f"{op:<14}{mode:<28}{gas:>5}{mj:>9.2f}{ms:>9.2f}{ratio:>8.3f}"
                  f"{rj/1e6:>9.1f}{rs/1e6:>9.1f}{f'{nj}/{ns}':>8}")
        rr = [r[3] for r in sel]
        print("-" * 99)
        print(f"sa/joc: min {min(rr):.3f}  median {median(rr):.3f}  max {max(rr):.3f}"
              f"   within +/-10%: {sum(1 for x in rr if 0.9 <= x <= 1.1)}/{len(rr)}\n")

    dump(ctl, "CONTROL (overhead_baseline=True, no account-state work)")
    dump(work, "MEASURED (overhead_baseline=False)")

    for label, idx in (("account_mode", 1), ("opcode", 0)):
        agg = defaultdict(list)
        for r in work:
            agg[r[0][idx]].append(r[3])
        if not agg:
            continue
        print(f"median sa/joc by {label}:")
        for k in sorted(agg, key=lambda k: median(agg[k])):
            print(f"  {k:<28} {median(agg[k]):>7.3f}   (n={len(agg[k])})")
        print()


if __name__ == "__main__":
    main()
