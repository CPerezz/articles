#!/usr/bin/env bash
# After the E pairs: empty jochemnet's TblCodeCache (state-actor has none), promote, smoke, then the
# G pairs (ledger round 12, "the commit tail"). The cache is re-derivable from CodeDomain, so the
# state the benchmark reads doesn't change; only the per-boot seed scan of a 1.25 GB table goes.
# Usage: sudo clear-codecache-joc.sh      Waits for chain-B.done of the E chain; never beside a suite.
set -uo pipefail

STATE=/var/lib/schelk/er-joc.json
MNT=/schelk-er-joc
DATA=$MNT/snapshots/erigon/jochemnet/24402727
C=/bench/erigon/compact
L=/bench/erigon/logs
LOG=$L/clear-codecache-joc.log
DONE=$L/clear-codecache-joc.done
FAIL=$L/clear-codecache-joc.fail
BUSY=/bench/erigon/.busy
LOCK=/bench/erigon/.schelk.lock

rm -f "$DONE" "$FAIL"
cd /
exec >> "$LOG" 2>&1
fail() { echo "FAIL $1 ($(date -Is))"; echo "$1" > "$FAIL"; exit 1; }

until grep -aq "done  sa E2" $L/chain-B.log 2>/dev/null || [ -f $L/chain-B.fail ]; do sleep 60; done
[ -f $L/chain-B.fail ] && fail "E chain failed: $(cat $L/chain-B.fail)"
while [ -f "$BUSY" ] || pgrep -x benchmarkoor >/dev/null; do sleep 30; done
echo "clear-codecache-joc" > "$BUSY"
trap 'rm -f "$BUSY"' EXIT

echo "======== clear CodeCache: $(date -Is) ========"
flock "$LOCK" schelk restore -y --state-path "$STATE" || fail "restore"
podman run --rm --user 1000:1000 -e HOME=/tmp -v "$C":"$C" -v "$MNT":"$MNT" docker.io/library/golang:1.25-bookworm \
  "$C/bin/compactlatest" clear-code-cache --datadir "$DATA" || fail "clear"
time flock "$LOCK" schelk promote -y --state-path "$STATE" || fail "promote"
flock "$LOCK" schelk mount -y --state-path "$STATE"
flock "$LOCK" schelk recover -y --state-path "$STATE" || fail "unmount"

rm -f "$BUSY"; trap - EXIT
FILTER="$(cat /bench/erigon/tools/smoke.regex)" /bench/erigon/tools/run-suite.sh joc B S2
[ -f $L/suite-joc-S2.done ] || fail "smoke suite"
grep -aq "^0 validation failures" $L/suite-joc-S2.log || fail "smoke validation failures"
grep -aE "Test execution completed" $L/suite-joc-S2.log | tail -1 | grep -q "failed=0 .*passed=2" || fail "smoke not 2/2"
echo "rc=0" > "$DONE"
echo "G chain started $(date -Is)"
exec /bench/erigon/tools/chain-B.sh joc:G1 sa:G1 joc:G2 sa:G2
