#!/usr/bin/env python3
"""Page-fill gate for a regenerated reth store: never bench a miscalibrated store.
usage: gatecheck.py <mdbxmap stats> <fillgate json> <targets json>
targets json: {"<metric>": [lo, hi], ...}; metric names are the keys of `metrics` below.
Prints every metric with its range; exits 1 if any is out of range or missing."""
import ast
import json
import re
import sys

stats = {}
for line in open(sys.argv[1]):
    m = re.match(r"^(\w+) (\{.*\}) branch_fill=(\S+) leaf_fill=(\S+)", line)
    if m:
        d = ast.literal_eval(m.group(2))
        d["leaf_fill"] = None if m.group(4) == "None" else float(m.group(4))
        stats[m.group(1)] = d
fg = json.load(open(sys.argv[2]))
targets = json.load(open(sys.argv[3]))


def dig(o, *path):
    for p in path:
        if not isinstance(o, dict) or p not in o:
            return None
        o = o[p]
    return o


metrics = {
    "HashedAccounts.leaf_fill": dig(stats, "HashedAccounts", "leaf_fill"),
    "AccountsTrie.leaf_fill": dig(stats, "AccountsTrie", "leaf_fill"),
    "bloated.HashedStorages.height": dig(fg, "bloated", "HashedStorages", "descriptor", "height"),
    "bloated.HashedStorages.items": dig(fg, "bloated", "HashedStorages", "descriptor", "items"),
    "bloated.HashedStorages.leaf_fill": dig(fg, "bloated", "HashedStorages", "leaf_fill", "mean"),
    "bloated.StoragesTrie.height": dig(fg, "bloated", "StoragesTrie", "descriptor", "height"),
    "bloated.StoragesTrie.items": dig(fg, "bloated", "StoragesTrie", "descriptor", "items"),
    "bloated.StoragesTrie.leaf_fill": dig(fg, "bloated", "StoragesTrie", "leaf_fill", "mean"),
    "midsize.HashedStorages.leaf_fill": dig(fg, "midsize", "HashedStorages", "per_tree_leaf_fill", "mean"),
    "main.StoragesTrie.leaf_fill": dig(fg, "main_trees", "StoragesTrie", "leaf_fill_uniform", "mean"),
}
bad = 0
for name, (lo, hi) in targets.items():
    v = metrics.get(name)
    ok = v is not None and lo <= v <= hi
    bad += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name:36} {v!s:>14}  in [{lo}, {hi}]")
# Informational: what the gate does not bound.
for name in ("HashedStorages", "StoragesTrie"):
    print(f"info main tree {name}: leaf fill {dig(fg, 'main_trees', name, 'leaf_fill_uniform', 'mean')}, "
          f"height {dig(fg, 'main_trees', name, 'height')}")
sys.exit(1 if bad else 0)
