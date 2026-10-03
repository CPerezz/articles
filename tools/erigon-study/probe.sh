#!/usr/bin/env bash
# Boot erigon once on an arm's promoted store, read what it reports, then throw the writes away
# (plan sections 3.6 and 4.4). Probes run on the scratch and end with a schelk restore, so the
# golden image never sees them.
#
# Usage: probe.sh joc|sa
set -uo pipefail

ARM="${1:?usage: probe.sh joc|sa}"
IMG=docker.io/ethpandaops/erigon:glamsterdam-devnet-7
WANT_IMG_ID=2e208c1ec0a502760be6402af36d57454c2085eac6f8d02efd1f93bd982e9fad
case "$ARM" in
  joc) DATA=/schelk-er-joc/snapshots/erigon/jochemnet/24402727; AMS=1769856769; PORT=18545 ;;
  sa)  DATA=/schelk-er-sa/erigon;                                 AMS=1;          PORT=18546 ;;
  *) echo "arm must be joc or sa"; exit 2 ;;
esac
STATE=/var/lib/schelk/er-$ARM.json
NAME=er-probe-$ARM
OUT=/bench/erigon/probe/$ARM
LOG=/bench/erigon/logs/probe-$ARM.log
DONE=/bench/erigon/logs/probe-$ARM.done
FAIL=/bench/erigon/logs/probe-$ARM.fail
LOCK=/bench/erigon/.schelk.lock

rm -f "$DONE" "$FAIL"; mkdir -p "$OUT"
cd /
fail() { echo "FAIL $1" | tee -a "$LOG"; echo "$1" > "$FAIL"; }
rpc() { curl -s -m 10 -H 'content-type: application/json' \
          -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}" "http://127.0.0.1:$PORT"; }

findmnt -n "/schelk-er-$ARM" >/dev/null || { fail "/schelk-er-$ARM not mounted"; exit 1; }
[ "$(sudo podman image inspect -f '{{.Id}}' "$IMG")" = "$WANT_IMG_ID" ] || { fail "erigon image id changed"; exit 1; }
[ -f /bench/erigon/probe/jwtsecret ] || openssl rand -hex 32 > /bench/erigon/probe/jwtsecret

{
  echo "======== probe $ARM: $(date -Is) ========"
  sudo podman rm -f "$NAME" >/dev/null 2>&1
  t0=$(date +%s)
  sudo podman run -d --name "$NAME" -p "127.0.0.1:$PORT:8545" \
    -v "$DATA":/data -v /bench/erigon/probe/jwtsecret:/tmp/jwtsecret:ro "$IMG" \
    --datadir=/data --nat=none --maxpeers=0 --txpool.disable --nodiscover --no-downloader \
    --torrent.download.rate=0 --torrent.upload.rate=0 \
    --http --http.addr=0.0.0.0 --http.port=8545 --http.vhosts='*' --http.api=web3,eth,net,engine,debug \
    --authrpc.addr=0.0.0.0 --authrpc.port=8551 --authrpc.vhosts='*' --authrpc.jwtsecret=/tmp/jwtsecret \
    --prune.mode=full --log.dir.disable --private.api.addr=0.0.0.0:9090 --externalcl \
    --fcu.timeout=0 --fcu.background.prune=false --sync.parallel-state-flushing=false \
    --exec.no-merge=true --exec.no-prune=true --exec.no-background-maintenance \
    --experimental.parallel-commitment --override.amsterdam=$AMS
  up=""
  for _ in $(seq 1 720); do
    sudo podman container exists "$NAME" && [ "$(sudo podman inspect -f '{{.State.Running}}' "$NAME")" = true ] || break
    r=$(rpc eth_chainId '[]'); case "$r" in *result*) up=$(( $(date +%s) - t0 )); break ;; esac
    sleep 5
  done
  echo "rpc up after: ${up:-never} s"
  if [ -n "$up" ]; then
    echo "eth_chainId     : $(rpc eth_chainId '[]')"
    echo "eth_blockNumber : $(rpc eth_blockNumber '[]')"
    echo "block 0         : $(rpc eth_getBlockByNumber '["0x0",false]' | python3 -c 'import sys,json;b=json.load(sys.stdin)["result"];print(b["hash"],b["stateRoot"],b["timestamp"])')"
    echo "latest          : $(rpc eth_getBlockByNumber '["latest",false]' | python3 -c 'import sys,json;b=json.load(sys.stdin)["result"];print(int(b["number"],16),b["hash"],b["stateRoot"])')"
    if [ "$ARM" = sa ]; then
      echo "balance 0x1000  : $(rpc eth_getBalance '["0x0000000000000000000000000000000000001000","latest"]')"
      echo "code eip8282    : $(rpc eth_getCode '["0x0000884d2AA32eAa155F59A2f24eFa73D9008282","latest"]' | head -c 120)"
    fi
  fi
  sudo podman logs "$NAME" > "$OUT/erigon.log" 2>&1
  echo "--- chain config / fork lines ---"
  grep -iE "amsterdam|osaka|chain config|chainid|chain id" "$OUT/erigon.log" | head -20
  echo "--- errors / rebuilds ---"
  grep -iE "error|fatal|panic|missing|rebuild|building|index" "$OUT/erigon.log" | head -30
  ts=$(date +%s); sudo podman stop -t 600 "$NAME" >/dev/null; echo "stop took $(( $(date +%s) - ts )) s"
  sudo podman logs "$NAME" > "$OUT/erigon.log" 2>&1
  tail -5 "$OUT/erigon.log"
  sudo podman rm "$NAME" >/dev/null
  # The probe's writes must not survive: restore the scratch from the golden image and remount.
  flock "$LOCK" sudo schelk restore -y --state-path "$STATE"
  echo "restore rc: $?"
  findmnt -n "/schelk-er-$ARM" >/dev/null || flock "$LOCK" sudo schelk mount -y --state-path "$STATE"
  findmnt -n "/schelk-er-$ARM"
  echo "finished: $(date -Is)"
} >> "$LOG" 2>&1

grep -q "rpc up after: never" "$LOG" && { fail "erigon never answered RPC (see $OUT/erigon.log)"; exit 1; }
echo "rc=0" > "$DONE"
