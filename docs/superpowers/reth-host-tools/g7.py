import json, glob, os, re
J = "/root/.cache/benchmarkoor/eest-url/6142626aac06abc4/fixtures/benchmarkoor-build-artifacts/eest-payloads/geth/blockchain_tests_stateful_engine"
S = "/root/bench/reth/fixtures/sa-v2-full/nethermind/blockchain_tests_stateful_engine"
def ids(root):
    out = {}
    for p in glob.glob(root + "/**/*.json", recursive=True):
        if "/pre_run" in p:
            continue
        try:
            d = json.load(open(p))
        except Exception:
            continue
        for k in d:
            if re.search(r"value_(160|240)M\]", k):
                out[re.sub(r"^tests/", "", k)] = p
    return out
j, s = ids(J), ids(S)
common = sorted(set(j) & set(s))
print("J", len(j), "S", len(s), "common", len(common))
only_j = sorted(set(j) - set(s)); only_s = sorted(set(s) - set(j))
fam = lambda k: re.search(r"::(test_[a-z_]+)\[", k).group(1)
from collections import Counter
print("only J by family", Counter(map(fam, only_j)).most_common(8))
print("only S by family", Counter(map(fam, only_s)).most_common(8))
json.dump(common, open("/root/bench/reth/cfg/common-ids.json", "w"), indent=0)
print(common[0])
