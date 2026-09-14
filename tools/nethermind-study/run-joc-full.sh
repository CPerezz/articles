#!/usr/bin/env bash
# Full 1463-test corrected arm: same store state as the 266-test subset (flat/Account and
# flat/StateNodes rebuilt with state-actor's per-CF options and PROMOTED, so the per-test
# rollback preserves them), pre-run stripped so it cannot re-cluster.
#
# Purpose: make the headline comparison full-suite vs full-suite against the 1461-test baseline,
# and give an 11-point gas slope so the result is directly comparable to the geth study's metric.
set -uo pipefail
LOG=/bench/logs/baseline-joc-full.log
rm -rf /bench/results/nm-joc-full
rm -f /bench/logs/joc-full.done
{
  echo "=== started : $(date -Is) ==="
  sudo env SCHELK_STATE=/var/lib/schelk/nm-joc.json \
    benchmarkoor run --config /bench/cfg/nm-joc-full.yaml
  echo "rc=$?"
  echo "=== finished: $(date -Is) ==="
} > "$LOG" 2>&1
grep -c "Test completed" "$LOG" > /bench/logs/joc-full.done 2>/dev/null
echo "done $(date -Is)" >> /bench/logs/joc-full.done
