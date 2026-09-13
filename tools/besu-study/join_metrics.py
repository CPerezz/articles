#!/usr/bin/env python3
"""Join scraped Besu counters to test ids, positionally.

`rollback_strategy: container-recreate` gives exactly one container per test and resets the
counters with it, so a container's final values are that test's totals. The scraper records
containers in first-seen order; the suite executes tests in result.json order. Zip.

The join is checked, not assumed: if the counts differ the script says so and emits nothing,
because a silently misaligned join would attribute one test's reads to another.

Usage: join_metrics.py <metrics.json> <run-dir> [label]
"""
import json
import os
import re
import sys

metrics = json.load(open(sys.argv[1]))
run_dir = sys.argv[2]
label = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(run_dir.rstrip("/"))

index = json.load(open(os.path.join(run_dir, "result.json")))["tests"]
tests = list(index)

# The first container is the one benchmarkoor boots before the first test's own container in
# some runs; drop leading containers until the counts line up from the tail.
order = metrics["order"]
if len(order) > len(tests):
    order = order[len(order) - len(tests):]

if len(order) != len(tests):
    print(f"JOIN MISMATCH: {len(order)} containers vs {len(tests)} tests -- not emitting",
          file=sys.stderr)
    sys.exit(1)

FIELDS = re.compile(
    r"opcode_(?P<opcode>[A-Z0-9]+)"
    r"|value_sent_(?P<value_sent>\d+)"
    r"|account_mode_AccountMode\.(?P<mode>[A-Z_]+)"
    r"|gas-value_(?P<gas>\d+)M"
)

out = []
for name, test_id in zip(order, tests):
    c = {k: v for k, v in metrics["containers"].get(name, {}).items() if not k.startswith("_")}
    if not c:
        continue
    r = {}
    for m in FIELDS.finditer(test_id):
        for k, v in m.groupdict().items():
            if v is not None:
                r[k] = v
    agg = (index[test_id].get("steps", {}).get("test") or {}).get("aggregated") or {}
    rt = agg.get("resource_totals", {})
    r.update(
        test_id=test_id,
        container=name,
        reads=c.get("besu_blockchain_get_account_total", 0),
        reads_flat=c.get("besu_blockchain_get_account_flat_database_total", 0),
        reads_missing=c.get("besu_blockchain_get_account_missing_flat_database_total", 0),
        cache_hits=c.get("besu_blockchain_bonsai_cache_hits_total", 0),
        cache_misses=c.get("besu_blockchain_bonsai_cache_misses_total", 0),
        gas_used=agg.get("gas_used_total", 0),
        wall_ns=agg.get("gas_used_time_total") or agg.get("time_total", 0),
        disk_read_bytes=rt.get("disk_read_bytes", 0),
    )
    out.append(r)

print(f"{label}: joined {len(out)} tests", file=sys.stderr)
json.dump(out, sys.stdout)
