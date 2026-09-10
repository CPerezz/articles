#!/usr/bin/env bash
# Tear down the state-actor schelk pair and build the jochemnet one in its place.
#
# Sequencing is forced by space: NVMe is 3.5 T and the two arms cannot both be resident
# (SA pair ~1.28 T + jochemnet pair ~2.5 T). The SA store survives at /data/sa-besu-archive.
#
# Run ONLY after the state-actor suite has finished — it destroys that arm's volumes.
set -euo pipefail

TARBALL=/data/snapshots/besu/snapshot-24402727.tar.zst
DEST=/schelk/snapshots/besu/jochemnet/24402727
IMG_V=/schelk-vols/besu-joc-virgin.img
IMG_S=/schelk-vols/besu-joc-scratch.img
SIZE=1400G
LOG=/root/bench/joc-build-$(date +%Y%m%d-%H%M%S).log
DONE=/root/bench/joc-build.done
rm -f "$DONE"

{
  echo "======== jochemnet arm build ========"
  echo "started : $(date -Is)"

  echo "-------- 1. tear down the state-actor pair --------"
  # promote already unmounts, but a suite leaves it mounted; be idempotent.
  umount /schelk 2>/dev/null || true
  dmsetup remove besu_sa_era 2>/dev/null || true
  losetup -D 2>/dev/null || true
  rm -f /schelk-vols/besu-sa-virgin.img /schelk-vols/besu-sa-scratch.img
  # Strays under the mountpoint would be shadowed and silently waste root-fs space.
  rm -rf /schelk/snapshots /schelk/state-actor 2>/dev/null || true
  echo "free after teardown: $(df -h / | tail -1 | awk '{print $4}')"

  echo "-------- 2. create the jochemnet pair --------"
  truncate -s "$SIZE" "$IMG_V"
  truncate -s "$SIZE" "$IMG_S"
  V=$(losetup --find --show "$IMG_V")
  S=$(losetup --find --show "$IMG_S")
  echo "virgin=$V scratch=$S"
  schelk init-new -y --virgin "$V" --scratch "$S" --ramdisk /dev/ram0 \
    --mount-point /schelk --granularity 65536 --dm-era-name besu_joc_era 2>&1 \
    | grep -vE "^\s+[0-9]+ / " | tail -5
  schelk mount -y 2>&1 | tail -2

  echo "-------- 3. extract --------"
  mkdir -p "$DEST"
  # zstd frames carry checksums and the archive already passed `zstd -t`, so a clean exit
  # here is the second integrity check as well as the extraction.
  time zstd -dc "$TARBALL" | tar -C "$DEST" -xf -
  echo "extracted: $(du -sh "$DEST" | cut -f1)"
  echo "top level:"; ls "$DEST" | head -12

  echo "-------- 4. pristine census (BEFORE any besu opens it) --------"
  # The WAL is the leading P2 candidate; opening the store replays and clears it, so this
  # census must happen before any `besu storage` subcommand touches the datadir.
  D="$DEST/database"
  echo "sst files : $(ls $D/*.sst  2>/dev/null | wc -l)"
  echo "blob files: $(ls $D/*.blob 2>/dev/null | wc -l)"
  echo "wal  files: $(ls $D/*.log  2>/dev/null | wc -l)"
  echo "sst bytes : $(du -cb $D/*.sst  2>/dev/null | tail -1 | cut -f1)"
  echo "blob bytes: $(du -cb $D/*.blob 2>/dev/null | tail -1 | cut -f1)"
  echo "wal bytes : $(du -cb $D/*.log  2>/dev/null | tail -1 | cut -f1)"
  echo "caches    : $(ls $DEST/caches 2>/dev/null | wc -l) files, $(du -sh $DEST/caches 2>/dev/null | cut -f1)"

  echo "-------- 5. promote --------"
  schelk promote -y 2>&1 | grep -vE "Progress: " | tail -6

  echo "finished: $(date -Is)"
  echo "free    : $(df -h / | tail -1 | awk '{print $4}')"
  echo "rc=0" > "$DONE"
} 2>&1 | tee -a "$LOG"

echo "LOG: $LOG"
