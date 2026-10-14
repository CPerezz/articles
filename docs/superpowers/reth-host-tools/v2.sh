#!/bin/bash
# Stage 1 of the v2 campaign (2026-10-06): jochemnet v1 -> v2 with `reth db migrate-v2`, the original
# state-actor store back in place, then the 266-test DIO baseline vj1 vs1 vj2 vs2 against the v2 store.
# Steps with a marker in logs/v2.done/ are skipped, so rerunning resumes. A failed check exits non-zero;
# the EXIT trap puts md2's readahead back and, if nothing is mapped, both scratch loops back to buffered.
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
DONE=logs/v2.done
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
FC="$(cat cfg/common-filter.txt)"
JV=/data/schelk-vols/reth-joc-virgin.img
SV=/data/schelk-vols/reth-sa-virgin.img
SO=/data/schelk-vols/reth-sa-virgin.pre-repack.img
SR=/data/schelk-vols/reth-sa-virgin.repacked.img
rdb() { podman run --rm --ulimit nofile=1048576:1048576 -v /schelk-joc/reth:/var/lib/reth --entrypoint reth $IMG db --datadir /var/lib/reth "$@"; }
loopw() { awk '{print $7}' /sys/block/$1/stat; }

echo "## stage 1 $(date)"
unmapped
if step migrate; then
  SCHELK_STATE=$(st J) schelk -y restore > /dev/null 2>&1 || abort restore
  rdb settings get > logs/v2-settings-before.txt 2>&1
  du -sb /schelk-joc/reth/* > logs/v2-du-before.txt
  t0=$(date +%s)
  rdb migrate-v2 --chain mainnet > logs/v2-migrate.log 2>&1
  rc=$?
  echo "migrate exit $rc in $(( $(date +%s) - t0 )) s"
  rdb settings get > logs/v2-settings-after.txt 2>&1
  du -sb /schelk-joc/reth/* > logs/v2-du-after.txt
  if [ $rc != 0 ] || ! grep -q "storage_v2: true" logs/v2-settings-after.txt; then
    SCHELK_STATE=$(st J) schelk -y recover > /dev/null 2>&1
    abort "migrate rc $rc; the scratch was recovered from the v1 virgin"
  fi
  ok migrate
fi
if step srestore; then
  # The S virgin holds the repacked store; put the original state-actor output (main 005a19c) back.
  [ "$(nmapped)" = 1 ] && mount | grep -q ' /schelk-joc ' || abort "expected only the migrated J scratch mapped"
  [ -f $SO ] && [ ! -e $SR ] || abort "backup missing or $SR exists"
  losetup -d /dev/loop0 || abort "detach loop0"
  [ ! -e /sys/block/loop0/loop/backing_file ] || abort "loop0 still attached"
  mv $SV $SR && mv $SO $SV || abort mv
  losetup /dev/loop0 $SV
  [ "$(cat /sys/block/loop0/loop/backing_file)" = "$SV" ] || abort "loop0 not on $SV"
  schelk -y init-from --state-path $(st S) --virgin /dev/loop0 --scratch /dev/loop3 --ramdisk /dev/ram1 \
    --mount-point /schelk-sa --fstype ext4 --granularity 65536 --dm-era-name reth_sa_era > logs/srestore.log 2>&1 || abort init-from
  mount | grep -q ' /schelk-sa ' || SCHELK_STATE=$(st S) schelk -y restore > /dev/null 2>&1 || abort "restore S"
  repack/repack -db /schelk-sa/reth/db -table HashedAccounts -stats 2>/dev/null | tee logs/srestore-stats.txt
  grep -q "LeafPages:11698671" logs/srestore-stats.txt || abort "S is not the original store"
  SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  ok srestore
fi
if step promote-j; then
  until [ -f $DONE/jbackup ] || [ -f $DONE/jbackup.failed ]; do sleep 60; done
  [ -f $DONE/jbackup ] || abort "v1 backup failed; not promoting"
  mount | grep -q ' /schelk-joc ' || abort "J scratch not mounted: the migrated store is not on it"
  sync
  SCHELK_STATE=$(st J) schelk -y promote > logs/promote-v2.log 2>&1 || abort promote
  ok promote-j
fi
if step gate-j; then
  unmapped
  SCHELK_STATE=$(st J) schelk -y restore > /dev/null 2>&1 || abort restore
  rdb settings get > logs/v2-settings-promoted.txt 2>&1
  w0=$(loopw loop1); sleep 60; w1=$(loopw loop1)
  echo "idle J v2 scratch: $(( (w1 - w0) * 512 / 1000000 )) MB written in 60 s"
  SCHELK_STATE=$(st J) schelk -y recover > /dev/null 2>&1
  grep -q "storage_v2: true" logs/v2-settings-promoted.txt || abort "promoted J store is not v2"
  ok gate-j
fi
unmapped; setdio 1 || abort setdio; want_dio 1
set -f; ./mkexp.py vjsmoke J $IMG "$FF" > /dev/null || abort mkexp; set +f
if step vjsmoke; then want_dio 1; bench vjsmoke J 6 || abort vjsmoke; ok vjsmoke; fi
for r in vj1:J vs1:S vj2:J vs2:S; do
  IFS=: read -r rid a <<< "$r"
  ./mkexp.py $rid $a $IMG "$FC" > /dev/null || abort "mkexp $rid"
done
for r in vj1:J vs1:S vj2:J vs2:S; do
  IFS=: read -r rid a <<< "$r"
  if step $rid; then want_dio 1; bench $rid $a 266 || abort $rid; ok $rid; fi
done
if step reduce; then python3 reth_reduce.py v > results/baseline-v2.json 2> logs/reduce-v2.err || abort reduce; ok reduce; fi
echo "== STAGE1-DONE $(date)"
