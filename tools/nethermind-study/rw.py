#!/usr/bin/env python3
"""Read vs write volume per matched measured test, per arm.

Heavy writes on one arm only would indicate background compaction running during the
measurement — which would inflate read I/O without any extra lookups.
"""
import json, glob, os, re, sys
from statistics import median


def load(root):
    best, bn = None, -1
    for rj in glob.glob(os.path.join(root, "runs", "*", "result.json")):
        try:
            n = len(json.load(open(rj)).get("tests", {}))
        except Exception:
            continue
        if n > bn:
            best, bn = rj, n
    out = {}
    for tid, meta in json.load(open(best))["tests"].items():
        a = ((meta.get("steps") or {}).get("test") or {}).get("aggregated") or {}
        if a.get("fail") or not a.get("gas_used_total"):
            continue
        r = a.get("resource_totals", {})
        out[tid] = {
            "read": r.get("disk_read_bytes", 0),
            "write": r.get("disk_write_bytes", 0),
            "riops": r.get("disk_read_iops", 0),
            "wiops": r.get("disk_write_iops", 0),
            "mem": r.get("memory_bytes", 0),
        }
    return out


def main():
    joc, sa = load(sys.argv[1]), load(sys.argv[2])
    com = [t for t in set(joc) & set(sa) if re.search(r"overhead_baseline_False", t)]
    print("matched measured tests:", len(com))
    print(f"{'arm':<13}{'readMB':>9}{'writeMB':>10}{'W/R':>7}"
          f"{'readIOPS':>10}{'writeIOPS':>11}{'memGB':>8}")
    for nm, src in (("jochemnet", joc), ("state-actor", sa)):
        rd = median(src[t]["read"] for t in com)
        wr = median(src[t]["write"] for t in com)
        print(f"{nm:<13}{rd/1e6:>9.0f}{wr/1e6:>10.0f}{wr/max(rd,1):>7.2f}"
              f"{median(src[t]['riops'] for t in com):>10.0f}"
              f"{median(src[t]['wiops'] for t in com):>11.0f}"
              f"{median(src[t]['mem'] for t in com)/1e9:>8.1f}")


if __name__ == "__main__":
    main()
