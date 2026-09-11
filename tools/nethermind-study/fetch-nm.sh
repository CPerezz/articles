#!/usr/bin/env bash
# Fetch the jochemnet Nethermind snapshot (block 24402727) and verify it.
#
# Retry policy is not optional: the Besu fetch died at 72% with "Connection closed ... Giving
# up" (wget exit 4) and the resumed run logged (try: 7). Over a ~5 hour transfer the far end
# drops the connection repeatedly.
set -o pipefail

URL="https://snapshots.ethpandaops.io/jochemnet/nethermind/24402727/snapshot.tar.zst"
TARBALL=/bench/snapshots/nethermind/snapshot-24402727.tar.zst
LOG=/bench/logs/nm-fetch-$(date +%Y%m%d-%H%M%S).log
DONE=/bench/logs/nm-fetch.done
EXPECTED_BYTES=1261351401168

mkdir -p "$(dirname "$TARBALL")" /bench/logs
rm -f "$DONE"

{
  echo "======== nethermind snapshot fetch ========"
  echo "started  : $(date -Is)"
  echo "url      : $URL"
  echo "expected : $EXPECTED_BYTES bytes"
  echo "free     : $(df -h / | tail -1 | awk '{print $4}')"

  echo "-------- phase 1: download --------"
  wget -c --progress=dot:giga \
       --tries=0 --retry-connrefused --waitretry=10 \
       --timeout=60 --read-timeout=120 \
       -O "$TARBALL" "$URL"
  echo "wget exit: $?"

  got=$(stat -c %s "$TARBALL" 2>/dev/null || echo 0)
  echo "downloaded: $got bytes"
  if [ "$got" != "$EXPECTED_BYTES" ]; then
    echo "FATAL: size mismatch (want $EXPECTED_BYTES, got $got)"
    echo "rc=1" > "$DONE"; exit 1
  fi
  echo "size matches Content-Length"

  echo "-------- phase 2: integrity --------"
  # zstd frames carry content checksums; upstream publishes no .sha256.
  zstd -t "$TARBALL"
  zrc=$?
  echo "zstd -t exit: $zrc"
  [ "$zrc" -ne 0 ] && { echo "FATAL: corrupt archive"; echo "rc=1" > "$DONE"; exit 1; }

  echo "-------- phase 3: top-level layout --------"
  zstd -dc "$TARBALL" | tar -t 2>/dev/null | head -30

  echo "finished : $(date -Is)"
  echo "free     : $(df -h / | tail -1 | awk '{print $4}')"
  echo "rc=0" > "$DONE"
} 2>&1 | tee -a "$LOG"

echo "LOG: $LOG"
