#!/usr/bin/env python3
"""Tests diverging >10% from the plain jochemnet arm, bucketed by type.

Mirrors the geth report's classification, which split tests into DIFF_MAX / flat / other rather
than quoting one median over a bimodal population.

Reference arm is **jochemnet as shipped** (untreated). Measured against it:
  treated      the same database after flush + full compaction
  state_actor  the generated companion

Buckets, following the geth article's vocabulary:
  absent        NON_EXISTING_ACCOUNT -- absence lookups; the class the treatment does not move
  leaf-only     BALANCE / EXISTING_EOA targets -- reads the account leaf, never the code
  code-reading  EXTCODE*/CALL-family into contracts -- additionally reads the code blob
"""
import collections
import json
import statistics as st

CODE_OPS = {"EXTCODECOPY", "EXTCODEHASH", "EXTCODESIZE", "CALL", "CALLCODE",
            "DELEGATECALL", "STATICCALL"}
THRESH = 0.10


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
REF = "untreated"

counts = collections.defaultdict(lambda: collections.Counter())
for c in common:
    b = bucket(c[0], c[1])
    counts[b]["n"] += 1
    for arm in ("treated", "state_actor"):
        r = i[arm][c]["mgas_s"] / i[REF][c]["mgas_s"]
        if abs(r - 1.0) > THRESH:
            counts[b][arm] += 1

print(f"=== per-test divergence from jochemnet (as shipped), |delta| > 10% ===")
print(f'{"bucket":<14}{"tests":>7}{"treated":>10}{"state_actor":>13}')
tot = collections.Counter()
for b in ("absent", "leaf-only", "code-reading"):
    c = counts[b]
    tot.update(c)
    print(f'{b:<14}{c["n"]:>7}{c["treated"]:>10}{c["state_actor"]:>13}')
print(f'{"TOTAL":<14}{tot["n"]:>7}{tot["treated"]:>10}{tot["state_actor"]:>13}')

cat = collections.defaultdict(list)
for c in common:
    cat[(bucket(c[0], c[1]), c[0], c[1], c[3])].append(
        (i[REF][c]["mgas_s"], i["treated"][c]["mgas_s"], i["state_actor"][c]["mgas_s"])
    )

rows = []
for k, v in cat.items():
    mj = st.median([x[0] for x in v])
    mt = st.median([x[1] for x in v])
    ms = st.median([x[2] for x in v])
    rows.append((k, len(v), mj, mt, ms, mt / mj, ms / mj))

flagged = [r for r in rows if abs(r[5] - 1) > THRESH or abs(r[6] - 1) > THRESH]
print(f"\n=== categories diverging >10% from jochemnet ({len(flagged)} of {len(rows)}) ===")
print(f'{"bucket":<13}{"opcode":<14}{"account_mode":<28}{"vs":>3}{"n":>5}'
      f'{"jochem":>9}{"treated":>9}{"sa":>9}{"tr/joc":>8}{"sa/joc":>8}')
for (b, op, mode, vs), n, mj, mt, ms, rt, rs in sorted(flagged, key=lambda r: r[5]):
    print(f"{b:<13}{op:<14}{mode:<28}{str(vs):>3}{n:>5}"
          f"{mj:>9.2f}{mt:>9.2f}{ms:>9.2f}{rt:>8.3f}{rs:>8.3f}")

within = [r for r in rows if r not in flagged]
print(f"\n=== categories within 10% on BOTH comparisons: {len(within)} ===")
for (b, op, mode, vs), n, mj, mt, ms, rt, rs in sorted(within, key=lambda r: r[5]):
    print(f"{b:<13}{op:<14}{mode:<28}{str(vs):>3}{n:>5}"
          f"{mj:>9.2f}{mt:>9.2f}{ms:>9.2f}{rt:>8.3f}{rs:>8.3f}")
