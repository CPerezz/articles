#!/usr/bin/env bash
# Step 1 (ledger round 8): give jochemnet the tiering a running node would have, then promote it.
#
# The benchmark runs erigon with --exec.no-background-maintenance and --exec.no-prune, so nothing
# written after jochemnet's last frozen step (block 24,349,407), pre-run included, ever left MDBX.
# `erigon snapshots retire` (offline, needs the datadir lock) builds every finished step into files,
# merges them and prunes MDBX; `mdbx_copy -c` then hands the freed pages back. No value changes:
# the head and its state root must read the same before and after, and the smoke pair must pass
# (newPayload re-checks the state root) before the image is trusted.
#
# Usage: sudo fold-joc.sh        Never beside a suite (.busy). One-way: the promote replaces the
# untreated jochemnet image.
set -uo pipefail

IMG=docker.io/ethpandaops/erigon:glamsterdam-devnet-7
WANT_IMG_ID=2e208c1ec0a502760be6402af36d57454c2085eac6f8d02efd1f93bd982e9fad
MDBX_GO=v0.43.0   # erigon 5f62f4ed's go.mod pins mdbx-go v0.43.0; its tools match the db format
STATE=/var/lib/schelk/er-joc.json
DATA=/schelk-er-joc/snapshots/erigon/jochemnet/24402727
HEAD=24410463
OUT=/bench/erigon/fold
LOG=/bench/erigon/logs/fold-joc.log
DONE=/bench/erigon/logs/fold-joc.done
FAIL=/bench/erigon/logs/fold-joc.fail
BUSY=/bench/erigon/.busy
PORT=18545

rm -f "$DONE" "$FAIL"; mkdir -p "$OUT"
cd /
exec >> "$LOG" 2>&1
fail() { echo "FAIL $1"; echo "$1" > "$FAIL"; exit 1; }
rpc() { curl -s -m 10 -H 'content-type: application/json' \
          -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}" "http://127.0.0.1:$PORT"; }

while [ -f "$BUSY" ] || pgrep -x benchmarkoor >/dev/null; do sleep 60; done
echo "fold-joc" > "$BUSY"
trap 'podman rm -f er-fold >/dev/null 2>&1; rm -f "$BUSY"' EXIT
[ "$(podman image inspect -f '{{.Id}}' "$IMG")" = "$WANT_IMG_ID" ] || fail "erigon image id changed"

inventory() {
  echo "--- inventory: $1 ---"
  echo "mdbx.dat bytes: $(stat -c %s "$DATA/chaindata/mdbx.dat")"
  du -sb "$DATA"/snapshots/* 2>/dev/null
  ls -l "$DATA/snapshots/domain" > "$OUT/domain-$1.txt"
  echo "domain files: $(wc -l < "$OUT/domain-$1.txt")"
  echo "fs used/avail: $(df -B1 --output=used,avail /schelk-er-joc | tail -1)"
}

# Boot with the benchmark's flags, read the head, stop. Run before and after: they must agree.
headcheck() {
  podman rm -f er-fold >/dev/null 2>&1
  podman run -d --name er-fold -p "127.0.0.1:$PORT:8545" -v "$DATA":/data \
    -v /bench/erigon/probe/jwtsecret:/tmp/jwtsecret:ro "$IMG" \
    --datadir=/data --nat=none --maxpeers=0 --txpool.disable --nodiscover --no-downloader \
    --http --http.addr=0.0.0.0 --http.port=8545 --http.vhosts='*' --http.api=eth,net \
    --authrpc.jwtsecret=/tmp/jwtsecret --prune.mode=full --log.dir.disable --externalcl \
    --exec.no-merge=true --exec.no-prune=true --exec.no-background-maintenance \
    --experimental.parallel-commitment --override.amsterdam=1769856769 >/dev/null
  local latest=""
  for _ in $(seq 1 720); do
    latest=$(rpc eth_getBlockByNumber '["latest",false]' | python3 -c \
      'import sys,json;b=json.load(sys.stdin)["result"];print(int(b["number"],16),b["hash"],b["stateRoot"])' 2>/dev/null) && break
    sleep 5
  done
  podman logs er-fold > "$OUT/erigon-$1.log" 2>&1
  podman stop -t 600 er-fold >/dev/null; podman rm er-fold >/dev/null
  echo "$latest" > "$OUT/head-$1.txt"
  echo "head $1: ${latest:-none}"
}

echo "======== fold jochemnet: $(date -Is) ========"
flock /bench/erigon/.schelk.lock schelk restore -y --state-path "$STATE" || fail "restore"
findmnt -n /schelk-er-joc || fail "not mounted after restore"
inventory before
headcheck before

echo "======== retire: $(date -Is) ========"
time podman run --rm --name er-retire --user 1000:1000 -v "$DATA":/data --entrypoint erigon "$IMG" \
  snapshots retire --datadir=/data
rc=$?; echo "retire rc: $rc"; [ "$rc" = 0 ] || fail "retire failed"
inventory retired

echo "======== compact: $(date -Is) ========"
# mdbx_copy built from the same mdbx-go release erigon links, in a throwaway Go container.
time podman run --rm --user 0 -v "$DATA/chaindata":/db docker.io/library/golang:1.25-bookworm bash -c "
  set -e
  git clone -q --depth 1 --branch $MDBX_GO https://github.com/erigontech/mdbx-go /src
  cd /src && MDBX_BUILD_TIMESTAMP=unknown make tools >/dev/null
  ./libmdbx/mdbx_copy -c -u /db /db/mdbx.dat.tmp
  mv /db/mdbx.dat.tmp /db/mdbx.dat
  chown 1000:1000 /db/mdbx.dat
  ./libmdbx/mdbx_stat -e /db | head -40"
rc=$?; echo "compact rc: $rc"; [ "$rc" = 0 ] || fail "compact failed"
inventory compacted
headcheck after

b=$(cat "$OUT/head-before.txt"); a=$(cat "$OUT/head-after.txt")
[ -n "$b" ] && [ "$b" = "$a" ] && [ "${b%% *}" = "$HEAD" ] || fail "head moved or unreadable: before '$b' after '$a'"

echo "======== promote: $(date -Is) ========"
time flock /bench/erigon/.schelk.lock schelk promote -y --state-path "$STATE"
rc=$?; echo "promote rc: $rc"; [ "$rc" = 0 ] || fail "promote failed"
flock /bench/erigon/.schelk.lock schelk mount -y --state-path "$STATE"
findmnt -n /schelk-er-joc || fail "not mounted after promote"

# The smoke pair re-executes two blocks; newPayload rejects a block whose state root the folded
# store can't reproduce.
rm -f "$BUSY"; trap - EXIT
FILTER="$(cat /bench/erigon/tools/smoke.regex)" /bench/erigon/tools/run-suite.sh joc B F0
[ -f /bench/erigon/logs/suite-joc-F0.done ] || fail "smoke suite failed"
grep -aq "^0 validation failures" /bench/erigon/logs/suite-joc-F0.log || fail "smoke validation failures"
grep -aE "Test execution completed" /bench/erigon/logs/suite-joc-F0.log | tail -1 | grep -q "failed=0 .*passed=2" \
  || fail "smoke did not pass 2/2"
echo "finished: $(date -Is)"
echo "rc=0" > "$DONE"
