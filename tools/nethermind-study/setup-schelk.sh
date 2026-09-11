#!/usr/bin/env bash
# Build one schelk instance (virgin+scratch pair, dm-era tracked, mounted).
#
# Two instances coexist on this box so both arms stay hot for on-demand benchmarking. schelk
# keeps per-instance state in its own file, so each needs a distinct --state-path,
# --dm-era-name, --ramdisk and mount point. Sharing any of those silently corrupts the other.
#
# Usage: setup-schelk.sh <name> <ramdisk> <mount> <size>
#   e.g. setup-schelk.sh nm-joc /dev/ram0 /schelk-joc 1600G
set -euo pipefail

NAME="${1:?usage: setup-schelk.sh <name> <ramdisk> <mount> <size>}"
RAMDISK="${2:?}"
MOUNT="${3:?}"
SIZE="${4:?}"

VOLS=/bench/schelk-vols
VIRGIN="$VOLS/$NAME-virgin.img"
SCRATCH="$VOLS/$NAME-scratch.img"
STATE="/var/lib/schelk/$NAME.json"

sudo mkdir -p "$VOLS" "$MOUNT" /var/lib/schelk

# Sparse: the images cost nothing until written. schelk's clone is NOT sparse-aware, so scratch
# becomes fully allocated during init; virgin stays sparse until the first promote.
[ -f "$VIRGIN" ]  || sudo truncate -s "$SIZE" "$VIRGIN"
[ -f "$SCRATCH" ] || sudo truncate -s "$SIZE" "$SCRATCH"

V=$(losetup --list --output NAME,BACK-FILE | awk -v f="$VIRGIN"  '$2==f{print $1}' | head -1)
S=$(losetup --list --output NAME,BACK-FILE | awk -v f="$SCRATCH" '$2==f{print $1}' | head -1)
[ -n "$V" ] || V=$(sudo losetup --find --show "$VIRGIN")
[ -n "$S" ] || S=$(sudo losetup --find --show "$SCRATCH")

echo "instance : $NAME"
echo "virgin   : $VIRGIN -> $V"
echo "scratch  : $SCRATCH -> $S"
echo "ramdisk  : $RAMDISK"
echo "mount    : $MOUNT"
echo "state    : $STATE"

# 65536 granularity matches the geth/besu studies, so dm-era block accounting is comparable.
sudo schelk init-new -y \
  --virgin "$V" --scratch "$S" --ramdisk "$RAMDISK" \
  --mount-point "$MOUNT" --granularity 65536 \
  --dm-era-name "${NAME//-/_}_era" --state-path "$STATE"

sudo schelk mount -y --state-path "$STATE"
df -h "$MOUNT" | tail -1
