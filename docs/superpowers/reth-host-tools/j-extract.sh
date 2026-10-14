#!/bin/bash
# After the download and the schelk init: extract the reth jochemnet snapshot into the J scratch,
# record its layout, then promote scratch -> virgin before anything boots on it.
L=/root/bench/reth/logs
until grep -q J-SETUP-DONE $L/j-setup.log && grep -q -E "DL-OK|DL-BAD" $L/dl.log; do sleep 60; done
grep -q DL-OK $L/dl.log || { echo "download failed"; exit 1; }
echo "extract start $(date -Is)"
mkdir -p /schelk-joc/reth
time (zstd -dc -T0 /data/dl/reth-joc-24402727.tar.zst | tar -x -C /schelk-joc/reth)
rc=$?; echo "EXTRACT-EXIT=$rc $(date -Is)"; [ $rc -eq 0 ] || exit 1
ls -la /schelk-joc/reth; du -sh /schelk-joc/reth/* 2>/dev/null; cat /schelk-joc/reth/db/database.version 2>/dev/null; echo
ls /schelk-joc/reth/static_files | sed -E "s/_[0-9]+_[0-9]+.*//" | sort | uniq -c
df -h /schelk-joc
echo "promote start $(date -Is)"
time schelk -y promote --state-path /var/lib/schelk/reth-joc.json
echo "PROMOTE-EXIT=$? $(date -Is)"
schelk --state-path /var/lib/schelk/reth-joc.json status
mountpoint -q /schelk-joc || schelk -y mount --state-path /var/lib/schelk/reth-joc.json
mountpoint /schelk-joc
echo J-EXTRACT-DONE
