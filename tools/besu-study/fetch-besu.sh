#!/usr/bin/env bash
# Fetch the jochemnet Besu snapshot (block 24402727) and verify it.
#
# Mirrors the geth fetch: tarball lands on /data (HDD, plenty free) and is KEPT,
# so a re-extract never re-downloads. zstd frames carry content checksums, so
# `zstd -t` is the integrity check — upstream publishes no .sha256.
set -o pipefail

URL="https://snapshots.ethpandaops.io/jochemnet/besu/24402727/snapshot.tar.zst"
TARBALL=/data/snapshots/besu/snapshot-24402727.tar.zst
LOG=/root/bench/besu-fetch-$(date +%Y%m%d-%H%M%S).log
DONE=/root/bench/besu-fetch.done
EXPECTED_BYTES=1003259660471

mkdir -p "$(dirname "$TARBALL")" /root/bench
rm -f "$DONE"

{
  echo "======== besu snapshot fetch ========"
  echo "started  : $(date -Is)"
  echo "url      : $URL"
  echo "tarball  : $TARBALL"
  echo "expected : $EXPECTED_BYTES bytes"
  echo "free     : $(df -h /data | tail -1 | awk '{print $4}')"

  echo "-------- phase 1: download --------"
  # -c so a network blip resumes instead of restarting 1 TB.
  wget -c --progress=dot:giga -O "$TARBALL" "$URL"
  rc=$?
  echo "wget exit: $rc"

  got=$(stat -c %s "$TARBALL" 2>/dev/null || echo 0)
  echo "downloaded: $got bytes"
  if [ "$got" != "$EXPECTED_BYTES" ]; then
    echo "FATAL: size mismatch (want $EXPECTED_BYTES, got $got)"
    echo "rc=1" > "$DONE"; exit 1
  fi
  echo "size matches Content-Length"

  echo "-------- phase 2: integrity --------"
  zstd -t "$TARBALL"
  zrc=$?
  echo "zstd -t exit: $zrc"
  [ "$zrc" -ne 0 ] && { echo "FATAL: corrupt archive"; echo "rc=1" > "$DONE"; exit 1; }

  echo "-------- phase 3: top-level layout --------"
  zstd -dc "$TARBALL" | tar -t 2>/dev/null | head -40

  echo "finished : $(date -Is)"
  echo "free     : $(df -h /data | tail -1 | awk '{print $4}')"
  echo "rc=0" > "$DONE"
} 2>&1 | tee -a "$LOG"

echo "LOG: $LOG"
