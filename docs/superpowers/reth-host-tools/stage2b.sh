#!/bin/bash
# Stages 2 and 3 of the v2 campaign (plan docs/superpowers/plans/2026-10-06-reth-v2-state-actor-prs.md):
# build state-actor with PR1+PR2, regenerate the reth store, adopt it as the S virgin, gate it, then the
# 266-test DIO re-bench against v2 jochemnet plus T2 traces. Build, generation and the virgin copy run while
# stage 1 migrates and rebuilds (nothing is measured then); the S-scratch swap and every run wait for stage 1.
# Steps with a marker in
# logs/fix.done/ are skipped, so rerunning resumes. A failed check exits non-zero.
set -u
cd /root/bench/reth
IMGH=docker.io/benchlocal/reth:devnet7-hashedreads
IMGB=docker.io/benchlocal/reth:devnet7-sigkill
HR=RETH_FORCE_HASHED_READS=1
F160='regex:(test_account_access\[.*overhead_baseline_False.*160M|test_sload_bloated\[.*160M|test_sstore_bloated\[.*160M)'
FE='regex:test_ether_transfers_onchain_receivers\[.*value_(160|240)M\]'
FF='regex:(opcode_BALANCE-value_sent_0-account_mode_AccountMode\.(NON_EXISTING_ACCOUNT|EXISTING_EOA|EXISTING_CONTRACT_MINIMAL|EXISTING_CONTRACT_DIFF_MAX)-overhead_baseline_False.*160M|test_sload_bloated\[.*160M)'
FIO2='regex:opcode_BALANCE-value_sent_0-account_mode_AccountMode\.(EXISTING_CONTRACT_MINIMAL|EXISTING_EOA)-overhead_baseline_False-cache_strategy_CacheStrategy\.NO_CACHE-benchmark-gas-value_160M\]'
T2='regex:(opcode_BALANCE-value_sent_0-account_mode_AccountMode\.(EXISTING_CONTRACT_MINIMAL|EXISTING_CONTRACT_SAME_MAX|EXISTING_EOA|EXISTING_CONTRACT_DIFF_MAX)-overhead_baseline_False-cache_strategy_CacheStrategy\.NO_CACHE-benchmark-gas-value_160M|opcode_CALL-value_sent_0-account_mode_AccountMode\.(EXISTING_EOA|NON_EXISTING_ACCOUNT|EXISTING_CONTRACT_MINIMAL)-overhead_baseline_False-cache_strategy_CacheStrategy\.NO_CACHE-benchmark-gas-value_160M|opcode_CALL-value_sent_1-account_mode_AccountMode\.EXISTING_EOA-overhead_baseline_False-cache_strategy_CacheStrategy\.NO_CACHE-benchmark-gas-value_160M|test_sload_bloated\[.*NO_CACHE-existing_slots_False-benchmark-gas-value_160M|test_sstore_bloated\[.*NO_CACHE-existing_slots_False-write_new_value_True-benchmark-gas-value_160M|transfer_amount_0-case_id_diff_to_(contract|existent|nonexistent|self)-benchmark-gas-value_160M)\]'
TABLES="PlainAccountState HashedAccounts Bytecodes AccountsTrie PlainStorageState HashedStorages StoragesTrie"
GENESIS=0x0cb035288eb4e257f34f3d570ed4f43f9d2fc45c09f19db6c0392f60f4a68623
ROOT=0x48d611bb839188317e983453705b31e1420b2c4416675f98d776ad8e130d51b8
MD2RA=/sys/block/md2/queue/read_ahead_kb
RA0=$(cat $MD2RA)
DONE=logs/fix.done
mkdir -p $DONE

abort() { echo "ABORT $* $(date)"; exit 1; }
st() { [ "$1" = J ] && echo /var/lib/schelk/reth-joc.json || echo /var/lib/schelk/reth-sa.json; }
# LOOP_SET_DIRECT_IO; the kernel refuses it while dm-era holds the loop, so call it with no scratch mapped.
setdio() { python3 -c 'import os,fcntl,sys; [fcntl.ioctl(os.open(d, os.O_RDONLY), 0x4C08, int(sys.argv[1])) for d in sys.argv[2:]]' "$1" /dev/loop1 /dev/loop3; }
dio() { echo "dio loop1=$(cat /sys/block/loop1/loop/dio) loop3=$(cat /sys/block/loop3/loop/dio)"; }
want_dio() { [ "$(cat /sys/block/loop1/loop/dio)$(cat /sys/block/loop3/loop/dio)" = "$1$1" ] || abort "want dio=$1, $(dio)"; }
nmapped() { dmsetup ls | grep -c _era; }
unmapped() { [ "$(nmapped)" = 0 ] || abort "a scratch is still mapped: $(dmsetup ls | tr '\n' ' ')"; }
trap 'echo "$RA0" > $MD2RA; [ "$(nmapped)" = 0 ] && setdio 0; echo "exit: $(dio) md2_ra=$(cat $MD2RA) mapped=$(nmapped) $(date)"' EXIT
step() { [ -f $DONE/$1 ] && { echo "skip $1"; return 1; }; echo "== $1 $(date)"; }
ok() { touch $DONE/$1; echo "$1 ok $(dio) $(date)"; }
plain() { sed 's/\x1b\[[0-9;]*m//g' "$1"; }
# check <rid> <expected tests> <exit code>: discovered count, exit code and passes from logs/<rid>.log.
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
# trace <rid> <J|S> <n>: trace-run.sh (page-cache inserts of mdbx.dat and of the backing image), then windows.
trace() {
  ./trace-run.sh $1 $2 > /dev/null
  local rc
  rc=$(grep -o 'BENCH-EXIT [0-9]*' logs/$1.log | tail -1 | cut -d' ' -f2)
  check $1 $3 "${rc:-1}" || return 1
  python3 pcwin.py $1 > probe/$1.win && [ "$(wc -l < probe/$1.win)" = "$3" ]
}
# map <J|S> <out> <rid...>: classify the union of the rids' traced pages by table on a restored store.
map() {
  local arm=$1 out=$2 a rc r
  shift 2
  a=$([ $arm = J ] && echo joc || echo sa)
  SCHELK_STATE=$(st $arm) schelk -y restore > /dev/null 2>&1 || return 1
  for r in "$@"; do cat probe/$r-[0-9]*.pages; done | sort -un > probe/$out-all.pages
  python3 mdbxmap.py /schelk-$a/reth/db/mdbx.dat probe/$out-all.pages probe/$out.map $TABLES 2> probe/$out.map.log
  rc=$?
  SCHELK_STATE=$(st $arm) schelk -y recover > /dev/null 2>&1
  [ $rc = 0 ] && [ "$(nmapped)" = 0 ]
}

IMG=docker.io/benchlocal/reth:devnet7-sigkill
SAIMG=localhost/state-actor-reth:layout-fixes
FC="$(cat cfg/common-filter.txt)"
SO=/data/schelk-vols/reth-sa-virgin.img
SF=/data/schelk-vols/reth-sa-fix-virgin.img
SCR=/schelk-vols/reth-sa-scratch.img
GEN=/sa-gen-fix
SPILL=/data/spill-reth-fix
HA_HASH="HashedAccounts c1710919b935756ca2f2934c7c2a04ba1b7c2ee94eefb6ec7178740ea38a2ff0 entries=430696738"
loopw() { awk '{print $7}' /sys/block/$1/stat; }
md2free() { df -BG / | awk 'NR==2{print $4+0}'; }

echo "## stage 2 (chain B) $(date)"
if step build; then
  podman build -f Dockerfile.reth -t $SAIMG --build-arg STATE_ACTOR_VERSION=layout-fixes /root/bench/reth/state-actor-fix > logs/sa-build-fix.log 2>&1 || abort build
  ok build
fi
if step gen; then
  rm -rf $GEN $SPILL; mkdir -p $GEN $SPILL
  ( while sleep 30; do podman ps --format '{{.Names}}' | grep -q sa-gen-fix || continue
      [ "$(md2free)" -lt 50 ] && { echo "md2 free < 50 GB: stopping sa-gen-fix"; podman stop -t 120 sa-gen-fix; break; }
    done ) > logs/gen-fix-guard.log 2>&1 &
  G=$!
  ( while sleep 600; do echo "$(date -Is) gen=$(du -sm $GEN | cut -f1)MB spill=$(du -sm $SPILL | cut -f1)MB md2free=$(md2free)GB"; done ) > logs/gen-fix-size.log 2>&1 &
  Z=$!
  t0=$(date +%s)
  podman run --rm --name sa-gen-fix --ulimit nofile=1048576:1048576 -v $GEN:/data \
    -v /root/bench/reth/cfg/state-actor-spec-baseline.yaml:/spec.yaml:ro -v $SPILL:/spill -e TMPDIR=/spill \
    $SAIMG --db=/data --client=reth --target-size=350GB --spec=/spec.yaml --seed=42 --fork=osaka --gas-limit=1000000000 --verbose > logs/gen-fix.log 2>&1
  rc=$?
  kill $G $Z 2>/dev/null
  echo "gen exit $rc in $(( ($(date +%s) - t0) / 60 )) min; $(grep -E 'State Root' logs/gen-fix.log | tail -1)"
  [ $rc = 0 ] || abort gen
  grep -qE "State Root: +$ROOT" logs/gen-fix.log || abort "state root differs from $ROOT"
  ok gen
fi
if step gen-check; then
  repack/repack -db $GEN/db -table HashedAccounts -hash 2>/dev/null | tee logs/gen-fix-hash.txt
  grep -q "$HA_HASH" logs/gen-fix-hash.txt || abort "HashedAccounts content differs from the original store"
  python3 mdbxmap.py $GEN/db/mdbx.dat /dev/null /dev/null HashedAccounts AccountsTrie HashedStorages StoragesTrie Bytecodes 2> probe/fix-tables.stats
  du -sb $GEN > logs/gen-fix-du.txt
  cat probe/fix-tables.stats logs/gen-fix-du.txt
  ok gen-check
fi
if step mkvirgin; then
  gb=$(( $(du -sb $GEN | cut -f1) * 13 / 10 / 1073741824 + 50 ))
  echo "$gb" > logs/fix-virgin-gb
  rm -f $SF; truncate -s ${gb}G $SF
  mkfs.ext4 -F -q -E lazy_itable_init=0,lazy_journal_init=0 $SF || abort mkfs
  mkdir -p /mnt/safix; mount -o loop $SF /mnt/safix || abort "mount virgin"
  mkdir /mnt/safix/reth && cp -a $GEN/. /mnt/safix/reth/ && sync || { umount /mnt/safix; abort copy; }
  repack/repack -db /mnt/safix/reth/db -table HashedAccounts -hash 2>/dev/null | tee logs/fix-virgin-hash.txt
  a=$(du -sb $GEN | cut -f1); b=$(du -sb /mnt/safix/reth | cut -f1)
  umount /mnt/safix
  grep -q "$HA_HASH" logs/fix-virgin-hash.txt && [ "$a" = "$b" ] || abort "virgin copy differs ($a vs $b bytes)"
  rm -rf $GEN $SPILL
  ok mkvirgin
fi
echo "fix virgin ready; waiting for stage 1 (baseline) to finish $(date)"
until [ -f logs/v2.done/STAGE1 ]; do
  grep -qE "ABORT|V2B-EXIT" logs/v2b.out 2>/dev/null && abort "stage 1 ended without STAGE1"
  sleep 60
done
if step drop-sscratch; then
  # The original state-actor store stays as the S virgin file on md3; only its md2 clone goes.
  [ -f $SO ] || abort "original S virgin missing"
  losetup -d /dev/loop3 || abort "detach loop3"
  [ ! -e /sys/block/loop3/loop/backing_file ] || abort "loop3 still attached"
  rm -f $SCR
  echo "md2 free after dropping the S scratch: $(md2free) GB"
  ok drop-sscratch
fi
if step adopt; then
  unmapped
  gb=$(cat logs/fix-virgin-gb)
  losetup -d /dev/loop0 || abort "detach loop0"
  [ ! -e /sys/block/loop0/loop/backing_file ] || abort "loop0 still attached"
  losetup /dev/loop0 $SF
  [ "$(cat /sys/block/loop0/loop/backing_file)" = "$SF" ] || abort "loop0 not on $SF"
  fallocate -l ${gb}G $SCR || abort fallocate
  losetup /dev/loop3 $SCR
  [ "$(cat /sys/block/loop3/loop/backing_file)" = "$SCR" ] || abort "loop3 not on $SCR"
  blockdev --setrw /dev/loop0 /dev/loop3
  schelk -y init-from --state-path $(st S) --virgin /dev/loop0 --scratch /dev/loop3 --ramdisk /dev/ram1 \
    --mount-point /schelk-sa --fstype ext4 --granularity 65536 --dm-era-name reth_sa_era > logs/fix-adopt.log 2>&1 || abort init-from
  mount | grep -q ' /schelk-sa ' && SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  ok adopt
fi
if step gate-s; then
  unmapped
  SCHELK_STATE=$(st S) schelk -y restore > /dev/null 2>&1 || abort restore
  repack/repack -db /schelk-sa/reth/db -table HashedAccounts -hash 2>/dev/null | tee logs/fix-scratch-hash.txt
  w0=$(loopw loop3); sleep 60; w1=$(loopw loop3)
  echo "idle S fix scratch: $(( (w1 - w0) * 512 / 1000000 )) MB written in 60 s"
  SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  grep -q "$HA_HASH" logs/fix-scratch-hash.txt || abort "scratch HashedAccounts differs"
  ok gate-s
fi
unmapped; setdio 1 || abort setdio; want_dio 1
set -f
./mkexp.py fsmoke S $IMG "$FF" > /dev/null || abort mkexp
for c in fj1:J fs1:S fj2:J fs2:S; do IFS=: read -r r a <<< "$c"; ./mkexp.py $r $a $IMG "$FC" > /dev/null || abort "mkexp $r"; done
./mkexp.py t2jv J $IMG "$T2" > /dev/null && ./mkexp.py t2sf S $IMG "$T2" > /dev/null || abort mkexp
set +f
if step fsmoke; then want_dio 1; bench fsmoke S 6 || abort fsmoke; ok fsmoke; fi
echo "## stage 3 $(date)"
for c in fj1:J fs1:S fj2:J fs2:S; do
  IFS=: read -r r a <<< "$c"
  if step $r; then want_dio 1; bench $r $a 266 || abort $r; ok $r; fi
done
if step reduce; then python3 reth_reduce.py f > results/baseline-fix.json 2> logs/reduce-fix.err || abort reduce; ok reduce; fi
for c in t2jv:J t2sf:S; do
  IFS=: read -r r a <<< "$c"
  if step $r; then want_dio 1; trace $r $a 14 || abort $r; ok $r; fi
done
if step map-t2jv; then map J t2jv t2jv || abort map-t2jv; ok map-t2jv; fi
if step map-t2sf; then map S t2sf t2sf || abort map-t2sf; ok map-t2sf; fi
echo "== STAGE2-DONE $(date)"
