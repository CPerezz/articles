#!/usr/bin/env bash
# Stages 3-5, re-run after a self-inflicted failure.
#
# BUG FIXED: the first attempt extracted into the mounted SCRATCH and went straight to the
# suite. benchmarkoor opens every run with `schelk restore`, which resets scratch from virgin --
# and virgin was the empty filesystem `init-new` had just created. The 1.1 TB extraction was
# discarded before the first test, and stages 4/5 then ran against an empty datadir.
# Extraction must be followed by `promote` so the extracted state IS the baseline.
#
# Also added: each stage refuses to start unless the previous one recorded rc=0, so a failure
# stops the chain instead of producing three runs of nothing.
set -uo pipefail

B=/root/bench
FILTER='regex:opcode_(BALANCE|CALL|EXTCODESIZE)-.*gas-value_(100|200|300)M'
TARBALL=/data/snapshots/besu/snapshot-24402727.tar.zst
JOC=/schelk/snapshots/besu/jochemnet/24402727
D="$JOC/database"

mark() { echo "$2" > "$B/stage$1.done"; }
log()  { echo "[$(date -Is)] $*"; }
gate() { [ "$(cat "$B/stage$1.done" 2>/dev/null)" = "rc=0" ] || { log "stage $1 did not succeed; stopping"; exit 1; }; }
census() { echo "sst=$(ls $D/*.sst 2>/dev/null | wc -l) sstB=$(du -cb $D/*.sst 2>/dev/null | tail -1 | cut -f1) walB=$(du -cb $D/*.log 2>/dev/null | tail -1 | cut -f1) blob=$(ls $D/*.blob 2>/dev/null | wc -l)"; }

mkcfg() {
  sed "s|results_dir: /data/bench-results/[a-z0-9-]*|results_dir: /data/bench-results/$2|" "$B/$1" > "$B/$2.yaml"
  sed -i "/      metadata:/i\\      filter: \"$FILTER\"" "$B/$2.yaml"
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

# ---------------------------------------------------------------- stage 3
log "STAGE 3: extract, PROMOTE, then replay pre-runs (PLAIN + noise floor)"
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
zstd -dc "$TARBALL" | tar -C "$JOC" -xf - || { mark 3 "rc=1 extract"; exit 1; }
log "extracted: $(du -sh "$JOC" | cut -f1)"
log "pristine  $(census)"
schelk promote -y 2>&1 | grep -vE 'Progress: ' | tail -3      # <-- the fix
schelk mount -y 2>&1 | tail -1
mkcfg besu-jochemnet.yaml s3-plain
run_suite s3-plain; mark 3 "rc=$?"
log "post-pre-run  $(census)"

# ---------------------------------------------------------------- stage 4
gate 3
log "STAGE 4: WAL drained, levels untouched"
schelk restore -y 2>&1 | grep -vE '^\s+[0-9]+ / |Progress: ' | tail -1
log "before  $(census)"
/home/CPerezz/rockscompact/rockscompact "$JOC" flush-only 2>&1 | tail -3
log "after   $(census)"
schelk promote -y 2>&1 | grep -vE 'Progress: ' | tail -3
schelk mount -y 2>&1 | tail -1
mkcfg besu-jochemnet.yaml s4-drained
run_suite s4-drained; mark 4 "rc=$?"

# ---------------------------------------------------------------- stage 5
gate 4
log "STAGE 5: drained + fully compacted"
schelk restore -y 2>&1 | grep -vE '^\s+[0-9]+ / |Progress: ' | tail -1
/home/CPerezz/rockscompact/rockscompact "$JOC" 2>&1 | tail -4
log "after   $(census)"
schelk promote -y 2>&1 | grep -vE 'Progress: ' | tail -3
schelk mount -y 2>&1 | tail -1
mkcfg besu-jochemnet.yaml s5-compacted
run_suite s5-compacted; mark 5 "rc=$?"

log "STAGES 3-5 COMPLETE"
