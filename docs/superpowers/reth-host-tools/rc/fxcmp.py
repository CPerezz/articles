#!/usr/bin/env python3
"""Compare two fixture trees test by test: payload counts, txs, gas, BAL size.
usage: fxcmp.py <tree A> <tree B> [max tests]. Trees are blockchain_tests_stateful_engine roots.
Equal block contents are expected to differ only in hashes/roots (the fillers are different clients)."""
import json, os, sys
A, B = sys.argv[1], sys.argv[2]
LIM = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9

def load(root):
    out = {}
    for d, _, fs in os.walk(root):
        if "/pre_run" in d or "/.meta" in d:
            continue
        for f in fs:
            if f.endswith(".json"):
                for tid, t in json.load(open(os.path.join(d, f))).items():
                    out[tid] = t
    return out

def shape(t):
    def p(ps):
        return [(int(x["params"][0]["gasUsed"], 16), len(x["params"][0]["transactions"]),
                 len(x["params"][0].get("blockAccessList") or "") // 2, x["newPayloadVersion"]) for x in ps]
    return {"setup": p(t.get("setupEngineNewPayloads", [])), "bench": p(t["engineNewPayloads"]),
            "benchmarkGasUsed": t.get("benchmarkGasUsed")}

a, b = load(A), load(B)
common = sorted(set(a) & set(b))
print(f"A {len(a)} tests, B {len(b)} tests, common {len(common)}, only A {len(set(a)-set(b))}, only B {len(set(b)-set(a))}")
same = 0
for tid in common[:LIM]:
    sa, sb = shape(a[tid]), shape(b[tid])
    if sa == sb:
        same += 1
        continue
    print("DIFF", tid.split("::")[-1][:140])
    for k in sa:
        if sa[k] != sb[k]:
            print(f"  {k}: A {str(sa[k])[:200]}\n  {' ' * len(k)}  B {str(sb[k])[:200]}")
print(f"identical shape (gas, tx count, BAL bytes, version): {same}/{min(len(common), LIM)}")
