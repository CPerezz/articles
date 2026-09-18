#!/usr/bin/env python3
"""Decide whether the 129-test arm licenses the 22 h full arm.

Thresholds are the ones adjudicated in the plan, fixed before any v3 number existed:

  1. every test in the filter arm passes. A failure means the store, the fixtures or the
     rollback disagree, and a 22 h run would inherit that.
  2. absent class, control-normalised, inside 0.85-1.15. #133 removed the mechanism, so the
     0.117 regime must be gone. Anything still near 0.117 means the filters are not in play
     and the store is not what we think it is.
  3. distinct-code class median > 0.95. #138 over-corrects, so this class should be at or
     above parity. Still near 0.828 means #138 did not take effect in this store.

These gate the *spend*, not the conclusion. A pass says the store is coherent enough to be
worth a day of device time; it does not decide what the residual is.

Exit 0 to proceed, 1 to stop.
"""
import glob
import json
import os
import re
import statistics as st
import sys

DARK = ("EXISTING_CONTRACT_DIFF_MAX", "EXISTING_CONTRACT_JUMPDEST")
ABSENT = "NON_EXISTING_ACCOUNT"


def parse(tid):
    return dict(re.findall(r"(opcode|account_mode|gas|value_sent|overhead_baseline)"
                           r"_(?:AccountMode\.)?([A-Za-z0-9_]+)", tid))


def load(results_dir):
    runs = sorted(d for d in glob.glob(os.path.join(results_dir, "runs", "*")) if os.path.isdir(d))
    if not runs:
        print(f"FAIL: no runs under {results_dir}")
        sys.exit(1)
    res = json.load(open(os.path.join(runs[-1], "result.json")))
    rows, npass, nfail = {}, 0, 0
    for tid, meta in res.get("tests", {}).items():
        status = str(meta.get("status", "")).lower()
        if status in ("passed", "pass", "ok", "success"):
            npass += 1
        elif status:
            nfail += 1
        agg = (meta.get("steps", {}).get("test") or {}).get("aggregated")
        if not agg:
            continue
        ns = agg.get("gas_used_time_total") or agg.get("time_total")
        gas = agg.get("gas_used_total")
        if not ns or not gas:
            continue
        f = parse(tid)
        if not all(k in f for k in ("opcode", "account_mode", "gas")):
            continue
        g = int(re.sub(r"[^0-9]", "", f["gas"]) or 0)
        rows[(f["opcode"], f["account_mode"], g, int(f.get("value_sent", -1)),
              f.get("overhead_baseline") == "True")] = gas / (ns / 1e9) / 1e6
    return rows, npass, nfail


def main():
    results = sys.argv[1] if len(sys.argv) > 1 else "/data/bench-results/v3-filter"
    dpath = sys.argv[2] if len(sys.argv) > 2 else "/root/bench/report_data_archived.json"
    rows, npass, nfail = load(results)
    D = json.load(open(dpath))
    key = lambda r: (r["opcode"], r["mode"], r["gas"], r["value_sent"], r["baseline"])
    comp = {key(r): r["mgas_s"] for r in D["full"]["compacted"]}

    common = [k for k in rows if k in comp]
    meas = [k for k in common if not k[4]]
    ctrl = [k for k in common if k[4]]
    if not meas:
        print("FAIL: no measurement rows joined to the archived compacted arm")
        return 1
    r = lambda k: rows[k] / comp[k]
    cn = st.median([r(k) for k in ctrl]) if ctrl else 1.0

    absent = [r(k) for k in meas if k[1] == ABSENT]
    dark = [r(k) for k in meas if k[1] in DARK]
    a_med = st.median(absent) / cn if absent else float("nan")
    d_med = st.median(dark) if dark else float("nan")

    checks = [
        (f"all tests pass ({npass} passed, {nfail} failed)", nfail == 0 and npass > 0),
        (f"absent control-normalised {a_med:.3f} in 0.85-1.15", 0.85 <= a_med <= 1.15),
        (f"distinct-code median {d_med:.3f} > 0.95", d_med > 0.95),
    ]
    print(f"joined {len(common)} tests ({len(meas)} measurement, {len(ctrl)} control), "
          f"control {cn:.4f}")
    for name, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    bad = [n for n, ok in checks if not ok]
    if bad:
        print("\nGO/NO-GO: NO-GO. The 22 h arm is not licensed; re-gate the store.")
        return 1
    print("\nGO/NO-GO: GO. Proceeding to the full suite.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
