#!/usr/bin/env bash
# Generate the Nethermind state-actor store — the generated-state arm.
#
# Identical parameters to the geth and besu baselines: same spec, same seed, same target size,
# same fork, same gas limit, no --chain-id (default 1337). Only --client and the container
# differ. The nethermind writer, like besu's, is a cgo build and ships only as an image.
set -o pipefail

IMG=localhost/state-actor-nethermind:latest
DB=/bench/nm-store/v1
SPEC=/home/ubuntu/state-actor-spec-baseline.yaml
SPILL=/bench/nm-store/spill
LOG=/bench/logs/sa-nm-$(date +%Y%m%d-%H%M%S).log
DONE=/bench/logs/sa-nm.done

mkdir -p "$DB" "$SPILL" /bench/logs
rm -f "$DONE"

{
  echo "======== state-actor nethermind baseline ========"
  echo "started   : $(date -Is)"
  echo "image     : $IMG ($(podman image inspect -f '{{.Id}}' $IMG 2>/dev/null | head -c 20))"
  echo "source    : e4cb205-dirty (30 erigon WIP files; go.mod reverted to HEAD)"
  echo "db        : $DB (datadir root)"
  echo "free      : $(df -h / | tail -1 | awk '{print $4}')"
  echo "======== begin ========"

  time podman run --rm \
    -v "$DB":/data \
    -v "$SPEC":/spec.yaml:ro \
    -v "$SPILL":/spill \
    -e TMPDIR=/spill \
    "$IMG" \
    --db=/data \
    --client=nethermind \
    --target-size=350GB \
    --spec=/spec.yaml \
    --seed=42 \
    --fork=osaka \
    --gas-limit=1000000000 \
    --verbose
  rc=$?

  echo "======== end ========"
  echo "exit code : $rc"
  echo "finished  : $(date -Is)"
  echo "db size   : $(du -sh "$DB" 2>/dev/null | cut -f1)"
  echo "spill left: $(du -sh "$SPILL" 2>/dev/null | cut -f1)"
  echo "free      : $(df -h / | tail -1 | awk '{print $4}')"
  echo "--- per-database sizes (nethermind splits into separate rocksdb dirs) ---"
  du -sh "$DB"/*/ 2>/dev/null
  echo "rc=$rc" > "$DONE"
} 2>&1 | tee -a "$LOG"

echo "LOG: $LOG"
