#!/usr/bin/env python3
"""Same test id, full 1463-test suite vs filtered 129-test run.

The filtered arms disagree with the full suites by large factors. Either the filtered runs are
not comparable (in which case stages 1-6 cannot answer the mechanism question) or the full-suite
figures include something the filtered ones do not. Compare identical test ids directly.
"""
import glob
import json
import os

full = json.load(open("/root/bench/arms-three.json"))


def load(results_dir):
    runs = sorted(d for d in glob.glob(os.path.join(results_dir, "runs", "*")) if os.path.isdir(d))
    index = json.load(open(os.path.join(runs[-1], "result.json")))["tests"]
    out = {}
    for tid, meta in index.items():
        agg = (meta.get("steps", {}).get("test") or {}).get("aggregated")
        if agg:
            out[tid] = agg
    return out


filt = load("/data/bench-results/s3-plain")
byid = {r["test_id"]: r for r in full["untreated"]}
shared = [t for t in filt if t in byid]
print(f"test ids shared between full untreated and filtered plain: {len(shared)}")

print(f'\n{"":<4}{"full MGas/s":>13}{"filt MGas/s":>13}{"full bytes":>15}{"filt bytes":>15}  test')
for i, t in enumerate(sorted(shared)[:6]):
    f = byid[t]
    a = filt[t]
    ns = a.get("gas_used_time_total") or a.get("time_total")
    fm = a["gas_used_total"] / (ns / 1e9) / 1e6
    fb = a.get("resource_totals", {}).get("disk_read_bytes", 0)
    short = t.split("opcode_")[1].split("-overhead")[0] if "opcode_" in t else t[-40:]
    print(f'{i:<4}{f["mgas_s"]:>13.2f}{fm:>13.2f}{f["disk_read_bytes"]:>15}{fb:>15}  {short[:58]}')

# also: do the two runs agree on gas for the shared ids?
gf = sum(byid[t]["gas_used"] for t in shared)
gl = sum(filt[t]["gas_used_total"] for t in shared)
print(f"\ngas: full={gf:.6g} filtered={gl:.6g} ratio={gl/gf:.6f}")
