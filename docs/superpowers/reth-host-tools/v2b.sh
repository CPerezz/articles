#!/bin/bash
# Stage 1, continued (chain A). migrate-v2 clears the trie tables and resets SenderRecovery/MerkleExecute,
# so the migrated jochemnet store needs one pipeline run before it can be promoted: `reth node --debug.terminate`
# backfills the reset stages to the tip (MerkleExecute checks the root against the tip header) and exits.
# Takes over from v2.sh, which is parked in its promote step. Waits for chain B (stage2b.sh) to finish the
# fix-store generation before measuring, then runs the 266-test DIO baseline vj1 vs1 vj2 vs2.
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
TIP=24410463
rdb() { podman run --rm --ulimit nofile=1048576:1048576 -v /schelk-joc/reth:/var/lib/reth --entrypoint reth $IMG db --datadir /var/lib/reth "$@"; }
loopw() { awk '{print $7}' /sys/block/$1/stat; }

echo "## stage 1b $(date)"
until [ -f $DONE/migrate ] && [ -f $DONE/srestore ] && grep -q "jbackup ok" logs/jbackup.out && grep -q "^== promote-j" logs/v2.out; do
  grep -q "ABORT" logs/v2.out && abort "v2.sh aborted: $(grep ABORT logs/v2.out | tail -1)"
  grep -q "jbackup FAILED" logs/jbackup.out && abort "v1 backup failed"
  sleep 60
done
tmux kill-session -t reth-v2 2>/dev/null
sleep 5
pgrep -f "[.]/v2.sh" > /dev/null && abort "v2.sh still running"
echo "v2.sh stopped at its promote step; migrate, srestore and the v1 backup are done"
if step rebuild; then
  mount | grep -q ' /schelk-joc ' || abort "J scratch not mounted: the migrated store is not on it"
  rdb stage-checkpoints get > logs/v2-checkpoints-before.txt 2>&1
  mkdir -p logs/rebuild && openssl rand -hex 32 > logs/rebuild/jwt
  podman rm -f rbuild > /dev/null 2>&1
  t0=$(date +%s)
  podman run --rm --name rbuild --ulimit nofile=1048576:1048576 -v /schelk-joc/reth:/var/lib/reth \
    -v /root/bench/besu-mainnet-genesis.json:/tmp/genesis.json:ro -v /root/bench/reth/logs/rebuild/jwt:/tmp/jwtsecret:ro \
    $IMG node --datadir=/var/lib/reth --chain=/tmp/genesis.json --full --debug.skip-genesis-validation \
    --engine.disable-precompile-cache --engine.persistence-threshold=0 --engine.memory-block-buffer-target=0 \
    --authrpc.jwtsecret=/tmp/jwtsecret --authrpc.addr=127.0.0.1 --disable-discovery --nat=none \
    --max-outbound-peers=0 --max-inbound-peers=0 --debug.terminate > logs/rebuild.log 2>&1
  rc=$?
  echo "rebuild exit $rc in $(( ($(date +%s) - t0) / 60 )) min"
  rdb stage-checkpoints get > logs/v2-checkpoints-after.txt 2>&1
  rdb settings get > logs/v2-settings-rebuilt.txt 2>&1
  [ $rc = 0 ] || abort "rebuild exit $rc (see logs/rebuild.log)"
  for s in SenderRecovery MerkleExecute Execution Finish; do
    grep -qE "$s[^0-9]*$TIP" logs/v2-checkpoints-after.txt || abort "$s checkpoint not at $TIP (see logs/v2-checkpoints-after.txt)"
  done
  grep -q "storage_v2: true" logs/v2-settings-rebuilt.txt || abort "store not v2 after rebuild"
  ok rebuild
fi
if step promote-j; then
  mount | grep -q ' /schelk-joc ' || abort "J scratch not mounted"
  sync
  SCHELK_STATE=$(st J) schelk -y promote > logs/promote-v2.log 2>&1 || abort promote
  tail -4 logs/promote-v2.log
  ok promote-j
fi
if step gate-j; then
  SCHELK_STATE=$(st J) schelk -y restore > /dev/null 2>&1 || abort restore
  rdb settings get > logs/v2-settings-promoted.txt 2>&1
  rdb stage-checkpoints get > logs/v2-checkpoints-promoted.txt 2>&1
  w0=$(loopw loop1); sleep 60; w1=$(loopw loop1)
  echo "idle J v2 scratch: $(( (w1 - w0) * 512 / 1000000 )) MB written in 60 s"
  SCHELK_STATE=$(st J) schelk -y recover > /dev/null 2>&1
  grep -q "storage_v2: true" logs/v2-settings-promoted.txt || abort "promoted J store is not v2"
  grep -qE "MerkleExecute[^0-9]*$TIP" logs/v2-checkpoints-promoted.txt || abort "promoted J store lost its MerkleExecute checkpoint"
  ok gate-j
fi
echo "waiting for chain B (fix-store generation) before measuring $(date)"
until [ -f logs/fix.done/mkvirgin ] || grep -qE "ABORT|FIX-EXIT" logs/fix.out 2>/dev/null; do sleep 60; done
[ -f logs/fix.done/mkvirgin ] || echo "chain B ended without the fix virgin: $(grep -E 'ABORT|FIX-EXIT' logs/fix.out | tail -1); the baseline goes ahead"
pgrep -f "sa-gen-fix|/mnt/safix" > /dev/null && abort "chain B still has generation or copy work running"
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
touch $DONE/STAGE1
echo "== STAGE1-DONE $(date)"
