#!/usr/bin/env bash
# Start the E pairs (both arms, direct-I/O loops) once compact-joc.sh succeeds; nothing if it fails.
L=/bench/erigon/logs
until ls $L/compact-joc.done $L/compact-joc.fail >/dev/null 2>&1; do sleep 60; done
[ -f $L/compact-joc.done ] || { echo "compact failed; E chain not started" > $L/after-compact.log; exit 1; }
for l in loop4 loop8; do [ "$(cat /sys/block/$l/loop/dio)" = 1 ] || { echo "$l not on direct I/O" > $L/after-compact.log; exit 1; }; done
echo "E chain started $(date -Is)" > $L/after-compact.log
exec /bench/erigon/tools/chain-B.sh joc:E1 sa:E1 joc:E2 sa:E2
