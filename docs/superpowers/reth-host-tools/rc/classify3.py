#!/usr/bin/env python3
"""Per-test page attribution of a trace run, including the bloated contract's nested trees and
Bytecodes overflow runs (mdbxmap.py labels main trees only). Copy of the step-0 classify.py,
parameterized for any traced run."""
import sys, json, time, struct as _s, bisect
sys.path.insert(0, "/root/bench/reth/rc")
import lib
from concurrent.futures import ThreadPoolExecutor

HK = bytes.fromhex("8eec99cefee2786a3a42aea2bec51737b9e6106cfb5d443d5b12207d487aee7c")
# usage: classify3.py <mdbx.dat> <rid> <n tests> <out.json>
DBS = {sys.argv[2]: (sys.argv[1], sys.argv[2])}
NTESTS = int(sys.argv[3])
PROBE = "/root/bench/reth/probe"


def bytecode_ranges(db, pool):
    bt = db.tables()["Bytecodes"]
    lv = db.levels(bt)
    leaves = lv[-1]
    pages = list(pool.map(db.page, leaves, chunksize=64))
    heads = set()
    for p in pages:
        for dsize, nflags, ksize, o in lib.nodes(p):
            if nflags & lib.N_BIG:
                heads.add(int.from_bytes(p[o + ksize:o + ksize + 4], "little"))
    heads = sorted(heads)

    def ov(pg):
        p = db.page(pg)
        flags, lower, upper, pgno = lib.hdr(p)
        n = _s.unpack_from("<I", p, 12)[0]
        return (pg, n, pgno == pg and bool(flags & lib.P_LARGE))

    info = list(pool.map(ov, heads, chunksize=64))
    bad = [x for x in info if not x[2]]
    ranges = sorted((h, h + n) for h, n, ok in info)
    return ranges, len(heads), len(bad)


def in_ranges(pg, starts, ranges):
    i = bisect.bisect_right(starts, pg) - 1
    return i >= 0 and ranges[i][0] <= pg < ranges[i][1]


def walk_nested_full(db, pool, nt):
    level, frontier = nt["height"], [nt["root"]]
    br, lf = set(), set()
    if level == 1:
        lf.add(nt["root"])
        return br, lf
    while level > 1 and frontier:
        last = level == 2
        nxt = []
        pages = list(pool.map(db.page, frontier, chunksize=64))
        for pgno, p2 in zip(frontier, pages):
            br.add(pgno)
            for d, f, k, o in lib.nodes(p2):
                nxt.append(d)
        if last:
            lf.update(nxt)
        else:
            frontier = nxt
        if last:
            break
        frontier = nxt
        level -= 1
    return br, lf


CATS = ["HashedAccounts:leaf", "HashedAccounts:branch", "AccountsTrie:leaf", "AccountsTrie:branch",
        "HashedStorages:main", "HashedStorages:nested(bloated)", "StoragesTrie:main",
        "StoragesTrie:nested(bloated)", "Bytecodes:leaf", "Bytecodes:branch", "Bytecodes:large", "other"]

out = {}
with ThreadPoolExecutor(64) as pool:
    for name, (path, rid) in DBS.items():
        t0 = time.time()
        db = lib.DB(path)
        t = db.tables()
        print(name, "building bytecode ranges...", flush=True)
        bc_ranges, bc_heads, bc_bad = bytecode_ranges(db, pool)
        bc_starts = [r[0] for r in bc_ranges]
        print(name, "bytecode ranges heads", bc_heads, "bad_heads", bc_bad, round(time.time() - t0, 2), "s", flush=True)

        nested_leaf, nested_branch = {}, {}
        for tab in ["HashedStorages", "StoragesTrie"]:
            pg, nf, data, p = db.search(t[tab], HK)
            nt = lib.tree(data, 0)
            t1 = time.time()
            br, lf = walk_nested_full(db, pool, nt)
            nested_branch[tab] = br
            nested_leaf[tab] = lf
            print(name, tab, "nested branch", len(br), "leaf", len(lf), round(time.time() - t1, 2), "s", flush=True)

        rid_map_path = f"{PROBE}/{rid}.map"
        label = {}
        with open(rid_map_path) as f:
            for line in f:
                pgs, lb = line.rstrip("\n").split("\t")
                label[int(pgs)] = lb
        print(name, "loaded map", len(label), "entries", round(time.time() - t0, 2), "s total so far", flush=True)

        out[name] = {"bc_heads": bc_heads, "bc_bad": bc_bad,
                      "nested_leaf_n": {k: len(v) for k, v in nested_leaf.items()},
                      "nested_branch_n": {k: len(v) for k, v in nested_branch.items()},
                      "tests": {}}
        for i in range(NTESTS):
            pf = f"{rid}-{i}.pages"
            pages = [int(x) for x in open(f"{PROBE}/{pf}") if x.strip()]
            counts = {c: 0 for c in CATS}
            for pg in pages:
                lb = label.get(pg)
                if lb in ("HashedAccounts:leaf", "HashedAccounts:branch", "AccountsTrie:leaf",
                          "AccountsTrie:branch", "Bytecodes:leaf", "Bytecodes:branch"):
                    cat = lb
                elif lb and lb.startswith("HashedStorages"):
                    cat = "HashedStorages:main"
                elif lb and lb.startswith("StoragesTrie"):
                    cat = "StoragesTrie:main"
                elif lb == "large":
                    cat = "Bytecodes:large"
                else:
                    if in_ranges(pg, bc_starts, bc_ranges):
                        cat = "Bytecodes:large"
                    elif pg in nested_leaf["HashedStorages"] or pg in nested_branch["HashedStorages"]:
                        cat = "HashedStorages:nested(bloated)"
                    elif pg in nested_leaf["StoragesTrie"] or pg in nested_branch["StoragesTrie"]:
                        cat = "StoragesTrie:nested(bloated)"
                    else:
                        cat = "other"
                counts[cat] += 1
            counts["total"] = len(pages)
            out[name]["tests"][pf] = counts
            print(name, pf, counts, flush=True)
        json.dump(out, open(sys.argv[4], "w"), indent=2)
        print(name, "DONE total", round(time.time() - t0, 2), "s", flush=True)

print("WROTE", sys.argv[4])
