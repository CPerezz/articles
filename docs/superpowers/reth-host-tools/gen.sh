#!/bin/bash
# state-actor reth store, the Nethermind v2 invocation with --client=reth (same image revision 005a19c,
# spec sha256 74dea7d1, seed 42, osaka, gas limit 1e9, target 350GB). Output on md2 NVMe, spill on md3 HDD.
mkdir -p /sa-gen /data/spill-reth
echo "started : $(date -Is)"
time podman run --rm --name sa-gen-reth --ulimit nofile=1048576:1048576 \
  -v /sa-gen:/data -v /root/bench/reth/cfg/state-actor-spec-baseline.yaml:/spec.yaml:ro -v /data/spill-reth:/spill -e TMPDIR=/spill \
  ghcr.io/ethereum/state-actor-reth:main-005a19c \
  --db=/data --client=reth --target-size=350GB --spec=/spec.yaml --seed=42 --fork=osaka --gas-limit=1000000000 --verbose
echo "exit code : $?"
echo "finished  : $(date -Is)"
du -sh /sa-gen/* 2>/dev/null
