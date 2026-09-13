#!/usr/bin/env bash
# Does a test still pass with the pre-run removed? The pre-run's state effects are already
# baked into the promoted volume, so it should - but 13 h of suite is too expensive to find
# out the hard way.
set -uo pipefail
L=/bench/logs/nm-joc-smoke.log
rm -f /bench/logs/nm-joc-smoke.done /bench/results/nm-joc-smoke -r 2>/dev/null
sudo env SCHELK_STATE=/var/lib/schelk/nm-joc.json \
  benchmarkoor run --config /bench/cfg/nm-joc-smoke.yaml > "$L" 2>&1
echo "rc=$?" > /bench/logs/nm-joc-smoke.done
