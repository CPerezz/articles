#!/usr/bin/env bash
# Measure physical bytes per account point-lookup in each arm's flat DB.
# Isolated from Nethermind and from benchmarkoor: same key count, same random access pattern,
# fresh process per probe, page cache dropped first.
set -uo pipefail

IMG=sa-neth-builder:latest
SA=/schelk-sa/state-actor/v1/nethermind/flat
JOC=/schelk-joc/snapshots/nethermind/24402727/mainnet/flat
N=${1:-5000}
CF=${2:-Account}

run() { # run <label> <dbpath> <args...>
  local lbl=$1 db=$2; shift 2
  sudo podman run --rm -v "$db":/db:ro -v /tmp:/out "$IMG" \
    /out/probe-flat -db /db -cf "$CF" "$@"
}

echo "######## sampling $N random keys from cf=$CF ########"
run sa  "$SA"  -mode sample -n "$N" -keys /out/k-sa.bin
run joc "$JOC" -mode sample -n "$N" -keys /out/k-joc.bin

for arm in sa joc; do
  echo
  echo "######## probing $arm (caches dropped, fresh process) ########"
  sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null; sleep 2
  if [ "$arm" = sa ]; then run sa "$SA" -mode probe -keys /out/k-sa.bin
  else                     run joc "$JOC" -mode probe -keys /out/k-joc.bin; fi
done
