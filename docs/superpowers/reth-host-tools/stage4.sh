#!/bin/bash
# Cycle 2 of plan docs/superpowers/plans/2026-10-08-reth-layout-root-causes.md: PR1-PR5.
# Regenerates the S store with --storage-model=mainnet (PR5) at J's account count (295061MB) and the
# `migrated` page fill, gates page fill and storage shape, adopts it as the S virgin, has reth rebuild
# its tries from the hashed tables (root included), refills the S fixtures with reth (the genesis
# changed), smokes, traces T3 on S (J's t3jg trace and store are
# unchanged), then the 266-test DIO re-bench hj1 hs1 hj2 hs2 and its reduction. One pass, no stop:
# every gate aborts the run instead.
# Steps with a marker in logs/h.done/ are skipped, so rerunning resumes. A failed check exits non-zero.
set -u
cd /root/bench/reth
FF='regex:(opcode_BALANCE-value_sent_0-account_mode_AccountMode\.(NON_EXISTING_ACCOUNT|EXISTING_EOA|EXISTING_CONTRACT_MINIMAL|EXISTING_CONTRACT_DIFF_MAX)-overhead_baseline_False.*160M|test_sload_bloated\[.*160M)'
T3=$(grep -m1 -oE "^T3='.*'$" stage3.sh | cut -d"'" -f2)
TABLES="PlainAccountState HashedAccounts Bytecodes AccountsTrie PlainStorageState HashedStorages StoragesTrie"
CONTENT="HashedAccounts AccountsTrie HashedStorages StoragesTrie Bytecodes"
MD2RA=/sys/block/md2/queue/read_ahead_kb
RA0=$(cat $MD2RA)
DONE=logs/h.done
mkdir -p $DONE

abort() { echo "ABORT $* $(date)"; exit 1; }
st() { [ "$1" = J ] && echo /var/lib/schelk/reth-joc.json || echo /var/lib/schelk/reth-sa.json; }
# LOOP_SET_DIRECT_IO; the kernel refuses it while dm-era holds the loop, so call it with no scratch mapped.
setdio() { python3 -c 'import os,fcntl,sys; [fcntl.ioctl(os.open(d, os.O_RDONLY), 0x4C08, int(sys.argv[1])) for d in sys.argv[2:]]' "$1" /dev/loop1 /dev/loop3; }
dio() { echo "dio loop1=$(cat /sys/block/loop1/loop/dio) loop3=$(cat /sys/block/loop3/loop/dio 2>/dev/null)"; }
want_dio() { [ "$(cat /sys/block/loop1/loop/dio)$(cat /sys/block/loop3/loop/dio)" = "$1$1" ] || abort "want dio=$1, $(dio)"; }
nmapped() { dmsetup ls | grep -c _era; }
unmapped() { [ "$(nmapped)" = 0 ] || abort "a scratch is still mapped: $(dmsetup ls | tr '\n' ' ')"; }
trap 'echo "$RA0" > $MD2RA; [ "$(nmapped)" = 0 ] && setdio 0; echo "exit: $(dio) md2_ra=$(cat $MD2RA) mapped=$(nmapped) $(date)"' EXIT
step() { [ -f $DONE/$1 ] && { echo "skip $1"; return 1; }; echo "== $1 $(date)"; }
ok() { touch $DONE/$1; echo "$1 ok $(dio) $(date)"; }
plain() { sed 's/\x1b\[[0-9;]*m//g' "$1"; }
check() {
  local n p
  n=$(plain logs/$1.log | grep -o 'Discovered EEST fixtures.*count=[0-9]*' | head -1 | grep -o '[0-9]*$')
  p=$(plain logs/$1.log | grep -o 'failed=[0-9]* instance=[^ ]* passed=[0-9]*' | tail -1)
  echo "$1 exit $3 discovered=${n:-?} $p"
  [ "$3" = 0 ] && [ "${n:-}" = "$2" ] && [[ "$p" == "failed=0 "*"passed=$2" ]]
}
bench() {
  env SCHELK_STATE=$(st $2) timeout 21600 benchmarkoor run --config cfg/$1.yaml > logs/$1.log 2>&1
  check $1 $3 $?
}
trace() {
  ./trace-run.sh $1 $2 > /dev/null
  local rc
  rc=$(grep -o 'BENCH-EXIT [0-9]*' logs/$1.log | tail -1 | cut -d' ' -f2)
  check $1 $3 "${rc:-1}" || return 1
  python3 pcwin.py $1 > probe/$1.win && [ "$(wc -l < probe/$1.win)" = "$3" ]
}
# hashes <db dir> <out>: content hash of every reth state table, in a fixed order.
hashes() { for t in $CONTENT; do repack/repack -db $1 -table $t -hash 2>/dev/null | grep HASH; done > $2; }

IMG=docker.io/benchlocal/reth:devnet7-sigkill
SAIMG=localhost/state-actor-reth:storage-model
FC="$(cat cfg/common-filter.txt)"
SH=/data/schelk-vols/reth-sa-h-virgin.img
SG=/data/schelk-vols/reth-sa-g-virgin.img
SCR=/schelk-vols/reth-sa-scratch.img
GEN=/sa-gen-h
SPILL=/data/spill-reth-h
FX=/data/fixtures/sa-h-reth
FILLARGS=$(cat cfg/h-fill-args)
loopw() { awk '{print $7}' /sys/block/$1/stat; }
md2free() { df -BG / | awk 'NR==2{print $4+0}'; }

echo "## stage 4 $(date)"
if step build; then
  podman build -f /root/bench/reth/state-actor-storage/Dockerfile.reth -t $SAIMG --build-arg STATE_ACTOR_VERSION=storage-model /root/bench/reth/state-actor-storage > logs/sa-build-h.log 2>&1 || abort build
  ok build
fi
if step gen; then
  rm -rf $GEN $SPILL; mkdir -p $GEN $SPILL
  ( while sleep 30; do podman ps --format '{{.Names}}' | grep -q sa-gen-h || continue
      [ "$(md2free)" -lt 50 ] && { echo "md2 free < 50 GB: stopping sa-gen-h"; podman stop -t 120 sa-gen-h; break; }
    done ) > logs/gen-h-guard.log 2>&1 &
  G=$!
  ( while sleep 600; do echo "$(date -Is) gen=$(du -sm $GEN | cut -f1)MB spill=$(du -sm $SPILL | cut -f1)MB md2free=$(md2free)GB mem_avail=$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)GB"; done ) > logs/gen-h-size.log 2>&1 &
  Z=$!
  t0=$(date +%s)
  # FILLARGS is a word list. 295061MB: auto-fill + the spec's 1,200,012 accounts = J's 354,792,873 (+145).
  podman run --rm --name sa-gen-h --ulimit nofile=1048576:1048576 -v $GEN:/data \
    -v /root/bench/reth/cfg/state-actor-spec-baseline.yaml:/spec.yaml:ro -v $SPILL:/spill -e TMPDIR=/spill \
    $SAIMG --db=/data --client=reth --target-size=295061MB --spec=/spec.yaml --seed=42 --fork=osaka --gas-limit=1000000000 \
    $FILLARGS --verbose > logs/gen-h.log 2>&1
  rc=$?
  kill $G $Z 2>/dev/null
  echo "gen exit $rc in $(( ($(date +%s) - t0) / 60 )) min; $(grep -E 'State Root' logs/gen-h.log | tail -1)"
  [ $rc = 0 ] || abort gen
  grep -oE 'State Root: +0x[0-9a-f]{64}' logs/gen-h.log | tail -1 | grep -oE '0x[0-9a-f]{64}' > logs/h-root.txt
  [ -s logs/h-root.txt ] || abort "no state root in gen log"
  ok gen
fi
if step gen-check; then
  hashes $GEN/db logs/gen-h-hash.txt
  [ "$(grep -c '^HASH' logs/gen-h-hash.txt)" = 5 ] || abort "table hashes missing"
  cat logs/gen-h-hash.txt
  python3 mdbxmap.py $GEN/db/mdbx.dat /dev/null /dev/null HashedAccounts AccountsTrie HashedStorages StoragesTrie Bytecodes 2> probe/h-tables.stats
  python3 rc/fillgate.py $GEN/db/mdbx.dat > probe/h-fill.json || abort fillgate
  python3 rc/jwalk.py $GEN/db/mdbx.dat probe/jwalk-h.json > /dev/null || abort jwalk
  cp $GEN/state-actor-manifest.json logs/h-manifest.json
  du -sb $GEN > logs/gen-h-du.txt
  cat probe/h-tables.stats logs/gen-h-du.txt
  python3 rc/gatecheck.py probe/h-tables.stats probe/h-fill.json cfg/h-fill-targets.json || abort "page fill off target"
  python3 rc/distgate.py probe/jwalk-h.json probe/jwalk-j.json logs/h-manifest.json || abort "storage shape off J"
  ok gen-check
fi
if step mkvirgin; then
  gb=$(( $(du -sb $GEN | cut -f1) * 13 / 10 / 1073741824 + 50 ))
  echo "$gb" > logs/h-virgin-gb
  rm -f $SH; truncate -s ${gb}G $SH
  mkfs.ext4 -F -q -E lazy_itable_init=0,lazy_journal_init=0 $SH || abort mkfs
  mkdir -p /mnt/sah; mount -o loop $SH /mnt/sah || abort "mount virgin"
  mkdir /mnt/sah/reth && cp -a $GEN/. /mnt/sah/reth/ && sync || { umount /mnt/sah; abort copy; }
  repack/repack -db /mnt/sah/reth/db -table HashedAccounts -hash 2>/dev/null | grep HASH > logs/h-virgin-hash.txt
  a=$(du -sb $GEN | cut -f1); b=$(du -sb /mnt/sah/reth | cut -f1)
  umount /mnt/sah
  grep -qxF -f logs/h-virgin-hash.txt logs/gen-h-hash.txt && [ "$a" = "$b" ] || abort "virgin copy differs ($a vs $b bytes)"
  rm -rf $GEN $SPILL
  ok mkvirgin
fi
if step drop-sscratch; then
  # The S-g store stays as its virgin file on md3; only its md2 clone goes. The S-g validation refill
  # runs on that clone, so wait for it.
  while tmux has-session -t rc-fill 2>/dev/null; do sleep 60; done
  [ -f $SG ] || abort "S-g virgin missing"
  unmapped
  losetup -d /dev/loop3 || abort "detach loop3"
  [ ! -e /sys/block/loop3/loop/backing_file ] || abort "loop3 still attached"
  rm -f $SCR
  echo "md2 free after dropping the S scratch: $(md2free) GB"
  ok drop-sscratch
fi
if step adopt; then
  unmapped
  gb=$(cat logs/h-virgin-gb)
  losetup -d /dev/loop0 || abort "detach loop0"
  [ ! -e /sys/block/loop0/loop/backing_file ] || abort "loop0 still attached"
  losetup /dev/loop0 $SH
  [ "$(cat /sys/block/loop0/loop/backing_file)" = "$SH" ] || abort "loop0 not on $SH"
  fallocate -l ${gb}G $SCR || abort fallocate
  losetup /dev/loop3 $SCR
  [ "$(cat /sys/block/loop3/loop/backing_file)" = "$SCR" ] || abort "loop3 not on $SCR"
  blockdev --setrw /dev/loop0 /dev/loop3
  schelk -y init-from --state-path $(st S) --virgin /dev/loop0 --scratch /dev/loop3 --ramdisk /dev/ram1 \
    --mount-point /schelk-sa --fstype ext4 --granularity 65536 --dm-era-name reth_sa_era > logs/h-adopt.log 2>&1 || abort init-from
  mount | grep -q ' /schelk-sa ' && SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  ok adopt
fi
if step gate-s; then
  unmapped
  SCHELK_STATE=$(st S) schelk -y restore > /dev/null 2>&1 || abort restore
  repack/repack -db /schelk-sa/reth/db -table HashedAccounts -hash 2>/dev/null | grep HASH > logs/h-scratch-hash.txt
  w0=$(loopw loop3); sleep 60; w1=$(loopw loop3)
  echo "idle S h scratch: $(( (w1 - w0) * 512 / 1000000 )) MB written in 60 s"
  SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  grep -qxF -f logs/h-scratch-hash.txt logs/gen-h-hash.txt || abort "scratch HashedAccounts differs"
  ok gate-s
fi
if step rootcheck; then
  # reth rebuilds every account and storage trie node from the hashed tables and compares it with the
  # stored one, root included. Read-only, because a read-write open runs genesis init, which rejects
  # the store (the chainspec has no alloc to hash). A read-only open cannot add the BAL column family
  # this RocksDB lacks, so RocksDB is moved aside (repair-trie reads only MDBX). Read-only still drops
  # reth.toml and RocksDB dirs into the datadir: run it on the scratch, which recover discards.
  unmapped
  SCHELK_STATE=$(st S) schelk -y restore > /dev/null 2>&1 || abort restore
  mv /schelk-sa/reth/rocksdb /schelk-sa/reth/rocksdb.hide
  t0=$(date +%s)
  podman run --rm -v /schelk-sa/reth:/data $IMG db --datadir /data --chain /data/chainspec.json repair-trie --dry-run > logs/h-rootcheck.log 2>&1
  rc=$?
  SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  echo "repair-trie exit $rc in $(( ($(date +%s) - t0) / 60 )) min; $(plain logs/h-rootcheck.log | grep -oE 'Found [0-9]+ inconsistencies.*' | tail -1)"
  [ $rc = 0 ] && plain logs/h-rootcheck.log | grep -q 'Found 0 inconsistencies' || abort "reth trie check"
  unmapped
  ok rootcheck
fi
if step refill; then
  unmapped
  ./refill.sh $FX 160,240 tests/benchmark/stateful/bloatnet > logs/refill-h.out 2>&1
  cat logs/refill-h.out
  grep -q '^fill exit 0 ' logs/refill-h.out || abort "refill"
  unmapped
  python3 rc/fxcmp.py $FX/blockchain_tests_stateful_engine /data/fixtures/sa-g-reth/blockchain_tests_stateful_engine > logs/refill-h-cmp.txt 2>&1
  tail -1 logs/refill-h-cmp.txt
  ok refill
fi
unmapped; setdio 1 || abort setdio; want_dio 1
set -f
export S_FX=$FX
./mkexp.py hsmoke S $IMG "$FF" > /dev/null && ./mkexp.py t3sh S $IMG "$T3" > /dev/null || abort mkexp
for c in hj1:J hs1:S hj2:J hs2:S; do IFS=: read -r r a <<< "$c"; ./mkexp.py $r $a $IMG "$FC" > /dev/null || abort "mkexp $r"; done
set +f
if step hsmoke; then want_dio 1; bench hsmoke S 6 || abort hsmoke; ok hsmoke; fi
if step t3sh; then want_dio 1; trace t3sh S 21 || abort t3sh; ok t3sh; fi
if step map-t3sh; then
  SCHELK_STATE=$(st S) schelk -y restore > /dev/null 2>&1 || abort restore
  cat probe/t3sh-[0-9]*.pages | sort -un > probe/t3sh-all.pages
  python3 mdbxmap.py /schelk-sa/reth/db/mdbx.dat probe/t3sh-all.pages probe/t3sh.map $TABLES 2> probe/t3sh.map.log
  rc=$?
  python3 rc/classify3.py /schelk-sa/reth/db/mdbx.dat t3sh 21 probe/t3sh.classify.json > logs/t3sh-classify.log 2>&1 || rc=1
  SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  [ $rc = 0 ] && [ "$(nmapped)" = 0 ] || abort map-t3sh
  want_dio 1
  ok map-t3sh
fi
echo "== T3-DONE $(date)"
for c in hj1:J hs1:S hj2:J hs2:S; do
  IFS=: read -r r a <<< "$c"
  if step $r; then want_dio 1; bench $r $a 266 || abort $r; ok $r; fi
done
if step reduce; then python3 reth_reduce.py h > results/baseline-h.json 2> logs/reduce-h.err || abort reduce; ok reduce; fi
echo "== STAGE4-DONE $(date)"
