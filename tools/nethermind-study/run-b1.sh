#!/usr/bin/env bash
# B1: does the cross-step block-cache carry-over explain the control-category gap?
#
# The harness drops the OS page cache between setup and the measured step but cannot touch the
# client's own RocksDB block cache, because Nethermind is not restarted inside a test. Shrinking
# that cache to near nothing removes the carry-over without needing a harness change.
#
# Both arms must be re-run: the flag applies to both, so only a matched pair is comparable. They
# run SEQUENTIALLY - concurrent arms pollute each other's I/O, which invalidated two earlier rounds.
set -uo pipefail
LOG=/bench/logs/b1.log
rm -f /bench/logs/b1.done
{
  echo "=== started : $(date -Is) ==="
  for arm in joc sa; do
    if [ "$arm" = joc ]; then
      CFG=/bench/cfg/nm-joc-b1.yaml; STATE=/var/lib/schelk/nm-joc.json
    else
      CFG=/bench/cfg/nm-sa-b1.yaml;  STATE=/var/lib/schelk/nm-sa.json
    fi
    echo "--------- arm $arm : $(date -Is) ---------"
    rm -rf /bench/results/nm-$arm-b1
    sudo env SCHELK_STATE=$STATE benchmarkoor run --config $CFG
    echo "arm $arm rc=$?"
  done
  echo "=== finished: $(date -Is) ==="
} > "$LOG" 2>&1
grep -c "Test completed" "$LOG" > /bench/logs/b1.done 2>/dev/null
echo "done $(date -Is)" >> /bench/logs/b1.done
