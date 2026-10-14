#!/bin/bash
# Attribute every traced page of t3jg / t3sg to its table on a restored scratch, then recover.
# Run between stage3.sh's T3-DONE and the bench phase: it must not overlap a measurement.
set -u
cd /root/bench/reth || exit 1
[ "$(dmsetup ls | grep -c _era)" = 0 ] || { echo "ABORT a scratch is mapped"; exit 1; }
for c in t3jg:J:joc:/var/lib/schelk/reth-joc.json t3sg:S:sa:/var/lib/schelk/reth-sa.json; do
  IFS=: read -r rid arm a state <<< "$c"
  SCHELK_STATE=$state schelk -y restore > /dev/null 2>&1 || { echo "ABORT restore $arm"; exit 1; }
  python3 rc/classify3.py /schelk-$a/reth/db/mdbx.dat $rid 21 probe/$rid.classify.json > logs/$rid-classify.log 2>&1
  echo "$rid classify exit $?"
  SCHELK_STATE=$state schelk -y recover > /dev/null 2>&1 || echo "WARN recover $arm failed"
done
echo "== done $(date) mapped=$(dmsetup ls | grep -c _era)"
