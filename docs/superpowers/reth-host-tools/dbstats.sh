#!/bin/bash
# reth db settings + table stats for both stores (read-only), then restore both scratches.
IMG=docker.io/ethpandaops/reth:glamsterdam-devnet-7@sha256:dc8936043e0c327aae5aa18adb804c48ca290700ed1ca40ba589783c4d042a48
O=/root/bench/reth/probe; mkdir -p $O
for a in joc sa; do mountpoint -q /schelk-$a || SCHELK_STATE=/var/lib/schelk/reth-$a.json schelk -y mount > /dev/null; done
podman run --rm -v /schelk-joc/reth:/var/lib/reth $IMG db --datadir /var/lib/reth --chain mainnet settings get > $O/joc-settings.txt 2>&1
podman run --rm -v /schelk-joc/reth:/var/lib/reth $IMG db --datadir /var/lib/reth --chain mainnet stats > $O/joc-stats.txt 2>&1
podman run --rm -v /schelk-sa/reth:/var/lib/reth $IMG db --datadir /var/lib/reth --chain /var/lib/reth/chainspec.json settings get > $O/sa-settings.txt 2>&1
podman run --rm -v /schelk-sa/reth:/var/lib/reth $IMG db --datadir /var/lib/reth --chain /var/lib/reth/chainspec.json stats > $O/sa-stats.txt 2>&1
for a in joc sa; do SCHELK_STATE=/var/lib/schelk/reth-$a.json schelk -y restore > /dev/null 2>&1; done
echo DBSTATS-DONE
