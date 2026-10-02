#!/usr/bin/env bash
# jochemnet arm, end to end up to the probe (plan section 3): wait for the verified tarball and the
# mounted er-joc scratch, extract into it with a listing, check the extract, delete the tarball,
# promote, remount, then probe.
#
# The scratch is not the baseline: every benchmarkoor run starts with a schelk restore from the
# virgin image, so the extract only counts once it has been promoted.
set -uo pipefail

TARBALL=/bench/erigon/snapshots/erigon-jochemnet-24402727.tar.zst
DEST=/schelk-er-joc/snapshots/erigon/jochemnet/24402727
STATE=/var/lib/schelk/er-joc.json
LOCK=/bench/erigon/.schelk.lock
MDBX_BYTES=572455387136
LOG=/bench/erigon/logs/extract-joc.log
DONE=/bench/erigon/logs/extract-joc.done
FAIL=/bench/erigon/logs/extract-joc.fail

rm -f "$DONE" "$FAIL"
fail() { echo "FAIL $1" | tee -a "$LOG"; echo "$1" > "$FAIL"; exit 1; }

until [ -f /bench/logs/erigon/fetch-joc.done ]; do sleep 60; done
grep -q "rc=0" /bench/logs/erigon/fetch-joc.done || fail "G1: download $(cat /bench/logs/erigon/fetch-joc.done)"
until [ -f /bench/erigon/logs/setup-schelk.done ] || [ -f /bench/erigon/logs/setup-schelk.fail ]; do sleep 60; done
[ -f /bench/erigon/logs/setup-schelk.done ] || fail "G2: schelk setup failed"
findmnt -n /schelk-er-joc >/dev/null || fail "G2: /schelk-er-joc not mounted"

{
  echo "======== extract: $(date -Is) ========"
  echo "free on scratch: $(df -h /schelk-er-joc | tail -1)"
  mkdir -p "$DEST"
  cd "$DEST" || exit 1
  nice -n 10 ionice -c2 -n7 tar -I zstd -xvf "$TARBALL" > /bench/erigon/logs/joc-extract-list.txt
  echo "tar rc: $?" | tee /bench/erigon/logs/joc-extract.rc
  echo "finished: $(date -Is)"
} >> "$LOG" 2>&1

grep -q "tar rc: 0" /bench/erigon/logs/joc-extract.rc || fail "G3: tar failed"
{
  listed=$(grep -c . /bench/erigon/logs/joc-extract-list.txt)
  found=$(cd "$DEST" && find . -mindepth 1 | wc -l)
  echo "entries listed $listed, found $found"
  [ $((listed)) -le $((found + 1)) ] && [ $((found)) -le $((listed + 1)) ] || echo "ENTRY MISMATCH"
  mdbx=$(stat -c %s "$DEST/chaindata/mdbx.dat")
  echo "mdbx.dat apparent $mdbx (want $MDBX_BYTES), allocated $(du -sh "$DEST/chaindata/mdbx.dat" | cut -f1)"
  [ "$mdbx" = "$MDBX_BYTES" ] || echo "MDBX SIZE MISMATCH"
  echo "snapshot metadata block: $(python3 -c "import json;print(int(json.load(open('$DEST/_snapshot_eth_getBlockByNumber.json'))['result']['number'],16))")"
  echo "top level: $(ls "$DEST" | tr '\n' ' ')"
  echo "extract size: $(du -sh "$DEST" | cut -f1)"
  du -sh "$DEST"/*/ 2>/dev/null | sort -rh | head
  rm -f "$DEST/chaindata/mdbx.lck"
  sudo chown -R 1000:1000 "$DEST"
} >> "$LOG" 2>&1
grep -qE "ENTRY MISMATCH|MDBX SIZE MISMATCH" "$LOG" && fail "G3: extract check"

rm -f "$TARBALL"
echo "tarball deleted; free $(df -h / | tail -1 | awk '{print $4}')" >> "$LOG"

# A promote allocates the whole virgin image; keep half a terabyte spare on the shared host.
free_kb=$(df --output=avail -k / | tail -1)
virgin_kb=$(( $(stat -c %s /bench/schelk-vols/er-joc-virgin.img) / 1024 ))
alloc_kb=$(du -k /bench/schelk-vols/er-joc-virgin.img | cut -f1)
need_kb=$(( virgin_kb - alloc_kb + 500 * 1024 * 1024 ))
[ "$free_kb" -ge "$need_kb" ] || fail "disk gate: free ${free_kb} KiB < need ${need_kb} KiB"

{
  echo "======== promote: $(date -Is) ========"
  time flock "$LOCK" sudo schelk promote -y --state-path "$STATE"
  flock "$LOCK" sudo schelk mount -y --state-path "$STATE"
  findmnt -n /schelk-er-joc
  sudo schelk status --state-path "$STATE"
  echo "virgin allocated: $(du -sh /bench/schelk-vols/er-joc-virgin.img | cut -f1)"
} >> "$LOG" 2>&1
[ -d "$DEST/chaindata" ] || fail "promote/remount: $DEST/chaindata missing"

/bench/erigon/tools/probe.sh joc
echo "rc=0" > "$DONE"
