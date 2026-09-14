#!/usr/bin/env bash
# Phase 2: stratified subset on the corrected store.
#
# Store state: flat/Account and flat/StateNodes force-rewritten with state-actor's exact
# per-CF options (ribbon filter restored, kNoCompression/kLZ4 correct, restart 4/8,
# kDataBlockBinaryAndHash, format 5), both now single-level. code/ already matched Nethermind's
# real settings. flat/Storage and flat/StorageNodes deliberately untouched - Storage is the
# control that should not move, StorageNodes does not fit in the free space.
#
# Subset: gas 160M and 240M = 266 tests, covering all six test families and every
# opcode x account_mode cell at two gas points, so ratios and their gas-slope are both checkable.
set -uo pipefail
LOG=/bench/logs/baseline-joc-clean.log
rm -rf /bench/results/nm-joc-clean
rm -f /bench/logs/joc-clean.done
{
  echo "=== started : $(date -Is) ==="
  sudo env SCHELK_STATE=/var/lib/schelk/nm-joc.json \
    benchmarkoor run --config /bench/cfg/nm-joc-clean.yaml
  echo "rc=$?"
  echo "=== finished: $(date -Is) ==="
} > "$LOG" 2>&1
grep -c "Test completed" "$LOG" > /bench/logs/joc-clean.done 2>/dev/null
echo "done $(date -Is)" >> /bench/logs/joc-clean.done
