#!/usr/bin/env python3
"""Compare the RocksDB configuration of the two Nethermind snapshots, database by database
and column family by column family.

Reads each store's own OPTIONS file (plain text, written by whoever last opened the DB), so
this reflects what the store was actually built/opened with — not what we think we configured.

Usage: cmp_rocksdb.py <state_actor_datadir> <jochemnet_datadir>
"""
import os, sys, glob
from collections import OrderedDict

# Keys that change point-lookup cost. A difference in any of these would, on its own,
# explain a large read-amplification gap.
CRITICAL = [
    "filter_policy", "whole_key_filtering", "block_size", "index_type",
    "data_block_index_type", "format_version", "compression",
    "bottommost_compression", "optimize_filters_for_hits", "prefix_extractor",
    "cache_index_and_filter_blocks", "pin_l0_filter_and_index_blocks_in_cache",
    "block_restart_interval", "no_block_cache", "partition_filters",
    "max_bytes_for_level_base", "target_file_size_base", "write_buffer_size",
    "level0_file_num_compaction_trigger", "num_levels", "compression_per_level",
]


def parse(path):
    """OPTIONS file -> {section: {key: value}}"""
    out = OrderedDict()
    cur = None
    with open(path, errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                cur = line
                out.setdefault(cur, {})
                continue
            if cur and "=" in line:
                k, v = line.split("=", 1)
                out[cur][k.strip()] = v.strip()
    return out


def latest_options(dbdir):
    files = glob.glob(os.path.join(dbdir, "OPTIONS-*"))
    return max(files, key=lambda p: os.path.getmtime(p)) if files else None


def main():
    sa_root, joc_root = sys.argv[1], sys.argv[2]
    sa_dbs = {d for d in os.listdir(sa_root) if os.path.isdir(os.path.join(sa_root, d))}
    joc_dbs = {d for d in os.listdir(joc_root) if os.path.isdir(os.path.join(joc_root, d))}
    common = sorted(sa_dbs & joc_dbs)
    print(f"databases only in state-actor : {sorted(sa_dbs - joc_dbs)}")
    print(f"databases only in jochemnet   : {sorted(joc_dbs - sa_dbs)}")
    print(f"databases in both             : {common}\n")

    for db in common:
        sa_o, joc_o = latest_options(os.path.join(sa_root, db)), latest_options(os.path.join(joc_root, db))
        if not sa_o or not joc_o:
            print(f"### {db}: OPTIONS missing (sa={bool(sa_o)} joc={bool(joc_o)})\n")
            continue
        A, B = parse(sa_o), parse(joc_o)
        print(f"### {db}   SA:{os.path.basename(sa_o)}   JOC:{os.path.basename(joc_o)}")
        secs = [s for s in (set(A) | set(B)) if s.startswith("[CFOptions") or s.startswith("[TableOptions")
                or s == "[DBOptions]"]
        total_diff = 0
        for sec in sorted(secs):
            a, b = A.get(sec, {}), B.get(sec, {})
            keys = sorted(set(a) | set(b))
            diff = [k for k in keys if a.get(k) != b.get(k)]
            crit = [k for k in diff if k in CRITICAL]
            total_diff += len(diff)
            if crit:
                print(f"  {sec}  ({len(diff)} differing keys, {len(crit)} CRITICAL)")
                for k in crit:
                    print(f"      !! {k:<40} SA={a.get(k,'-'):<26} JOC={b.get(k,'-')}")
            elif diff:
                print(f"  {sec}  ({len(diff)} differing keys, none critical): {diff[:6]}")
        if total_diff == 0:
            print("  IDENTICAL across all sections")
        print()


if __name__ == "__main__":
    main()
