#!/usr/bin/env bash
# Extract the jochemnet Nethermind snapshot into the mounted schelk scratch volume.
set -euo pipefail

TARBALL=/bench/snapshots/nethermind/snapshot-24402727.tar.zst
DEST=/schelk-joc/snapshots/nethermind/24402727

[ -f "$TARBALL" ] || { echo "FATAL: tarball missing"; exit 2; }
findmnt -n /schelk-joc >/dev/null || { echo "FATAL: /schelk-joc not mounted"; exit 2; }

echo "started : $(date -Is)"
echo "free    : $(df -h /schelk-joc | tail -1 | awk '{print $4}')"

mkdir -p "$DEST"
# -I zstd lets tar stream the 1.26 TB without a separate decompress pass.
tar -I zstd -xf "$TARBALL" -C "$DEST"
echo "tar exit: $?"

echo "finished: $(date -Is)"
echo "--- top level ---"
ls -1 "$DEST" | head -20
echo "--- db dirs under mainnet ---"
ls -1 "$DEST/mainnet" 2>/dev/null | head -20
echo "--- sizes ---"
du -sh "$DEST" | cut -f1
du -sh "$DEST"/mainnet/*/ 2>/dev/null | sort -rh | head -12
echo "free    : $(df -h /schelk-joc | tail -1 | awk '{print $4}')"
