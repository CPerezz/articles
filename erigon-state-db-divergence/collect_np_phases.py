#!/usr/bin/env python3
"""Split each test's measured newPayload time into the phases Erigon's own log marks.

benchmarkoor's log carries both its "RPC call completed" lines (host clock, UTC, with the call's
duration) and the client's log lines (Erigon's clock, the same host, millisecond resolution). Over
every newPayload of the test step (benchmarkoor's own timing sums them; most steps send one):
  before: request start to "[NewPayload] Handling new payload", the engine server's checks
  exec:   Erigon's "[5/5 Execution] parallel done in=<d>"
  rest:   whatever is left of benchmarkoor's duration (commitment, validation, the response)

Usage on the box: collect_np_phases.py <run-dir>... > phases.json
"""
import datetime as dt
import json
import re
import sys

STAMP = re.compile(r"(\d{4})-(\d\d-\d\dT[\d:.]+)Z")
STEP = re.compile(r"Running test step .*?test=(\S+)")
CALL = re.compile(r"RPC call completed .*?full_duration=(\S+) method=engine_newPayloadV\d")
ERIGON = re.compile(r"\[(\d\d)-(\d\d)\|([\d:.]+)\] (.*)")
DONE_IN = re.compile(r"\[5/5 Execution\] parallel done\s+in=(\S+)")
GO_DUR = re.compile(r"(\d+(?:\.\d+)?)(h|ms|µs|us|ns|m|s)")
UNIT = {"h": 3600, "m": 60, "s": 1, "ms": 1e-3, "µs": 1e-6, "us": 1e-6, "ns": 1e-9}


def go_secs(s):
    return sum(float(v) * UNIT[u] for v, u in GO_DUR.findall(s))


def ts(year, rest):
    return dt.datetime.fromisoformat(f"{year}-{rest}").timestamp()


def resolve(events, call):
    """One newPayload with the handling and execution lines inside its window. Erigon's execution
    line can land just after benchmarkoor's completion line, same millisecond."""
    end, total = call
    start = end - total
    hand = [t for k, t, _ in events if k == "handling" and start - 0.005 <= t <= end + 0.002]
    exe = [v for k, t, v in events if k == "exec" and start <= t <= end + 0.05]
    return total, (hand[-1] - start) if hand else None, exe[-1] if exe else None


def split(run):
    tests, test, events, calls = {}, None, [], []

    def close():
        if test is None or not calls:
            return
        parts = [resolve(events, c) for c in calls]
        ok = all(b is not None and e is not None for _, b, e in parts)
        tests[test] = {"calls": len(parts), "total_ms": 1e3 * sum(t for t, _, _ in parts),
                       "before_ms": 1e3 * sum(b for _, b, _ in parts) if ok else None,
                       "exec_ms": 1e3 * sum(e for _, _, e in parts) if ok else None}
    for line in open(run.rstrip("/") + "/benchmarkoor.log", errors="replace"):
        m = STEP.search(line)
        # The next test's setup block runs before its "Running test step"; it must not count here.
        if m or "Running setup step" in line:
            close()
            test, events, calls = (m.group(1) if m else None), [], []
            continue
        if test is None:
            continue
        s = STAMP.search(line)
        e = ERIGON.search(line)
        if e and s:
            t = ts(s.group(1), f"{e.group(1)}-{e.group(2)}T{e.group(3)}")
            if "Handling new payload" in e.group(4):
                events.append(("handling", t, None))
            elif DONE_IN.search(e.group(4)):
                events.append(("exec", t, go_secs(DONE_IN.search(e.group(4)).group(1))))
        m = CALL.search(line)
        if m and s:
            calls.append((ts(s.group(1), s.group(2)), go_secs(m.group(1))))
    close()
    return tests


def main():
    out = {run: split(run) for run in sys.argv[1:]}
    for run, t in out.items():
        ok = sum(1 for v in t.values() if v["before_ms"] is not None and v["exec_ms"] is not None)
        print(f"{run}: {len(t)} tests, {ok} with both phases", file=sys.stderr)
    json.dump(out, sys.stdout, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
