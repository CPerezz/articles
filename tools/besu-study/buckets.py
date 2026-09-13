#!/usr/bin/env python3
"""Final per-bucket summary: throughput and bytes, all three arms, jochemnet as reference."""
import collections
import json
import statistics as st

CODE = {"EXTCODECOPY", "EXTCODEHASH", "EXTCODESIZE", "CALL", "CALLCODE",
        "DELEGATECALL", "STATICCALL"}


def bucket(op, mode):
    if mode == "NON_EXISTING_ACCOUNT":
        return "absent"
    if mode == "EXISTING_EOA" or op == "BALANCE":
        return "leaf-only"
    return "code-reading" if op in CODE else "leaf-only"


a = json.load(open("/root/bench/arms-three.json"))


def idx(rows):
    return {
        (r["opcode"], r["mode"], r["gas"], r.get("value_sent"), r.get("baseline")): r
        for r in rows
        if all(k in r for k in ("opcode", "mode", "gas"))
    }


i = {k: idx(v) for k, v in a.items()}
common = sorted(set.intersection(*(set(v) for v in i.values())))

thr = collections.defaultdict(list)
byt = collections.defaultdict(list)
for c in common:
    b = bucket(c[0], c[1])
    thr[b].append((
        i["treated"][c]["mgas_s"] / i["untreated"][c]["mgas_s"],
        i["state_actor"][c]["mgas_s"] / i["untreated"][c]["mgas_s"],
        i["state_actor"][c]["mgas_s"] / i["treated"][c]["mgas_s"],
    ))
    byt[b].append((i["untreated"][c]["disk_read_bytes"],
                   i["treated"][c]["disk_read_bytes"],
                   i["state_actor"][c]["disk_read_bytes"]))

hdr = f'{"bucket":<14}{"n":>5}{"tr/joc":>9}{"sa/joc":>9}{"sa/tr":>9}{"bytes tr/joc":>14}{"bytes sa/joc":>14}'
print(hdr)
for b in ("absent", "leaf-only", "code-reading"):
    t = thr[b]
    d = byt[b]
    j = sum(x[0] for x in d)
    tt = sum(x[1] for x in d)
    s = sum(x[2] for x in d)
    print(f"{b:<14}{len(t):>5}"
          f"{st.median([x[0] for x in t]):>9.3f}"
          f"{st.median([x[1] for x in t]):>9.3f}"
          f"{st.median([x[2] for x in t]):>9.3f}"
          f"{tt/j:>14.2f}{s/j:>14.2f}")
