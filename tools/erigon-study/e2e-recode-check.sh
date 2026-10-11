#!/usr/bin/env bash
# Round 15, point 2, cross-check before the full-size re-encode: on the small e2e stores (round 14),
# re-encoding the published generator's storage and commitment files with compactlatest must give
# what the fixed generator (state-actor cbc1719) wrote itself: the same (key, value) streams, and
# byte-identical files if the two erigon pins' compressors agree (5f62f4ed here, 14273f79a6 in the
# builder). Also times each recode and samples its temp-dir peak, to size the full-size run.
# Usage: sudo e2e-recode-check.sh      Touches no scratch; never beside a suite.
set -uo pipefail

GO_IMG=docker.io/library/golang:1.25-bookworm
C=/bench/erigon/compact
E=/bench/erigon/e2e
W=$E/recode
LOG=/bench/erigon/logs/e2e-recode-check.log
OUTJ=$E/recode-check.json
cd /
exec >> "$LOG" 2>&1
fail() { echo "FAIL $1 ($(date -Is))"; exit 1; }
pgrep -x benchmarkoor >/dev/null && fail "a suite is running"
tool() { podman run --rm --user 1000:1000 -e HOME=/tmp -v "$C":"$C" -v "$E":"$E" "$GO_IMG" "$C/bin/$@"; }
echo "======== e2e recode check: $(date -Is) ========"

rm -rf "$W" && mkdir -p "$W" && cp -a "$E/old" "$W/data" && chown -R 1000:1000 "$W"
for d in storage commitment; do
  mkdir -p "$W/tmp-$d" && chown 1000:1000 "$W/tmp-$d"
  ( peak=0; while sleep 1; do s=$(du -sb "$W/tmp-$d" "$W/staging-$d" 2>/dev/null | awk '{t+=$1} END {print t+0}'); [ "$s" -gt "$peak" ] && peak=$s && echo "$peak" > "$W/peak-$d"; done ) &
  mon=$!
  t0=$(date +%s.%N)
  tool compactlatest recode --domain "$d" --datadir "$W/data" --dst "$W/staging-$d" --tmp "$W/tmp-$d" \
    --samples "$W/samples-$d.txt" --sample-every 1000 > "$W/report-$d.json" || { kill $mon; fail "recode $d"; }
  t1=$(date +%s.%N)
  kill $mon
  echo "$d recode $(echo "$t1 - $t0" | bc) s, temp+staging peak $(cat "$W/peak-$d") B"
  for s in old new; do
    tool compactlatest streamhash --domain "$d" --datadir "$W/data" --kv "$E/$s/snapshots/domain/v1.0-$d.0-1.kv" > "$W/hash-$d-$s.json" || fail "streamhash $d $s"
  done
  ls -la "$W/staging-$d"
done

python3 - "$W" "$E" > "$OUTJ" <<'EOF' || fail "compare"
import filecmp, glob, json, os, sys
W, E = sys.argv[1:]
out = {}
for d in ("storage", "commitment"):
    rep = json.load(open(f"{W}/report-{d}.json"))[d]
    old, new = (json.load(open(f"{W}/hash-{d}-{s}.json"))[d] for s in ("old", "new"))
    files = {}
    for p in sorted(glob.glob(f"{W}/staging-{d}/*")):
        n = os.path.basename(p)
        ref = f"{E}/new/snapshots/domain/{n}"
        files[n] = {"bytes": os.path.getsize(p), "new_bytes": os.path.getsize(ref) if os.path.exists(ref) else None,
                    "identical_to_new": os.path.exists(ref) and filecmp.cmp(p, ref, shallow=False)}
    out[d] = {"keys": rep["keys"], "stream_recoded": rep["sha256"], "stream_old": old["sha256"],
              "stream_new": new["sha256"], "old_kv_bytes": os.path.getsize(f"{E}/old/snapshots/domain/v1.0-{d}.0-1.kv"),
              "temp_peak_bytes": int(open(f"{W}/peak-{d}").read().strip()), "files": files}
json.dump(out, sys.stdout, indent=1, sort_keys=True)
EOF
cat "$OUTJ"
python3 - "$OUTJ" <<'EOF' || fail "streams differ"
import json, sys
r = json.load(open(sys.argv[1]))
ok = all(v["stream_recoded"] == v["stream_old"] == v["stream_new"] for v in r.values())
print("streams equal:", ok, "| byte-identical:", {d: all(f["identical_to_new"] for f in v["files"].values()) for d, v in r.items()})
sys.exit(0 if ok else 1)
EOF
echo "rc=0 $(date -Is)"
