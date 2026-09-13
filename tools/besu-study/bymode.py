#!/usr/bin/env python3
"""state_actor / treated, split by account_mode AND value_sent.

The geth study found that value_sent=1 changes what a NON_EXISTING lookup costs: a value-bearing
CALL to an absent account additionally pays account-creation gas, so the loop iterates far fewer
times for the same gas budget. If the Besu NON_EXISTING anomaly is that pricing interaction
rather than a storage property, it should separate on value_sent.
"""
import collections
import json
import statistics as st

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
n = collections.defaultdict(list)
for c in common:
    key = (c[1], c[3])
    g[key].append(i["state_actor"][c]["mgas_s"] / i["treated"][c]["mgas_s"])
    n[key].append((i["treated"][c]["mgas_s"], i["state_actor"][c]["mgas_s"]))

print(f'{"account_mode":<30}{"value_sent":>11}{"n":>5}{"treated":>10}{"sa":>10}{"sa/treated":>12}')
for k, v in sorted(g.items(), key=lambda kv: st.median(kv[1])):
    mt = st.median([x[0] for x in n[k]])
    ms = st.median([x[1] for x in n[k]])
    print(f"{k[0]:<30}{str(k[1]):>11}{len(v):>5}{mt:>10.2f}{ms:>10.2f}{st.median(v):>12.3f}")
