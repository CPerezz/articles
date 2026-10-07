#!/usr/bin/env bash
# Round 14: where every code value sits in each store's code file, read-only (compactlatest codespan).
# jochemnet's file is the staging copy the rebuild promoted; state-actor's is the generated store's
# raw copy, the bytes its promoted image carries. Neither touches a schelk scratch.
# Usage: sudo codespan.sh <tag> [joc-kv] [sa-kv]      Never beside a suite (.busy).
set -uo pipefail

TAG="${1:?tag}"
C=/bench/erigon/compact
L=/bench/erigon/logs
JOC=${2:-$C/staging/v2.0-code.0-1.kv}
SA=${3:-/bench/erigon/sa-store/snapshots/domain/v1.0-code.0-1.kv}
BUSY=/bench/erigon/.busy
DONE=$L/codespan-$TAG.done
FAIL=$L/codespan-$TAG.fail

rm -f "$DONE" "$FAIL"
cd /
fail() { echo "FAIL $1" >> "$L/codespan-$TAG.log"; echo "$1" > "$FAIL"; exit 1; }
while [ -f "$BUSY" ] || pgrep -x benchmarkoor >/dev/null; do sleep 60; done
echo "codespan-$TAG" > "$BUSY"
trap 'rm -f "$BUSY"' EXIT

span() { # arm kv
  podman run --rm -v /bench/erigon:/bench/erigon docker.io/library/golang:1.25-bookworm \
    "$C/bin/compactlatest" codespan --kv "$2" --fixtures "$C/codespan-$1-$TAG.tsv" \
    > "$C/codespan-$1-$TAG.json" 2> "$L/codespan-$1-$TAG.log"
}
span joc "$JOC" & a=$!
span sa "$SA" & b=$!
wait $a || fail "joc"
wait $b || fail "sa"
echo "rc=0" > "$DONE"
