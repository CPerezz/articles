#!/usr/bin/env bash
# Measure physical bytes Nethermind pulls per client-served account read.
#
# Comparable by construction to probe-flat: same store, same key population, cold caches.
#   raw RocksDB Account lookup  ~8 KB   (measured)
#   benchmark per account access ~44 KB (measured)
# If a getBalance at head == CurrentState costs ~8 KB, the client adds nothing here and the
# benchmark's excess must come from executing blocks past CurrentState. If it costs ~44 KB,
# the client pays it unconditionally.
set -uo pipefail
N=${1:-20000}
RPC=http://127.0.0.1:8545
PID=$(sudo podman inspect -f '{{.State.Pid}}' nmprobe)
[ -n "$PID" ] || { echo "nmprobe not running"; exit 2; }

rd() { sudo awk '/^read_bytes:/{print $2}' /proc/$PID/io; }

sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null; sleep 3
B=$(rd)
S=$(date +%s.%N)
python3 - "$N" "$RPC" <<'PY'
import json, sys, urllib.request
n, rpc = int(sys.argv[1]), sys.argv[2]
def send(b):
    req = urllib.request.Request(rpc, json.dumps(b).encode(), {"content-type": "application/json"})
    urllib.request.urlopen(req, timeout=300).read()
batch = []
for i in range(n):
    batch.append({"jsonrpc": "2.0", "method": "eth_getBalance",
                  "params": ["0x" + ("%040x" % (0x1000 + i)), "latest"], "id": i})
    if len(batch) == 200:
        send(batch); batch = []
if batch:
    send(batch)
PY
E=$(date +%s.%N)
A=$(rd)
python3 - "$B" "$A" "$N" "$S" "$E" <<'PY'
import sys
b, a, n = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
s, e = float(sys.argv[4]), float(sys.argv[5])
d = a - b
print("  lookups       : %d" % n)
print("  wall          : %.2f s  (%.0f us/lookup)" % (e - s, (e - s) * 1e6 / n))
print("  disk read     : %.1f MB" % (d / 1e6))
print("  BYTES/LOOKUP  : %.0f" % (d / n))
print("  BLOCKS/LOOKUP : %.2f" % (d / n / 4096))
PY
