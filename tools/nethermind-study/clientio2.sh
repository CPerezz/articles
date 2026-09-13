#!/usr/bin/env bash
# Cold client-served cost of reading an account that REALLY EXISTS in this store.
#
# Existence matters: a missing account short-circuits, so comparing stores demands
# addresses present in each. Here they are harvested from the store's own recent blocks.
set -uo pipefail
N=${1:-20000}
FROMBLK=${2:-300}
RPC=http://127.0.0.1:8545
PID=$(sudo podman inspect -f '{{.State.Pid}}' nmprobe)
[ -n "$PID" ] || { echo "nmprobe not running"; exit 2; }

python3 - "$N" "$FROMBLK" "$RPC" > /tmp/addrs.txt <<'PY'
import json, sys, urllib.request
n, nblk, rpc = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
def call(m, p):
    req = urllib.request.Request(rpc, json.dumps(
        {"jsonrpc": "2.0", "method": m, "params": p, "id": 1}).encode(),
        {"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())["result"]
head = int(call("eth_blockNumber", []), 16)
seen = []
got = set()
for i in range(nblk):
    b = call("eth_getBlockByNumber", [hex(head - i), True])
    if not b:
        continue
    for t in b["transactions"]:
        for k in ("from", "to"):
            a = t.get(k)
            if a and a not in got:
                got.add(a)
                seen.append(a)
    if len(seen) >= n:
        break
for a in seen[:n]:
    print(a)
PY
CNT=$(wc -l < /tmp/addrs.txt)
echo "  harvested existing addresses: $CNT (from recent blocks)"

sudo podman restart nmprobe >/dev/null 2>&1
for i in $(seq 1 60); do curl -s -m 3 "$RPC" -X POST -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' 2>/dev/null | grep -q result && break; sleep 5; done
PID=$(sudo podman inspect -f '{{.State.Pid}}' nmprobe)
rd() { sudo awk '/^read_bytes:/{print $2}' /proc/$PID/io; }
sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null; sleep 3

B=$(rd); S=$(date +%s.%N)
python3 - "$RPC" < /tmp/addrs.txt <<'PY'
import json, sys, urllib.request
rpc = sys.argv[1]
addrs = [l.strip() for l in sys.stdin if l.strip()]
def send(b):
    req = urllib.request.Request(rpc, json.dumps(b).encode(), {"content-type": "application/json"})
    urllib.request.urlopen(req, timeout=300).read()
batch = []
for i, a in enumerate(addrs):
    batch.append({"jsonrpc": "2.0", "method": "eth_getBalance", "params": [a, "latest"], "id": i})
    if len(batch) == 200:
        send(batch); batch = []
if batch:
    send(batch)
print("  lookups       : %d" % len(addrs))
PY
E=$(date +%s.%N); A=$(rd)
python3 - "$B" "$A" "$CNT" "$S" "$E" <<'PY'
import sys
b, a, n = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
s, e = float(sys.argv[4]), float(sys.argv[5])
d = a - b
print("  wall          : %.2f s  (%.0f us/lookup)" % (e - s, (e - s) * 1e6 / n))
print("  disk read     : %.1f MB" % (d / 1e6))
print("  BYTES/LOOKUP  : %.0f" % (d / n))
print("  BLOCKS/LOOKUP : %.2f" % (d / n / 4096))
PY
