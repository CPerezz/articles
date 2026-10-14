#!/bin/bash
# Fill stateful EEST fixtures for the S store with reth itself as the filler. benchmarkoor's builder only
# accepts geth/besu/nethermind fillers, so this replays its recorded invocation (fixtures.ini of the
# sa-v2-full fill) by hand. reth runs on the restored S scratch; schelk recover throws its blocks away.
# usage: refill.sh <out dir> <gas values, e.g. 160,240> <pytest target> [-k expression]
set -u
cd /root/bench/reth || exit 1
OUT=$1 GAS=$2 TARGET=$3 K=${4:-}
E=/root/bench/reth/eest-13b7913
REF=13b791382048f083f8243b0eb5071273775c6440
# acf6e17 rebuilt with testing_buildBlockV1 returning the block access list (build-reth-fill.sh); the
# stock binary drops it and every engine_newPayloadV5 of a built block fails.
IMG=localhost/reth-fill:acf6e17-bal
FILLIMG=localhost/benchmarkoor-eest-fill:local
SEED=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
W=/root/bench/reth/fill
export SCHELK_STATE=/var/lib/schelk/reth-sa.json
abort() { echo "ABORT $* $(date)"; podman rm -f fill-reth > /dev/null 2>&1; mount | grep -q ' /schelk-sa ' && schelk -y recover > /dev/null 2>&1; exit 1; }
[ "$(dmsetup ls | grep -c _era)" = 0 ] || { echo "ABORT a scratch is mapped"; exit 1; }
if [ ! -d $E/.git ]; then
  git init -q $E && git -C $E remote add origin https://github.com/ethereum/execution-specs.git \
    && git -C $E fetch -q --depth 1 origin $REF && git -C $E checkout -q FETCH_HEAD || { echo "ABORT eest checkout"; exit 1; }
fi
# fill-stateful checks every stub address exists on chain; state-actor's spec plants only the 10GB one,
# the only stub these families use (it also names the sload/sstore_bloated[10GB-…] test ids).
SRC=$(grep -l '"bloated_eoa_10GB"' $E/tests/benchmark/stateful/stubs/*.json 2>/dev/null | head -1)
[ -n "$SRC" ] || { echo "ABORT no stubs file with bloated_eoa_10GB"; exit 1; }
mkdir -p $W $OUT
STUBS=$W/stubs.json
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); json.dump({"bloated_eoa_10GB": d["bloated_eoa_10GB"]}, open(sys.argv[2],"w"))' $SRC $STUBS || { echo "ABORT stubs"; exit 1; }
schelk -y restore > /dev/null 2>&1 || abort restore
python3 -c 'import json,sys; g=json.load(open(sys.argv[1])); g["config"]["amsterdamTime"]=1; json.dump(g,open(sys.argv[2],"w"))' \
  /schelk-sa/reth/chainspec.json $W/genesis.json || abort genesis
openssl rand -hex 32 > $W/jwt
podman rm -f fill-reth > /dev/null 2>&1
podman run -d --name fill-reth --network host --ulimit nofile=1048576:1048576 -v /schelk-sa/reth:/var/lib/reth \
  -v $W/genesis.json:/tmp/genesis.json:ro -v $W/jwt:/tmp/jwtsecret:ro $IMG node --datadir=/var/lib/reth \
  --http --http.addr=127.0.0.1 --http.api=eth,net,web3,debug,txpool,testing --http.port=8545 \
  --authrpc.jwtsecret=/tmp/jwtsecret --authrpc.addr=127.0.0.1 --authrpc.port=8551 --engine.disable-precompile-cache \
  --debug.skip-genesis-validation --full --chain=/tmp/genesis.json --disable-discovery --max-outbound-peers=0 --max-inbound-peers=0 > /dev/null || abort "reth start"
for i in $(seq 120); do
  H=$(curl -s -X POST -H 'content-type: application/json' --data '{"jsonrpc":"2.0","id":1,"method":"eth_getBlockByNumber","params":["latest",false]}' http://127.0.0.1:8545 | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["hash"])' 2>/dev/null) && break
  sleep 2
done
[ -n "${H:-}" ] || abort "reth rpc not up"
echo "snapshot block $H, stubs $(basename $STUBS) $(date)"
args=(uv run fill -c /eest/packages/testing/src/execution_testing/cli/pytest_commands/pytest_ini_files/pytest-fill-stateful.ini
  --rootdir . -v --rpc-endpoint=http://127.0.0.1:8545 --engine-endpoint=http://127.0.0.1:8551 --engine-jwt-secret-file=/jwt/jwtsecret
  --fork=amsterdam --snapshot-block=$H --output=/out --gas-benchmark-values=$GAS --rpc-seed-key=$SEED --address-stubs=/stubs.json $TARGET)
[ -n "$K" ] && args+=(-k "$K")
rm -rf $OUT && mkdir -p $OUT
t0=$(date +%s)
podman run --rm --network host -v $E:/eest -v $OUT:/out -v $W/jwt:/jwt/jwtsecret:ro -v $STUBS:/stubs.json:ro \
  -v /root/.cache/benchmarkoor-uv:/root/.cache/uv $FILLIMG "${args[@]}" > $W/fill.log 2>&1
rc=$?
# pytest exits 1 whenever a test fails, and some tests always fail on a state-actor store (the depth
# benchmarks, the MISSING_STUBS variants, the extcodesize bytecode-size family): the nethermind fill and
# the reth fill of the S g store (REF_FAILS) failed the same 112 and filled the same 456. The verdict
# (the "fill exit" code callers gate on) is 0 when every failure is one of REF_FAILS and something filled.
REF_FAILS=${REF_FAILS:-/root/bench/reth/logs/refill-g-fill.log}
fails() { grep -E '\] (FAILED|ERROR) +\[' "$1" | sed -E 's/ (FAILED|ERROR) +\[.*//' | sort -u; }
filled=$(grep -cE '\] FILLED +\[' $W/fill.log)
unexpected=$( { [ -f "$REF_FAILS" ] && comm -23 <(fails $W/fill.log) <(fails $REF_FAILS) || fails $W/fill.log; } | wc -l)
verdict=$([ "$unexpected" = 0 ] && [ "$filled" -gt 0 ] && echo 0 || echo 1)
cp $W/fill.log $OUT/.meta/refill-fill.log 2>/dev/null
echo "fill exit $verdict in $(( $(date +%s) - t0 )) s; pytest exit $rc; $filled filled, $unexpected unexpected failures; $(grep -E '[0-9]+ (passed|failed)' $W/fill.log | tail -1)"
podman logs --tail 20 fill-reth > $W/reth-tail.log 2>&1
podman rm -f fill-reth > /dev/null
schelk -y recover > /dev/null 2>&1 || echo "WARN recover failed"
echo "== done $(date) mapped=$(dmsetup ls | grep -c _era) fixtures=$(find $OUT -name '*.json' | wc -l)"
