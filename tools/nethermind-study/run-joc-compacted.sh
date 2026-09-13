#!/usr/bin/env bash
# The intervention arm: same jochemnet store, same fixtures, same client, same flags -
# but with the clustering removed (flat/Account and code/ fully compacted) and the pre-run
# stripped so it cannot re-cluster. Detached: this box drops SSH sessions under sustained
# benchmark I/O, and every previous detached run survived it.
set -uo pipefail
LOG=/bench/logs/baseline-joc-compacted.log
rm -rf /bench/results/nm-joc-compacted
rm -f /bench/logs/joc-compacted.done
{
  echo "=== started : $(date -Is) ==="
  sudo env SCHELK_STATE=/var/lib/schelk/nm-joc.json \
    benchmarkoor run --config /bench/cfg/nm-joc-compacted.yaml
  echo "rc=$?"
  echo "=== finished: $(date -Is) ==="
} > "$LOG" 2>&1
grep -c "Test completed" "$LOG" > /bench/logs/joc-compacted.done 2>/dev/null
echo "done $(date -Is)" >> /bench/logs/joc-compacted.done
