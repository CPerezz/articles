#!/usr/bin/env bash
# Attribute Nethermind's physical reads to databases while it serves account reads.
#
# Head == flat CurrentState here (no blocks executed), so a correctly working flat layout
# should satisfy eth_getBalance from the Account column alone. Any large counter movement on
# the trie-node databases means reads are not being served from flat.
set -uo pipefail
N=${1:-3000}
RPC=http://127.0.0.1:8545
MET=http://127.0.0.1:8008/metrics

snap() { curl -s -m 10 "$MET" | grep -E "^nethermind_db_reads" ; }

echo "=== head block ==="
curl -s -m 5 "$RPC" -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'
echo

snap > /tmp/m_before.txt

echo "=== issuing $N eth_getBalance on sequential EOAs (0x1000+) ==="
python3 - "$N" "$RPC" <<'PY'
import json, sys, urllib.request
n, rpc = int(sys.argv[1]), sys.argv[2]
batch = []
for i in range(n):
    addr = "0x" + ("%040x" % (0x1000 + i))
    batch.append({"jsonrpc": "2.0", "method": "eth_getBalance",
                  "params": [addr, "latest"], "id": i})
    if len(batch) == 200:
        req = urllib.request.Request(rpc, json.dumps(batch).encode(),
                                     {"content-type": "application/json"})
        urllib.request.urlopen(req, timeout=120).read()
        batch = []
if batch:
    req = urllib.request.Request(rpc, json.dumps(batch).encode(),
                                 {"content-type": "application/json"})
    urllib.request.urlopen(req, timeout=120).read()
print("done", n, "lookups")
PY

snap > /tmp/m_after.txt

echo "=== per-database read delta ==="
python3 - <<'PY'
def load(p):
    out = {}
    for line in open(p):
        line = line.strip()
        if not line.startswith("nethermind_db_reads"):
            continue
        name, val = line.rsplit(" ", 1)
        out[name] = float(val)
    return out
b, a = load("/tmp/m_before.txt"), load("/tmp/m_after.txt")
rows = []
for k in sorted(set(a) | set(b)):
    d = a.get(k, 0) - b.get(k, 0)
    if d:
        rows.append((d, k))
rows.sort(reverse=True)
if not rows:
    print("  (no counter movement)")
for d, k in rows[:20]:
    lbl = k[k.find("{"):] if "{" in k else k
    print(f"  {d:>12,.0f}  {lbl}")
PY
