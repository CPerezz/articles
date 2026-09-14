#!/usr/bin/env python3
"""Print the read-path options a store actually uses, per column family.

Source of truth for rebuilding jochemnet's SSTs: round 10 established that before any of my
edits, the two stores matched on every read-path knob except max_bytes_for_level_base
(SA 128 MB vs JOC 67 MB), so state-actor's OPTIONS is the faithful template.
"""
import glob
import os
import re
import sys

TABLE_KEYS = ("filter_policy", "whole_key_filtering", "block_size", "block_restart_interval",
              "data_block_index_type", "format_version", "index_type",
              "cache_index_and_filter_blocks", "pin_l0_filter_and_index_blocks_in_cache",
              "no_block_cache")
CF_KEYS = ("compression", "target_file_size_base", "target_file_size_multiplier",
           "max_bytes_for_level_base", "level_compaction_dynamic_level_bytes")


def newest(path):
    files = glob.glob(os.path.join(path, "OPTIONS-*"))
    return max(files, key=os.path.getmtime) if files else None


def section(txt, header):
    m = re.search(re.escape(header) + r"\](.*?)(?=\n\[|\Z)", txt, re.S)
    return m.group(1) if m else ""


def show(label, path, cf):
    f = newest(path)
    if not f:
        print(f"  {label}: no OPTIONS file")
        return
    txt = open(f).read()
    print(f"  --- {label}  ({os.path.basename(f)})  CF={cf}")
    for keys, hdr in ((TABLE_KEYS, f'[TableOptions/BlockBasedTable "{cf}"'),
                      (CF_KEYS, f'[CFOptions "{cf}"')):
        sec = section(txt, hdr)
        for k in keys:
            m = re.search(r"^\s*" + k + r"=(.*)$", sec, re.M)
            val = m.group(1).strip() if m else "(absent)"
            print("      %-44s %s" % (k, val))


if __name__ == "__main__":
    cf = sys.argv[1] if len(sys.argv) > 1 else "Account"
    show("state-actor", "/schelk-sa/state-actor/v1/nethermind/flat", cf)
    show("jochemnet", "/schelk-joc/snapshots/nethermind/24402727/mainnet/flat", cf)
