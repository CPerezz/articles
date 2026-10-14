#!/bin/bash
cd /root/bench/reth || exit 1
export SCHELK_STATE=/var/lib/schelk/reth-sa.json
[ "$(dmsetup ls | grep -c _era)" = 0 ] || { echo ABORT mapped; exit 1; }
schelk -y restore > /dev/null 2>&1 || { echo ABORT restore; exit 1; }
echo "== build $(date)"
timeout 7200 benchmarkoor build --config cfg/fill-reth-trial.yaml --force > logs/fill-reth-trial.log 2>&1
echo "build exit $? $(date)"
schelk -y recover > /dev/null 2>&1 || echo WARN recover
find /data/fixtures/refill-trial -name "*.json" | head; cat /data/fixtures/refill-trial/reth/.benchmarkoor-fill.json 2>/dev/null
echo "== done mapped=$(dmsetup ls | grep -c _era)"
