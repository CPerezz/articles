#!/bin/bash
IMG=docker.io/ethpandaops/reth:glamsterdam-devnet-7@sha256:dc8936043e0c327aae5aa18adb804c48ca290700ed1ca40ba589783c4d042a48
O=/root/bench/reth/probe
mountpoint -q /schelk-sa || SCHELK_STATE=/var/lib/schelk/reth-sa.json schelk -y mount > /dev/null
R="podman run --rm -v /schelk-sa/reth:/var/lib/reth -v /tmp/sa-chainspec.json:/cs.json $IMG db --datadir /var/lib/reth --chain /cs.json"
$R settings set v2 true > $O/sa-rw.txt 2>&1
$R stats > $O/sa-stats.txt 2>&1
SCHELK_STATE=/var/lib/schelk/reth-sa.json schelk -y restore > /dev/null 2>&1
echo SA-DONE; which mdbx_stat mdbx_copy mdbx_chk 2>&1
