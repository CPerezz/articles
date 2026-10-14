#!/bin/bash
# Reth baseline pipeline, run on the host so it survives the operator's session:
#   state-actor boot gate (G2/G4) -> smoke on both arms (G6) -> J1 S1 J2 S2 -> reduce.
# Stops on a wrong head/genesis, any INVALID payload, or a schelk error. Each step logs to logs/.
set -u
B=/root/bench/reth; L=$B/logs; cd $B
IMG=docker.io/ethpandaops/reth:glamsterdam-devnet-7@sha256:dc8936043e0c327aae5aa18adb804c48ca290700ed1ca40ba589783c4d042a48
say() { echo "[$(date -Is)] $*" | tee -a $L/baseline.log; }
die() { say "STOP: $*"; exit 1; }
until grep -qE "SA-SETUP-DONE|G1-FAIL|generation failed|mismatch|read-only" $L/sa-setup.log 2>/dev/null; do sleep 60; done
grep -q SA-SETUP-DONE $L/sa-setup.log || die "state-actor setup did not finish: $(tail -1 $L/sa-setup.log)"

# --- G2/G4 on the state-actor store: genesis must be the Nethermind v2 genesis, no rewrite at boot
python3 - <<'PY'
import json
g = json.load(open("/schelk-sa/reth/chainspec.json")); c = g["config"]
c["amsterdamTime"] = 1
bs = c.get("blobSchedule") or {}
if bs and "amsterdam" not in bs:
    bs["amsterdam"] = bs[list(bs)[-1]]
json.dump(g, open("/root/bench/reth/cfg/sa-genesis-gate.json", "w"))
PY
SL=$(basename "$(python3 -c 'import json;print(json.load(open("/var/lib/schelk/reth-sa.json"))["scratch"])')")
./gate-boot.sh sa /schelk-sa/reth $B/cfg/sa-genesis-gate.json $IMG $SL reth_sa_era > $L/gate-sa.out 2>&1
cat $L/gate-sa.out | tee -a $L/baseline.log
grep -q "genesis=0x0cb035288eb4e257f34f3d570ed4f43f9d2fc45c09f19db6c0392f60f4a68623" $L/gate-sa/summary || die "state-actor genesis hash differs"
grep -q 'blockNumber=.*"0x0"' $L/gate-sa/summary || die "state-actor head is not block 0"
SCHELK_STATE=/var/lib/schelk/reth-sa.json schelk -y restore > $L/gate-sa-restore.log 2>&1 || die "schelk restore (sa) failed"
mountpoint -q /schelk-joc || SCHELK_STATE=/var/lib/schelk/reth-joc.json schelk -y mount >> $L/baseline.log 2>&1

# --- 1 s scratch-device sampler for the whole sequence (joined to per-test timestamps later)
JL=$(basename "$(python3 -c 'import json;print(json.load(open("/var/lib/schelk/reth-joc.json"))["scratch"])')")
nohup sh -c "while :; do echo \"\$(date +%s.%N) $JL \$(cat /sys/block/$JL/stat) | $SL \$(cat /sys/block/$SL/stat)\"; sleep 1; done" > $L/io-1s.log 2>&1 &
SAMPLER=$!

run() {  # run <cfg> <state> <log>
  say "run $1 start"
  env SCHELK_STATE=/var/lib/schelk/$2.json timeout 43200 benchmarkoor run --config cfg/$1.yaml > $L/$3.log 2>&1
  rc=$?
  inv=$(grep -c "status is INVALID\|INVALID_BLOCK\|\"INVALID\"" $L/$3.log)
  sch=$(grep -ciE "schelk.*(error|failed)" $L/$3.log)
  sum=$(grep -E "Test execution completed" $L/$3.log | tail -1 | grep -oE "failed=[0-9]+|passed=[0-9]+|total=[0-9]+" | tr "\n" " ")
  say "run $1 exit=$rc invalid=$inv schelk_err=$sch $sum free=$(df -m / | awk 'NR==2{print $4}')MB"
  podman ps -aq --filter name=benchmarkoor | xargs -r podman rm -f > /dev/null 2>&1
  [ "$inv" -eq 0 ] && [ "$sch" -eq 0 ] || die "run $1 had INVALID payloads or schelk errors"
}

# --- G6 smoke, both arms, a control and two state-reading tests at 160M
SMOKE='regex:(test_sload_bloated\[|opcode_BALANCE-value_sent_0-account_mode_AccountMode\.EXISTING_EOA-).*value_160M\]'
SMOKE="$SMOKE" python3 - <<'PY'
import os, re
for a in ("J", "S"):
    s = open(f"/root/bench/reth/cfg/{a}-smoke.yaml").read()
    s = re.sub(r"(?m)^      filter: .*$", lambda m: "      filter: '" + os.environ["SMOKE"] + "'", s)
    open(f"/root/bench/reth/cfg/{a}-smoke.run.yaml", "w").write(s)
PY
run J-smoke.run reth-joc j-smoke
run S-smoke.run reth-sa s-smoke
for s in j-smoke s-smoke; do
  grep -E "Test execution completed" $L/$s.log | grep -q "failed=0" || die "$s had failed tests"
done

# --- baseline: two independent pairs, jochemnet first in each
run J1 reth-joc j1
run S1 reth-sa s1
run J2 reth-joc j2
run S2 reth-sa s2
kill $SAMPLER
python3 $B/reth_reduce.py > $B/results/baseline.json 2> $L/reduce.err && say "reduced -> results/baseline.json" || say "reduce failed, see logs/reduce.err"
say BASELINE-DONE
