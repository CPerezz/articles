#!/usr/bin/env bash
# Drive both Nethermind baseline suites, sequentially and unattended.
#
# Sequential by necessity: both arms live on the same NVMe array, so running them
# concurrently would have each arm's I/O pollute the other's timings — the exact mistake
# that invalidated rounds 13/17/18 of the geth study.
#
# Each arm needs its own schelk instance mounted first: benchmarkoor unmounts on teardown,
# and SCHELK_STATE selects which instance it operates on.
set -uo pipefail

LOGDIR=/bench/logs
mkdir -p "$LOGDIR" /bench/results
rm -f "$LOGDIR/baselines.done"

run_arm() {
  local name="$1" state="$2" mount="$3" cfg="$4"
  local log="$LOGDIR/baseline-$name.log"

  echo "======== $name ========" | tee -a "$LOGDIR/baselines.log"
  echo "started : $(date -Is)" | tee -a "$LOGDIR/baselines.log"

  # Remount: a previous arm's teardown leaves this unmounted.
  if ! findmnt -n "$mount" >/dev/null 2>&1; then
    sudo schelk mount -y --state-path "$state" >>"$LOGDIR/baselines.log" 2>&1
  fi
  findmnt -n "$mount" >/dev/null 2>&1 || {
    echo "FATAL: $mount not mounted" | tee -a "$LOGDIR/baselines.log"; return 2; }

  sudo env SCHELK_STATE="$state" benchmarkoor run --config "$cfg" > "$log" 2>&1
  local rc=$?
  echo "$name rc=$rc" | tee -a "$LOGDIR/baselines.log"
  echo "finished: $(date -Is)" | tee -a "$LOGDIR/baselines.log"
  grep -aE "Test execution completed" "$log" | tail -1 | tee -a "$LOGDIR/baselines.log"
  echo "rc=$rc" > "$LOGDIR/baseline-$name.done"
  return $rc
}

run_arm state-actor /var/lib/schelk/nm-sa.json  /schelk-sa  /bench/cfg/nm-state-actor.yaml
run_arm jochemnet   /var/lib/schelk/nm-joc.json /schelk-joc /bench/cfg/nm-jochemnet.yaml

echo "ALL DONE $(date -Is)" | tee -a "$LOGDIR/baselines.log"
echo "rc=0" > "$LOGDIR/baselines.done"
