"""Shared parsing for v3 result dirs.

Split out because the first version of this logic lived duplicated inside two scripts, and both
copies had the same two bugs. Validating them by monkeypatching the loader hid both: the
comparison logic was exercised, the parsing never was.

The two bugs, for the record:
  * gas is encoded in a test id as `benchmark-gas-value_100M`, not `gas_100M`. A regex keyed on
    `gas_` matches nothing, so every row was silently dropped and the join came out empty.
  * there is no per-test `status` field. Pass and fail counts live in
    steps.test.aggregated.{success,fail}.
"""
import glob
import json
import os
import re

DARK = ("EXISTING_CONTRACT_DIFF_MAX", "EXISTING_CONTRACT_JUMPDEST")
ABSENT = "NON_EXISTING_ACCOUNT"


def parse(tid):
    """opcode / account_mode / value_sent / overhead_baseline / gas out of a pytest id."""
    f = dict(re.findall(
        r"(opcode|account_mode|value_sent|overhead_baseline)_(?:AccountMode\.)?([A-Za-z0-9_]+)",
        tid))
    m = re.search(r"gas-value_(\d+)M", tid)
    if m:
        f["gas"] = m.group(1)
    return f


def cls(mode):
    return "absent" if mode == ABSENT else ("dark" if mode in DARK else "light")


def load(results_dir):
    """-> rows keyed like the archived data, plus aggregate success/fail counts."""
    runs = sorted(d for d in glob.glob(os.path.join(results_dir, "runs", "*"))
                  if os.path.isdir(d))
    if not runs:
        raise SystemExit(f"no runs under {results_dir}")
    tests = json.load(open(os.path.join(runs[-1], "result.json")))["tests"]
    rows, succ, fail = {}, 0, 0
    for tid, meta in tests.items():
        agg = (meta.get("steps", {}).get("test") or {}).get("aggregated")
        if not agg:
            continue
        succ += int(agg.get("success") or 0)
        fail += int(agg.get("fail") or 0)
        ns = agg.get("gas_used_time_total") or agg.get("time_total")
        gas = agg.get("gas_used_total")
        if not ns or not gas:
            continue
        f = parse(tid)
        if not all(k in f for k in ("opcode", "account_mode", "gas")):
            continue
        rows[(f["opcode"], f["account_mode"], int(f["gas"]),
              int(f.get("value_sent", -1)), f.get("overhead_baseline") == "True")] = dict(
            mgas_s=gas / (ns / 1e9) / 1e6, gas_used=gas)
    return rows, succ, fail


def archived(dpath):
    D = json.load(open(dpath))
    key = lambda r: (r["opcode"], r["mode"], r["gas"], r["value_sent"], r["baseline"])
    return {a: {key(r): r for r in D["full"][a]} for a in ("compacted", "state_actor")}
