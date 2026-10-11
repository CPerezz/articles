#!/usr/bin/env bash
# Round 15, point 2: re-encode state-actor's commitment, storage and accounts files the way Erigon
# writes its own, check they answer exactly as before, promote, smoke, trace (T4), then run the I
# pairs. Round 14 did the code file. state-actor's generator writes every file at format version
# v1.0 with raw keys; Erigon 5f62f4ed compresses storage and commitment keys against a pattern
# dictionary (state_schema.go:229, :274) and writes storage .kv/.bt v2.0, commitment .kv v2.2, .kvi
# v2.1 and .kvei v1.2. Accounts aren't compressed, but their .kv/.bt/.kvei versions differ too.
#
# Only the encoding changes: same keys, same values, same step. Each new file's (key, value) stream
# must hash like the old one's, read through the domain's own reader, and eth_getBalance,
# eth_getStorageAt and eth_getProof (which walks the commitment trie) must answer byte for byte the
# same.
#
# The domains run one after the other, largest first: the compressor keeps a raw copy of every word
# and its dictionary candidates in temp space (2.5x the commitment file at e2e scale), so the peak
# is ~0.7 TB during the commitment recode; the rootfs has ~1.24 TB free.
#
# One-way for the promoted image (/bench/erigon/sa-store was deleted on 2026-10-11 with Anon's ok).
# Usage: sudo recode-sa-domains.sh      Never beside a suite (.busy).
set -uo pipefail

IMG=docker.io/ethpandaops/erigon:glamsterdam-devnet-7
GO_IMG=docker.io/library/golang:1.25-bookworm
STATE=/var/lib/schelk/er-sa.json
MNT=/schelk-er-sa
DATA=$MNT/erigon
C=/bench/erigon/compact
S=$C/staging-sc
L=/bench/erigon/logs
LOG=$L/recode-sa-domains.log
DONE=$L/recode-sa-domains.done
FAIL=$L/recode-sa-domains.fail
BUSY=/bench/erigon/.busy
LOCK=/bench/erigon/.schelk.lock
PORT=18546
DOMAINS="commitment storage accounts"
# ~2,100 RPC samples each for storage (2.1 B keys) and accounts (429 M); commitment's go unused.
declare -A EVERY=([commitment]=1000000 [storage]=1000000 [accounts]=200000)

rm -f "$DONE" "$FAIL"
cd /
exec >> "$LOG" 2>&1
# uid 1000 like erigon: a root-owned LOCK or temp dir in the datadir would stop the node booting.
tool() { podman run --rm --user 1000:1000 -e HOME=/tmp -v "$C":"$C" -v "$MNT":"$MNT" "$GO_IMG" "$C/bin/$@"; }
fail() { echo "FAIL $1 ($(date -Is))"; echo "$1" > "$FAIL"; exit 1; }
step() { echo; echo "======== $1: $(date -Is) ========"; }
sha() { python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]]['sha256'])" "$@"; }

while [ -f "$BUSY" ] || pgrep -x benchmarkoor >/dev/null; do sleep 60; done
echo "recode-sa-sc" > "$BUSY"
trap 'podman rm -f er-recode-probe >/dev/null 2>&1; rm -f "$BUSY"' EXIT

boot() { # boot erigon with the benchmark's flags on the current scratch and wait for RPC
  podman rm -f er-recode-probe >/dev/null 2>&1
  podman run -d --name er-recode-probe -p "127.0.0.1:$PORT:8545" -v "$DATA":/data \
    -v /bench/erigon/probe/jwtsecret:/tmp/jwtsecret:ro "$IMG" \
    --datadir=/data --nat=none --maxpeers=0 --txpool.disable --nodiscover --no-downloader \
    --http --http.addr=0.0.0.0 --http.port=8545 --http.vhosts='*' --http.api=eth,net,debug \
    --authrpc.jwtsecret=/tmp/jwtsecret --prune.mode=full --log.dir.disable --externalcl \
    --exec.no-merge=true --exec.no-prune=true --exec.no-background-maintenance \
    --experimental.parallel-commitment --override.amsterdam=1 >/dev/null
  for _ in $(seq 1 720); do
    curl -s -m 5 -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' \
      "http://127.0.0.1:$PORT" | grep -q result && return 0
    podman container exists er-recode-probe || break
    sleep 5
  done
  podman logs er-recode-probe 2>&1 | tail -30
  return 1
}
halt() { podman logs er-recode-probe > "$C/erigon-sa-sc-$1.log" 2>&1; podman stop -t 600 er-recode-probe >/dev/null; podman rm er-recode-probe >/dev/null; }

step "restore scratch"
flock "$LOCK" schelk restore -y --state-path "$STATE" || fail "restore"
findmnt -n "$MNT" || fail "not mounted"
[ "$(df --output=avail -BG / | tail -1 | tr -dc 0-9)" -ge 900 ] || fail "rootfs needs 900 GB free"
rm -rf "$S" "$C/tmp-sc" && mkdir -p "$S" "$C/tmp-sc" && chown 1000:1000 "$S" "$C/tmp-sc"

for d in $DOMAINS; do
  OLD=$(ls "$DATA"/snapshots/domain/v*-$d.0-1.kv)
  [ "$(echo "$OLD" | wc -l)" = 1 ] || fail "expected one $d .kv, found: $OLD"
  step "stream hash of the old $d file"
  time tool compactlatest streamhash --domain "$d" --datadir "$DATA" --kv "$OLD" > "$C/streamhash-sa-$d-old.json" || fail "old streamhash $d"
  cat "$C/streamhash-sa-$d-old.json"
  step "recode $d (read-only on the scratch)"
  mkdir -p "$S/$d" && chown 1000:1000 "$S/$d"
  time tool compactlatest recode --domain "$d" --datadir "$DATA" --dst "$S/$d" --tmp "$C/tmp-sc" \
    --samples "$C/samples-sc-$d.txt" --sample-every "${EVERY[$d]}" > "$C/recode-sa-$d-report.json" || fail "recode $d"
  cat "$C/recode-sa-$d-report.json"
  [ "$(sha "$C/recode-sa-$d-report.json" "$d")" = "$(sha "$C/streamhash-sa-$d-old.json" "$d")" ] || fail "recoded $d stream differs from the old file's"
  rm -rf "$C/tmp-sc"/*
  ls -la "$S/$d"
done
# Storage samples answer eth_getStorageAt and eth_getProof (the commitment trie walk), account
# samples balance, nonce and account proofs; commitment keys aren't addressable over RPC, so the
# proofs are its check.
cat "$C/samples-sc-storage.txt" "$C/samples-sc-accounts.txt" > "$C/samples-sc.txt"
wc -l "$C/samples-sc.txt"

step "answers on the old layout"
boot || fail "old boot"
python3 "$C/rpc-sample.py" "$PORT" "$C/samples-sc.txt" "$C/answers-sc-old.jsonl" || fail "old answers"
halt old
flock "$LOCK" schelk restore -y --state-path "$STATE" || fail "restore after old probe"

step "swap the re-encoded files"
for d in $DOMAINS; do
  find "$DATA/snapshots/domain" -maxdepth 1 -type f -name "v*-$d.0-1.*" -print -delete
  cp -v "$S/$d"/* "$DATA/snapshots/domain/" || fail "copy staged $d files"
done
chown -R 1000:1000 "$DATA/snapshots/domain"
ls -la "$DATA/snapshots/domain"
for d in $DOMAINS; do
  NEW=$(ls "$DATA"/snapshots/domain/v*-$d.0-1.kv)
  tool compactlatest streamhash --domain "$d" --datadir "$DATA" --kv "$NEW" > "$C/streamhash-sa-$d-new.json" || fail "new streamhash $d"
  [ "$(sha "$C/streamhash-sa-$d-new.json" "$d")" = "$(sha "$C/streamhash-sa-$d-old.json" "$d")" ] || fail "new $d file's stream differs"
done

step "answers on the new layout"
boot || fail "new boot"
python3 "$C/rpc-sample.py" "$PORT" "$C/samples-sc.txt" "$C/answers-sc-new.jsonl" || fail "new answers"
halt new
cmp "$C/answers-sc-old.jsonl" "$C/answers-sc-new.jsonl" || fail "answers differ"
echo "answers identical: $(wc -l < "$C/answers-sc-new.jsonl") lines"

step "promote"
time flock "$LOCK" schelk promote -y --state-path "$STATE" || fail "promote"
flock "$LOCK" schelk mount -y --state-path "$STATE"; findmnt -n "$MNT" || fail "not mounted after promote"
flock "$LOCK" schelk recover -y --state-path "$STATE" || fail "unmount after promote"

step "smoke and traces"
rm -f "$BUSY"; trap - EXIT
FILTER="$(cat /bench/erigon/tools/smoke.regex)" /bench/erigon/tools/run-suite.sh sa B S4
[ -f $L/suite-sa-S4.done ] || fail "smoke suite"
grep -aq "^0 validation failures" $L/suite-sa-S4.log || fail "smoke validation failures"
grep -aE "Test execution completed" $L/suite-sa-S4.log | tail -1 | grep -q "failed=0 .*passed=2" || fail "smoke not 2/2"
# T4: the five T2 tests and the six T3 tests on state-actor; jochemnet hasn't changed since T2/T3.
python3 -c "import sys; a, b = (open(p).read().strip()[1:-1] for p in sys.argv[1:3]); open(sys.argv[3], 'w').write('(' + a + '|' + b + ')\n')" \
  /bench/erigon/tools/trace-tests-T2.regex /bench/erigon/tools/trace-tests-T3.regex /bench/erigon/tools/trace-tests-T4.regex
TRACE_REGEX=/bench/erigon/tools/trace-tests-T4.regex /bench/erigon/tools/trace-tests.sh sa T4
[ -f $L/trace-sa-T4.done ] || fail "trace sa T4"
echo "rc=0" > "$DONE"
echo "I chain started $(date -Is)"
exec /bench/erigon/tools/chain-B.sh joc:I1 sa:I1 joc:I2 sa:I2
