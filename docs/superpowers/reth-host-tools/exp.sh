#!/bin/bash
# Attribution sequence: S forensic trace, page->table mapping for both arms, J hashed-reads
# forensic trace, then J timing runs with the patched binary (hashed reads on / off).
cd /root/bench/reth
IMGH=docker.io/benchlocal/reth:devnet7-hashedreads
F160='regex:(test_account_access\[.*overhead_baseline_False.*160M|test_sload_bloated\[.*160M|test_sstore_bloated\[.*160M)'
FF='regex:(opcode_BALANCE-value_sent_0-account_mode_AccountMode\.(NON_EXISTING_ACCOUNT|EXISTING_EOA|EXISTING_CONTRACT_MINIMAL|EXISTING_CONTRACT_DIFF_MAX)-overhead_baseline_False.*160M|test_sload_bloated\[.*160M)'
./mkexp.py jh J $IMGH "$F160" RETH_FORCE_HASHED_READS=1
./mkexp.py jc J $IMGH "$F160"
./mkexp.py fjh J $IMGH "$FF" RETH_FORCE_HASHED_READS=1
echo "== fs $(date)"; ./trace-run.sh fs S; python3 pcwin.py fs > probe/fs.win
echo "== fjh $(date)"; ./trace-run.sh fjh J; python3 pcwin.py fjh > probe/fjh.win
python3 pcwin.py fj > probe/fj.win
for a in joc:fj sa:fs; do
  A=${a%%:*}; R=${a##*:}
  echo "== map $R $(date)"
  SCHELK_STATE=/var/lib/schelk/reth-$A.json schelk -y restore > /dev/null 2>&1
  cat probe/$R-[0-9]*.pages | sort -un > probe/$R-all.pages
  [ $R = fj ] && cat probe/fjh-[0-9]*.pages | sort -un > probe/fjh-all.pages && sort -mun probe/fj-all.pages probe/fjh-all.pages > probe/fj-union.pages && mv probe/fj-union.pages probe/fj-all.pages
  python3 mdbxmap.py /schelk-$A/reth/db/mdbx.dat probe/$R-all.pages probe/$R.map 2> probe/$R.map.log
done
echo "== jh $(date)"; env SCHELK_STATE=/var/lib/schelk/reth-joc.json timeout 21600 benchmarkoor run --config cfg/jh.yaml > logs/jh.log 2>&1; echo "jh exit $?"
echo "== jc $(date)"; env SCHELK_STATE=/var/lib/schelk/reth-joc.json timeout 21600 benchmarkoor run --config cfg/jc.yaml > logs/jc.log 2>&1; echo "jc exit $?"
echo "== EXP-DONE $(date)"
