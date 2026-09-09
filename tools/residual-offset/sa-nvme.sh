#!/usr/bin/env bash
# Restore the state-actor store to NVMe so it can be compared against
# jochemnet on the same physical device. The surviving copy lives on md3 (the
# HDD array); every measurement so far had to work around that.
#
# Same stack as jochemnet deliberately: a loop-backed ext4 image on md2.
set -o pipefail
LOG=/root/bench/sa-nvme.log
IMG=/schelk-vols/sa-nvme.img
MNT=/mnt/sa-nvme
SRC=/data/sa-store/state-actor/v1/geth
log() { echo "$(date -Is) | $*" | tee -a "$LOG"; }

rm -f /root/bench/sa-nvme.done
log "free before: $(df -h / | tail -1 | awk '{print $4}')"

log "allocating $IMG"
fallocate -l 600G "$IMG" || { log "FATAL fallocate"; exit 1; }

# mkfs issues discards which the loop device passes through, punching holes in
# the backing file - that is how a previous run ended up thin-provisioned and
# would have hit ENOSPC mid-benchmark. Disable discard, then re-reserve.
log "mkfs (nodiscard)"
mkfs.ext4 -q -F -m 0 -E nodiscard "$IMG" || { log "FATAL mkfs"; exit 1; }
fallocate -l 600G "$IMG"
log "actual allocation: $(du -sh --apparent-size=never $IMG | cut -f1)"

LOOP=$(losetup -f --show "$IMG") || { log "FATAL losetup"; exit 1; }
log "loop: $LOOP"
mkdir -p "$MNT"
mount -o noatime "$LOOP" "$MNT" || { log "FATAL mount"; exit 1; }

log "rsync $SRC -> $MNT (551 G from HDD)"
rsync -aHAX --numeric-ids --info=progress2 "$SRC/" "$MNT/" 2>&1 | tail -3 | tee -a "$LOG"
RC=$?
sync
log "rsync rc=$RC"

log "verifying (dry-run diff must be empty)"
DIFF=$(rsync -aHAX --numeric-ids --itemize-changes --dry-run "$SRC/" "$MNT/" | head -5)
log "diff: ${DIFF:-<none>}"
log "file counts: src=$(find $SRC -type f | wc -l) dst=$(find $MNT -type f | wc -l)"
log "sizes: src=$(du -sh $SRC | cut -f1) dst=$(du -sh $MNT | cut -f1)"
log "free after: $(df -h / | tail -1 | awk '{print $4}')"
echo "$RC" > /root/bench/sa-nvme.done
log "DONE"
