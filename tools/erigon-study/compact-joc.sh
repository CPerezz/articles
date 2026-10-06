#!/usr/bin/env bash
# Rebuild jochemnet as a node whose whole state sits in its bottom file (ledger round 12), check
# it answers exactly as before, promote it, then smoke and trace it.
#
# The benchmark's cold reads must hit the worst case: the key's only copy in the oldest file, not
# in MDBX. state-actor's store is built that way; jochemnet keeps the pre-run's accounts in MDBX,
# because everything after block 24,349,407 is one unfinished step erigon never freezes.
# compactlatest writes every key's latest value into one [0,1) file set per state domain with
# step size = head's last txNum + 1, so the file ends exactly at the head block.
#
# One-way: the promote replaces the untreated image (no backup; its baselines are collected).
# Usage: sudo compact-joc.sh      Never beside a suite (.busy).
set -uo pipefail

IMG=docker.io/ethpandaops/erigon:glamsterdam-devnet-7
GO_IMG=docker.io/library/golang:1.25-bookworm
STATE=/var/lib/schelk/er-joc.json
MNT=/schelk-er-joc
DATA=$MNT/snapshots/erigon/jochemnet/24402727
C=/bench/erigon/compact
LOG=/bench/erigon/logs/compact-joc.log
DONE=/bench/erigon/logs/compact-joc.done
FAIL=/bench/erigon/logs/compact-joc.fail
BUSY=/bench/erigon/.busy
LOCK=/bench/erigon/.schelk.lock
PORT=18545

rm -f "$DONE" "$FAIL"
cd /
# uid 1000 like erigon: a root-owned LOCK or temp dir in the datadir would stop the node booting.
tool() { podman run --rm --user 1000:1000 -e HOME=/tmp -v "$C":"$C" -v "$MNT":"$MNT" "$GO_IMG" "$C/bin/$@"; }
fail() { echo "FAIL $1 ($(date -Is))"; echo "$1" > "$FAIL"; exit 1; }
step() { echo; echo "======== $1: $(date -Is) ========"; }
tool() { podman run --rm --user 0 -v "$C":"$C" -v "$MNT":"$MNT" "$GO_IMG" "$C/bin/$@"; }

while [ -f "$BUSY" ] || pgrep -x benchmarkoor >/dev/null; do sleep 60; done
echo "compact-joc" > "$BUSY"
trap 'podman rm -f er-compact-probe >/dev/null 2>&1; rm -f "$BUSY"' EXIT

boot() { # boot erigon with the benchmark's flags on the current scratch and wait for RPC
  podman rm -f er-compact-probe >/dev/null 2>&1
  podman run -d --name er-compact-probe -p "127.0.0.1:$PORT:8545" -v "$DATA":/data \
    -v /bench/erigon/probe/jwtsecret:/tmp/jwtsecret:ro "$IMG" \
    --datadir=/data --nat=none --maxpeers=0 --txpool.disable --nodiscover --no-downloader \
    --http --http.addr=0.0.0.0 --http.port=8545 --http.vhosts='*' --http.api=eth,net,debug \
    --authrpc.jwtsecret=/tmp/jwtsecret --prune.mode=full --log.dir.disable --externalcl \
    --exec.no-merge=true --exec.no-prune=true --exec.no-background-maintenance \
    --experimental.parallel-commitment --override.amsterdam=1769856769 >/dev/null
  for _ in $(seq 1 720); do
    curl -s -m 5 -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' \
      "http://127.0.0.1:$PORT" | grep -q result && return 0
    podman container exists er-compact-probe || break
    sleep 5
  done
  podman logs er-compact-probe 2>&1 | tail -30
  return 1
}
halt() { podman logs er-compact-probe > "$C/erigon-$1.log" 2>&1; podman stop -t 600 er-compact-probe >/dev/null; podman rm er-compact-probe >/dev/null; }

step "restore untreated scratch"
flock "$LOCK" schelk restore -y --state-path "$STATE" || fail "restore"
findmnt -n "$MNT" || fail "not mounted"
[ "$(df --output=avail -BG / | tail -1 | tr -dc 0-9)" -ge 600 ] || fail "rootfs needs 600 GB free"
rm -rf "$C/staging" "$C/tmp" && mkdir -p "$C/staging" "$C/tmp"

step "compact (read-only on the untreated store)"
time tool compactlatest compact --datadir "$DATA" --dst "$C/staging" --tmp "$C/tmp" --workers 32 \
  --samples "$C/samples.txt" > "$C/compact-report.json" || fail "compact"
cat "$C/compact-report.json"
H=$(python3 -c "import json;print(json.load(open('$C/compact-report.json'))['head']['state_block'])")
N=$(python3 -c "import json;print(json.load(open('$C/compact-report.json'))['new_step_size'])")
echo "head $H new step size $N"
ls -la "$C/staging"
rm -rf "$C/tmp"

step "answers on the untreated layout"
boot || fail "untreated boot"
python3 "$C/rpc-sample.py" "$PORT" "$C/samples.txt" "$C/answers-old.jsonl" || fail "old answers"
halt old
flock "$LOCK" schelk restore -y --state-path "$STATE" || fail "restore after old probe"

step "reset MDBX state, execution progress := $H"
tool compactlatest reset --datadir "$DATA" --head "$H" || fail "reset"

step "swap state files, step size := $N"
for d in domain history idx accessor; do
  find "$DATA/snapshots/$d" -maxdepth 1 -type f -name 'v*' -print -delete | wc -l | sed "s/^/deleted from $d: /"
done
cp -v "$C/staging"/* "$DATA/snapshots/domain/" || fail "copy staged files"
printf 'step_size = %s\nsteps_in_frozen_file = 64\n' "$N" > "$DATA/snapshots/erigondb.toml"
rm -f "$DATA/snapshots/erigondb.toml.torrent"
cat "$DATA/snapshots/erigondb.toml"

step "compact mdbx.dat"
ls -la "$DATA/chaindata"
time tool mdbx_copy -c -u "$DATA/chaindata" "$DATA/chaindata/mdbx.dat.tmp" || fail "mdbx_copy"
mv "$DATA/chaindata/mdbx.dat.tmp" "$DATA/chaindata/mdbx.dat"
ls -la "$DATA/chaindata"
tool mdbx_stat -e "$DATA/chaindata" | head -30
chown -R 1000:1000 "$DATA"

step "inspect the new layout"
tool compactlatest inspect --datadir "$DATA" > "$C/inspect-new.json" || fail "inspect"
cat "$C/inspect-new.json"
python3 - "$C/inspect-new.json" "$H" "$N" <<'EOF' || fail "new layout is not at the head"
import json, sys
h, head, n = json.load(open(sys.argv[1])), int(sys.argv[2]), int(sys.argv[3])
assert h["step_size"] == n and h["exec_progress"] == head and h["state_block"] == head, h
assert h["state_txnum"] == n - 1 == h["max_txnum_of_state_block"], h
assert set(h["files_end_txnum"].values()) == {n}, h
print("new layout ok")
EOF

step "answers on the new layout"
boot || fail "new boot"
python3 "$C/rpc-sample.py" "$PORT" "$C/samples.txt" "$C/answers-new.jsonl" || fail "new answers"
halt new
cmp "$C/answers-old.jsonl" "$C/answers-new.jsonl" || fail "answers differ"
echo "answers identical: $(wc -l < "$C/answers-new.jsonl") lines"

step "promote"
time flock "$LOCK" schelk promote -y --state-path "$STATE" || fail "promote"
flock "$LOCK" schelk mount -y --state-path "$STATE"; findmnt -n "$MNT" || fail "not mounted after promote"
flock "$LOCK" schelk recover -y --state-path "$STATE" || fail "unmount after promote"

step "smoke and trace"
rm -f "$BUSY"; trap - EXIT
FILTER="$(cat /bench/erigon/tools/smoke.regex)" /bench/erigon/tools/run-suite.sh joc B F1
[ -f /bench/erigon/logs/suite-joc-F1.done ] || fail "smoke suite"
grep -aq "^0 validation failures" /bench/erigon/logs/suite-joc-F1.log || fail "smoke validation failures"
grep -aE "Test execution completed" /bench/erigon/logs/suite-joc-F1.log | tail -1 | grep -q "failed=0 .*passed=2" || fail "smoke not 2/2"
/bench/erigon/tools/trace-tests.sh joc T1
[ -f /bench/erigon/logs/trace-joc-T1.done ] || fail "trace"
echo "finished: $(date -Is)"
echo "rc=0" > "$DONE"
