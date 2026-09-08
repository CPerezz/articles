#!/usr/bin/env bash
# Round-1 probe: identical logical read workload against one datadir, measured
# with geth's own pathdb meters so the result does not depend on the storage
# medium (jochemnet sits on NVMe, the surviving state-actor copy on HDD).
#
# usage: probe_reads.sh <datadir> <label>
set -o pipefail
D="$1"; LABEL="$2"
IMG=ghcr.io/jochem-brouwer/go-ethereum:glamsterdam-devnet-7-blobpool-fix
OUT=/root/bench/probe-${LABEL}.json

podman rm -f probegeth >/dev/null 2>&1
podman run -d --name probegeth --network host -v "$D":/data:O "$IMG" \
  --datadir /data --http --http.addr 127.0.0.1 --http.port 8545 \
  --http.api eth,debug,web3,net --metrics --metrics.addr 127.0.0.1 \
  --metrics.port 6060 --maxpeers 0 --nodiscover --nat=none \
  --override.amsterdam=1769856769 >/dev/null

for i in $(seq 1 120); do
  curl -s -m 2 -X POST -H 'Content-Type: application/json' \
    --data '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' \
    http://127.0.0.1:8545 | grep -q result && break
  sleep 5
done

# cold start for the OS page cache, exactly as the harness does between tests
sync; echo 3 > /proc/sys/vm/drop_caches; sleep 2

python3 /root/bench/probe_reads.py "$LABEL" > "$OUT" 2>/root/bench/probe-${LABEL}.err
RC=$?
podman logs probegeth 2>&1 | grep -iE "snapshot|journal|Initialized path" | head -6 \
  >> /root/bench/probe-${LABEL}.err
podman rm -f probegeth >/dev/null 2>&1
echo "probe rc=$RC -> $OUT"
