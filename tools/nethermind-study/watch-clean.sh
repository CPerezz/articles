#!/usr/bin/env bash
# Supervises the Phase 2 subset run and classifies it on completion, so the result does not
# depend on anyone holding an SSH session (this box drops them under benchmark I/O).
set -uo pipefail
LOG=/bench/logs/baseline-joc-clean.log
MON=/bench/logs/joc-clean-monitor.log
OUT=/bench/logs/joc-clean-classification.txt
SA=/bench/results/nm-state-actor
JOC=/bench/results/nm-joc-clean

say() { echo "[$(date -Is)] $*" | tee -a "$MON"; }
say "supervisor up; watching $LOG"

while true; do
  done_n=$(grep -ac "Test completed" "$LOG" 2>/dev/null); done_n=${done_n:-0}
  fails=$(grep -ac "Response validation failed" "$LOG" 2>/dev/null); fails=${fails:-0}
  alive=$(pgrep -fc "benchmarkoor run" 2>/dev/null); alive=${alive:-0}
  say "tests=${done_n}/266 failures=${fails} procs=${alive} load=$(cut -d' ' -f1-3 /proc/loadavg)"
  if [ "$alive" -eq 0 ] && [ "$done_n" -gt 50 ]; then
    say "run finished; classifying"; break
  fi
  if [ "$alive" -eq 0 ] && [ "$done_n" -le 50 ]; then
    say "WARNING: benchmarkoor gone after only ${done_n} tests - not classifying"; sleep 600; continue
  fi
  sleep 180
done

{
  echo "################ PHASE 2 (corrected options) vs state-actor ################"
  echo "### generated $(date -Is)"
  tail -5 "$LOG"
  echo
  echo "################ exact-id bucketing ################"
  python3 /home/ubuntu/buckets.py "$JOC" "$SA" 2>&1
  echo
  echo "################ physical evidence per category ################"
  python3 /home/ubuntu/buckets2.py "$JOC" "$SA" 2>&1
} > "$OUT" 2>&1

say "classification written to $OUT"
while true; do sleep 3600; done
