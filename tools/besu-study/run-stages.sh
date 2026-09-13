#!/usr/bin/env bash
# Stages 2-5 of the mechanism study, run unattended.
#
#   2  state-actor restored to NVMe              -> account-read counters for the generated store
#   3  jochemnet re-extracted, pre-runs replayed -> PLAIN arm, and a repeat of the original
#                                                   untreated run (the noise floor we lacked)
#   4  same store, WAL drained, levels untouched -> isolates drain from compaction
#   5  same store, then fully compacted          -> completes the lineage
#
# Stages 3-5 share one extraction, so plain/drained/compacted differ ONLY by the treatment
# applied between them. That is the decomposition the geth study had (380 -> 272 -> 18.5) and
# this study so far lacked, because its treatment did flush and compact together.
#
# Each stage writes a marker; a failure stops the chain rather than cascading into runs whose
# inputs are wrong.
set -uo pipefail

B=/root/bench
FILTER='regex:opcode_(BALANCE|CALL|EXTCODESIZE)-.*gas-value_(100|200|300)M'
TARBALL=/data/snapshots/besu/snapshot-24402727.tar.zst
JOC=/schelk/snapshots/besu/jochemnet/24402727

mark() { echo "$2" > "$B/stage$1.done"; }
log()  { echo "[$(date -Is)] $*"; }

teardown() {
  umount /schelk 2>/dev/null || true
  for d in $(dmsetup ls 2>/dev/null | awk '{print $1}'); do dmsetup remove "$d" 2>/dev/null || true; done
  losetup -D 2>/dev/null || true
  rm -f /schelk-vols/*.img
  rm -rf /schelk/snapshots /schelk/state-actor 2>/dev/null || true
  log "teardown done, free: $(df -h / | tail -1 | awk '{print $4}')"
}

make_pair() {  # $1=prefix $2=size $3=dm-name
  truncate -s "$2" "/schelk-vols/$1-virgin.img"
  truncate -s "$2" "/schelk-vols/$1-scratch.img"
  V=$(losetup --find --show "/schelk-vols/$1-virgin.img")
  S=$(losetup --find --show "/schelk-vols/$1-scratch.img")
  schelk init-new -y --virgin "$V" --scratch "$S" --ramdisk /dev/ram0 \
    --mount-point /schelk --granularity 65536 --dm-era-name "$3" 2>&1 | grep -vE '^\s+[0-9]+ / ' | tail -2
  schelk mount -y 2>&1 | tail -1
}

mkcfg() {  # $1=src $2=name
  sed "s|results_dir: /data/bench-results/[a-z0-9-]*|results_dir: /data/bench-results/$2|" "$B/$1" > "$B/$2.yaml"
  sed -i "/      metadata:/i\\      filter: \"$FILTER\"" "$B/$2.yaml"
}

run_suite() {  # $1=cfgname
  rm -f "$B/$1-metrics.json"
  pkill -f scrape_besu.py 2>/dev/null || true
  setsid nohup "$B/scrape_besu.py" "$B/$1-metrics.json" >/dev/null 2>&1 </dev/null &
  benchmarkoor run --config "$B/$1.yaml" > "$B/$1.log" 2>&1
  rc=$?
  sleep 5; pkill -f scrape_besu.py 2>/dev/null || true
  log "$1 rc=$rc  $(grep -oE 'passed=[0-9]+ .*total=[0-9]+' "$B/$1.log" | tail -1)"
  return $rc
}

# ---------------------------------------------------------------- stage 2
log "STAGE 2: state-actor on NVMe"
teardown
make_pair besu-sa 640G besu_sa_era
mkdir -p /schelk/state-actor/v1
cp -a /data/sa-besu-archive/v1 /schelk/state-actor/v1/besu || { mark 2 "rc=1 copy"; exit 1; }
log "copied: $(du -sh /schelk/state-actor/v1/besu | cut -f1)"
schelk promote -y 2>&1 | grep -vE 'Progress: ' | tail -3
schelk mount -y 2>&1 | tail -1
mkcfg besu-state-actor.yaml s2-sa
run_suite s2-sa; mark 2 "rc=$?"

# ---------------------------------------------------------------- stage 3
log "STAGE 3: re-extract jochemnet, replay pre-runs (PLAIN + noise floor)"
teardown
make_pair besu-joc 1400G besu_joc_era
mkdir -p "$JOC"
zstd -dc "$TARBALL" | tar -C "$JOC" -xf - || { mark 3 "rc=1 extract"; exit 1; }
log "extracted: $(du -sh "$JOC" | cut -f1)"
D="$JOC/database"
log "pristine census: sst=$(ls $D/*.sst 2>/dev/null | wc -l) walB=$(du -cb $D/*.log 2>/dev/null | tail -1 | cut -f1) blob=$(ls $D/*.blob 2>/dev/null | wc -l)"
mkcfg besu-jochemnet.yaml s3-plain
run_suite s3-plain; mark 3 "rc=$?"
log "post-pre-run census: sst=$(ls $D/*.sst 2>/dev/null | wc -l) walB=$(du -cb $D/*.log 2>/dev/null | tail -1 | cut -f1)"

# ---------------------------------------------------------------- stage 4
log "STAGE 4: WAL drained, levels untouched"
schelk restore -y 2>&1 | grep -vE '^\s+[0-9]+ / |Progress: ' | tail -1
log "before: sst=$(ls $D/*.sst | wc -l) walB=$(du -cb $D/*.log 2>/dev/null | tail -1 | cut -f1)"
/home/CPerezz/rockscompact/rockscompact "$JOC" flush-only 2>&1 | tail -3
log "after:  sst=$(ls $D/*.sst | wc -l) walB=$(du -cb $D/*.log 2>/dev/null | tail -1 | cut -f1)"
schelk promote -y 2>&1 | grep -vE 'Progress: ' | tail -3
schelk mount -y 2>&1 | tail -1
mkcfg besu-jochemnet.yaml s4-drained
run_suite s4-drained; mark 4 "rc=$?"

# ---------------------------------------------------------------- stage 5
log "STAGE 5: drained + fully compacted"
schelk restore -y 2>&1 | grep -vE '^\s+[0-9]+ / |Progress: ' | tail -1
/home/CPerezz/rockscompact/rockscompact "$JOC" 2>&1 | tail -4
log "after:  sst=$(ls $D/*.sst | wc -l) walB=$(du -cb $D/*.log 2>/dev/null | tail -1 | cut -f1)"
schelk promote -y 2>&1 | grep -vE 'Progress: ' | tail -3
schelk mount -y 2>&1 | tail -1
mkcfg besu-jochemnet.yaml s5-compacted
run_suite s5-compacted; mark 5 "rc=$?"

log "ALL STAGES COMPLETE"
