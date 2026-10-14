#!/bin/bash
# v1 jochemnet virgin -> md3 copy before stage 1 promotes the v2 store over it.
cd /root/bench/reth
V=/data/schelk-vols/reth-joc-virgin.img; B=/data/schelk-vols/reth-joc-virgin.v1.img; D=logs/v2.done
mkdir -p $D
echo "jbackup start $(date)"
fail() { echo "jbackup FAILED: $*"; touch $D/jbackup.failed; exit 1; }
[ -e $B ] && fail "$B exists"
cp --sparse=always $V $B || fail cp
[ "$(stat -c %s $V)" = "$(stat -c %s $B)" ] || fail size
last=$(( $(stat -c %s $V) / 1073741824 - 1 ))
for off in 0 $last; do
  [ "$(dd if=$V bs=1G skip=$off count=1 status=none | sha256sum)" = "$(dd if=$B bs=1G skip=$off count=1 status=none | sha256sum)" ] || fail "sha at GiB $off"
done
echo "jbackup ok $(du -h --apparent-size $B | cut -f1) apparent, $(du -h $B | cut -f1) allocated $(date)"
touch $D/jbackup
