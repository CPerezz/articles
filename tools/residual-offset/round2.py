#!/usr/bin/env python3
"""Round 2: I/O volume vs CPU, from our own reproduction where both arms sat
on symmetric NVMe schelk volumes.

Per test the harness records resources: disk_read_bytes, disk_read_iops,
cpu_delta_usec. Normalised by gas and joined on (opcode, mode, gas), these
separate "state-actor moves more bytes" from "state-actor burns more CPU"
from "same work, slower wall clock".
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
        dn = d.get("duration_ns")
        dur = (dn[0] if isinstance(dn, list) and dn
               else dn.get("0") if isinstance(dn, dict) else None)
        if not g or not mg:
            continue
        mgas = g / 1e6
        out[(op, mode, gas)] = {
            "mgas_s": mg,
            "ms": dur / 1e6 if dur else None,
            "read_kb_per_mgas": (r.get("disk_read_bytes") or 0) / 1024 / mgas,
            "read_iops_per_mgas": (r.get("disk_read_iops") or 0) / mgas,
            "cpu_us_per_mgas": (r.get("cpu_delta_usec") or 0) / mgas,
            "write_kb_per_mgas": (r.get("disk_write_bytes") or 0) / 1024 / mgas,
        }
    return out


def med(v):
    return statistics.median(v) if v else float("nan")


data = {k: harvest(v) for k, v in RUNS.items()}
keys = sorted(set(data["jochemnet"]) & set(data["state-actor"]))
honest = [k for k in keys if k[1] != DM]
dmax = [k for k in keys if k[1] == DM]
print(f"joined cells: {len(keys)}  honest: {len(honest)}  DIFF_MAX: {len(dmax)}\n")

for name, sel in (("HONEST MODES (the residual)", honest), ("DIFF_MAX", dmax)):
    if not sel:
        continue
    print(f"=== {name} ===")
    print(f"{'metric':<24}{'jochemnet':>13}{'state-actor':>13}{'sa/joc':>9}"
          f"{'paired':>9}")
    for field in ("mgas_s", "read_kb_per_mgas", "read_iops_per_mgas",
                  "cpu_us_per_mgas", "write_kb_per_mgas"):
        j = [data["jochemnet"][k][field] for k in sel]
        s = [data["state-actor"][k][field] for k in sel]
        paired = [data["state-actor"][k][field] / data["jochemnet"][k][field]
                  for k in sel if data["jochemnet"][k][field]]
        mj, ms_ = med(j), med(s)
        ratio = ms_ / mj if mj else float("nan")
        print(f"{field:<24}{mj:>13.2f}{ms_:>13.2f}{ratio:>9.3f}{med(paired):>9.3f}")
    print()

print("=== per-mode throughput ratio (state-actor / jochemnet) ===")
modes = sorted({k[1] for k in keys})
for m in modes:
    sel = [k for k in keys if k[1] == m]
    pr = [data["state-actor"][k]["mgas_s"] / data["jochemnet"][k]["mgas_s"]
          for k in sel if data["jochemnet"][k]["mgas_s"]]
    cpu = [data["state-actor"][k]["cpu_us_per_mgas"] / data["jochemnet"][k]["cpu_us_per_mgas"]
           for k in sel if data["jochemnet"][k]["cpu_us_per_mgas"]]
    rd = [data["state-actor"][k]["read_kb_per_mgas"] / data["jochemnet"][k]["read_kb_per_mgas"]
          for k in sel if data["jochemnet"][k]["read_kb_per_mgas"]]
    print(f"  {m:<32} mgas/s {med(pr):>6.3f}   cpu {med(cpu):>6.3f}   "
          f"read_kb {med(rd) if rd else float('nan'):>7.3f}   n={len(sel)}")
