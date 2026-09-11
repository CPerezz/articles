#!/usr/bin/env python3
"""Extract per-test metrics from benchmarkoor result trees into one comparable table.

Everything needed is in each run's `result.json`: it maps the FULL pytest id to the aggregated
metrics for each step. Two things make that the only correct source:

  - result directory names are truncated and hash-suffixed
    (`...-overhead_base-10a14f08e594b0ba`), so the gas label and trailing fields are absent
    from the path -- parsing paths silently yields uncategorised rows;
  - `tests[id]["steps"]["test"]["aggregated"]` already carries the metrics, so no directory
    walking is needed at all.

The `test` step is the measurement; `setup` is the fixture's preparatory block and is reported
separately rather than summed into it.

Account-read counts are NOT available here -- they live in Besu's metrics endpoint, which the
harness does not scrape -- so P5 needs its own probe rather than a column invented in this file.

Usage: extract_arms.py <label>=<run-dir> [...] > arms.json
"""
import json
import os
import re
import sys

FIELDS = re.compile(
    r"opcode_(?P<opcode>[A-Z0-9]+)"
    r"|value_sent_(?P<value_sent>\d+)"
    r"|account_mode_AccountMode\.(?P<mode>[A-Z_]+)"
    r"|overhead_baseline_(?P<baseline>True|False)"
    r"|cache_strategy_CacheStrategy\.(?P<cache>[A-Z_]+)"
    r"|gas-value_(?P<gas>\d+)M"
)


def parse_id(test_id):
    out = {}
    for m in FIELDS.finditer(test_id):
        for k, v in m.groupdict().items():
            if v is not None:
                out[k] = v
    return out


def row(test_id, agg, step):
    ns = agg.get("gas_used_time_total") or agg.get("time_total")
    gas = agg.get("gas_used_total")
    if not ns or not gas:
        return None
    rt = agg.get("resource_totals", {})
    r = parse_id(test_id)
    r.update(
        test_id=test_id,
        step=step,
        mgas_s=gas / (ns / 1e9) / 1e6,
        gas_used=gas,
        wall_ns=ns,
        disk_read_bytes=rt.get("disk_read_bytes", 0),
        disk_read_iops=rt.get("disk_read_iops", 0),
        disk_write_bytes=rt.get("disk_write_bytes", 0),
        cpu_usec=rt.get("cpu_usec", 0),
        success=agg.get("success", 0),
        fail=agg.get("fail", 0),
    )
    return r


def collect(run_dir, step="test"):
    index = json.load(open(os.path.join(run_dir, "result.json")))["tests"]
    rows = []
    for test_id, meta in index.items():
        agg = (meta.get("steps", {}).get(step) or {}).get("aggregated")
        if not agg:
            continue
        r = row(test_id, agg, step)
        if r:
            rows.append(r)
    return rows


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    arms = {}
    for arg in sys.argv[1:]:
        label, _, path = arg.partition("=")
        rows = collect(path)
        arms[label] = rows
        uncategorised = sum(1 for r in rows if "opcode" not in r or "mode" not in r)
        print(
            f"{label}: {len(rows)} tests, {sum(r['fail'] for r in rows)} failed, "
            f"{uncategorised} uncategorised",
            file=sys.stderr,
        )
    json.dump(arms, sys.stdout)


if __name__ == "__main__":
    main()
