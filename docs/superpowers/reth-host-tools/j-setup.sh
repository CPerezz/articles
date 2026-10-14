#!/bin/bash
# Reth jochemnet schelk pair: scratch on md2 NVMe (benchmark reads), virgin on md3 HDD (restores/promotes).
# Loops are attached explicitly: loop0/loop1 kept a read-only flag from the Besu schelk virgins.
set -x
LV=$(losetup -j /data/schelk-vols/reth-joc-virgin.img | cut -d: -f1); LS=$(losetup -j /schelk-vols/reth-joc-scratch.img | cut -d: -f1)
echo "virgin=$LV ro=$(blockdev --getro $LV) scratch=$LS ro=$(blockdev --getro $LS)"
[ "$(blockdev --getro $LV)$(blockdev --getro $LS)" = "00" ] || { echo "a loop is read-only"; exit 1; }
time schelk -y init-new --virgin $LV --scratch $LS --ramdisk /dev/ram0 --mount-point /schelk-joc --granularity 65536 --dm-era-name reth_joc_era --state-path /var/lib/schelk/reth-joc.json || exit 1
time schelk -y mount --state-path /var/lib/schelk/reth-joc.json --state-path /var/lib/schelk/reth-joc.json 2>/dev/null || time schelk -y --state-path /var/lib/schelk/reth-joc.json mount
df -h /schelk-joc; losetup -l; dmsetup ls
echo J-SETUP-DONE
