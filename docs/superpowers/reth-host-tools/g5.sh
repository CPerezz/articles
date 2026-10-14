#!/bin/bash
# G5: replay the jochemnet pre-run once on the promoted snapshot, promote it into the virgin, run a smoke filter.
cd /root/bench/reth
echo "start $(date -Is)"; df -h /schelk-joc | tail -1
env SCHELK_STATE=/var/lib/schelk/reth-joc.json timeout 21600 benchmarkoor run --config cfg/J-prerun.yaml
echo "G5-EXIT=$? $(date -Is)"; df -h /schelk-joc | tail -1
