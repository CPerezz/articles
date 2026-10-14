#!/bin/bash
# Content hashes of the five reth state tables on the S-fixed store (PR1+PR2): the identity reference
# that stage3.sh's gen-check compares the PR3+PR4 store against. The S scratch lost its dm-era device
# (recover failed while the virgin was mounted elsewhere), so it is rebuilt from the virgin first.
set -u
cd /root/bench/reth || exit 1
export SCHELK_STATE=/var/lib/schelk/reth-sa.json
echo "== full-recover $(date)"
schelk -y full-recover 2>&1 | tail -5
echo "== restore $(date)"
schelk -y restore > /dev/null 2>&1 || { echo "ABORT restore"; exit 1; }
for t in HashedAccounts AccountsTrie HashedStorages StoragesTrie Bytecodes; do
  s=$(date +%s)
  repack/repack -db /schelk-sa/reth/db -table $t -hash 2>/dev/null | grep HASH >> logs/sfix-tables-hash.new
  echo "  $t took $(( $(date +%s) - s )) s"
done
schelk -y recover 2>&1 | tail -2
[ "$(grep -c '^HASH' logs/sfix-tables-hash.new)" = 5 ] && mv logs/sfix-tables-hash.new logs/sfix-tables-hash.ref
cat logs/sfix-tables-hash.ref
echo "== done $(date) mapped=$(dmsetup ls | grep -c _era)"
schelk status 2>&1 | sed -n '/Runtime/,/era:/p'
