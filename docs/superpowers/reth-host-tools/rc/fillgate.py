#!/usr/bin/env python3
"""Fill gate for a reth mdbx.dat (libmdbx 0.13, 4 KiB pages), read-only via pread.

usage: python3 rc/fillgate.py <mdbx.dat> [--sample N] [--seed S]

Prints one JSON object:
  bloated    nested HashedStorages/StoragesTrie trees of the bloatnet contract: descriptor, exact branch fill
             (full branch walk), uniform leaf fill from 2,000 leaves of that walk.
  midsize    nested trees of contracts with 29..4000 storage slots, found on the leaf pages landed by N random
             main-tree descents (all entries of each landed page, not only the landed key). Up to 300 trees per
             table, each walked fully: per-tree mean leaf fill (mean/p10/p50/p90), page-weighted leaf fill,
             branch fill, height distribution. StoragesTrie trees are those of the same mid-size accounts
             (looked up by hashed address), plus how many such accounts have no StoragesTrie row at all.
  main_trees HashedStorages/StoragesTrie main (addrHash-keyed) tree only: height, exact main-only branch/leaf
             page counts and branch fill from a main-tree branch walk, leaf fill from the descent sample and from
             a uniform sample of the walked leaves. tree_t.leaf/branch in the catalog include nested-tree pages
             for DUPSORT tables, so main_only_* differs from them.
"""
import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib  # noqa: E402

BLOATED_HK = bytes.fromhex("8eec99cefee2786a3a42aea2bec51737b9e6106cfb5d443d5b12207d487aee7c")
MID_LO, MID_HI, MID_MAX_TREES = 29, 4000, 300
LEAF_SAMPLE = 2000


def fill(p):
    return lib.used(p) / (lib.PS - 20)


def pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(q / 100 * len(s)))]


def summary(xs):
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean": sum(xs) / len(xs), "p10": pct(xs, 10), "p50": pct(xs, 50), "p90": pct(xs, 90)}


def walk(db, pool, t):
    """Full branch-level walk of a tree_t. Returns (branch fills, leaf pgnos)."""
    if t["height"] <= 1:
        return [], [t["root"]]
    bfills, frontier = [], [t["root"]]
    for level in range(t["height"], 1, -1):
        nxt = []
        for i in range(0, len(frontier), 65536):
            for p in pool.map(db.page, frontier[i:i + 65536], chunksize=64):
                bfills.append(fill(p))
                nxt.extend(d for d, *_ in lib.nodes(p))
        frontier = nxt
    return bfills, frontier


def uniform_leaf_fill(db, pool, leaves, n, rnd):
    samp = leaves if len(leaves) <= n else rnd.sample(leaves, n)
    return summary(list(pool.map(lambda pg: fill(db.page(pg)), samp, chunksize=32)))


def nested_tree_stats(db, pool, t):
    bf, leaves = walk(db, pool, t)
    lf = [fill(db.page(pg)) for pg in leaves]
    return {"height": t["height"], "items": t["items"], "leaves": len(leaves), "branches": len(bf),
            "leaf_fill": sum(lf) / len(lf), "leaf_fill_sum": sum(lf),
            "branch_fill": (sum(bf) / len(bf)) if bf else None}


def aggregate(trees):
    if not trees:
        return {"n_trees": 0}
    heights = {}
    for x in trees:
        heights[x["height"]] = heights.get(x["height"], 0) + 1
    nleaf = sum(x["leaves"] for x in trees)
    bf = [x["branch_fill"] for x in trees if x["branch_fill"] is not None]
    return {"n_trees": len(trees), "per_tree_leaf_fill": summary([x["leaf_fill"] for x in trees]),
            "page_weighted_leaf_fill": sum(x["leaf_fill_sum"] for x in trees) / nleaf,
            "per_tree_branch_fill": summary(bf), "height_dist": dict(sorted(heights.items())),
            "items": summary([x["items"] for x in trees]), "leaves_per_tree": summary([x["leaves"] for x in trees])}


def descend(db, t, rnd, n):
    """n random-key descents of a main tree. Returns {landed leaf pgno: page bytes}."""
    pages = {}
    for _ in range(n):
        _, _, _, path = db.search(t, rnd.randbytes(32))
        if path[-1] not in pages:
            pages[path[-1]] = db.page(path[-1])
    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--sample", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=None, help="checkpoint path, written after every stage (optional)")
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    db = lib.DB(a.db)
    tabs = db.tables()
    out = {"db": a.db, "sample": a.sample, "seed": a.seed, "catalog": {}}

    def checkpoint():
        if a.out:
            json.dump(out, open(a.out + ".tmp", "w"), indent=1, default=str)
            os.replace(a.out + ".tmp", a.out)
    t0 = time.time()
    with ThreadPoolExecutor(64) as pool:
        out["main_trees"] = {}
        landed = {}
        for name in ("HashedStorages", "StoragesTrie"):
            t = tabs[name]
            out["catalog"][name] = t
            bf, leaves = walk(db, pool, t)
            landed[name] = descend(db, t, rnd, a.sample)
            out["main_trees"][name] = {
                "height": t["height"], "main_only_branch_pages": len(bf), "main_only_leaf_pages": len(leaves),
                "main_only_branch_fill": sum(bf) / len(bf) if bf else None,
                "leaf_fill_uniform": uniform_leaf_fill(db, pool, leaves, LEAF_SAMPLE, rnd),
                "leaf_fill_descent": summary([fill(p) for p in landed[name].values()]),
                "entries_per_leaf_descent": summary([len(list(lib.nodes(p))) for p in landed[name].values()]),
            }
            print(f"main {name} {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
            checkpoint()

        out["bloated"] = {}
        for name in ("HashedStorages", "StoragesTrie"):
            _, nf, data, _ = db.search(tabs[name], BLOATED_HK)
            if data is None or not nf & lib.N_TREE:
                out["bloated"][name] = None
                continue
            nt = lib.tree(data, 0)
            bf, leaves = walk(db, pool, nt)
            out["bloated"][name] = {"descriptor": nt, "branch_fill_exact": sum(bf) / len(bf) if bf else None,
                                    "walked_branches": len(bf), "walked_leaves": len(leaves),
                                    "leaf_fill": uniform_leaf_fill(db, pool, leaves, LEAF_SAMPLE, rnd)}
            print(f"bloated {name} {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
            checkpoint()

        # mid-size accounts: every N_TREE entry on the landed HashedStorages leaf pages
        hs_slots, kinds = {}, {"single": 0, "inline_dup": 0, "nested": 0}
        for p in landed["HashedStorages"].values():
            for dsize, nflags, ksize, o in lib.nodes(p):
                key = p[o:o + ksize]
                if nflags & lib.N_TREE:
                    kinds["nested"] += 1
                    hs_slots[key] = lib.tree(p, o + ksize)
                elif nflags & lib.N_DUP:
                    kinds["inline_dup"] += 1
                else:
                    kinds["single"] += 1
        mid = [(k, t) for k, t in hs_slots.items() if MID_LO <= t["items"] <= MID_HI]
        rnd.shuffle(mid)
        mid = mid[:MID_MAX_TREES]
        hs_trees = [nested_tree_stats(db, pool, kt[1]) for kt in mid]
        st_trees, st_kinds = [], {"no_row": 0, "inline": 0, "nested": 0}
        for k, _ in mid:
            _, nf, data, _ = db.search(tabs["StoragesTrie"], k)
            if nf is None:
                st_kinds["no_row"] += 1
            elif nf & lib.N_TREE:
                st_kinds["nested"] += 1
                st_trees.append(nested_tree_stats(db, pool, lib.tree(data, 0)))
            else:
                st_kinds["inline"] += 1
        out["midsize"] = {
            "landed_hs_pages": len(landed["HashedStorages"]), "entry_kinds_on_landed_pages": kinds,
            "n_midsize_found": sum(1 for t in hs_slots.values() if MID_LO <= t["items"] <= MID_HI),
            "HashedStorages": aggregate(hs_trees),
            "StoragesTrie_rows_for_same_accounts": st_kinds,
            "StoragesTrie": aggregate(st_trees),
        }
        print(f"midsize {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    out["elapsed_s"] = round(time.time() - t0, 1)
    checkpoint()
    json.dump(out, sys.stdout, indent=1, default=str)
    print()


main()
