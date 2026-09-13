#!/usr/bin/env bash
# Supervises the detached intervention run and classifies it the moment it lands, so the
# analysis does not depend on anyone holding an SSH session open. Lives in tmux ("joc") for
# attachability; the benchmark itself is already systemd-parented and independent of both.
set -uo pipefail
LOG=/bench/logs/baseline-joc-compacted.log
MON=/bench/logs/joc-monitor.log
OUT=/bench/logs/joc-compacted-classification.txt
SA=/bench/results/nm-state-actor
JOC=/bench/results/nm-joc-compacted

say() { echo "[$(date -Is)] $*" | tee -a "$MON"; }

say "supervisor up; watching $LOG"

while true; do
  done_n=$(grep -ac "Test completed" "$LOG" 2>/dev/null); done_n=${done_n:-0}
  fails=$(grep -ac "Response validation failed" "$LOG" 2>/dev/null); fails=${fails:-0}
  alive=$(pgrep -fc "benchmarkoor run" 2>/dev/null); alive=${alive:-0}
  load=$(cut -d' ' -f1-3 /proc/loadavg)
  free=$(df -h /schelk-joc | awk 'NR==2{print $4}')
  say "tests=${done_n}/1463 failures=${fails} benchmarkoor_procs=${alive} load=${load} free=${free}"

  if [ "$alive" -eq 0 ] && [ "$done_n" -gt 100 ]; then
    say "run finished (or exited); classifying"
    break
  fi
  # A dead process with almost no progress means it died on startup, not that it completed.
  if [ "$alive" -eq 0 ] && [ "$done_n" -le 100 ]; then
    say "WARNING: benchmarkoor gone after only ${done_n} tests - investigate, not classifying"
    sleep 600
    continue
  fi
  sleep 300
done

{
  echo "################ intervention arm vs state-actor ################"
  echo "### generated $(date -Is)"
  echo
  echo "### tail of run log"
  tail -6 "$LOG"
  echo
  echo "################ exact-id bucketing (agree <=10% vs divergent) ################"
  python3 /home/ubuntu/buckets.py "$JOC" "$SA" 2>&1
  echo
  echo "################ physical evidence per category ################"
  python3 /home/ubuntu/buckets2.py "$JOC" "$SA" 2>&1
  echo
  echo "################ category medians ################"
  python3 /home/ubuntu/classify.py "$JOC" "$SA" 2>&1
} > "$OUT" 2>&1

say "classification written to $OUT"
say "supervisor idle; results are durable on disk"
while true; do sleep 3600; done
