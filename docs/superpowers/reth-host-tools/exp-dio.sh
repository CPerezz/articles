#!/bin/bash
# Loop direct-io intervention: no backing-file page cache (so no backing readahead) under both
# scratches. Forensic traces of the 6-test set, then the 66-test 160M timing set, both arms on the
# same binary (S is v2, J forced to hashed reads). Loops go back to buffered on exit.
cd /root/bench/reth
IMGH=docker.io/benchlocal/reth:devnet7-hashedreads
F160='regex:(test_account_access\[.*overhead_baseline_False.*160M|test_sload_bloated\[.*160M|test_sstore_bloated\[.*160M)'
FF='regex:(opcode_BALANCE-value_sent_0-account_mode_AccountMode\.(NON_EXISTING_ACCOUNT|EXISTING_EOA|EXISTING_CONTRACT_MINIMAL|EXISTING_CONTRACT_DIFF_MAX)-overhead_baseline_False.*160M|test_sload_bloated\[.*160M)'
# LOOP_SET_DIRECT_IO; the kernel refuses it while dm-era holds the loop, so set it with no scratch mapped.
setdio() { python3 -c 'import os,fcntl,sys; [fcntl.ioctl(os.open(d, os.O_RDONLY), 0x4C08, int(sys.argv[1])) for d in sys.argv[2:]]' "$1" /dev/loop1 /dev/loop3; }
dio() { echo "dio loop1=$(cat /sys/block/loop1/loop/dio) loop3=$(cat /sys/block/loop3/loop/dio)"; }
trap 'setdio 0 || echo "DIO-RESTORE-FAIL (set loop1/loop3 dio=0 by hand)"; echo "restored $(dio)"' EXIT
setdio 1 || { echo DIO-SET-FAIL; exit 1; }
dio
./mkexp.py xfs S $IMGH "$FF"
./mkexp.py xfjh J $IMGH "$FF" RETH_FORCE_HASHED_READS=1
./mkexp.py xs S $IMGH "$F160"
./mkexp.py xjh J $IMGH "$F160" RETH_FORCE_HASHED_READS=1
echo "== xfs $(date)"; ./trace-run.sh xfs S; python3 pcwin.py xfs > probe/xfs.win; dio
echo "== xfjh $(date)"; ./trace-run.sh xfjh J; python3 pcwin.py xfjh > probe/xfjh.win; dio
echo "== xs $(date)"; env SCHELK_STATE=/var/lib/schelk/reth-sa.json timeout 21600 benchmarkoor run --config cfg/xs.yaml > logs/xs.log 2>&1; echo "xs exit $?"; dio
echo "== xjh $(date)"; env SCHELK_STATE=/var/lib/schelk/reth-joc.json timeout 21600 benchmarkoor run --config cfg/xjh.yaml > logs/xjh.log 2>&1; echo "xjh exit $?"; dio
echo "== EXP-DIO-DONE $(date)"
