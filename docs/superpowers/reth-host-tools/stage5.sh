#!/bin/bash
# Cycle 3 of plan docs/superpowers/plans/2026-10-13-reth-study-finalize.md: PR1-PR5 + A (scale-free
# storage tail) + B (StoragesTrie rows in address order) + C (mainnet account model).
# Regenerates the S store at J's account count (295061MB; the account count does not depend on the
# models), gates page fill, storage shape and account shape against J, adopts it as the S virgin (the
# cycle-2 virgin stays on disk until cycle 3 passes), has reth rebuild its tries from the hashed tables,
# refills the S fixtures with reth, smokes, traces T3 on S, then the 266-test DIO bench kj1 ks1 kj2 ks2
# and its reduction. One pass, no stop: every gate aborts the run instead.
# Steps with a marker in logs/k.done/ are skipped, so rerunning resumes. A failed check exits non-zero.
set -u
cd /root/bench/reth
FF='regex:(opcode_BALANCE-value_sent_0-account_mode_AccountMode\.(NON_EXISTING_ACCOUNT|EXISTING_EOA|EXISTING_CONTRACT_MINIMAL|EXISTING_CONTRACT_DIFF_MAX)-overhead_baseline_False.*160M|test_sload_bloated\[.*160M)'
T3=$(grep -m1 -oE "^T3='.*'$" stage3.sh | cut -d"'" -f2)
TABLES="PlainAccountState HashedAccounts Bytecodes AccountsTrie PlainStorageState HashedStorages StoragesTrie"
CONTENT="HashedAccounts AccountsTrie HashedStorages StoragesTrie Bytecodes"
MD2RA=/sys/block/md2/queue/read_ahead_kb
RA0=$(cat $MD2RA)
DONE=logs/k.done
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
SAIMG=localhost/state-actor-reth:final
SASRC=/root/bench/reth/state-actor-final
FC="$(cat cfg/common-filter.txt)"
SK=/data/schelk-vols/reth-sa-k-virgin.img
SCR=/schelk-vols/reth-sa-scratch.img
GEN=/sa-gen-k
SPILL=/data/spill-reth-k
FX=/data/fixtures/sa-k-reth
FXPREV=/data/fixtures/sa-h-reth
FILLARGS=$(cat cfg/k-fill-args)
loopw() { awk '{print $7}' /sys/block/$1/stat; }
md2free() { df -BG / | awk 'NR==2{print $4+0}'; }

echo "## stage 5 $(date)"
if step build; then
  podman build -f $SASRC/Dockerfile.reth -t $SAIMG --build-arg STATE_ACTOR_VERSION=final $SASRC > logs/sa-build-k.log 2>&1 || abort build
  ok build
fi
if step gen; then
  rm -rf $GEN $SPILL; mkdir -p $GEN $SPILL
  ( while sleep 30; do podman ps --format '{{.Names}}' | grep -q sa-gen-k || continue
      [ "$(md2free)" -lt 50 ] && { echo "md2 free < 50 GB: stopping sa-gen-k"; podman stop -t 120 sa-gen-k; break; }
    done ) > logs/gen-k-guard.log 2>&1 &
  G=$!
  ( while sleep 600; do echo "$(date -Is) gen=$(du -sm $GEN | cut -f1)MB spill=$(du -sm $SPILL | cut -f1)MB md2free=$(md2free)GB mem_avail=$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)GB"; done ) > logs/gen-k-size.log 2>&1 &
  Z=$!
  t0=$(date +%s)
  # FILLARGS is a word list. 295061MB: auto-fill + the spec's 1,200,012 accounts = J's 354,792,873 (+145).
  podman run --rm --name sa-gen-k --ulimit nofile=1048576:1048576 -v $GEN:/data \
    -v /root/bench/reth/cfg/state-actor-spec-baseline.yaml:/spec.yaml:ro -v $SPILL:/spill -e TMPDIR=/spill \
    $SAIMG --db=/data --client=reth --target-size=295061MB --spec=/spec.yaml --seed=42 --fork=osaka --gas-limit=1000000000 \
    $FILLARGS --verbose > logs/gen-k.log 2>&1
  rc=$?
  kill $G $Z 2>/dev/null
  echo "gen exit $rc in $(( ($(date +%s) - t0) / 60 )) min; $(grep -E 'State Root' logs/gen-k.log | tail -1)"
  [ $rc = 0 ] || abort gen
  grep -oE 'State Root: +0x[0-9a-f]{64}' logs/gen-k.log | tail -1 | grep -oE '0x[0-9a-f]{64}' > logs/k-root.txt
  [ -s logs/k-root.txt ] || abort "no state root in gen log"
  ok gen
fi
if step gen-check; then
  hashes $GEN/db logs/gen-k-hash.txt
  [ "$(grep -c '^HASH' logs/gen-k-hash.txt)" = 5 ] || abort "table hashes missing"
  cat logs/gen-k-hash.txt
  python3 mdbxmap.py $GEN/db/mdbx.dat /dev/null /dev/null HashedAccounts AccountsTrie HashedStorages StoragesTrie Bytecodes 2> probe/k-tables.stats
  python3 rc/fillgate.py $GEN/db/mdbx.dat > probe/k-fill.json || abort fillgate
  python3 rc/jwalk.py $GEN/db/mdbx.dat probe/jwalk-k.json > /dev/null || abort jwalk
  python3 rc/acctsize.py $GEN/db/mdbx.dat 200000 probe/acctsize-k.json > /dev/null || abort acctsize
  python3 rc/acctkind.py $GEN/db/mdbx.dat 20000 probe/acctkind-k.json > /dev/null || abort acctkind
  cp $GEN/state-actor-manifest.json logs/k-manifest.json
  du -sb $GEN > logs/gen-k-du.txt
  cat probe/k-tables.stats logs/gen-k-du.txt
  python3 rc/gatecheck.py probe/k-tables.stats probe/k-fill.json cfg/k-fill-targets.json || abort "page fill off target"
  python3 rc/distgate.py probe/jwalk-k.json probe/jwalk-j.json logs/k-manifest.json || abort "storage shape off J"
  python3 rc/acctgate.py probe/acctsize-k.json probe/acctsize-J.json probe/acctkind-k.json probe/acctkind-J.json || abort "account shape off J"
  ok gen-check
fi
if step mkvirgin; then
  gb=$(( $(du -sb $GEN | cut -f1) * 13 / 10 / 1073741824 + 50 ))
  echo "$gb" > logs/k-virgin-gb
  rm -f $SK; truncate -s ${gb}G $SK
  mkfs.ext4 -F -q -E lazy_itable_init=0,lazy_journal_init=0 $SK || abort mkfs
  mkdir -p /mnt/sak; mount -o loop $SK /mnt/sak || abort "mount virgin"
  mkdir /mnt/sak/reth && cp -a $GEN/. /mnt/sak/reth/ && sync || { umount /mnt/sak; abort copy; }
  repack/repack -db /mnt/sak/reth/db -table HashedAccounts -hash 2>/dev/null | grep HASH > logs/k-virgin-hash.txt
  a=$(du -sb $GEN | cut -f1); b=$(du -sb /mnt/sak/reth | cut -f1)
  umount /mnt/sak
  grep -qxF -f logs/k-virgin-hash.txt logs/gen-k-hash.txt && [ "$a" = "$b" ] || abort "virgin copy differs ($a vs $b bytes)"
  rm -rf $GEN $SPILL
  ok mkvirgin
fi
if step drop-sscratch; then
  # The cycle-2 S store stays as its virgin file on /data; only its md2 scratch goes.
  unmapped
  losetup -d /dev/loop3 || abort "detach loop3"
  [ ! -e /sys/block/loop3/loop/backing_file ] || abort "loop3 still attached"
  rm -f $SCR
  echo "md2 free after dropping the S scratch: $(md2free) GB"
  ok drop-sscratch
fi
if step adopt; then
  unmapped
  gb=$(cat logs/k-virgin-gb)
  losetup -d /dev/loop0 || abort "detach loop0"
  [ ! -e /sys/block/loop0/loop/backing_file ] || abort "loop0 still attached"
  losetup /dev/loop0 $SK
  [ "$(cat /sys/block/loop0/loop/backing_file)" = "$SK" ] || abort "loop0 not on $SK"
  fallocate -l ${gb}G $SCR || abort fallocate
  losetup /dev/loop3 $SCR
  [ "$(cat /sys/block/loop3/loop/backing_file)" = "$SCR" ] || abort "loop3 not on $SCR"
  blockdev --setrw /dev/loop0 /dev/loop3
  schelk -y init-from --state-path $(st S) --virgin /dev/loop0 --scratch /dev/loop3 --ramdisk /dev/ram1 \
    --mount-point /schelk-sa --fstype ext4 --granularity 65536 --dm-era-name reth_sa_era > logs/k-adopt.log 2>&1 || abort init-from
  mount | grep -q ' /schelk-sa ' && SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  ok adopt
fi
if step gate-s; then
  unmapped
  SCHELK_STATE=$(st S) schelk -y restore > /dev/null 2>&1 || abort restore
  repack/repack -db /schelk-sa/reth/db -table HashedAccounts -hash 2>/dev/null | grep HASH > logs/k-scratch-hash.txt
  w0=$(loopw loop3); sleep 60; w1=$(loopw loop3)
  echo "idle S k scratch: $(( (w1 - w0) * 512 / 1000000 )) MB written in 60 s"
  SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  grep -qxF -f logs/k-scratch-hash.txt logs/gen-k-hash.txt || abort "scratch HashedAccounts differs"
  ok gate-s
fi
if step rootcheck; then
  # See stage4.sh: read-only repair-trie on the scratch with RocksDB moved aside; recover discards it.
  unmapped
  SCHELK_STATE=$(st S) schelk -y restore > /dev/null 2>&1 || abort restore
  mv /schelk-sa/reth/rocksdb /schelk-sa/reth/rocksdb.hide
  t0=$(date +%s)
  podman run --rm -v /schelk-sa/reth:/data $IMG db --datadir /data --chain /data/chainspec.json repair-trie --dry-run > logs/k-rootcheck.log 2>&1
  rc=$?
  SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  echo "repair-trie exit $rc in $(( ($(date +%s) - t0) / 60 )) min; $(plain logs/k-rootcheck.log | grep -oE 'Found [0-9]+ inconsistencies.*' | tail -1)"
  [ $rc = 0 ] && plain logs/k-rootcheck.log | grep -q 'Found 0 inconsistencies' || abort "reth trie check"
  unmapped
  ok rootcheck
fi
if step refill; then
  unmapped
  ./refill.sh $FX 160,240 tests/benchmark/stateful/bloatnet > logs/refill-k.out 2>&1
  cat logs/refill-k.out
  grep -q '^fill exit 0 ' logs/refill-k.out || abort "refill"
  unmapped
  python3 rc/fxcmp.py $FX/blockchain_tests_stateful_engine $FXPREV/blockchain_tests_stateful_engine > logs/refill-k-cmp.txt 2>&1
  tail -1 logs/refill-k-cmp.txt
  ok refill
fi
unmapped; setdio 1 || abort setdio; want_dio 1
set -f
export S_FX=$FX
./mkexp.py ksmoke S $IMG "$FF" > /dev/null && ./mkexp.py t3sk S $IMG "$T3" > /dev/null || abort mkexp
for c in kj1:J ks1:S kj2:J ks2:S; do IFS=: read -r r a <<< "$c"; ./mkexp.py $r $a $IMG "$FC" > /dev/null || abort "mkexp $r"; done
set +f
if step ksmoke; then want_dio 1; bench ksmoke S 6 || abort ksmoke; ok ksmoke; fi
if step t3sk; then want_dio 1; trace t3sk S 21 || abort t3sk; ok t3sk; fi
if step map-t3sk; then
  SCHELK_STATE=$(st S) schelk -y restore > /dev/null 2>&1 || abort restore
  cat probe/t3sk-[0-9]*.pages | sort -un > probe/t3sk-all.pages
  python3 mdbxmap.py /schelk-sa/reth/db/mdbx.dat probe/t3sk-all.pages probe/t3sk.map $TABLES 2> probe/t3sk.map.log
  rc=$?
  python3 rc/classify3.py /schelk-sa/reth/db/mdbx.dat t3sk 21 probe/t3sk.classify.json > logs/t3sk-classify.log 2>&1 || rc=1
  SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  [ $rc = 0 ] && [ "$(nmapped)" = 0 ] || abort map-t3sk
  want_dio 1
  ok map-t3sk
fi
echo "== T3-DONE $(date)"
for c in kj1:J ks1:S kj2:J ks2:S; do
  IFS=: read -r r a <<< "$c"
  if step $r; then want_dio 1; bench $r $a 266 || abort $r; ok $r; fi
done
if step reduce; then python3 reth_reduce.py k > results/baseline-k.json 2> logs/reduce-k.err || abort reduce; ok reduce; fi
echo "== STAGE5-DONE $(date)"
