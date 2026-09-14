#!/usr/bin/env bash
# Generic run supervisor: watch-run.sh <tag> <total>
# Watches /bench/logs/baseline-<tag>.log, then classifies /bench/results/nm-<tag> against the
# state-actor arm. Lives in tmux so the result does not depend on an SSH session surviving.
set -uo pipefail
TAG=${1:?tag required}
TOTAL=${2:?total required}
LOG=/bench/logs/baseline-${TAG}.log
MON=/bench/logs/${TAG}-monitor.log
OUT=/bench/logs/${TAG}-classification.txt
SA=/bench/results/nm-state-actor
ARM=/bench/results/nm-${TAG}

say() { echo "[$(date -Is)] $*" | tee -a "$MON"; }
say "supervisor up for ${TAG}; watching $LOG"

while true; do
  done_n=$(grep -ac "Test completed" "$LOG" 2>/dev/null); done_n=${done_n:-0}
  fails=$(grep -ac "Response validation failed" "$LOG" 2>/dev/null); fails=${fails:-0}
  alive=$(pgrep -fc "benchmarkoor run" 2>/dev/null); alive=${alive:-0}
  say "tests=${done_n}/${TOTAL} failures=${fails} procs=${alive} load=$(cut -d' ' -f1-3 /proc/loadavg)"
  # A dead process with almost nothing done is a startup failure, not a completed run.
  if [ "$alive" -eq 0 ] && [ "$done_n" -gt 100 ]; then say "finished; classifying"; break; fi
  if [ "$alive" -eq 0 ] && [ "$done_n" -le 100 ]; then
    say "WARNING: benchmarkoor gone after only ${done_n} tests - not classifying"; sleep 600; continue
  fi
  sleep 300
done

{
  echo "################ ${TAG} vs state-actor ################"
  echo "### generated $(date -Is)"
  tail -5 "$LOG"
  echo; echo "################ exact-id bucketing ################"
  python3 /home/ubuntu/buckets.py "$ARM" "$SA" 2>&1
  echo; echo "################ physical evidence per category ################"
  python3 /home/ubuntu/buckets2.py "$ARM" "$SA" 2>&1
  echo; echo "################ remaining divergence, decomposed ################"
  python3 /home/ubuntu/outliers.py "$ARM" "$SA" 2>&1
  echo; echo "################ additive vs multiplicative excess ################"
  python3 /home/ubuntu/additive.py "$ARM" "$SA" 2>&1
} > "$OUT" 2>&1

say "classification written to $OUT"
while true; do sleep 3600; done
