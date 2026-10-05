#!/usr/bin/env bash
# Step 0 (ledger round 8): which file every page a test reads comes from.
#
# Runs the four traced tests (trace-tests.regex) as one benchmarkoor suite on one arm, with the
# kernel's filemap:mm_filemap_add_to_page_cache event filtered to that arm's dm device. Each event
# is one page (or folio) read into the page cache, so it sees erigon's mmap reads of mdbx.dat and of
# the frozen files alike. The page cache is dropped before every test step (drop_memory_caches:
# steps), so the events inside a step's window are what that step read from disk. Afterwards the
# scratch is restored and listed (inode, size, path): the inode map and the tier inventory.
#
# Usage: sudo trace-tests.sh joc|sa <tag>     Never run beside a suite (.busy).
set -uo pipefail

ARM="${1:?arm}"; TAG="${2:?tag}"
STATE=/var/lib/schelk/er-$ARM.json
SRC=/bench/erigon/tools/er-$ARM-B.yaml
DAY=$(date -u +%Y%m%d)
CFG=/bench/cfg/er-$ARM-$TAG.yaml
OUT=/bench/erigon/trace/$ARM-$TAG
LOG=/bench/erigon/logs/trace-$ARM-$TAG.log
DONE=/bench/erigon/logs/trace-$ARM-$TAG.done
FAIL=/bench/erigon/logs/trace-$ARM-$TAG.fail
BUSY=/bench/erigon/.busy
T=/sys/kernel/tracing
EV=$T/events/filemap/mm_filemap_add_to_page_cache

rm -f "$DONE" "$FAIL"
cd /
fail() { echo "FAIL $1" | tee -a "$LOG"; echo "$1" > "$FAIL"; exit 1; }

while [ -f "$BUSY" ] || pgrep -x benchmarkoor >/dev/null; do sleep 60; done
echo "trace-$ARM-$TAG" > "$BUSY"
# Tracing must never outlive the script: a filtered event left enabled would keep logging.
untrace() {
  echo 0 > $T/tracing_on; echo 0 > $EV/enable; echo 0 > $EV/filter
  [ -n "${CAT_PID:-}" ] && kill "$CAT_PID" 2>/dev/null; CAT_PID=
}
trap 'untrace; rm -f "$BUSY"' EXIT

mkdir -p "$OUT"
FILTER=$(cat /bench/erigon/tools/trace-tests.regex)
python3 - "$SRC" "$CFG" "$ARM" "$TAG" "$DAY" "$FILTER" <<'EOF'
import sys
src, cfg, arm, tag, day, flt = sys.argv[1:]
s = open(src).read()
s = s.replace(f"er-{arm}-B-RUNDATE", f"er-{arm}-{tag}-{day}").replace(f"id: er-{arm}-B\n", f"id: er-{arm}-{tag}\n")
s = s.replace(f"name: er-{arm}-B-", f"name: er-{arm}-{tag}-")
old = "      filter: 'regex:(160M|240M)'\n"
assert old in s, "filter line not found"
s = s.replace(old, "      filter: 'regex:" + flt.replace("'", "''") + "'\n")
open(cfg, "w").write(s)
EOF
[ -s "$CFG" ] || fail "config not written"

# The scratch's dm device, as the kernel's dev_t (major << 20 | minor) the event filter compares.
dm=$(readlink -f /dev/mapper/er_${ARM}_era)
maj=$((16#$(stat -c %t "$dm"))); min=$((16#$(stat -c %T "$dm")))
devt=$(( (maj << 20) | min ))
{
  echo "======== trace $ARM $TAG: $(date -Is) ========"
  echo "config : $CFG ($(sha256sum "$CFG" | cut -d' ' -f1))"
  echo "device : $dm $maj:$min dev_t $devt"
  cat $EV/format | grep -E "field:" 
} >> "$LOG" 2>&1

echo 0 > $T/tracing_on; echo > $T/trace
echo 32768 > $T/buffer_size_kb
echo "s_dev == $devt" > $EV/filter || fail "event filter rejected"
echo 1 > $EV/enable
cat $T/trace_pipe > "$OUT/trace.txt" &
CAT_PID=$!
echo 1 > $T/tracing_on
echo "WALL $(date +%s.%N)" > $T/trace_marker
env SCHELK_STATE="$STATE" benchmarkoor run --config "$CFG" >> "$LOG" 2>&1
echo "benchmarkoor rc=$?" >> "$LOG"
echo "WALL $(date +%s.%N)" > $T/trace_marker
sleep 3
untrace
grep -q "benchmarkoor rc=0" "$LOG" || fail "benchmarkoor failed"
echo "events: $(grep -c mm_filemap_add_to_page_cache "$OUT/trace.txt")" >> "$LOG"

# Inode map and inventory from the store as promoted.
schelk restore -y --state-path "$STATE" >> "$LOG" 2>&1 || fail "restore"
findmnt -n "/schelk-er-$ARM" >/dev/null || fail "not mounted after restore"
find "/schelk-er-$ARM" -xdev -type f -printf '%i %s %p\n' > "$OUT/files.txt"
cp "$CFG" "$OUT/"
ls -d /bench/results/er-$ARM-$TAG-$DAY/runs/*/ > "$OUT/run_dir.txt"
echo "files: $(wc -l < "$OUT/files.txt")" >> "$LOG"
echo "rc=0" > "$DONE"
