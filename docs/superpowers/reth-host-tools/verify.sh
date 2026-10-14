#!/bin/bash
# Reth gap verification driver. Plan: articles-wt-specs docs/superpowers/plans/2026-10-06-reth-gap-verification.md.
# Phases 1 -> 2 -> 3 in order, one benchmark at a time. A step whose marker is in logs/verify.done/ is
# skipped, so rerunning resumes after the last finished step. A failed check exits non-zero; the EXIT
# trap puts md2's readahead back and, if nothing is mapped, both scratch loops back to buffered.
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
DONE=logs/verify.done
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
fio_bench() {
  local F=/root/bench/reth/fio-bench.img L mode j e k t a
  fio --name=fill --filename=$F --size=64G --rw=write --bs=1M --direct=1 --ioengine=libaio --iodepth=16 --output-format=json > logs/fio-fill.json || return 1
  L=$(losetup --find --show $F) || return 1
  for mode in buffered dio raw; do
    t=$L
    case $mode in buffered) losetup --direct-io=off $L ;; dio) losetup --direct-io=on $L ;; raw) t=$F ;; esac
    if [ $mode != raw ] && [ "$(cat /sys/block/${L#/dev/}/loop/dio)" != "$([ $mode = dio ] && echo 1 || echo 0)" ]; then losetup -d $L; return 1; fi
    for j in psync:1 psync:4 psync:16 psync:64 libaio:1 libaio:16 libaio:64; do
      e=${j%%:*}; k=${j##*:}
      sync; echo 3 > /proc/sys/vm/drop_caches
      if [ $e = psync ]; then a="--ioengine=psync --numjobs=$k"; else a="--ioengine=libaio --iodepth=$k --numjobs=1"; fi
      fio --name=rr --filename=$t --rw=randread --bs=4k --direct=1 $a --group_reporting --time_based --runtime=15 --size=64G --randrepeat=0 --output-format=json > logs/fio-$mode-$e-$k.json || { losetup -d $L; return 1; }
      python3 -c "import json; r=json.load(open('logs/fio-$mode-$e-$k.json'))['jobs'][0]['read']; print('fio $mode $e $k iops', round(r['iops']), 'mean_us', round(r['clat_ns']['mean']/1000, 1))"
    done
  done
  losetup -d $L
  rm -f $F
}
# sampled <rid> <J|S> <n>: bench with 1 s iostat and 100 ms in-flight counters (loop1, nvme0n1, nvme1n1).
sampled() {
  local I S rc
  iostat -x -y -t 1 nvme0n1 nvme1n1 md2 loop1 > logs/$1.iostat &
  I=$!
  ( while :; do echo "$(date +%s.%N) $(cat /sys/block/loop1/inflight) $(cat /sys/block/nvme0n1/inflight) $(cat /sys/block/nvme1n1/inflight)"; sleep 0.1; done ) > logs/$1.inflight &
  S=$!
  bench $1 $2 $3
  rc=$?
  kill $I $S 2>/dev/null
  wait $I $S 2>/dev/null
  return $rc
}
# ra_attach <kb>: re-attach both scratch loops so their backing files open with md2 readahead = <kb>
# (a file copies its readahead size at open), then put md2 back to its own value at once.
ra_attach() {
  unmapped
  local f1 f3 r1 r3
  f1=$(losetup -n -O BACK-FILE /dev/loop1 | tr -d ' ')
  f3=$(losetup -n -O BACK-FILE /dev/loop3 | tr -d ' ')
  [ "$f1" = /schelk-vols/reth-joc-scratch.img ] && [ "$f3" = /schelk-vols/reth-sa-scratch.img ] || return 1
  losetup -d /dev/loop1 && losetup -d /dev/loop3 || return 1
  [ -z "$(losetup -n -O BACK-FILE /dev/loop1 /dev/loop3 2>/dev/null)" ] || return 1
  echo $1 > $MD2RA
  losetup /dev/loop1 $f1; r1=$?
  losetup /dev/loop3 $f3; r3=$?
  echo $RA0 > $MD2RA
  blockdev --setrw /dev/loop1 /dev/loop3
  echo "attached at md2 ra=$1 kB: $(losetup -l -n -O NAME,BACK-FILE,DIO,RO /dev/loop1 /dev/loop3 | tr -s ' ' | tr '\n' ';') md2 ra now $(cat $MD2RA)"
  [ $r1 = 0 ] && [ $r3 = 0 ]
}

echo "## phase 1 $(date) md2_ra=$RA0"
unmapped
setdio 1 || abort setdio
want_dio 1
for c in "xs2 S $F160" "xjh2 J $F160 $HR" "xjc2 J $F160" "xse2 S $FE" "xjhe2 J $FE $HR" "xjce2 J $FE" "t2jc J $T2" "t2jh J $T2 $HR" "t2s S $T2"; do
  set -f; set -- $c; set +f
  ./mkexp.py $1 $2 $IMGH "$3" ${4:-} > /dev/null || abort "mkexp $1"
done
for s in xs2:S:66 xjh2:J:66 xjc2:J:66 xse2:S:36 xjhe2:J:36 xjce2:J:36; do
  IFS=: read -r r a n <<< "$s"
  if step $r; then want_dio 1; bench $r $a $n || abort $r; ok $r; fi
done
for s in t2jc:J t2jh:J t2s:S; do
  IFS=: read -r r a <<< "$s"
  if step $r; then want_dio 1; trace $r $a 14 || abort $r; ok $r; fi
done
if step map-t2j; then map J t2j t2jc t2jh || abort map-t2j; ok map-t2j; fi
if step map-t2s; then map S t2s t2s || abort map-t2s; ok map-t2s; fi

echo "## phase 2 $(date)"
if step fio; then fio_bench || abort fio; ok fio; fi
./mkexp.py iod J $IMGH "$FIO2" $HR > /dev/null && ./mkexp.py iob J $IMGH "$FIO2" $HR > /dev/null || abort mkexp
./mkexp.py ras S $IMGH "$FF" > /dev/null && ./mkexp.py rajh J $IMGH "$FF" $HR > /dev/null || abort mkexp
unmapped; setdio 1 || abort setdio; want_dio 1
if step iod; then sampled iod J 2 || abort iod; ok iod; fi
unmapped; setdio 0 || abort setdio; want_dio 0
if step iob; then sampled iob J 2 || abort iob; ok iob; fi
if step ra; then
  want_dio 0
  if ra_attach 0 && trace ras S 6 && trace rajh J 6; then rc=0; else rc=1; fi
  ra_attach $RA0 || abort "re-attach at md2 ra=$RA0 failed: attach loop1/loop3 by hand"
  [ $rc = 0 ] || abort ra
  ok ra
fi

echo "## phase 3 $(date)"
V=/data/schelk-vols/reth-sa-virgin.img
B=/data/schelk-vols/reth-sa-virgin.pre-repack.img
if step backup; then
  unmapped
  rm -f $B
  cp --sparse=always $V $B || abort backup
  [ "$(stat -c %s $V)" = "$(stat -c %s $B)" ] || abort backup-size
  last=$(( $(stat -c %s $V) / 1073741824 - 1 ))
  for off in 0 $last; do
    [ "$(dd if=$V bs=1G skip=$off count=1 status=none | sha256sum)" = "$(dd if=$B bs=1G skip=$off count=1 status=none | sha256sum)" ] || abort "backup sha at GiB $off"
  done
  echo "backup $(du -h --apparent-size $B | cut -f1) apparent, $(du -h $B | cut -f1) allocated"
  ok backup
fi
if step repack; then
  SCHELK_STATE=$(st S) schelk -y restore > /dev/null 2>&1 || abort restore
  python3 mdbxmap.py /schelk-sa/reth/db/mdbx.dat /dev/null /dev/null HashedAccounts 2> probe/repack-before.stats
  df -B1 /schelk-sa > logs/repack-df-before
  repack/repack -db /schelk-sa/reth/db -table HashedAccounts > logs/repack.log 2>&1
  if ! grep -q REPACK-OK logs/repack.log; then
    SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
    abort "repack failed; scratch recovered from the untouched virgin"
  fi
  sync
  python3 mdbxmap.py /schelk-sa/reth/db/mdbx.dat /dev/null /dev/null HashedAccounts 2> probe/repack-after.stats
  df -B1 /schelk-sa > logs/repack-df-after
  ok repack
fi
if step promote; then
  mount | grep -q ' /schelk-sa ' || abort "scratch not mounted: the repacked store is not on it"
  sync
  SCHELK_STATE=$(st S) schelk -y promote > logs/promote-repack.log 2>&1 || abort promote
  ok promote
fi
if step gate; then
  SCHELK_STATE=$(st S) schelk -y restore > /dev/null 2>&1 || abort restore
  ./gate-boot.sh repack /schelk-sa/reth /schelk-sa/reth/chainspec.json $IMGB loop3 reth_sa_era > logs/gate-repack.out 2>&1
  SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  grep -q "^latest=0 $GENESIS $ROOT" logs/gate-repack/summary && grep -q "^genesis=$GENESIS $ROOT" logs/gate-repack/summary || abort "gate: $(tr '\n' ' ' < logs/gate-repack/summary)"
  ok gate
fi
unmapped; setdio 1 || abort setdio; want_dio 1
for c in "xsr S $F160" "xsr2 S $F160" "xser S $FE" "xser2 S $FE" "t2sr S $T2"; do
  set -f; set -- $c; set +f
  ./mkexp.py $1 $2 $IMGH "$3" > /dev/null || abort "mkexp $1"
done
for s in xsr:S:66 xsr2:S:66 xser:S:36 xser2:S:36; do
  IFS=: read -r r a n <<< "$s"
  if step $r; then want_dio 1; bench $r $a $n || abort $r; ok $r; fi
done
if step t2sr; then want_dio 1; trace t2sr S 14 || abort t2sr; ok t2sr; fi
if step map-t2sr; then map S t2sr t2sr || abort map-t2sr; ok map-t2sr; fi
echo "== VERIFY-DONE $(date)"
