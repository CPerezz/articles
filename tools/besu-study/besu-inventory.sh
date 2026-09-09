#!/usr/bin/env bash
# Store inventory for the Besu study — the `geth db inspect` analogue plus the bits geth had
# no equivalent of. Run on each store before any timing run; the output is the side-by-side
# table the article opens with.
#
# Usage: besu-inventory.sh <datadir> <genesis-file> <label> [outfile]
set -uo pipefail
DATADIR="${1:?usage: besu-inventory.sh <datadir> <genesis> <label> [out]}"
GENESIS="${2:?}"
LABEL="${3:?}"
OUT="${4:-/root/bench/besu-inventory-$LABEL.txt}"
IMG=hyperledger/besu:25.11.0

# --genesis-state-hash-cache-enabled is mandatory on offline storage subcommands, not just at
# boot: state-actor emits an empty chainspec alloc, so the default recompute path aborts with
# "Supplied genesis block does not match chain data stored".
besu_cmd() {
  docker run --rm -v "$DATADIR":/data -v "$GENESIS":/genesis.json:ro "$IMG" \
    --data-path=/data --genesis-file=/genesis.json --network-id=1337 \
    --genesis-state-hash-cache-enabled=true "$@" 2>&1 | grep -vE "\| (INFO|WARN|DEBUG) +\|"
}

{
  echo "======== besu store inventory: $LABEL ========"
  echo "datadir : $DATADIR"
  echo "taken   : $(date -Is)"
  echo "apparent: $(du -sh "$DATADIR" 2>/dev/null | cut -f1)"

  echo
  echo "-------- trie logs (the journal analogue) --------"
  besu_cmd storage trie-log count

  echo
  echo "-------- rocksdb usage by column family --------"
  besu_cmd storage rocksdb usage

  echo
  echo "-------- physical file inventory --------"
  D="$DATADIR/database"
  echo "sst   files : $(ls "$D"/*.sst  2>/dev/null | wc -l)"
  echo "blob  files : $(ls "$D"/*.blob 2>/dev/null | wc -l)"
  echo "sst   bytes : $(du -cb "$D"/*.sst  2>/dev/null | tail -1 | cut -f1)"
  echo "blob  bytes : $(du -cb "$D"/*.blob 2>/dev/null | tail -1 | cut -f1)"
  echo "wal   files : $(ls "$D"/*.log 2>/dev/null | wc -l)"
  echo "wal   bytes : $(du -cb "$D"/*.log 2>/dev/null | tail -1 | cut -f1)"

  echo
  echo "-------- sst size distribution (MB buckets) --------"
  ls -l "$D"/*.sst 2>/dev/null | awk '{s=$5/1048576;
    if(s<1)b="<1"; else if(s<8)b="1-8"; else if(s<32)b="8-32"; else if(s<80)b="32-80"; else b=">80";
    n[b]++; t+=s} END {for(k in n) printf "  %-6s %d\n", k, n[k]; printf "  mean %.1f MB\n", t/NR}'
} | tee "$OUT"

echo "WROTE: $OUT"
