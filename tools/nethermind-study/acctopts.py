#!/usr/bin/env python3
"""Compare the read-path-critical RocksDB table options for chosen column families
between the two Nethermind snapshots."""
import glob, os, sys

SA_DIR = "/schelk-sa/state-actor/v1/nethermind/flat"
JOC_DIR = "/schelk-joc/snapshots/nethermind/24402727/mainnet/flat"

KEYS = [
    "filter_policy", "whole_key_filtering", "block_size", "index_type",
    "partition_filters", "cache_index_and_filter_blocks",
    "pin_l0_filter_and_index_blocks_in_cache", "format_version",
    "data_block_index_type", "block_restart_interval", "no_block_cache",
    "metadata_block_size", "optimize_filters_for_hits", "compression",
    "prefix_extractor", "target_file_size_base", "target_file_size_multiplier",
    "max_bytes_for_level_base", "num_levels", "level_compaction_dynamic_level_bytes",
]


def sections(path):
    out, cur = {}, None
    for line in open(path, errors="ignore"):
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            cur = line
            out.setdefault(cur, {})
            continue
        if cur and "=" in line:
            k, v = line.split("=", 1)
            out[cur][k.strip()] = v.strip()
    return out


def latest(d):
    return max(glob.glob(os.path.join(d, "OPTIONS-*")), key=os.path.getmtime)


def main():
    cfs = sys.argv[1:] or ["Account", "Storage"]
    A, B = sections(latest(SA_DIR)), sections(latest(JOC_DIR))
    for cf in cfs:
        for kind in ("TableOptions/BlockBasedTable", "CFOptions"):
            hdr = '[%s "%s"]' % (kind, cf)
            a, b = A.get(hdr, {}), B.get(hdr, {})
            if not a and not b:
                continue
            print("=== %s" % hdr)
            for k in KEYS:
                if k in a or k in b:
                    same = a.get(k) == b.get(k)
                    print("  %-44s SA=%-24s JOC=%-24s%s"
                          % (k, a.get(k, "-"), b.get(k, "-"), "" if same else "  <<< DIFF"))
            print()


if __name__ == "__main__":
    main()
