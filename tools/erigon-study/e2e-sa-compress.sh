#!/usr/bin/env bash
# Round 14, the state-actor fix end to end: generate the same small store (the baseline spec, every
# count cut to 3,000) with the published image and with the fixed one. The two must hold the same
# state (same root, same code stream, same RPC answers through Erigon); the fixed one's code file
# must be written the way Erigon writes it (a pattern dictionary, test contracts under 1 KB).
# Usage: sudo e2e-sa-compress.sh <new-image>      Never beside a suite (.busy).
set -uo pipefail

NEW="${1:?new image}"
OLD=ghcr.io/ethereum/state-actor-erigon:main-005a19c
IMG=docker.io/ethpandaops/erigon:glamsterdam-devnet-7
GO_IMG=docker.io/library/golang:1.25-bookworm
E=/bench/erigon/e2e
C=/bench/erigon/compact
L=/bench/erigon/logs
BUSY=/bench/erigon/.busy
PORT=18547

rm -f "$L/e2e-sa-compress.done" "$L/e2e-sa-compress.fail"
cd /
exec >> "$L/e2e-sa-compress.log" 2>&1
fail() { echo "FAIL $1 ($(date -Is))"; echo "$1" > "$L/e2e-sa-compress.fail"; exit 1; }
while [ -f "$BUSY" ] || pgrep -x benchmarkoor >/dev/null; do sleep 30; done
echo "e2e-sa-compress" > "$BUSY"
trap 'podman rm -f er-e2e-probe >/dev/null 2>&1; rm -f "$BUSY"' EXIT
mkdir -p "$E"
echo "======== e2e $(date -Is): old $OLD new $NEW ========"

python3 - <<'EOF' || fail "spec"
import re
s = open("/bench/erigon/cfg/state-actor-spec-baseline.yaml").read()
s, n = re.subn(r"\b(salt_count|count): 150000\b", r"\1: 3000", s)
s = s.replace("final: 335545082", "final: 30000")
assert n >= 7, n
open("/bench/erigon/e2e/spec-small.yaml", "w").write(s)
EOF

gen() { # name image
  rm -rf "${E:?}/$1" && mkdir -p "$E/$1"
  time podman run --rm -v "$E/$1":/data -v "$E/spec-small.yaml":/spec.yaml:ro "$2" \
    --db=/data --client=erigon --target-size=256MB --spec=/spec.yaml \
    --seed=42 --fork=osaka --gas-limit=1000000000 > "$E/gen-$1.log" 2>&1 || fail "generate $1"
  chown -R 1000:1000 "$E/$1"
}
gen old "$OLD"
gen new "$NEW"
root() { python3 -c "import json;print(json.load(open('$E/$1/state-actor-manifest.json'))['result']['state_root'])"; }
echo "roots: $(root old) $(root new)"
[ "$(root old)" = "$(root new)" ] || fail "state roots differ"
for s in old new; do
  ls -la "$E/$s/snapshots/domain/"
  podman run --rm -v /bench/erigon:/bench/erigon "$GO_IMG" "$C/bin/compactlatest" codespan \
    --kv "$(ls "$E/$s"/snapshots/domain/*-code.0-1.kv)" --fixtures "$E/codespan-$s.tsv" > "$E/codespan-$s.json" || fail "codespan $s"
done
python3 - <<'EOF' || fail "code files"
import json
o, n = (json.load(open(f"/bench/erigon/e2e/codespan-{s}.json")) for s in ("old", "new"))
print("code stream", o["stream_sha256"] == n["stream_sha256"], o["keys"], n["keys"])
print("dictionary", o["pattern_dict_bytes"], n["pattern_dict_bytes"], "file", o["file_bytes"], "->", n["file_bytes"])
assert o["stream_sha256"] == n["stream_sha256"] and o["keys"] == n["keys"]
assert o["pattern_dict_bytes"] == 0 < n["pattern_dict_bytes"]
for g in ("615fff56@44", "00000000@12", "005b5b5b@-1"):
    a, b = o["max_size_groups"][g], n["max_size_groups"][g]
    print(g, a["n"], a["encoded_value_bytes"], "->", b["encoded_value_bytes"], b["pages_key_and_value"])
    assert a["n"] == b["n"] > 0 and b["encoded_value_bytes"]["max"] < 1024
EOF

# Samples: every test contract's code, the sequential EOAs and seed, and the storage-pattern
# contract's first slots, answered through Erigon on each store.
python3 - <<'EOF' || fail "samples"
lines = []
for l in open("/bench/erigon/e2e/codespan-old.tsv"):
    lines.append("e2e code " + l.split("\t")[0])
for i in range(0, 3000, 7):
    lines.append("e2e accounts %040x" % (0x1000 + i))
lines.append("e2e accounts f39fd6e51aad88f6f4ce6ab8827279cfffb92266")
for s in range(64):
    lines.append("e2e storage 87a6314da5ac8832f6e7a176c8fb133b19f5be04%064x" % s)
open("/bench/erigon/e2e/samples.txt", "w").write("\n".join(lines) + "\n")
print(len(lines), "samples")
EOF
for s in old new; do
  podman rm -f er-e2e-probe >/dev/null 2>&1
  podman run -d --name er-e2e-probe -p "127.0.0.1:$PORT:8545" -v "$E/$s":/data \
    -v /bench/erigon/probe/jwtsecret:/tmp/jwtsecret:ro "$IMG" \
    --datadir=/data --nat=none --maxpeers=0 --txpool.disable --nodiscover --no-downloader \
    --http --http.addr=0.0.0.0 --http.port=8545 --http.vhosts='*' --http.api=eth,net,debug \
    --authrpc.jwtsecret=/tmp/jwtsecret --prune.mode=full --log.dir.disable --externalcl \
    --exec.no-merge=true --exec.no-prune=true --exec.no-background-maintenance \
    --experimental.parallel-commitment --override.amsterdam=1 >/dev/null || fail "boot $s"
  up=""
  for _ in $(seq 1 120); do
    curl -s -m 5 -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}' \
      "http://127.0.0.1:$PORT" | grep -q result && up=1 && break
    podman container exists er-e2e-probe || break
    sleep 5
  done
  [ -n "$up" ] || { podman logs er-e2e-probe 2>&1 | tail -30; fail "rpc $s"; }
  python3 "$C/rpc-sample.py" "$PORT" "$E/samples.txt" "$E/answers-$s.jsonl" || fail "answers $s"
  podman logs er-e2e-probe > "$E/erigon-$s.log" 2>&1
  podman stop -t 120 er-e2e-probe >/dev/null; podman rm er-e2e-probe >/dev/null
done
cmp "$E/answers-old.jsonl" "$E/answers-new.jsonl" || fail "answers differ"
python3 - <<'EOF' || fail "answer content"
import json
rows = [json.loads(l) for l in open("/bench/erigon/e2e/answers-new.jsonl")][1:]
code = [r for r in rows if r["domain"] == "code"]
assert code and all(isinstance(r["answers"][0], str) and len(r["answers"][0]) == 2 + 2 * 24576 for r in code), "a test contract's code came back wrong"
print(len(rows), "answers identical;", len(code), "test contracts returned 24,576 bytes each")
EOF
echo "rc=0" > "$L/e2e-sa-compress.done"
echo "finished $(date -Is)"
