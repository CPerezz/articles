#!/bin/bash
# Continuation under loop direct-io (exp-dio.sh: buffered loops dominate every test's time). J arm v1
# reads on the 66-test set, the ether-transfer family on all three read setups, then the full 266-test
# baseline again (dj1 ds1 dj2 ds2) with J1/S1's image and filter, so DIO is the only difference.
cd /root/bench/reth
IMGH=docker.io/benchlocal/reth:devnet7-hashedreads
IMGB=docker.io/benchlocal/reth:devnet7-sigkill
F160='regex:(test_account_access\[.*overhead_baseline_False.*160M|test_sload_bloated\[.*160M|test_sstore_bloated\[.*160M)'
FE='regex:test_ether_transfers_onchain_receivers\['
FC="$(cat cfg/common-filter.txt)"
# LOOP_SET_DIRECT_IO; the kernel refuses it while dm-era holds the loop, so set it with no scratch mapped.
setdio() { python3 -c 'import os,fcntl,sys; [fcntl.ioctl(os.open(d, os.O_RDONLY), 0x4C08, int(sys.argv[1])) for d in sys.argv[2:]]' "$1" /dev/loop1 /dev/loop3; }
dio() { echo "dio loop1=$(cat /sys/block/loop1/loop/dio) loop3=$(cat /sys/block/loop3/loop/dio)"; }
trap 'setdio 0 || echo "DIO-RESTORE-FAIL (set loop1/loop3 dio=0 by hand)"; echo "restored $(dio)"' EXIT
setdio 1 || { echo DIO-SET-FAIL; exit 1; }
dio
./mkexp.py xjc J $IMGH "$F160"
./mkexp.py xse S $IMGH "$FE"
./mkexp.py xjhe J $IMGH "$FE" RETH_FORCE_HASHED_READS=1
./mkexp.py xjce J $IMGH "$FE"
for a in dj1:J ds1:S dj2:J ds2:S; do ./mkexp.py ${a%%:*} ${a##*:} $IMGB "$FC" > /dev/null; done
run() {
  local st=/var/lib/schelk/reth-$([ "$2" = J ] && echo joc || echo sa).json rc
  echo "== $1 $(date)"
  env SCHELK_STATE=$st timeout 21600 benchmarkoor run --config cfg/$1.yaml > logs/$1.log 2>&1; rc=$?
  echo "$1 exit $rc $(grep -o 'failed=[0-9]* instance=[^ ]* passed=[0-9]*' logs/$1.log | tail -1)"; dio
}
run xjc J; run xse S; run xjhe J; run xjce J
run dj1 J; run ds1 S; run dj2 J; run ds2 S
echo "== EXP-DIO2-DONE $(date)"
