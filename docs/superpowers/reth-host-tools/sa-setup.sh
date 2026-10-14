#!/bin/bash
# After generation: G1 identity gate, then move the store into an HDD virgin and adopt it with schelk
# (scratch on md2 NVMe, like the jochemnet pair). The store is never booted before it is the virgin.
set -u
L=/root/bench/reth/logs
# reth's generator logs the state root but not the genesis hash; the hash is checked at boot
# (baseline.sh, eth_getBlockByNumber 0x0 must equal the Nethermind v2 genesis 0x0cb03528...).
until grep -q "^exit code" $L/gen.log; do sleep 60; done
grep -q "^exit code : 0" $L/gen.log || { echo "generation failed"; exit 1; }
SR=$(grep -aoiE "state root *[=:] *0x[0-9a-f]{64}" $L/gen.log | tail -1 | grep -oE "0x[0-9a-f]{64}")
echo "root=$SR"
if [ "$SR" = "0x48d611bb839188317e983453705b31e1420b2c4416675f98d776ad8e130d51b8" ]; then echo G1-ROOT-PASS; else echo G1-FAIL; exit 1; fi
ls -la /sa-gen; du -sh /sa-gen/* /sa-gen/db/* 2>/dev/null
X=$(du -sb /sa-gen | cut -f1); N=$(find /sa-gen -type f | wc -l)
S=$(( (X * 13 / 10 + 50 * 1024 ** 3) / 1024 ** 3 + 1 ))
echo "store bytes=$X files=$N image=${S}G"

# 1. virgin on md3 HDD, populated directly
truncate -s ${S}G /data/schelk-vols/reth-sa-virgin.img
LV=$(losetup -f --show /data/schelk-vols/reth-sa-virgin.img); blockdev --setrw $LV
[ "$(blockdev --getro $LV)" = "0" ] || { echo "virgin loop $LV is read-only"; exit 1; }
mkfs.ext4 -F -q $LV || exit 1
mkdir -p /mnt/sa-virgin && mount $LV /mnt/sa-virgin && mkdir -p /mnt/sa-virgin/reth
echo "copy to virgin start $(date -Is)"
time cp -a /sa-gen/. /mnt/sa-virgin/reth/ || exit 1
sync
X2=$(du -sb /mnt/sa-virgin/reth | cut -f1); N2=$(find /mnt/sa-virgin/reth -type f | wc -l)
echo "virgin bytes=$X2 files=$N2"
cmp -s /sa-gen/chainspec.json /mnt/sa-virgin/reth/chainspec.json && [ "$N2" = "$N" ] && [ "$X2" = "$X" ] || { echo "copy mismatch"; exit 1; }
umount /mnt/sa-virgin

# 2. free NVMe, then the scratch on md2 NVMe cloned from the virgin
rm -rf /sa-gen
truncate -s ${S}G /schelk-vols/reth-sa-scratch.img
LS=$(losetup -f --show /schelk-vols/reth-sa-scratch.img); blockdev --setrw $LS
echo "virgin=$LV scratch=$LS"
time schelk -y init-from --virgin $LV --scratch $LS --ramdisk /dev/ram1 --mount-point /schelk-sa --fstype ext4 \
  --granularity 65536 --dm-era-name reth_sa_era --state-path /var/lib/schelk/reth-sa.json || exit 1
SCHELK_STATE=/var/lib/schelk/reth-sa.json schelk -y mount || exit 1
mountpoint /schelk-sa && ls -la /schelk-sa/reth && du -sh /schelk-sa/reth
df -h / /data /schelk-sa
echo SA-SETUP-DONE
