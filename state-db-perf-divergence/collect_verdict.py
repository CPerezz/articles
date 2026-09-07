#!/usr/bin/env python3
"""Collect the three-way verdict cells (orig jochemnet / drained+compacted
jochemnet / state-actor) from benchmarkoor result trees on the bench host.

Run ON THE HOST:  python3 collect_verdict.py > drained_verdict.json
Committed next to the generator so the JSON's provenance is reproducible.
"""
import json, os, re, sys

ROOTS = {
    "orig":    "/data/bench-results/jochemnet/runs/1787952270_6621b826_geth-bal-full",
    "drained": "/data/bench-results/jochemnet-drained/runs",
    "sa":      "/data/bench-results/state-actor/runs/1788015169_bc76d34c_geth-bal-full",
}
MODES = ("EXISTING_CONTRACT_DIFF_MAX", "EXISTING_CONTRACT_MINIMAL")
GAS = ("160M", "300M")
PAT = re.compile(r"opcode_([A-Z]+)-value_sent_(\d).*AccountMode\.([A-Z_]+)"
                 r"-overhead_baseline_(True|False).*gas-value_(\d+M)")


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
        if vs != "0" or ob != "False" or mode not in MODES or gas not in GAS:
            continue
        d = json.load(open(os.path.join(dp, "test.result-details.json")))
        mg = (d.get("mgas_s") or {}).get("0")
        if mg:
            out[(op, mode, gas)] = round(mg, 3)
    return out


data = {k: harvest(v) for k, v in ROOTS.items()}
keys = sorted(set(data["orig"]) & set(data["drained"]) & set(data["sa"]))
assert len(keys) == 32, f"expected 32 common cells, got {len(keys)}"
cells = [{"opcode": op, "mode": mode, "gas": gas,
          "orig": data["orig"][k], "drained": data["drained"][k],
          "sa": data["sa"][k]}
         for k in keys for op, mode, gas in [k]]

# Drain-only smoke (pre-compaction): the 272 MGas/s datapoint. Full-gas
# BALANCE/DIFF_MAX/160M cell of the first drained smoke run.
smoke = [{"opcode": "BALANCE", "mode": "EXISTING_CONTRACT_DIFF_MAX",
          "gas": "160M", "mgas_s": 272.226}]

json.dump({
    "provenance": {
        "host": "stateless-bloatnet-benchmarks",
        "collected": "2026-09-07",
        "runs": {k: v for k, v in ROOTS.items()},
        "binary": "benchmarkoor 1e0b9d4 (+ post-pre-run hook c3c46f1, dormant: baseline pre-drained)",
        "baseline": "jochemnet drained (drainjournal @ geth 4d92c8e) + geth db compact, schelk-promoted",
        "selection": "value_sent=0, overhead_baseline=False, gas in {160M,300M}",
        "smoke_note": "smoke_drain_only measured on the drain-only baseline "
                      "(before the post-drain compaction), run jochemnet-drained-smoke",
    },
    "cells": cells,
    "smoke_drain_only": smoke,
}, sys.stdout, indent=1)
print()
