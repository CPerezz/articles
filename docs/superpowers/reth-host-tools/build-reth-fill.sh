#!/bin/bash
# reth acf6e17 (the benchmarked build) with testing_buildBlockV1 returning the Amsterdam payload (V6
# envelope, ExecutionPayloadV4 with the block access list), so EEST fill-stateful can use reth as the
# filler. The stock handler builds the BAL and then drops it (ExecutionPayloadV3), which makes every
# engine_newPayloadV5 of the built block fail with "missing field blockAccessList". Used only to fill
# fixtures: every measurement keeps docker.io/benchlocal/reth:devnet7-sigkill.
set -eu
S=/root/bench/reth/reth-src
REF=acf6e175a531a43b1d2f96ef500390ec50e14ea8
if [ ! -d $S/.git ]; then
  git init -q $S && git -C $S remote add origin https://github.com/paradigmxyz/reth.git
  git -C $S fetch -q --depth 1 origin $REF && git -C $S checkout -q FETCH_HEAD
fi
cd $S && git checkout -q -- . && [ "$(git rev-parse HEAD)" = $REF ]
python3 - <<'PY'
import re
api = "crates/rpc/rpc-api/src/testing.rs"
s = open(api).read()
s = s.replace("ExecutionPayloadEnvelopeV5", "ExecutionPayloadEnvelopeV6")
assert s.count("ExecutionPayloadEnvelopeV6") == 2, api
open(api, "w").write(s)

impl = "crates/rpc/rpc/src/testing.rs"
s = open(impl).read()
s = s.replace("ExecutionData, ExecutionPayloadEnvelopeV5, ExecutionPayloadSidecar,\n    ExecutionPayloadV3,",
              "ExecutionData, ExecutionPayloadEnvelopeV6, ExecutionPayloadSidecar,\n    ExecutionPayloadV4,")
old = """    ) -> Result<ExecutionPayloadEnvelopeV5, Eth::Error> {
        let payload = self
            .build_payload_v1(request, self.skip_invalid_transactions, use_pool_transactions)
            .await?;
        let fees = payload.fees();
        let requests = payload.requests().unwrap_or_default();
"""
new = """    ) -> Result<ExecutionPayloadEnvelopeV6, Eth::Error> {
        let payload = self
            .build_payload_v1(request, self.skip_invalid_transactions, use_pool_transactions)
            .await?;
        let fees = payload.fees();
        let requests = payload.requests().unwrap_or_default();
        let block_access_list = payload.block_access_list().cloned().ok_or_else(|| {
            Eth::Error::from_eth_err(EthApiError::InvalidParams(
                "testing_buildBlockV1 builds Amsterdam blocks only".to_string(),
            ))
        })?;
"""
assert s.count(old) == 1, "build_block_v1 head"
s = s.replace(old, new)
old = """        Ok(ExecutionPayloadEnvelopeV5 {
            execution_payload: ExecutionPayloadV3::from_block_unchecked(block_hash, &block),"""
new = """        Ok(ExecutionPayloadEnvelopeV6 {
            execution_payload: ExecutionPayloadV4::from_block_unchecked_with_bal(
                block_hash,
                &block,
                block_access_list,
            ),"""
assert s.count(old) == 1, "envelope"
s = s.replace(old, new)
assert s.count(") -> RpcResult<ExecutionPayloadEnvelopeV5> {") == 1
s = s.replace(") -> RpcResult<ExecutionPayloadEnvelopeV5> {", ") -> RpcResult<ExecutionPayloadEnvelopeV6> {")
assert "ExecutionPayloadEnvelopeV5" not in s and "ExecutionPayloadV3" not in s, "leftovers"
open(impl, "w").write(s)
PY
git diff --stat
mkdir -p /root/.cache/reth-cargo
t0=$(date +%s)
# Default features pull revmc-llvm (needs LLVM 22); the JIT does not change EVM results, so the filler
# builds without it.
podman run --rm -v $S:/src -v /root/.cache/reth-cargo:/usr/local/cargo/registry -w /src \
  docker.io/library/rust:1.95-bookworm bash -c 'apt-get -qq update >/dev/null && apt-get -qq install -y clang libclang-dev >/dev/null && cargo build --release --locked --bin reth --no-default-features --features jemalloc,asm-keccak 2>&1 | tail -25'
echo "cargo done in $(( ($(date +%s) - t0) / 60 )) min"
ls -la $S/target/release/reth
mkdir -p /root/bench/reth/reth-fill-img && cp $S/target/release/reth /root/bench/reth/reth-fill-img/reth
printf 'FROM docker.io/benchlocal/reth:devnet7-sigkill\nCOPY reth /usr/local/bin/reth\n' > /root/bench/reth/reth-fill-img/Dockerfile
podman build -q -t localhost/reth-fill:acf6e17-bal /root/bench/reth/reth-fill-img
podman run --rm --entrypoint reth localhost/reth-fill:acf6e17-bal --version | head -3
echo BUILD-OK
