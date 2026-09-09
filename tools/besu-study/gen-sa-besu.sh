#!/usr/bin/env bash
# Generate the Besu state-actor store — the companion arm for the Besu study.
#
# Mirrors the geth baseline (run-state-actor-baseline.sh) exactly: same spec,
# same seed, same target size, same fork, same gas limit, no --chain-id (so the
# default 1337 applies, as it did for geth). Only two things differ, and both
# are forced:
#   - --client=besu, and --db is the DATADIR ROOT (geth took .../geth/chaindata)
#   - it runs in a container: the besu writer is a cgo build against librocksdb
#     and the host binary refuses --client=besu outright.
set -o pipefail

IMG=state-actor-besu:latest
DB=/sa-besu/v1
SPEC=/home/CPerezz/state-actor-spec-baseline.yaml
SPILL=/sa-besu/spill
LOG=/home/CPerezz/sa-besu-$(date +%Y%m%d-%H%M%S).log
DONE=/home/CPerezz/sa-besu.done
mkdir -p "$DB" "$SPILL"
rm -f "$DONE"

{
  echo "======== state-actor besu baseline ========"
  echo "started   : $(date -Is)"
  echo "image     : $IMG ($(docker image inspect -f '{{.Id}}' $IMG 2>/dev/null))"
  echo "source    : e4cb205-dirty (30 erigon WIP files; go.mod reverted to HEAD)"
  echo "db        : $DB (datadir root)"
  echo "spec      : $SPEC"
  echo "free NVMe : $(df -h / | tail -1 | awk '{print $4}')"
  echo
  echo "command:"
  echo "  state-actor --db=/data --client=besu --target-size=350GB \\"
  echo "    --spec=/spec.yaml --seed=42 --fork=osaka --gas-limit=1000000000"
  echo "======== begin ========"

  time docker run --rm \
    -v "$DB":/data \
    -v "$SPEC":/spec.yaml:ro \
    -v "$SPILL":/spill \
    -e TMPDIR=/spill \
    "$IMG" \
    --db=/data \
    --client=besu \
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
  echo "free NVMe : $(df -h / | tail -1 | awk '{print $4}')"
  echo "--- artifacts geth's arm also had ---"
  ls -la "$DB" 2>/dev/null | head -10
  echo "rc=$rc" > "$DONE"
} 2>&1 | tee -a "$LOG"

echo "LOG: $LOG"
