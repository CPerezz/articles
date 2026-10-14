import os, struct
PS = 4096
P_BRANCH, P_LEAF, P_LARGE, P_DUPFIX, P_SUBP = 1, 2, 4, 0x20, 0x40
N_BIG, N_TREE, N_DUP = 1, 2, 4
TREE = "<HHIIIIIQQQ"

class DB:
    def __init__(s, path):
        s.fd = os.open(path, os.O_RDONLY)
    def page(s, pg):
        return os.pread(s.fd, PS, pg * PS)
    def meta(s):
        best = None
        for m in range(3):
            p = s.page(m)
            a, b = struct.unpack_from("<Q", p, 28)[0], struct.unpack_from("<Q", p, 196)[0]
            if a == b and (best is None or a > best[0]):
                best = (a, p)
        return tree(best[1], 108)
    def tables(s):
        m = s.meta(); out = {}; fr = [m["root"]]
        for _ in range(m["height"] - 1):
            fr = [d for pg in fr for d, *_ in nodes(s.page(pg))]
        for pg in fr:
            p = s.page(pg)
            for d, f, k, o in nodes(p):
                out[p[o:o + k].decode(errors="replace")] = tree(p, o + k)
        return out
    def search(s, t, key):
        """Exact lookup in a main tree; returns (leafpg, nflags, data bytes) or None, plus path."""
        pg, path = t["root"], []
        for _ in range(t["height"] - 1):
            p = s.page(pg); path.append(pg); child = None
            for i, (d, f, k, o) in enumerate(nodes(p)):
                if i == 0 or p[o:o + k] <= key:
                    child = d
                else:
                    break
            pg = child
        p = s.page(pg); path.append(pg)
        for d, f, k, o in nodes(p):
            if p[o:o + k] == key:
                return pg, f, p[o + k:o + k + d], path
        return None, None, None, path
    def levels(s, t):
        """BFS branch levels of a (sub)tree; returns list of levels, last = leaf pgnos in key order."""
        lv = [[t["root"]]]
        for _ in range(t["height"] - 1):
            lv.append([d for pg in lv[-1] for d, *_ in nodes(s.page(pg))])
        return lv

def tree(p, off):
    t = struct.unpack_from(TREE, p, off)
    return dict(zip(["flags", "height", "dfs", "root", "branch", "leaf", "large", "seq", "items", "mod"], t))

def hdr(p):
    txnid, dks, flags, lower, upper, pgno = struct.unpack_from("<QHHHHI", p, 0)
    return flags, lower, upper, pgno

def nodes(p, base=0):
    flags, lower, upper, pgno = struct.unpack_from("<HHHI", p, base + 10)
    for i in range(lower >> 1):
        off = struct.unpack_from("<H", p, base + 20 + 2 * i)[0] + 20 + base
        dsize, nflags, extra, ksize = struct.unpack_from("<IBBH", p, off)
        yield dsize, nflags, ksize, off + 8

def used(p):
    flags, lower, upper, pgno = hdr(p)
    return PS - 20 - (upper - lower)

# keccak256, pure python
RC = [0x1,0x8082,0x800000000000808A,0x8000000080008000,0x808B,0x80000001,0x8000000080008081,0x8000000000008009,0x8A,0x88,0x80008009,0x8000000A,0x8000808B,0x800000000000008B,0x8000000000008089,0x8000000000008003,0x8000000000008002,0x8000000000000080,0x800A,0x800000008000000A,0x8000000080008081,0x8000000000008080,0x80000001,0x8000000080008008]
ROT = [[0,36,3,41,18],[1,44,10,45,2],[62,6,43,15,61],[28,55,25,21,56],[27,20,39,8,14]]
M = (1 << 64) - 1
def _f(A):
    for rc in RC:
        C = [A[x][0]^A[x][1]^A[x][2]^A[x][3]^A[x][4] for x in range(5)]
        D = [C[x-1] ^ (((C[(x+1)%5] << 1) | (C[(x+1)%5] >> 63)) & M) for x in range(5)]
        A = [[A[x][y]^D[x] for y in range(5)] for x in range(5)]
        B = [[0]*5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                r = ROT[x][y]; v = A[x][y]
                B[y][(2*x+3*y)%5] = ((v << r) | (v >> (64-r))) & M if r else v
        A = [[B[x][y] ^ ((~B[(x+1)%5][y]) & B[(x+2)%5][y]) for y in range(5)] for x in range(5)]
        A[0][0] ^= rc
    return A
def keccak(b):
    b = bytearray(b) + b"\x01"; b += b"\x00" * (-len(b) % 136); b[-1] |= 0x80
    A = [[0]*5 for _ in range(5)]
    for i in range(0, len(b), 136):
        for j in range(17):
            A[j%5][j//5] ^= int.from_bytes(b[i+8*j:i+8*j+8], "little")
        A = _f(A)
    return b"".join(A[j%5][j//5].to_bytes(8, "little") for j in range(4))
assert keccak(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"

def rlp_decode(b, i=0):
    t = b[i]
    if t < 0x80:
        return b[i:i+1], i+1
    if t < 0xb8:
        n = t - 0x80
        return b[i+1:i+1+n], i+1+n
    if t < 0xc0:
        ln = t - 0xb7
        n = int.from_bytes(b[i+1:i+1+ln], "big")
        o = i+1+ln
        return b[o:o+n], o+n
    if t < 0xf8:
        n = t - 0xc0
        items, o, end = [], i+1, i+1+n
        while o < end:
            v, o = rlp_decode(b, o)
            items.append(v)
        return items, end
    ln = t - 0xf7
    n = int.from_bytes(b[i+1:i+1+ln], "big")
    o = i+1+ln
    items, end = [], o+n
    while o < end:
        v, o = rlp_decode(b, o)
        items.append(v)
    return items, end

def tx_to(rawhex):
    """Return 'to' address (20B) or None (contract creation) for a legacy/typed tx hex string."""
    b = bytes.fromhex(rawhex[2:] if rawhex.startswith("0x") else rawhex)
    if b[0] <= 0x7f:  # typed tx: type byte then rlp list [chainId?,nonce,...,to,...]
        payload = b[1:]
        items, _ = rlp_decode(payload)
        # type 1/2/3/4: [chainId, nonce, (maxPrio,)(maxFee|gasPrice), gas, to, value, ...]
        idx = {0x01: 4, 0x02: 5, 0x03: 5, 0x04: 5}.get(b[0], 5)
        to = items[idx]
    else:
        items, _ = rlp_decode(b)
        to = items[3]  # legacy: nonce, gasPrice, gas, to, value, data, v, r, s
    return to.hex() if to else None

def walk_branches(db, t, pool, max_leaves=None):
    """BFS all branch levels of tree_t `t`; returns (branch_fill_mean, [leaf pgno,... key order]).
    `max_leaves` caps returned leaf-page count (still walks all branches) to bound memory."""
    level, frontier = t["height"], [t["root"]]
    if level == 1:
        return None, [t["root"]]
    bfill, leaves = [], []
    while level > 1 and frontier:
        last = level == 2
        nxt = []
        pages = list(pool.map(db.page, frontier, chunksize=64))
        for p in pages:
            bfill.append(used(p) / (PS - 20))
            for d, f, k, o in nodes(p):
                if last:
                    leaves.append(d)
                else:
                    nxt.append(d)
        frontier = nxt
        level -= 1
    return (sum(bfill) / len(bfill) if bfill else None), leaves

def sample_leaf_stats(db, pool, leaves, n=2000, seed=1):
    import random
    rnd = random.Random(seed)
    samp = leaves if len(leaves) <= n else rnd.sample(leaves, n)
    pages = list(pool.map(db.page, samp, chunksize=32))
    fills, items, dsizes = [], 0, []
    for p in pages:
        fills.append(used(p) / (PS - 20))
        for d, f, k, o in nodes(p):
            items += 1
            dsizes.append(d)
    return {
        "n_sampled_pages": len(samp),
        "mean_fill": sum(fills) / len(fills) if fills else None,
        "items_in_sample": items,
        "mean_item_bytes": sum(dsizes) / len(dsizes) if dsizes else None,
        "mean_key_plus_val_bytes": sum(dsizes) / len(dsizes) + 8 if dsizes else None,  # +node header(key implied by dsize already incl value; 8B node overhead(dsize,flags,extra,ksize)) approx
    }

def contiguity(leaves):
    """Physical spread/contiguity of a leaf-page list already in key order."""
    s = sorted(leaves)
    span = s[-1] - s[0] + 1 if s else 0
    gaps = [s[i+1] - s[i] for i in range(len(s)-1)]
    runs = sum(1 for g in gaps if g == 1) + (1 if s else 0)
    # count of maximal runs of consecutive pgnos
    nruns, i = 0, 0
    for i, g in enumerate(gaps):
        if g != 1:
            nruns += 1
    nruns += 1 if s else 0
    return {
        "n_leaves": len(s), "min_pg": s[0] if s else None, "max_pg": s[-1] if s else None,
        "span": span, "density": len(s) / span if span else None,
        "n_contig_runs": nruns, "mean_run_len": len(s) / nruns if nruns else None,
        "max_gap": max(gaps) if gaps else 0,
    }

def sample_tree_random(db, t, n=2000, keylen=32, seed=3):
    """Random-key descent sample of a tree_t (works for top-level tables or nested dupsort subtree
    descriptors alike). Returns per-entry content bytes as ksize+dsize (mdbx nested-dupsort leaf
    nodes store the full item in `key` with dsize=0; main-tree leaf nodes store it in `data`)."""
    import random
    rnd = random.Random(seed)
    seen = {}
    for _ in range(n):
        key = rnd.randbytes(keylen)
        pg, nf, data, path = db.search(t, key)
        leafpg = path[-1]
        if leafpg not in seen:
            seen[leafpg] = db.page(leafpg)
    fills, content, n_entries = [], [], 0
    for pg, p in seen.items():
        fills.append(used(p) / (PS - 20))
        for dsize, nflags, ksize, o in nodes(p):
            content.append(ksize + dsize)
            n_entries += 1
    return {
        "n_random_keys": n, "n_distinct_leaf_pages": len(seen),
        "mean_leaf_fill": sum(fills) / len(fills) if fills else None,
        "mean_entries_per_leaf": n_entries / len(seen) if seen else None,
        "mean_entry_content_bytes": sum(content) / len(content) if content else None,
        "min_entry_bytes": min(content) if content else None, "max_entry_bytes": max(content) if content else None,
    }

def lcp_nibbles(a, b):
    """Longest common prefix length in MPT nibbles (high nibble first) between two equal-length byte keys."""
    n = 0
    for x, y in zip(a, b):
        if x == y:
            n += 2
            continue
        if (x >> 4) == (y >> 4):
            n += 1
        return n
    return n
