#!/bin/bash
# Reth baseline, resumed after the gates and smokes passed and the state-actor virgin got its
# ext4 inode tables zeroed: idle-write check on both scratches, then J1 S1 J2 S2, then reduce.
set -u
B=/root/bench/reth; L=$B/logs; cd $B
say() { echo "[$(date -Is)] $*" | tee -a $L/baseline.log; }
die() { say "STOP: $*"; exit 1; }

# A freshly mounted scratch must sit idle: 60 s, under 5 MB written (the state-actor virgin used to
# restart ext4 lazy init on every mount, ~1.7 GB/min of background writes).
idle() {  # idle <state> <mount> <loop>
  mountpoint -q $2 || SCHELK_STATE=/var/lib/schelk/$1.json schelk -y mount > /dev/null 2>&1 || die "mount $1"
  a=$(awk '{print $7}' /sys/block/$3/stat); sleep 60; b=$(awk '{print $7}' /sys/block/$3/stat)
  mb=$(( (b - a) * 512 / 1000000 )); say "idle $1: ${mb} MB written in 60 s"
  [ $mb -lt 5 ] || die "$1 scratch is not idle after mount"
}
JL=$(basename "$(python3 -c 'import json;print(json.load(open("/var/lib/schelk/reth-joc.json"))["scratch"])')")
SL=$(basename "$(python3 -c 'import json;print(json.load(open("/var/lib/schelk/reth-sa.json"))["scratch"])')")
SCHELK_STATE=/var/lib/schelk/reth-sa.json schelk -y restore > /dev/null 2>&1 || die "restore sa"
SCHELK_STATE=/var/lib/schelk/reth-joc.json schelk -y restore > /dev/null 2>&1 || die "restore joc"
idle reth-sa /schelk-sa $SL
idle reth-joc /schelk-joc $JL

nohup sh -c "while :; do echo \"\$(date +%s.%N) $JL \$(cat /sys/block/$JL/stat) | $SL \$(cat /sys/block/$SL/stat)\"; sleep 1; done" > $L/io-1s.log 2>&1 &
SAMPLER=$!

run() {  # run <cfg> <state> <log>
  say "run $1 start"
  env SCHELK_STATE=/var/lib/schelk/$2.json timeout 43200 benchmarkoor run --config cfg/$1.yaml > $L/$3.log 2>&1
  rc=$?
  inv=$(grep -c "status is INVALID\|INVALID_BLOCK\|\"INVALID\"" $L/$3.log)
  sch=$(grep -ciE "schelk.*(error|failed)" $L/$3.log)
  sum=$(grep -E "Test execution completed" $L/$3.log | tail -1 | grep -oE "failed=[0-9]+|passed=[0-9]+|total=[0-9]+" | tr "\n" " ")
  say "run $1 exit=$rc invalid=$inv schelk_err=$sch $sum free=$(df -m / | awk 'NR==2{print $4}')MB"
  podman ps -aq --filter name=benchmarkoor | xargs -r podman rm -f > /dev/null 2>&1
  [ "$inv" -eq 0 ] && [ "$sch" -eq 0 ] || die "run $1 had INVALID payloads or schelk errors"
}

run J1 reth-joc j1
run S1 reth-sa s1
run J2 reth-joc j2
run S2 reth-sa s2
kill $SAMPLER
python3 $B/reth_reduce.py > $B/results/baseline.json 2> $L/reduce.err && say "reduced -> results/baseline.json" || say "reduce failed, see logs/reduce.err"
say BASELINE-DONE
