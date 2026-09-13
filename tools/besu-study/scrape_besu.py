#!/usr/bin/env python3
"""Sample Besu's account-read counters per test, alongside a running benchmarkoor suite.

benchmarkoor does not scrape the client's metrics endpoint, so the suite results carry bytes
and time but not *reads*. Without reads we can only say the arms were asked for the same work
(gas identity), not that they performed the same number of lookups -- which is the difference
between the geth article's "51,565 vs 51,562 accounts read, 1.119x bytes" and a much weaker
claim.

`rollback_strategy: container-recreate` gives one container per test and resets the counters
with it, so each container's final values ARE that test's totals. Containers are recorded in
first-seen order; the suite executes tests in result.json order, so the two zip positionally.
Polling at 2 s against ~60 s tests makes a missed container implausible.

Usage: scrape_besu.py <out.jsonl> [poll_seconds]
"""
import json
import subprocess
import sys
import time

OUT = sys.argv[1]
POLL = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0

KEYS = (
    "besu_blockchain_get_account_total",
    "besu_blockchain_get_account_flat_database_total",
    "besu_blockchain_get_account_missing_flat_database_total",
    "besu_blockchain_get_storagevalue_flat_database_total",
    "besu_blockchain_get_storagevalue_missing_flat_database_total",
    "besu_blockchain_bonsai_cache_hits_total",
    "besu_blockchain_bonsai_cache_misses_total",
)


def sh(*args, timeout=10):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


ips = {}
seen = {}
order = []

while True:
    names = [n for n in sh("podman", "ps", "--format", "{{.Names}}").splitlines()
             if n.startswith("benchmarkoor-")]
    for n in names:
        if n not in ips:
            ips[n] = sh("podman", "inspect", "-f",
                        "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", n)
            order.append(n)
        ip = ips[n]
        if not ip:
            continue
        body = sh("curl", "-s", "-m", "3", f"http://{ip}:8008/metrics", timeout=6)
        if not body:
            continue
        vals = {}
        for line in body.splitlines():
            if not line or line[0] == "#":
                continue
            k, _, v = line.partition(" ")
            if k in KEYS:
                try:
                    vals[k] = float(v)
                except ValueError:
                    pass
        if not vals:
            continue
        # counters only advance within a container's life, so max == final
        cur = seen.setdefault(n, {})
        for k, v in vals.items():
            if v > cur.get(k, -1):
                cur[k] = v
        cur["_last_seen"] = time.time()

    with open(OUT, "w") as fh:
        json.dump({"order": order, "containers": seen}, fh)
    time.sleep(POLL)
