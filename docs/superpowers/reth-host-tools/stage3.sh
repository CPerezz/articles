#!/bin/bash
# Cycle 1 of plan docs/superpowers/plans/2026-10-08-reth-layout-root-causes.md.
# `stage3.sh`: build state-actor with PR1-PR4, regenerate the reth store with the `migrated` page-fill
# profile, gate content (all five tables identical to the S-fixed store) and page fill, adopt it as the S
# virgin, smoke, then the extended page traces. It stops at T3-DONE so the traces can be checked against
# the page model before the long run.
# `stage3.sh bench`: the 266-test DIO re-bench gj1 gs1 gj2 gs2 against v2 jochemnet, and its reduction.
# Steps with a marker in logs/g.done/ are skipped, so rerunning resumes. A failed check exits non-zero.
set -u
cd /root/bench/reth
PHASE=${1:-prep}
FF='regex:(opcode_BALANCE-value_sent_0-account_mode_AccountMode\.(NON_EXISTING_ACCOUNT|EXISTING_EOA|EXISTING_CONTRACT_MINIMAL|EXISTING_CONTRACT_DIFF_MAX)-overhead_baseline_False.*160M|test_sload_bloated\[.*160M)'
# T2 plus one test per >= 0.5 s family it missed, and one SHA3-only control (21 tests in every arm).
T3='regex:(opcode_BALANCE-value_sent_0-account_mode_AccountMode\.(EXISTING_CONTRACT_MINIMAL|EXISTING_CONTRACT_SAME_MAX|EXISTING_EOA|EXISTING_CONTRACT_DIFF_MAX|EXISTING_CONTRACT_JUMPDEST)-overhead_baseline_False-cache_strategy_CacheStrategy\.NO_CACHE-benchmark-gas-value_160M|opcode_BALANCE-value_sent_0-account_mode_AccountMode\.EXISTING_CONTRACT_MINIMAL-overhead_baseline_True-cache_strategy_CacheStrategy\.NO_CACHE-benchmark-gas-value_160M|opcode_CALL-value_sent_0-account_mode_AccountMode\.(EXISTING_EOA|NON_EXISTING_ACCOUNT|EXISTING_CONTRACT_MINIMAL|EXISTING_CONTRACT_DIFF_MAX)-overhead_baseline_False-cache_strategy_CacheStrategy\.NO_CACHE-benchmark-gas-value_160M|opcode_CALL-value_sent_1-account_mode_AccountMode\.(EXISTING_EOA|EXISTING_CONTRACT_MINIMAL|EXISTING_CONTRACT_SAME_MAX)-overhead_baseline_False-cache_strategy_CacheStrategy\.NO_CACHE-benchmark-gas-value_160M|test_sload_bloated\[.*NO_CACHE-existing_slots_False-benchmark-gas-value_(160|240)M|test_sstore_bloated\[.*NO_CACHE-existing_slots_False-write_new_value_(True|False)-benchmark-gas-value_160M|transfer_amount_0-case_id_diff_to_(contract|existent|nonexistent|self)-benchmark-gas-value_160M)\]'
TABLES="PlainAccountState HashedAccounts Bytecodes AccountsTrie PlainStorageState HashedStorages StoragesTrie"
CONTENT="HashedAccounts AccountsTrie HashedStorages StoragesTrie Bytecodes"
ROOT=0x48d611bb839188317e983453705b31e1420b2c4416675f98d776ad8e130d51b8
MD2RA=/sys/block/md2/queue/read_ahead_kb
RA0=$(cat $MD2RA)
DONE=logs/g.done
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
# map <J|S> <out> <rid...>: classify the rids' traced pages by table, and measure page fill, on a restored store.
map() {
  local arm=$1 out=$2 a rc r
  shift 2
  a=$([ $arm = J ] && echo joc || echo sa)
  SCHELK_STATE=$(st $arm) schelk -y restore > /dev/null 2>&1 || return 1
  for r in "$@"; do cat probe/$r-[0-9]*.pages; done | sort -un > probe/$out-all.pages
  python3 mdbxmap.py /schelk-$a/reth/db/mdbx.dat probe/$out-all.pages probe/$out.map $TABLES 2> probe/$out.map.log
  rc=$?
  python3 rc/fillgate.py /schelk-$a/reth/db/mdbx.dat > probe/$out.fill.json || rc=1
  SCHELK_STATE=$(st $arm) schelk -y recover > /dev/null 2>&1
  [ $rc = 0 ] && [ "$(nmapped)" = 0 ]
}
# hashes <db dir> <out>: content hash of every reth state table, in a fixed order.
hashes() { for t in $CONTENT; do repack/repack -db $1 -table $t -hash 2>/dev/null | grep HASH; done > $2; }

IMG=docker.io/benchlocal/reth:devnet7-sigkill
SAIMG=localhost/state-actor-reth:fill-control
FC="$(cat cfg/common-filter.txt)"
SG=/data/schelk-vols/reth-sa-g-virgin.img
SF=/data/schelk-vols/reth-sa-fix-virgin.img
SCR=/schelk-vols/reth-sa-scratch.img
GEN=/sa-gen-g
SPILL=/data/spill-reth-g
REF=logs/sfix-tables-hash.ref
FILLARGS=$(cat cfg/g-fill-args)
loopw() { awk '{print $7}' /sys/block/$1/stat; }
md2free() { df -BG / | awk 'NR==2{print $4+0}'; }

echo "## stage 3 ($PHASE) $(date)"
if [ "$PHASE" = prep ]; then
if step build; then
  podman build -f Dockerfile.reth -t $SAIMG --build-arg STATE_ACTOR_VERSION=fill-control /root/bench/reth/state-actor-fill > logs/sa-build-g.log 2>&1 || abort build
  ok build
fi
if step gen; then
  rm -rf $GEN $SPILL; mkdir -p $GEN $SPILL
  ( while sleep 30; do podman ps --format '{{.Names}}' | grep -q sa-gen-g || continue
      [ "$(md2free)" -lt 50 ] && { echo "md2 free < 50 GB: stopping sa-gen-g"; podman stop -t 120 sa-gen-g; break; }
    done ) > logs/gen-g-guard.log 2>&1 &
  G=$!
  ( while sleep 600; do echo "$(date -Is) gen=$(du -sm $GEN | cut -f1)MB spill=$(du -sm $SPILL | cut -f1)MB md2free=$(md2free)GB"; done ) > logs/gen-g-size.log 2>&1 &
  Z=$!
  t0=$(date +%s)
  # FILLARGS is a word list.
  podman run --rm --name sa-gen-g --ulimit nofile=1048576:1048576 -v $GEN:/data \
    -v /root/bench/reth/cfg/state-actor-spec-baseline.yaml:/spec.yaml:ro -v $SPILL:/spill -e TMPDIR=/spill \
    $SAIMG --db=/data --client=reth --target-size=350GB --spec=/spec.yaml --seed=42 --fork=osaka --gas-limit=1000000000 \
    $FILLARGS --verbose > logs/gen-g.log 2>&1
  rc=$?
  kill $G $Z 2>/dev/null
  echo "gen exit $rc in $(( ($(date +%s) - t0) / 60 )) min; $(grep -E 'State Root' logs/gen-g.log | tail -1)"
  [ $rc = 0 ] || abort gen
  grep -qE "State Root: +$ROOT" logs/gen-g.log || abort "state root differs from $ROOT"
  ok gen
fi
if step gen-check; then
  [ "$(grep -c '^HASH' $REF)" = 5 ] || abort "S-fixed reference hashes missing ($REF)"
  hashes $GEN/db logs/gen-g-hash.txt
  cat logs/gen-g-hash.txt
  diff $REF logs/gen-g-hash.txt || abort "table contents differ from the S-fixed store"
  python3 mdbxmap.py $GEN/db/mdbx.dat /dev/null /dev/null HashedAccounts AccountsTrie HashedStorages StoragesTrie Bytecodes 2> probe/g-tables.stats
  python3 rc/fillgate.py $GEN/db/mdbx.dat > probe/g-fill.json || abort fillgate
  cp $GEN/state-actor-manifest.json logs/g-manifest.json
  du -sb $GEN > logs/gen-g-du.txt
  cat probe/g-tables.stats logs/gen-g-du.txt
  python3 rc/gatecheck.py probe/g-tables.stats probe/g-fill.json cfg/g-fill-targets.json || abort "page fill off target"
  ok gen-check
fi
if step mkvirgin; then
  gb=$(( $(du -sb $GEN | cut -f1) * 13 / 10 / 1073741824 + 50 ))
  echo "$gb" > logs/g-virgin-gb
  rm -f $SG; truncate -s ${gb}G $SG
  mkfs.ext4 -F -q -E lazy_itable_init=0,lazy_journal_init=0 $SG || abort mkfs
  mkdir -p /mnt/sag; mount -o loop $SG /mnt/sag || abort "mount virgin"
  mkdir /mnt/sag/reth && cp -a $GEN/. /mnt/sag/reth/ && sync || { umount /mnt/sag; abort copy; }
  repack/repack -db /mnt/sag/reth/db -table HashedAccounts -hash 2>/dev/null | grep HASH > logs/g-virgin-hash.txt
  a=$(du -sb $GEN | cut -f1); b=$(du -sb /mnt/sag/reth | cut -f1)
  umount /mnt/sag
  grep -qxF -f logs/g-virgin-hash.txt logs/gen-g-hash.txt && [ "$a" = "$b" ] || abort "virgin copy differs ($a vs $b bytes)"
  rm -rf $GEN $SPILL
  ok mkvirgin
fi
if step drop-sscratch; then
  # The S-fixed store stays as its virgin file on md3; only its md2 clone goes.
  tmux has-session -t rc-hash 2>/dev/null && abort "rc-hash still running on the S scratch"
  [ -f $SF ] || abort "S-fixed virgin missing"
  unmapped
  losetup -d /dev/loop3 || abort "detach loop3"
  [ ! -e /sys/block/loop3/loop/backing_file ] || abort "loop3 still attached"
  rm -f $SCR
  echo "md2 free after dropping the S scratch: $(md2free) GB"
  ok drop-sscratch
fi
if step adopt; then
  unmapped
  gb=$(cat logs/g-virgin-gb)
  losetup -d /dev/loop0 || abort "detach loop0"
  [ ! -e /sys/block/loop0/loop/backing_file ] || abort "loop0 still attached"
  losetup /dev/loop0 $SG
  [ "$(cat /sys/block/loop0/loop/backing_file)" = "$SG" ] || abort "loop0 not on $SG"
  fallocate -l ${gb}G $SCR || abort fallocate
  losetup /dev/loop3 $SCR
  [ "$(cat /sys/block/loop3/loop/backing_file)" = "$SCR" ] || abort "loop3 not on $SCR"
  blockdev --setrw /dev/loop0 /dev/loop3
  schelk -y init-from --state-path $(st S) --virgin /dev/loop0 --scratch /dev/loop3 --ramdisk /dev/ram1 \
    --mount-point /schelk-sa --fstype ext4 --granularity 65536 --dm-era-name reth_sa_era > logs/g-adopt.log 2>&1 || abort init-from
  mount | grep -q ' /schelk-sa ' && SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  ok adopt
fi
if step gate-s; then
  unmapped
  SCHELK_STATE=$(st S) schelk -y restore > /dev/null 2>&1 || abort restore
  repack/repack -db /schelk-sa/reth/db -table HashedAccounts -hash 2>/dev/null | grep HASH > logs/g-scratch-hash.txt
  w0=$(loopw loop3); sleep 60; w1=$(loopw loop3)
  echo "idle S g scratch: $(( (w1 - w0) * 512 / 1000000 )) MB written in 60 s"
  SCHELK_STATE=$(st S) schelk -y recover > /dev/null 2>&1
  grep -qxF -f logs/g-scratch-hash.txt logs/gen-g-hash.txt || abort "scratch HashedAccounts differs"
  ok gate-s
fi
fi
unmapped; setdio 1 || abort setdio; want_dio 1
set -f
./mkexp.py gsmoke S $IMG "$FF" > /dev/null || abort mkexp
./mkexp.py t3jg J $IMG "$T3" > /dev/null && ./mkexp.py t3sg S $IMG "$T3" > /dev/null || abort mkexp
for c in gj1:J gs1:S gj2:J gs2:S; do IFS=: read -r r a <<< "$c"; ./mkexp.py $r $a $IMG "$FC" > /dev/null || abort "mkexp $r"; done
set +f
if [ "$PHASE" = prep ]; then
  if step gsmoke; then want_dio 1; bench gsmoke S 6 || abort gsmoke; ok gsmoke; fi
  for c in t3jg:J t3sg:S; do
    IFS=: read -r r a <<< "$c"
    if step $r; then want_dio 1; trace $r $a 21 || abort $r; ok $r; fi
  done
  if step map-t3jg; then map J t3jg t3jg || abort map-t3jg; ok map-t3jg; fi
  if step map-t3sg; then map S t3sg t3sg || abort map-t3sg; ok map-t3sg; fi
  echo "== T3-DONE $(date)"
  exit 0
fi
[ -f $DONE/map-t3sg ] || abort "run the prep phase first"
for c in gj1:J gs1:S gj2:J gs2:S; do
  IFS=: read -r r a <<< "$c"
  if step $r; then want_dio 1; bench $r $a 266 || abort $r; ok $r; fi
done
if step reduce; then python3 reth_reduce.py g > results/baseline-g.json 2> logs/reduce-g.err || abort reduce; ok reduce; fi
echo "== STAGE3-DONE $(date)"
