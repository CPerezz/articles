#!/usr/bin/env bash
# Run one benchmarkoor suite against one arm (plan section 5).
#
# Usage: run-suite.sh joc|sa A|B <tag>     e.g. run-suite.sh joc B B1
#
# Suites never overlap: /bench/erigon/.busy holds the running suite's name, and the script refuses
# to start if another benchmarkoor is running on the box. Never stop a suite with SIGKILL; it wedges
# the dm-era device (Nethermind ledger, round 31).
set -uo pipefail

ARM="${1:?arm}"; SUITE="${2:?suite A|B}"; TAG="${3:?tag}"
IMG=docker.io/ethpandaops/erigon:glamsterdam-devnet-7
WANT_IMG_ID=2e208c1ec0a502760be6402af36d57454c2085eac6f8d02efd1f93bd982e9fad
STATE=/var/lib/schelk/er-$ARM.json
SRC=/bench/erigon/tools/er-$ARM-$SUITE.yaml
DAY=$(date -u +%Y%m%d)
CFG=/bench/cfg/er-$ARM-$TAG.yaml
LOG=/bench/erigon/logs/suite-$ARM-$TAG.log
DONE=/bench/erigon/logs/suite-$ARM-$TAG.done
FAIL=/bench/erigon/logs/suite-$ARM-$TAG.fail
BUSY=/bench/erigon/.busy

rm -f "$DONE" "$FAIL"
fail() { echo "FAIL $1" | tee -a "$LOG"; echo "$1" > "$FAIL"; exit 1; }

[ -f "$BUSY" ] && fail "busy: $(cat "$BUSY")"
pgrep -x benchmarkoor >/dev/null && fail "another benchmarkoor is running"
[ "$(sudo podman image inspect -f '{{.Id}}' "$IMG")" = "$WANT_IMG_ID" ] || fail "erigon image id changed"

sed -e "s|er-$ARM-$SUITE-RUNDATE|er-$ARM-$TAG-$DAY|" -e "s|id: er-$ARM-$SUITE\$|id: er-$ARM-$TAG|" \
    -e "s|name: er-$ARM-$SUITE-|name: er-$ARM-$TAG-|" "$SRC" > "$CFG"
echo "$ARM-$TAG" > "$BUSY"
{
  echo "======== suite $ARM $TAG ($SUITE): $(date -Is) ========"
  echo "config  : $CFG ($(sha256sum "$CFG" | cut -d' ' -f1))"
  echo "results : $(grep results_dir "$CFG" | awk '{print $2}')"
  sudo env SCHELK_STATE="$STATE" benchmarkoor run --config "$CFG"
  echo "benchmarkoor rc=$?"
  echo "finished: $(date -Is)"
} >> "$LOG" 2>&1
rm -f "$BUSY"

rc=$(grep -ao "benchmarkoor rc=[0-9]*" "$LOG" | tail -1 | cut -d= -f2)
echo "$(grep -ac 'Response validation failed' "$LOG") validation failures" >> "$LOG"
grep -aE "Test execution completed" "$LOG" | tail -1 >> "$LOG"
[ "$rc" = "0" ] || fail "benchmarkoor rc=$rc"
echo "rc=0" > "$DONE"
