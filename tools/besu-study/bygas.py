#!/usr/bin/env python3
"""Ratio vs gas budget, per bucket.

The per-test counts flag only 582/1100 as >10% from jochemnet while every category median sits
near 0.35. That is only consistent if the ratio varies strongly WITHIN a category, and the gas
sweep is the obvious axis: a bigger budget means more lookups per block, so an artifact that
serves a fixed working set from RAM should matter more as gas grows.
"""
import collections
import json
import statistics as st

CODE_OPS = {"EXTCODECOPY", "EXTCODEHASH", "EXTCODESIZE", "CALL", "CALLCODE",
            "DELEGATECALL", "STATICCALL"}


def bucket(op, mode):
    if mode == "NON_EXISTING_ACCOUNT":
        return "absent"
    if mode == "EXISTING_EOA" or op == "BALANCE":
        return "leaf-only"
    return "code-reading" if op in CODE_OPS else "leaf-only"


a = json.load(open("/root/bench/arms-three.json"))


def idx(rows):
    return {
        (r["opcode"], r["mode"], r["gas"], r.get("value_sent"), r.get("baseline")): r
        for r in rows
        if all(k in r for k in ("opcode", "mode", "gas"))
    }


i = {k: idx(v) for k, v in a.items()}
common = sorted(set.intersection(*(set(v) for v in i.values())))

g = collections.defaultdict(list)
for c in common:
    g[(bucket(c[0], c[1]), int(c[2]))].append(
        (i["treated"][c]["mgas_s"] / i["untreated"][c]["mgas_s"],
         i["state_actor"][c]["mgas_s"] / i["untreated"][c]["mgas_s"])
    )

print(f'{"bucket":<14}{"gas":>5}{"n":>5}{"treated/joc":>13}{"sa/joc":>9}')
for k in sorted(g, key=lambda k: (k[0], k[1])):
    v = g[k]
    print(f"{k[0]:<14}{k[1]:>5}{len(v):>5}"
          f"{st.median([x[0] for x in v]):>13.3f}{st.median([x[1] for x in v]):>9.3f}")
