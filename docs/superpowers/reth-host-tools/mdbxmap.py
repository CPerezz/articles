#!/usr/bin/env python3
"""Classify traced mdbx.dat page indexes by table (libmdbx 0.13 layout).
usage: mdbxmap.py <mdbx.dat> <pages.txt> <out.tsv> [table ...]
pages.txt: one page index per line. Walks the branch levels of the named tables (default: the
state/code/trie tables) to map leaf and branch pages exactly; large (overflow) runs are mapped
from their head page header; anything else gets a header-derived label.
Output: page <TAB> label."""
import os
import struct
import sys
from concurrent.futures import ThreadPoolExecutor

PS = 4096
DEFAULT = ["PlainAccountState", "HashedAccounts", "Bytecodes", "AccountsTrie", "PlainStorageState",
           "HashedStorages", "TransactionHashNumbers", "HeaderNumbers"]
P_BRANCH, P_LEAF, P_LARGE, P_META, P_DUPFIX, P_SUBP = 1, 2, 4, 8, 0x20, 0x40
N_BIG, N_TREE, N_DUP = 1, 2, 4

fd = os.open(sys.argv[1], os.O_RDONLY)


def page(pg):
    return os.pread(fd, PS, pg * PS)


def hdr(p):
    txnid, dks, flags, lower, upper, pgno = struct.unpack_from("<QHHHHI", p, 0)
    return flags, lower, upper, pgno


def nodes(p):
    flags, lower, upper, pgno = hdr(p)
    for i in range(lower >> 1):
        off = struct.unpack_from("<H", p, 20 + 2 * i)[0] + 20
        dsize, nflags, extra, ksize = struct.unpack_from("<IBBH", p, off)
        yield dsize, nflags, ksize, off + 8


def meta():
    best = None
    for m in range(3):
        p = page(m)
        txa = struct.unpack_from("<Q", p, 28)[0]
        txb = struct.unpack_from("<Q", p, 196)[0]
        if txa == txb and (best is None or txa > best[0]):
            best = (txa, p)
    p = best[1]
    psz = struct.unpack_from("<I", p, 64)[0]
    assert psz == PS, psz
    return struct.unpack_from("<HHIIIIIQQQ", p, 108)  # main tree_t


def tables():
    flags, height, dfs, root, *_ = meta()
    out, frontier = {}, [root]
    for _ in range(height - 1):
        nxt = []
        for pg in frontier:
            nxt += [d for d, f, k, o in nodes(page(pg))]
        frontier = nxt
    for pg in frontier:
        p = page(pg)
        for dsize, nflags, ksize, o in nodes(p):
            name = p[o:o + ksize].decode(errors="replace")
            t = struct.unpack_from("<HHIIIIIQQQ", p, o + ksize)
            out[name] = {"flags": t[0], "height": t[1], "root": t[3], "branch": t[4], "leaf": t[5], "large": t[6]}
    return out


def fill(p):
    flags, lower, upper, pgno = hdr(p)
    return 1 - (upper - lower) / (PS - 20)


def walk(name, t, want, label, pool):
    """BFS over branch levels; label pages in `want` that belong to this table's main tree.
    Returns (mean branch fill, mean fill of a 1-in-500 leaf sample)."""
    level, frontier = t["height"], [t["root"]]
    if level == 1:
        if t["root"] in want:
            label[t["root"]] = f"{name}:leaf"
        return None, fill(page(t["root"]))
    bfill, sample = [], []
    while level > 1 and frontier:
        for pg in frontier:
            if pg in want:
                label[pg] = f"{name}:branch"
        nxt, last = [], level == 2
        for i in range(0, len(frontier), 65536):
            for p in pool.map(page, frontier[i:i + 65536], chunksize=64):
                bfill.append(fill(p))
                for d, f, k, o in nodes(p):
                    if not last:
                        nxt.append(d)
                    else:
                        if d in want:
                            label[d] = f"{name}:leaf"
                        if d % 500 == 0:
                            sample.append(d)
        frontier = nxt
        level -= 1
    lf = list(pool.map(lambda pg: fill(page(pg)), sample[:20000]))
    return sum(bfill) / len(bfill), (sum(lf) / len(lf) if lf else None)


def main():
    want = {int(x) for x in open(sys.argv[2]) if x.strip()}
    tabs = tables()
    names = sys.argv[4:] or DEFAULT
    label = {}
    with ThreadPoolExecutor(64) as pool:
        for n in names:
            if n in tabs and tabs[n]["root"] != 0xFFFFFFFF:
                bf, lf = walk(n, tabs[n], want, label, pool)
                print(f"{n} {tabs[n]} branch_fill={bf} leaf_fill={lf}", file=sys.stderr, flush=True)
    # large runs and header-derived labels for the rest
    for pg in sorted(want):
        if pg in label:
            continue
        p = page(pg)
        flags, lower, upper, pgno = hdr(p)
        if pgno == pg and flags & P_LARGE:
            n = struct.unpack_from("<I", p, 16 - 4)[0]
            for q in range(pg, pg + n):
                if q in want and q not in label:
                    label[q] = "large"
        elif pgno == pg and flags & (P_BRANCH | P_LEAF):
            kinds = {(ksize, nflags) for dsize, nflags, ksize, o in list(nodes(p))[:4]}
            label[pg] = "unmapped:" + ("branch" if flags & P_BRANCH else "leaf") + ":" + \
                ",".join(f"k{k}f{f}" for k, f in sorted(kinds))
    for pg in want:
        label.setdefault(pg, "noheader")
    with open(sys.argv[3], "w") as f:
        for pg in sorted(want):
            f.write(f"{pg}\t{label[pg]}\n")


main()
