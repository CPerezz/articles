#!/usr/bin/env python3
"""Verdict for a v3 arm, against pre-registered expectations.

Reads a benchmarkoor results dir and compares it to the archived arms in the besu article's
report_data.json. Prints PASS/FAIL per gate so the conclusion is decided by thresholds written
before the numbers existed, not chosen after seeing them.

Two things make the comparison legitimate or not, and both are gates here:

  * The control canary. v3 is compared against the ARCHIVED compacted-snapshot arm rather than a
    freshly rebuilt one, so a drift in the host, image or harness between then and now would look
    like a store effect. The control rows touch no account state, so their ratio isolates that
    drift. It must sit at the archived 1.019 within 0.013, with no per-budget median off by more
    than 0.02. A miss does not attribute the cause and does not prove a pass; it only says the
    archived reference cannot carry small-effect claims.

  * Gas identity. Each test must burn the same gas as the archived run to six figures, or the two
    arms were not asked to do the same work.

Usage: analyse-v3.py <results_dir> [report_data.json]
"""
import glob
import json
import os
import re
import statistics as st
import sys

DARK = ("EXISTING_CONTRACT_DIFF_MAX", "EXISTING_CONTRACT_JUMPDEST")
ABSENT = "NON_EXISTING_ACCOUNT"


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v3lib import load, cls, DARK, ABSENT


def arm(results_dir):
    rows, _succ, _fail = load(results_dir)
    return rows


def med(xs):
    return st.median(xs) if xs else float("nan")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    new = arm(sys.argv[1])
    dpath = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "report_data.json")
    D = json.load(open(dpath))
    key = lambda r: (r["opcode"], r["mode"], r["gas"], r["value_sent"], r["baseline"])
    ref = {a: {key(r): r for r in D["full"][a]} for a in ("compacted", "state_actor")}

    common = [k for k in new if k in ref["compacted"]]
    if not common:
        sys.exit("no overlap between this arm and the archived compacted arm")
    meas = [k for k in common if not k[4]]
    ctrl = [k for k in common if k[4]]
    r = lambda k: new[k]["mgas_s"] / ref["compacted"][k]["mgas_s"]
    old = lambda k: ref["state_actor"][k]["mgas_s"] / ref["compacted"][k]["mgas_s"]

    print(f"overlap: {len(common)} tests ({len(meas)} measurement, {len(ctrl)} control)\n")

    fails = []

    # ---- gate: gas identity -------------------------------------------------
    bad = [k for k in common
           if abs(new[k]["gas_used"] / ref["compacted"][k]["gas_used"] - 1) > 1e-6]
    print(f"[{'PASS' if not bad else 'FAIL'}] gas identity: {len(bad)} of {len(common)} tests "
          f"differ from the archived arm by more than 1e-6")
    if bad:
        fails.append("gas identity")

    # ---- gate: control canary ----------------------------------------------
    if ctrl:
        c = med([r(k) for k in ctrl])
        per_budget = {g: med([r(k) for k in ctrl if k[2] == g]) for g in sorted({k[2] for k in ctrl})}
        drift = max(abs(v - c) for v in per_budget.values())
        ok = abs(c - 1.019) <= 0.013 and drift <= 0.02
        print(f"[{'PASS' if ok else 'FAIL'}] control canary: {c:.4f} against the archived 1.019 "
              f"(tolerance 0.013), worst per-budget drift {drift:.4f} (tolerance 0.020)")
        if not ok:
            fails.append("control canary")
            print("       -> the archived reference cannot carry small-effect claims. Only the "
                  "collapse of the 0.117 and 0.828 regimes may be stated; parity arrival and "
                  "sign-flip magnitude wait for a rebuilt snapshot arm.")
    else:
        print("[WARN] no control rows in this arm, so drift is unmeasured")

    # ---- the three classes, then and now -----------------------------------
    print(f"\n{'class':10s} {'cats':>5s} {'rows':>5s} {'archived':>9s} {'v3':>8s} "
          f"{'expected':>26s}  verdict")
    EXP = {"absent": ("collapse: 0.117 -> ~1.0", lambda v: v > 0.9),
           "light": ("rise from 0.947", lambda v: v > 0.947),
           "dark": ("sign flip: 0.828 -> >1.0", lambda v: v > 1.0)}
    for c in ("absent", "light", "dark"):
        ks = [k for k in meas if cls(k[1]) == c]
        if not ks:
            continue
        nv, ov = med([r(k) for k in ks]), med([old(k) for k in ks])
        label, test = EXP[c]
        good = test(nv)
        print(f"{c:10s} {len({(k[0], k[1]) for k in ks}):5d} {len(ks):5d} {ov:9.3f} {nv:8.3f} "
              f"{label:>26s}  {'as predicted' if good else 'NOT as predicted'}")

    # ---- descriptive, not gated -------------------------------------------
    allr = [r(k) for k in meas]
    print(f"\nmeasurement rows: min {min(allr):.3f} median {med(allr):.3f} max {max(allr):.3f}")
    print(f"rows faster than the snapshot: {sum(1 for v in allr if v > 1.0)} of {len(allr)}")
    print(f"rows inside +/-10%: {sum(1 for v in allr if abs(v - 1) <= 0.10)} of {len(allr)}")
    budgets = sorted({k[2] for k in meas})
    if len(budgets) > 1:
        print("\ngradient (does the gap still widen with the gas budget?)")
        for c in ("absent", "light", "dark"):
            row = [med([r(k) for k in meas if cls(k[1]) == c and k[2] == g]) for g in budgets]
            if row and row[0] == row[0]:
                print(f"  {c:8s} " + " ".join(f"{v:6.3f}" for v in row))

    print("\nVERDICT: " + ("PASS" if not fails else "FAIL on " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
