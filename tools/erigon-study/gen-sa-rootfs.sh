#!/usr/bin/env bash
# Generate the Erigon state-actor store on the rootfs, then copy it into the er-sa scratch.
#
# Replaces gen-sa.sh after the first run, writing straight into the 787 GB scratch, was heading
# for ENOSPC: the writer's stream-sort temp files alone reached ~590 GB and its snapshot/commitment
# phase was adding ~2 GB/min with three hours to go. On the rootfs the temp space is not bounded by
# the volume; only the finished store (temp files removed) is copied in.
set -uo pipefail

IMG=ghcr.io/ethereum/state-actor-erigon:main-005a19c
WANT_IMG_ID=f7eb453d4b48215ca0a450f4d51e7ef03dbb643ebc0166d0204893939f29277c
SPEC=/bench/erigon/cfg/state-actor-spec-baseline.yaml
WANT_SPEC_SHA=74dea7d1de9d869d87ddcabf52912cada6d48cb1eb295819d322aef51c3f7194
WANT_GENESIS=0x0cb035288eb4e257f34f3d570ed4f43f9d2fc45c09f19db6c0392f60f4a68623
WANT_ROOT=0x48d611bb839188317e983453705b31e1420b2c4416675f98d776ad8e130d51b8
SRC=/bench/erigon/sa-store
DB=/schelk-er-sa/erigon
LOG=/bench/erigon/logs/gen-sa.log
DONE=/bench/erigon/logs/gen-sa.done
FAIL=/bench/erigon/logs/gen-sa.fail

rm -f "$DONE" "$FAIL"
cd /
fail() { echo "FAIL $1" | tee -a "$LOG"; echo "$1" > "$FAIL"; exit 1; }

findmnt -n /schelk-er-sa >/dev/null || fail "/schelk-er-sa not mounted"
[ "$(sha256sum "$SPEC" | cut -d' ' -f1)" = "$WANT_SPEC_SHA" ] || fail "spec sha"
[ "$(sudo podman image inspect -f '{{.Id}}' "$IMG")" = "$WANT_IMG_ID" ] || fail "image id"
sudo rm -rf "$SRC"; mkdir -p "$SRC"

{
  echo "======== state-actor erigon (rootfs): $(date -Is) ========"
  echo "free on /: $(df -h / | tail -1 | awk '{print $4}')"
  time sudo nice -n 10 ionice -c2 -n7 podman run --rm -v "$SRC":/data -v "$SPEC":/spec.yaml:ro \
    -v /bench/erigon/spill:/spill -e TMPDIR=/spill "$IMG" \
    --db=/data --client=erigon --target-size=350GB --spec=/spec.yaml \
    --seed=42 --fork=osaka --gas-limit=1000000000 --verbose
  echo "writer rc=$?" | tee /bench/erigon/logs/gen-sa.rc
  echo "finished: $(date -Is)"
  echo "store size: $(sudo du -sh "$SRC" | cut -f1)"
  sudo du -sh "$SRC"/* 2>/dev/null | sort -rh | head -12
} >> "$LOG" 2>&1

grep -q "writer rc=0" /bench/erigon/logs/gen-sa.rc || fail "writer $(cat /bench/erigon/logs/gen-sa.rc)"
root=$(sudo python3 -c "import json;print(json.load(open('$SRC/state-actor-manifest.json'))['result']['state_root'])" 2>/dev/null)
[ "$root" = "$WANT_ROOT" ] || fail "state root ${root:-<none>}"
gen=$(grep -oiE "genesis( block)? hash *[=:] *0x[0-9a-f]{64}" "$LOG" | tail -1 | grep -oE "0x[0-9a-f]{64}")
[ "$gen" = "$WANT_GENESIS" ] || echo "NOTE writer log has no matching genesis hash line (${gen:-none}); the probe checks block 0" | tee -a "$LOG"
ls "$SRC"/streamsort-* >/dev/null 2>&1 && fail "stream-sort temp dirs left behind"

{
  echo "======== copy into the scratch: $(date -Is) ========"
  sudo rm -rf "$DB"; sudo mkdir -p "$DB"
  sudo cp -a "$SRC"/. "$DB"/
  s=$(sudo du -sb "$SRC" | cut -f1); d=$(sudo du -sb "$DB" | cut -f1)
  sf=$(sudo find "$SRC" -type f | wc -l); df_=$(sudo find "$DB" -type f | wc -l)
  echo "src $s B $sf files; dst $d B $df_ files"
  [ "$s" = "$d" ] && [ "$sf" = "$df_" ] && echo "COPY_OK" || echo "COPY MISMATCH"
  sudo chown -R 1000:1000 "$DB"
  echo "finished: $(date -Is)"
} >> "$LOG" 2>&1
grep -q "COPY_OK" "$LOG" || fail "copy check"
echo "OK state root $root" | tee -a "$LOG"
echo "rc=0" > "$DONE"
