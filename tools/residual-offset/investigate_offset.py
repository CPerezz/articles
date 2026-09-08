#!/usr/bin/env python3
"""Where does the residual ~10% offset between the arms live?

Step 1: the overhead_baseline tests are a control - they do no account-state
work, so compacted vs uncompacted (the SAME bytes on disk) must agree. Their
disagreement is the noise floor for every cross-arm claim.

Step 2: split total_ms into its phases at matched (opcode, mode, gas) and see
which phase carries the difference.

Read-only; reuses the report's own parser so the test classification is
identical.
"""
import os
import statistics

import gen_state_db_report as G


def load():
    raw, order = {}, {}
    for k, _, f in G.LOGS:
        raw[k], order[k] = G.parse_log(os.path.join(G.DATA, f))
    meas = {k: G.measured(raw[k]) for k in G.KEYS}
    common = [t for t in order["c"] if all(t in meas[k] for k in G.KEYS)]
    P = {t: G.parse_params(t) for t in common}
    return meas, P, common


def q(xs):
    xs = sorted(xs)
    n = len(xs)
    return (statistics.median(xs), xs[n // 4], xs[(3 * n) // 4], xs[0], xs[-1])


def ratios(tests, meas, num, den, path):
    out = []
    for t in tests:
        a, b = meas[num][t], meas[den][t]
        for key in path:
            a, b = a.get(key), b.get(key)
            if a is None or b is None:
                break
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b:
            out.append(a / b)
    return out


def main():
    meas, P, common = load()
    baseline = [t for t in common if P[t]["baseline"]]
    clean = [t for t in common if not P[t]["baseline"] and P[t]["value_sent"] == 0]
    print(f"common={len(common)} baseline={len(baseline)} clean={len(clean)}\n")

    sample = meas["c"][common[0]]
    print("=== available block-record sections ===")
    for k, v in sample.items():
        if isinstance(v, dict):
            print(f"  {k}: {', '.join(list(v)[:9])}")
    print()

    print("=== STEP 1: baseline control (no account-state work) ===")
    print("compacted vs uncompacted are the same database; any gap is run-level.\n")
    print(f"{'ratio':<22}{'median':>9}{'p25':>9}{'p75':>9}{'min':>9}{'max':>9}   n")
    for num, den in (("u", "c"), ("sa", "c"), ("sa", "u")):
        r = ratios(baseline, meas, num, den, ["timing", "total_ms"])
        m, p25, p75, lo, hi = q(r)
        print(f"{G.LABEL[num]+'/'+G.LABEL[den]:<22}{m:>9.3f}{p25:>9.3f}{p75:>9.3f}"
              f"{lo:>9.3f}{hi:>9.3f}   {len(r)}")

    print("\nper-arm baseline total_ms (median of the same 165 tests):")
    for k in G.KEYS:
        v = [meas[k][t]["timing"]["total_ms"] for t in baseline]
        m, p25, p75, lo, hi = q(v)
        print(f"  {G.LABEL[k]:<14}{m:>9.2f} ms   p25 {p25:>7.2f}  p75 {p75:>7.2f}")

    print("\n=== STEP 2: phase decomposition, state-touching tests ===")
    phases = [p for p in ("execution_ms", "state_read_ms", "commit_ms", "total_ms")
              if p in sample.get("timing", {})]
    print(f"phases present: {phases}\n")
    print(f"{'phase':<18}" + "".join(f"{G.LABEL[k]:>14}" for k in G.KEYS)
          + f"{'sa/c':>9}{'u/c':>9}")
    for ph in phases:
        med = {}
        for k in G.KEYS:
            vals = [meas[k][t]["timing"][ph] for t in clean
                    if isinstance(meas[k][t]["timing"].get(ph), (int, float))]
            med[k] = statistics.median(vals) if vals else float("nan")
        sa_c = med["sa"] / med["c"] if med["c"] else float("nan")
        u_c = med["u"] / med["c"] if med["c"] else float("nan")
        print(f"{ph:<18}" + "".join(f"{med[k]:>14.3f}" for k in G.KEYS)
              + f"{sa_c:>9.3f}{u_c:>9.3f}")

    print("\nsame, on the baseline tests (no state work):")
    for ph in phases:
        med = {}
        for k in G.KEYS:
            vals = [meas[k][t]["timing"][ph] for t in baseline
                    if isinstance(meas[k][t]["timing"].get(ph), (int, float))]
            med[k] = statistics.median(vals) if vals else float("nan")
        sa_c = med["sa"] / med["c"] if med["c"] else float("nan")
        u_c = med["u"] / med["c"] if med["c"] else float("nan")
        print(f"{ph:<18}" + "".join(f"{med[k]:>14.3f}" for k in G.KEYS)
              + f"{sa_c:>9.3f}{u_c:>9.3f}")

    print("\n=== gas accounting: is the same work being compared? ===")
    for k in G.KEYS:
        gas = [meas[k][t]["block"]["gas_used"] for t in clean]
        txs = [meas[k][t]["block"].get("tx_count") for t in clean]
        txs = [x for x in txs if isinstance(x, (int, float))]
        print(f"  {G.LABEL[k]:<14} median gas_used {statistics.median(gas):>12,.0f}"
              + (f"   median txs {statistics.median(txs):>5.1f}" if txs else ""))


if __name__ == "__main__":
    main()
