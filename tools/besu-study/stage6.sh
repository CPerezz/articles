#!/usr/bin/env bash
# Stage 6: the WAL-drained, levels-untouched arm -- gap A, third attempt.
#
# Attempt 1 died because the extraction was never promoted (round 25).
# Attempt 2 died because `rockscompact` hardcoded its java arguments and dropped the
# `flush-only` mode, so the stage ran a 90-minute full compaction instead (round 26).
#
# Both failures shared a shape: the stage *looked* like it worked. So this one asserts its own
# precondition -- flush-only must leave the SST count essentially unchanged while draining the
# WAL -- and refuses to run the suite otherwise.
set -uo pipefail

B=/root/bench
FILTER='regex:opcode_(BALANCE|CALL|EXTCODESIZE)-.*gas-value_(100|200|300)M'
SEED_FILTER='regex:opcode_BALANCE-value_sent_0-account_mode_AccountMode.EXISTING_CONTRACT_MINIMAL-.*gas-value_100M'
TARBALL=/data/snapshots/besu/snapshot-24402727.tar.zst
JOC=/schelk/snapshots/besu/jochemnet/24402727
D="$JOC/database"

log() { echo "[$(date -Is)] $*"; }
ssts() { ls $D/*.sst 2>/dev/null | wc -l; }
walb() { du -cb $D/*.log 2>/dev/null | tail -1 | cut -f1; }
census() { echo "sst=$(ssts) sstB=$(du -cb $D/*.sst 2>/dev/null | tail -1 | cut -f1) walB=$(walb)"; }

mkcfg() {
  sed "s|results_dir: /data/bench-results/[a-z0-9-]*|results_dir: /data/bench-results/$2|" "$B/besu-jochemnet.yaml" > "$B/$2.yaml"
  sed -i "/      metadata:/i\\      filter: \"$3\"" "$B/$2.yaml"
}

run_suite() {
  rm -f "$B/$1-metrics.json"
  pkill -f "scrape_bes[u]" 2>/dev/null || true
  setsid nohup "$B/scrape_besu.py" "$B/$1-metrics.json" >/dev/null 2>&1 </dev/null &
  benchmarkoor run --config "$B/$1.yaml" > "$B/$1.log" 2>&1
  local rc=$?
  sleep 5; pkill -f "scrape_bes[u]" 2>/dev/null || true
  log "$1 rc=$rc $(grep -oE 'passed=[0-9]+ .*total=[0-9]+' "$B/$1.log" | tail -1)"
  return $rc
}

log "rebuild volumes and extract"
umount /schelk 2>/dev/null || true
for d in $(dmsetup ls 2>/dev/null | awk '{print $1}'); do dmsetup remove "$d" 2>/dev/null || true; done
losetup -D 2>/dev/null || true
rm -f /schelk-vols/*.img
truncate -s 1400G /schelk-vols/besu-joc-virgin.img
truncate -s 1400G /schelk-vols/besu-joc-scratch.img
V=$(losetup --find --show /schelk-vols/besu-joc-virgin.img)
S=$(losetup --find --show /schelk-vols/besu-joc-scratch.img)
schelk init-new -y --virgin "$V" --scratch "$S" --ramdisk /dev/ram0 \
  --mount-point /schelk --granularity 65536 --dm-era-name besu_joc_era 2>&1 | grep -vE '^\s+[0-9]+ / ' | tail -1
schelk mount -y 2>&1 | tail -1
mkdir -p "$JOC"
zstd -dc "$TARBALL" | tar -C "$JOC" -xf - || { echo "rc=1 extract" > "$B/stage6.done"; exit 1; }
log "extracted $(census)"
schelk promote -y 2>&1 | grep -vE 'Progress: ' | tail -2
schelk mount -y 2>&1 | tail -1

log "seed run: replay pre-runs and promote (1 test)"
mkcfg besu-jochemnet.yaml s6-seed "$SEED_FILTER"
run_suite s6-seed || true

log "restore the promoted plain image"
schelk restore -y 2>&1 | grep -vE '^\s+[0-9]+ / |Progress: ' | tail -1
BEFORE_SST=$(ssts); BEFORE_WAL=$(walb)
log "before  sst=$BEFORE_SST walB=$BEFORE_WAL"
[ "$BEFORE_WAL" -gt 100000000 ] || { log "FATAL: expected a multi-hundred-MB WAL, got $BEFORE_WAL"; echo "rc=1 no-wal" > "$B/stage6.done"; exit 1; }

log "flush-only"
/home/CPerezz/rockscompact/rockscompact "$JOC" flush-only 2>&1 | tail -4
AFTER_SST=$(ssts); AFTER_WAL=$(walb)
log "after   sst=$AFTER_SST walB=$AFTER_WAL"

# The whole point of this arm: WAL gone, levels untouched. A full compaction would drop the
# SST count by ~1,200; anything beyond a small delta means the mode was ignored again.
DELTA=$(( BEFORE_SST > AFTER_SST ? BEFORE_SST - AFTER_SST : AFTER_SST - BEFORE_SST ))
[ "$DELTA" -lt 200 ] || { log "FATAL: SST count moved by $DELTA -- this was not flush-only"; echo "rc=1 compacted" > "$B/stage6.done"; exit 1; }
[ "$AFTER_WAL" -lt 1000000 ] || { log "FATAL: WAL still $AFTER_WAL -- flush did not drain"; echo "rc=1 wal-remains" > "$B/stage6.done"; exit 1; }
log "PRECONDITION OK: WAL drained, SST count moved by $DELTA"

schelk promote -y 2>&1 | grep -vE 'Progress: ' | tail -2
schelk mount -y 2>&1 | tail -1
mkcfg besu-jochemnet.yaml s6-drained "$FILTER"
run_suite s6-drained; echo "rc=$?" > "$B/stage6.done"
log "STAGE 6 COMPLETE"
