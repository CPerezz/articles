#!/usr/bin/env bash
# The baseline proper (plan section 5): B1 and B2 on both arms, strictly serial, stopping at the
# first failed suite. Each pair alternates arms so neither pair's two runs sit hours apart.
#
# Usage: chain-B.sh [suites...]   default: joc:B1 sa:B1 joc:B2 sa:B2
set -uo pipefail

LOG=/bench/erigon/logs/chain-B.log
DONE=/bench/erigon/logs/chain-B.done
FAIL=/bench/erigon/logs/chain-B.fail
rm -f "$DONE" "$FAIL"

steps=("$@"); [ ${#steps[@]} -gt 0 ] || steps=(joc:B1 sa:B1 joc:B2 sa:B2)
for s in "${steps[@]}"; do
  arm=${s%%:*}; tag=${s#*:}
  echo "$(date -Is) start $arm $tag" >> "$LOG"
  /bench/erigon/tools/run-suite.sh "$arm" B "$tag"
  if [ -f "/bench/erigon/logs/suite-$arm-$tag.done" ]; then
    echo "$(date -Is) done  $arm $tag: $(grep -a 'Test execution completed' /bench/erigon/logs/suite-$arm-$tag.log | tail -1 | cut -c1-200)" >> "$LOG"
  else
    echo "$(date -Is) FAIL  $arm $tag: $(cat /bench/erigon/logs/suite-$arm-$tag.fail 2>/dev/null)" >> "$LOG"
    echo "$arm $tag" > "$FAIL"; exit 1
  fi
done
echo "rc=0" > "$DONE"
