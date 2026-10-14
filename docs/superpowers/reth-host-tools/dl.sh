#!/bin/bash
# Resumable 8-stream download of the reth jochemnet snapshot to md3 HDD, then an exact-size check.
mkdir -p /data/dl && cd /data/dl
U=https://snapshots.ethpandaops.io/jochemnet/reth/24402727/snapshot.tar.zst
date -Is
aria2c -x8 -s8 -k256M -c --file-allocation=falloc --summary-interval=300 --console-log-level=warn -o reth-joc-24402727.tar.zst "$U"
echo "aria2c exit=$?"
sz=$(stat -c %s reth-joc-24402727.tar.zst); echo "size=$sz expected=1020907172580"
[ "$sz" = "1020907172580" ] && echo DL-OK || echo DL-BAD
date -Is
