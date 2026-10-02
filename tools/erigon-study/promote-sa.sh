#!/usr/bin/env bash
# state-actor arm after generation (plan section 4.3-4.4): disk gate, promote, remount, probe.
set -uo pipefail

STATE=/var/lib/schelk/er-sa.json
LOCK=/bench/erigon/.schelk.lock
LOG=/bench/erigon/logs/promote-sa.log
DONE=/bench/erigon/logs/promote-sa.done
FAIL=/bench/erigon/logs/promote-sa.fail

rm -f "$DONE" "$FAIL"
fail() { echo "FAIL $1" | tee -a "$LOG"; echo "$1" > "$FAIL"; exit 1; }

until [ -f /bench/erigon/logs/gen-sa.done ] || [ -f /bench/erigon/logs/gen-sa.fail ]; do sleep 60; done
[ -f /bench/erigon/logs/gen-sa.done ] || fail "G4: generation failed: $(cat /bench/erigon/logs/gen-sa.fail)"

free_kb=$(df --output=avail -k / | tail -1)
virgin_kb=$(( $(stat -c %s /bench/schelk-vols/er-sa-virgin.img) / 1024 ))
alloc_kb=$(du -k /bench/schelk-vols/er-sa-virgin.img | cut -f1)
need_kb=$(( virgin_kb - alloc_kb + 500 * 1024 * 1024 ))
[ "$free_kb" -ge "$need_kb" ] || fail "disk gate: free ${free_kb} KiB < need ${need_kb} KiB"

{
  echo "======== promote sa: $(date -Is) ========"
  time flock "$LOCK" sudo schelk promote -y --state-path "$STATE"
  flock "$LOCK" sudo schelk mount -y --state-path "$STATE"
  findmnt -n /schelk-er-sa
  sudo schelk status --state-path "$STATE"
  echo "virgin allocated: $(du -sh /bench/schelk-vols/er-sa-virgin.img | cut -f1)"
} >> "$LOG" 2>&1
[ -f /schelk-er-sa/erigon/state-actor-manifest.json ] || fail "promote/remount: store missing"

/bench/erigon/tools/probe.sh sa
echo "rc=0" > "$DONE"
