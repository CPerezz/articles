#!/usr/bin/env python3
"""Round 10: split the penalty by OPCODE, not by account mode.

Round 2 grouped by account_mode, and every mode averages over all eight
opcodes - which would hide a code-path effect completely. BALANCE and
EXTCODEHASH answer from the account record alone; CALL, CALLCODE,
DELEGATECALL, STATICCALL, EXTCODESIZE and EXTCODECOPY have to fetch the
contract code. state-actor holds 134.4 M distinct code blobs against
jochemnet's 2.4 M, so if the code table drives the residual, the two groups
must separate.
"""
import json
import os
import re
import statistics

RUNS = {
    "jochemnet": "/data/bench-results/jochemnet/runs/1787952270_6621b826_geth-bal-full",
    "state-actor": "/data/bench-results/state-actor/runs/1788015169_bc76d34c_geth-bal-full",
}
PAT = re.compile(r"opcode_([A-Z]+)-value_sent_(\d).*AccountMode\.([A-Z_]+)"
                 r"-overhead_baseline_(True|False).*gas-value_(\d+M)")
DM = "EXISTING_CONTRACT_DIFF_MAX"
LEAF_ONLY = {"BALANCE", "EXTCODEHASH"}


def harvest(root):
    out = {}
    for dp, _, fn in os.walk(root):
        if "test.result-details.json" not in fn:
            continue
        try:
            name = open(os.path.join(dp, ".test-name")).read()
        except OSError:
            continue
        m = PAT.search(name)
        if not m:
            continue
        op, vs, mode, ob, gas = m.groups()
        if vs != "0" or ob != "False":
            continue
        d = json.load(open(os.path.join(dp, "test.result-details.json")))
        r = (d.get("resources") or {}).get("0") or {}
        g = (d.get("gas_used") or {}).get("0")
        mg = (d.get("mgas_s") or {}).get("0")
        if not g or not mg:
            continue
        mgas = g / 1e6
        out[(op, mode, gas)] = {
            "mgas_s": mg,
            "read_kb": (r.get("disk_read_bytes") or 0) / 1024 / mgas,
            "iops": (r.get("disk_read_iops") or 0) / mgas,
            "cpu_us": (r.get("cpu_delta_usec") or 0) / mgas,
        }
    return out


def med(v):
    return statistics.median(v) if v else float("nan")


data = {k: harvest(v) for k, v in RUNS.items()}
keys = [k for k in sorted(set(data["jochemnet"]) & set(data["state-actor"]))
        if k[1] != DM]
print(f"non-DIFF_MAX cells joined: {len(keys)}\n")

print("=== per OPCODE (state-actor / jochemnet), DIFF_MAX excluded ===")
print(f"{'opcode':<14}{'reads code?':<13}{'mgas/s':>9}{'read_kb':>10}{'iops':>9}"
      f"{'cpu':>9}   n")
rows = {}
for op in sorted({k[0] for k in keys}):
    sel = [k for k in keys if k[0] == op]
    r = {}
    for f in ("mgas_s", "read_kb", "iops", "cpu_us"):
        r[f] = med([data["state-actor"][k][f] / data["jochemnet"][k][f]
                    for k in sel if data["jochemnet"][k][f]])
    rows[op] = r
    print(f"{op:<14}{'no' if op in LEAF_ONLY else 'YES':<13}"
          f"{r['mgas_s']:>9.3f}{r['read_kb']:>10.3f}{r['iops']:>9.3f}"
          f"{r['cpu_us']:>9.3f}   {len(sel)}")

leaf = [op for op in rows if op in LEAF_ONLY]
code = [op for op in rows if op not in LEAF_ONLY]
print("\n=== grouped ===")
for name, grp in (("leaf-only (no code read)", leaf), ("code-reading", code)):
    for f in ("mgas_s", "read_kb", "iops", "cpu_us"):
        pass
    print(f"  {name:<26}"
          + "  ".join(f"{f} {med([rows[o][f] for o in grp]):.3f}"
                      for f in ("mgas_s", "read_kb", "iops", "cpu_us")))

print("\n=== absolute read_kb per Mgas, to see what dominates ===")
print(f"{'opcode':<14}{'jochemnet':>12}{'state-actor':>13}{'delta':>10}")
for op in sorted(rows):
    sel = [k for k in keys if k[0] == op]
    j = med([data["jochemnet"][k]["read_kb"] for k in sel])
    s = med([data["state-actor"][k]["read_kb"] for k in sel])
    print(f"{op:<14}{j:>12.0f}{s:>13.0f}{s-j:>10.0f}")
