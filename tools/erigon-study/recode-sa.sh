#!/usr/bin/env bash
# Round 14: re-encode state-actor's code file the way Erigon writes its own (CompressVals against a
# pattern dictionary, the code domain's CompressCfg), check it answers exactly as before, promote it,
# smoke it, trace both stores (T2), then run the H pairs.
#
# state-actor's seg port has no pattern path, so its code .kv stores every value raw: a 24,576-byte
# fixture contract costs 7 pages per call, against 1 on jochemnet's Erigon-written file (codespan R14).
# Only the encoding changes: same keys, same values, same step. The new file's (key, value) stream
# must hash like the old one's, and eth_getCode must answer byte for byte the same.
#
# One-way for the promoted image; /bench/erigon/sa-store keeps the generator's original file.
# Usage: sudo recode-sa.sh      Never beside a suite (.busy).
set -uo pipefail

IMG=docker.io/ethpandaops/erigon:glamsterdam-devnet-7
GO_IMG=docker.io/library/golang:1.25-bookworm
STATE=/var/lib/schelk/er-sa.json
MNT=/schelk-er-sa
DATA=$MNT/erigon
RAW=/bench/erigon/sa-store/snapshots/domain/v1.0-code.0-1.kv
C=/bench/erigon/compact
S=$C/staging-sa
L=/bench/erigon/logs
LOG=$L/recode-sa.log
DONE=$L/recode-sa.done
FAIL=$L/recode-sa.fail
BUSY=/bench/erigon/.busy
LOCK=/bench/erigon/.schelk.lock
PORT=18546

rm -f "$DONE" "$FAIL"
cd /
exec >> "$LOG" 2>&1
# uid 1000 like erigon: a root-owned LOCK or temp dir in the datadir would stop the node booting.
tool() { podman run --rm --user 1000:1000 -e HOME=/tmp -v "$C":"$C" -v "$MNT":"$MNT" "$GO_IMG" "$C/bin/$@"; }
fail() { echo "FAIL $1 ($(date -Is))"; echo "$1" > "$FAIL"; exit 1; }
step() { echo; echo "======== $1: $(date -Is) ========"; }
same_stream() { # report.json key, codespan.json: both must name the same (key, value) stream
  python3 - "$@" <<'EOF'
import json, sys
a, path, b = sys.argv[1], sys.argv[2], json.load(open(sys.argv[3]))
x = json.load(open(a))
for k in path.split("."):
    x = x[k]
print("stream", x["sha256"] if isinstance(x, dict) else x, "keys", b["keys"])
want = x["sha256"] if isinstance(x, dict) else x
sys.exit(0 if want == b["stream_sha256"] else 1)
EOF
}

while [ -f "$BUSY" ] || pgrep -x benchmarkoor >/dev/null; do sleep 60; done
echo "recode-sa" > "$BUSY"
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
halt() { podman logs er-recode-probe > "$C/erigon-sa-$1.log" 2>&1; podman stop -t 600 er-recode-probe >/dev/null; podman rm er-recode-probe >/dev/null; }

step "restore scratch"
flock "$LOCK" schelk restore -y --state-path "$STATE" || fail "restore"
findmnt -n "$MNT" || fail "not mounted"
[ "$(df --output=avail -BG / | tail -1 | tr -dc 0-9)" -ge 200 ] || fail "rootfs needs 200 GB free"
OLD=$(ls "$DATA"/snapshots/domain/v*-code.0-1.kv)
[ "$(echo "$OLD" | wc -l)" = 1 ] || fail "expected one code .kv, found: $OLD"
time cmp "$OLD" "$RAW" || fail "the image's code file differs from the copy codespan R14 read"
rm -rf "$S" "$C/tmp-sa" && mkdir -p "$S" "$C/tmp-sa" && chown 1000:1000 "$S" "$C/tmp-sa"

step "recode (read-only on the scratch)"
time tool compactlatest recode --domain code --datadir "$DATA" --dst "$S" --tmp "$C/tmp-sa" \
  --samples "$C/samples-sa.txt" --sample-every 5000 > "$C/recode-sa-report.json" || fail "recode"
cat "$C/recode-sa-report.json"
same_stream "$C/recode-sa-report.json" code "$C/codespan-sa-R14.json" || fail "recoded stream differs from the old file's"
awk 'NR % 300 == 0 {print "fix code " $1}' "$C/codespan-sa-R14.tsv" >> "$C/samples-sa.txt"
wc -l "$C/samples-sa.txt"
ls -la "$S"
rm -rf "$C/tmp-sa"

step "answers on the old layout"
boot || fail "old boot"
python3 "$C/rpc-sample.py" "$PORT" "$C/samples-sa.txt" "$C/answers-sa-old.jsonl" || fail "old answers"
halt old
flock "$LOCK" schelk restore -y --state-path "$STATE" || fail "restore after old probe"

step "swap the code file"
find "$DATA/snapshots/domain" -maxdepth 1 -type f -name 'v*-code.0-1.*' -print -delete
cp -v "$S"/* "$DATA/snapshots/domain/" || fail "copy staged files"
chown -R 1000:1000 "$DATA/snapshots/domain"
NEW=$(ls "$DATA"/snapshots/domain/v*-code.0-1.kv)
ls -la "$DATA/snapshots/domain"

step "codespan on the new file"
podman run --rm -v /bench/erigon:/bench/erigon -v "$MNT":"$MNT" "$GO_IMG" "$C/bin/compactlatest" codespan \
  --kv "$NEW" --fixtures "$C/codespan-sa-recoded.tsv" > "$C/codespan-sa-recoded.json" || fail "codespan new"
same_stream "$C/codespan-sa-recoded.json" stream_sha256 "$C/codespan-sa-R14.json" || fail "new file's stream differs"

step "answers on the new layout"
boot || fail "new boot"
python3 "$C/rpc-sample.py" "$PORT" "$C/samples-sa.txt" "$C/answers-sa-new.jsonl" || fail "new answers"
halt new
cmp "$C/answers-sa-old.jsonl" "$C/answers-sa-new.jsonl" || fail "answers differ"
echo "answers identical: $(wc -l < "$C/answers-sa-new.jsonl") lines"

step "promote"
time flock "$LOCK" schelk promote -y --state-path "$STATE" || fail "promote"
flock "$LOCK" schelk mount -y --state-path "$STATE"; findmnt -n "$MNT" || fail "not mounted after promote"
flock "$LOCK" schelk recover -y --state-path "$STATE" || fail "unmount after promote"

step "smoke and traces"
rm -f "$BUSY"; trap - EXIT
FILTER="$(cat /bench/erigon/tools/smoke.regex)" /bench/erigon/tools/run-suite.sh sa B S3
[ -f $L/suite-sa-S3.done ] || fail "smoke suite"
grep -aq "^0 validation failures" $L/suite-sa-S3.log || fail "smoke validation failures"
grep -aE "Test execution completed" $L/suite-sa-S3.log | tail -1 | grep -q "failed=0 .*passed=2" || fail "smoke not 2/2"
for arm in sa joc; do
  TRACE_REGEX=/bench/erigon/tools/trace-tests-T2.regex /bench/erigon/tools/trace-tests.sh $arm T2
  [ -f $L/trace-$arm-T2.done ] || fail "trace $arm"
done
echo "rc=0" > "$DONE"
echo "H chain started $(date -Is)"
exec /bench/erigon/tools/chain-B.sh joc:H1 sa:H1 joc:H2 sa:H2
