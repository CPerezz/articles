#!/usr/bin/env bash
# Rebuild the CFs AND promote, so the per-test rollback preserves the change.
#
# The lesson that cost a 2.2 h run: `rollback_strategy: container-recreate` restores the volume
# from schelk's VIRGIN image before every test. A modification made on the mounted scratch volume
# is therefore discarded by test 1. `schelk promote` copies scratch -> virgin; without it the
# intervention silently does not exist during the run.
set -uo pipefail
LOG=/bench/logs/rebuild.log
JOC=/schelk-joc/snapshots/nethermind/24402727/mainnet/flat
{
  echo "=== started $(date -Is) ==="
  findmnt -n /schelk-joc >/dev/null 2>&1 || sudo schelk mount -y --state-path /var/lib/schelk/nm-joc.json

  echo "--- rebuild Account + StateNodes with state-actor's per-CF options ---"
  podman run --rm -v "$JOC":/db -v /tmp:/out localhost/sa-neth-builder:latest \
    /out/probe-flat -db /db -cf Account,StateNodes -mode rebuild

  echo "--- promote scratch -> virgin ---"
  sudo schelk promote -y --state-path /var/lib/schelk/nm-joc.json
  sudo schelk mount -y --state-path /var/lib/schelk/nm-joc.json

  echo "--- verify the promoted image actually carries the rebuild ---"
  for cf in Account StateNodes; do
    podman run --rm -v "$JOC":/db:ro -v /tmp:/out localhost/sa-neth-builder:latest \
      /out/probe-flat -db /db -cf "$cf" -mode locate -n 10 | grep "CF total" | sed "s/^/  $cf /"
  done
  python3 /home/ubuntu/dumpopts.py Account | tail -17
  echo "=== finished $(date -Is) ==="
} > "$LOG" 2>&1
echo "rc=$?" > /bench/logs/rebuild.done
