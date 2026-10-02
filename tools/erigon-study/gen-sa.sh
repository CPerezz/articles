#!/usr/bin/env bash
# Generate the Erigon state-actor store straight into the mounted er-sa scratch (plan section 4.2).
#
# Same generator revision, spec and parameters as the Nethermind v2 store, so the two stores share
# a genesis and state root and the existing 160M/240M fill applies unchanged. Asserted below rather
# than eyeballed: the spec hash, the writer's exit code, the state root and the genesis hash.
set -uo pipefail

IMG=ghcr.io/ethereum/state-actor-erigon:main-005a19c
WANT_IMG_ID=f7eb453d4b48215ca0a450f4d51e7ef03dbb643ebc0166d0204893939f29277c
SPEC=/bench/erigon/cfg/state-actor-spec-baseline.yaml
WANT_SPEC_SHA=74dea7d1de9d869d87ddcabf52912cada6d48cb1eb295819d322aef51c3f7194
WANT_GENESIS=0x0cb035288eb4e257f34f3d570ed4f43f9d2fc45c09f19db6c0392f60f4a68623
WANT_ROOT=0x48d611bb839188317e983453705b31e1420b2c4416675f98d776ad8e130d51b8
DB=/schelk-er-sa/erigon
SPILL=/bench/erigon/spill
LOG=/bench/erigon/logs/gen-sa.log
DONE=/bench/erigon/logs/gen-sa.done
FAIL=/bench/erigon/logs/gen-sa.fail

rm -f "$DONE" "$FAIL"
fail() { echo "FAIL $1" | tee -a "$LOG"; echo "$1" > "$FAIL"; exit 1; }

# Wait for the schelk volumes; the generator must write into the mounted scratch, not the rootfs.
until [ -f /bench/erigon/logs/setup-schelk.done ] || [ -f /bench/erigon/logs/setup-schelk.fail ]; do sleep 30; done
[ -f /bench/erigon/logs/setup-schelk.done ] || fail "schelk setup failed"
findmnt -n /schelk-er-sa >/dev/null || fail "/schelk-er-sa not mounted"

got_sha=$(sha256sum "$SPEC" | cut -d' ' -f1)
[ "$got_sha" = "$WANT_SPEC_SHA" ] || fail "spec sha $got_sha"
got_id=$(sudo podman image inspect -f '{{.Id}}' "$IMG")
[ "$got_id" = "$WANT_IMG_ID" ] || fail "image id $got_id"

mkdir -p "$DB" "$SPILL"
{
  echo "======== state-actor erigon ========"
  echo "started : $(date -Is)"
  echo "image   : $IMG ($got_id)"
  echo "spec    : $SPEC ($got_sha)"
  echo "free    : $(df -h /schelk-er-sa | tail -1 | awk '{print $4}') on /schelk-er-sa"
  time sudo nice -n 10 ionice -c2 -n7 podman run --rm \
    -v "$DB":/data -v "$SPEC":/spec.yaml:ro -v "$SPILL":/spill -e TMPDIR=/spill \
    "$IMG" \
    --db=/data --client=erigon --target-size=350GB --spec=/spec.yaml \
    --seed=42 --fork=osaka --gas-limit=1000000000 --verbose
  rc=$?
  echo "exit code : $rc"
  echo "finished  : $(date -Is)"
  echo "db size   : $(sudo du -sh "$DB" | cut -f1)"
  sudo du -sh "$DB"/*/ 2>/dev/null | sort -rh | head -12
  echo "rc=$rc" > /bench/erigon/logs/gen-sa.rc
} >> "$LOG" 2>&1

rc=$(cut -d= -f2 /bench/erigon/logs/gen-sa.rc)
[ "$rc" = "0" ] || fail "writer rc=$rc"
root=$(sudo python3 -c "import json;print(json.load(open('$DB/state-actor-manifest.json'))['result']['state_root'])" 2>/dev/null)
[ "$root" = "$WANT_ROOT" ] || fail "state root ${root:-<none>}"
gen=$(grep -oiE "genesis( block)? hash *[=:] *0x[0-9a-f]{64}" "$LOG" | tail -1 | grep -oE "0x[0-9a-f]{64}")
[ "$gen" = "$WANT_GENESIS" ] || fail "genesis hash ${gen:-<none>}"
[ -f "$DB/chainspec.json" ] || echo "NOTE no chainspec.json in $DB (listing: $(ls "$DB" | tr '\n' ' '))" | tee -a "$LOG"
sudo chown -R 1000:1000 "$DB"
echo "OK state root $root, genesis $gen" | tee -a "$LOG"
echo "rc=0" > "$DONE"
