#!/usr/bin/env bash
# Round 15, point 1: what an unknown block-hash lookup costs each store, cold and warm.
#
# Before Erigon logs "Handling new payload" it looks up the new block's hash, one it has never
# seen; BlockReader.HeaderByHash misses in MDBX and then checks every frozen headers segment.
# eth_getBlockByHash on a random hash takes the same path (rpchelper.GetBlockNumber ->
# BlockReader.HeaderNumber -> HeaderByHash). Each call is timed and its page-cache adds traced
# (filemap:mm_filemap_add_to_page_cache on the arm's dm device) between WALL markers:
#   cold:   page cache dropped before each call, a new random hash each time
#   warm:   the same hash again, nothing dropped
# Booted with the benchmark's flags on the restored scratch; the scratch is restored again after.
# Usage: sudo probe-hash.sh joc|sa      Never beside a suite (.busy).
set -uo pipefail

ARM="${1:?arm}"
IMG=docker.io/ethpandaops/erigon:glamsterdam-devnet-7
STATE=/var/lib/schelk/er-$ARM.json
MNT=/schelk-er-$ARM
DATA=$MNT/erigon
[ "$ARM" = joc ] && DATA=$MNT/snapshots/erigon/jochemnet/24402727   # as er-joc-B.yaml's ER_DATADIR
OUT=/bench/erigon/probe-hash/$ARM
LOG=/bench/erigon/logs/probe-hash-$ARM.log
DONE=/bench/erigon/logs/probe-hash-$ARM.done
FAIL=/bench/erigon/logs/probe-hash-$ARM.fail
BUSY=/bench/erigon/.busy
LOCK=/bench/erigon/.schelk.lock
PORT=18547
N=20
T=/sys/kernel/tracing
EV=$T/events/filemap/mm_filemap_add_to_page_cache

rm -f "$DONE" "$FAIL"
cd /
exec >> "$LOG" 2>&1
fail() { echo "FAIL $1 ($(date -Is))"; echo "$1" > "$FAIL"; exit 1; }
untrace() { echo 0 > $T/tracing_on; echo 0 > $EV/enable; echo 0 > $EV/filter; [ -n "${CAT_PID:-}" ] && kill "$CAT_PID" 2>/dev/null; CAT_PID=; }

while [ -f "$BUSY" ] || pgrep -x benchmarkoor >/dev/null; do sleep 60; done
echo "probe-hash-$ARM" > "$BUSY"
# Unmount on every exit, failures included, so the next arm's device is the only dm device.
trap 'untrace; podman rm -f er-hash-probe >/dev/null 2>&1; flock "$LOCK" schelk recover -y --state-path "$STATE" >/dev/null 2>&1; rm -f "$BUSY"' EXIT
echo "======== probe-hash $ARM: $(date -Is) ========"

flock "$LOCK" schelk restore -y --state-path "$STATE" || fail "restore"
findmnt -n "$MNT" >/dev/null || fail "not mounted"
maj=$(awk '$2 == "device-mapper" {print $1}' /proc/devices)
others=$(ls /dev/mapper | grep -v '^control$' | grep -v "^er_${ARM}_era$")
[ -z "$others" ] || fail "other dm devices present: $others"
rm -rf "$OUT"; mkdir -p "$OUT"
find "$MNT" -xdev -type f -printf '%i %s %p\n' > "$OUT/files.txt"

podman rm -f er-hash-probe >/dev/null 2>&1
podman run -d --name er-hash-probe -p "127.0.0.1:$PORT:8545" -v "$DATA":/data \
  -v /bench/erigon/probe/jwtsecret:/tmp/jwtsecret:ro "$IMG" \
  --datadir=/data --nat=none --maxpeers=0 --txpool.disable --nodiscover --no-downloader \
  --http --http.addr=0.0.0.0 --http.port=8545 --http.vhosts='*' --http.api=eth,net,debug \
  --authrpc.jwtsecret=/tmp/jwtsecret --prune.mode=full --log.dir.disable --externalcl \
  --exec.no-merge=true --exec.no-prune=true --exec.no-background-maintenance \
  --experimental.parallel-commitment --override.amsterdam=1 >/dev/null || fail "boot"
up=
for _ in $(seq 1 720); do
  curl -s -m 5 -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' \
    "http://127.0.0.1:$PORT" | grep -q result && { up=1; break; }
  podman container exists er-hash-probe || break
  sleep 5
done
[ -n "$up" ] || { podman logs er-hash-probe 2>&1 | tail -30; fail "rpc"; }
sleep 30   # let boot-time work settle, as benchmarkoor's first block comes after its own waits

call() { # $1 label, $2 hash: one timed eth_getBlockByHash between WALL markers
  echo "WALL $1 start $(date +%s.%N)" > $T/trace_marker
  t=$(curl -s -o "$OUT/last.json" -w '%{time_total}' -m 30 -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getBlockByHash\",\"params\":[\"$2\",false]}" "http://127.0.0.1:$PORT")
  echo "WALL $1 end $(date +%s.%N)" > $T/trace_marker
  grep -q '"result":null' "$OUT/last.json" || fail "unexpected answer for $2: $(head -c 200 "$OUT/last.json")"
  echo -e "$1\t$2\t$t" >> "$OUT/calls.tsv"
}

echo 0 > $T/tracing_on; echo > $T/trace
echo 32768 > $T/buffer_size_kb
echo "s_dev >= $((maj << 20)) && s_dev < $(((maj + 1) << 20))" > $EV/filter || fail "event filter"
echo 1 > $EV/enable
cat $T/trace_pipe > "$OUT/trace.txt" &
CAT_PID=$!
echo 1 > $T/tracing_on
for i in $(seq 1 $N); do
  h=0x$(openssl rand -hex 32)
  sync; echo 3 > /proc/sys/vm/drop_caches; sleep 1
  call "cold-$i" "$h"
  for j in 1 2; do call "warm-$i-$j" "$h"; done
done
sleep 2
untrace
podman logs er-hash-probe > "$OUT/erigon.log" 2>&1
podman stop -t 120 er-hash-probe >/dev/null; podman rm er-hash-probe >/dev/null
flock "$LOCK" schelk restore -y --state-path "$STATE" || fail "restore after"
flock "$LOCK" schelk recover -y --state-path "$STATE" || fail "recover"
echo "calls: $(wc -l < "$OUT/calls.tsv"), events: $(grep -c mm_filemap_add_to_page_cache "$OUT/trace.txt")"
echo "rc=0" > "$DONE"
