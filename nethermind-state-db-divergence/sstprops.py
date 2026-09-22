#!/usr/bin/env python3
"""Per-SST table properties straight from the file footer (no RocksDB needed): column family, entries,
data blocks, bytes per block, filter size, compression, creation time, writing host. Used to audit
which files of a store were written with which table options, and by whom.

usage: sstprops.py <flat-dir> [summary|files]"""
import glob
import os
import struct
import sys
import time
from collections import defaultdict

MAGIC = 0x88E241B785F4CFF7


def varint(b, i):
    r, s = 0, 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        if c < 0x80:
            return r, i
        s += 7


def block_entries(b):
    """Entries of an uncompressed block with restart interval 1 (metaindex / properties)."""
    n_restarts = struct.unpack_from("<I", b, len(b) - 4)[0]
    end = len(b) - 4 - 4 * n_restarts
    i, key = 0, b""
    out = []
    while i < end:
        shared, i = varint(b, i)
        non_shared, i = varint(b, i)
        vlen, i = varint(b, i)
        key = key[:shared] + b[i:i + non_shared]
        i += non_shared
        out.append((key, b[i:i + vlen]))
        i += vlen
    return out


def read_block(f, off, size):
    f.seek(off)
    raw = f.read(size + 5)
    if raw[size] != 0:
        raise ValueError("compressed meta block (type %d)" % raw[size])
    return raw[:size]


def props(path):
    with open(path, "rb") as f:
        f.seek(0, 2)
        n = f.tell()
        f.seek(n - 53)
        footer = f.read(53)
        magic = struct.unpack_from("<Q", footer, 45)[0]
        if magic != MAGIC:
            return {"error": "not a block-based table (magic %x)" % magic}
        version = struct.unpack_from("<I", footer, 41)[0]
        i = 1  # checksum type byte
        moff, i = varint(footer, i)
        msize, i = varint(footer, i)
        meta = block_entries(read_block(f, moff, msize))
        h = dict(meta).get(b"rocksdb.properties")
        if h is None:
            return {"error": "no properties block", "format": version}
        poff, j = varint(h, 0)
        psize, j = varint(h, j)
        out = {"format": version}
        for k, v in block_entries(read_block(f, poff, psize)):
            k = k.decode()
            if k in ("rocksdb.column.family.name", "rocksdb.compression", "rocksdb.filter.policy",
                     "rocksdb.creating.host.identity", "rocksdb.creating.db.identity", "rocksdb.comparator"):
                out[k] = v.decode(errors="replace")
            elif k in ("rocksdb.data.size", "rocksdb.index.size", "rocksdb.filter.size", "rocksdb.raw.key.size",
                       "rocksdb.raw.value.size", "rocksdb.num.data.blocks", "rocksdb.num.entries",
                       "rocksdb.creation.time", "rocksdb.oldest.key.time", "rocksdb.file.creation.time",
                       "rocksdb.original.file.number", "rocksdb.format.version", "rocksdb.block.based.table.index.type"):
                out[k] = varint(v, 0)[0]
        return out


def main():
    d = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "summary"
    rows = []
    for p in sorted(glob.glob(os.path.join(d, "*.sst"))):
        try:
            r = props(p)
        except Exception as e:  # noqa: BLE001
            r = {"error": str(e)}
        r["file"] = os.path.basename(p)
        r["size"] = os.path.getsize(p)
        rows.append(r)
    if mode == "files":
        print("%-10s %-14s %10s %8s %7s %7s %6s %-8s %-10s %s" % ("file", "cf", "entries", "blocks", "B/blk", "filtKB", "fmt", "compr", "created", "host"))
        for r in rows:
            if "error" in r:
                print("%-10s ERROR %s" % (r["file"], r["error"]))
                continue
            nb = r.get("rocksdb.num.data.blocks", 0) or 1
            print("%-10s %-14s %10d %8d %7.0f %7.0f %6d %-8s %-10s %s" % (
                r["file"], r.get("rocksdb.column.family.name", "?"), r.get("rocksdb.num.entries", 0), nb,
                r.get("rocksdb.data.size", 0) / nb, r.get("rocksdb.filter.size", 0) / 1e3, r.get("rocksdb.format.version", -1),
                r.get("rocksdb.compression", "?")[:8], time.strftime("%Y-%m-%d", time.gmtime(r.get("rocksdb.creation.time", 0))),
                r.get("rocksdb.creating.host.identity", "?")[:12]))
        return
    # summary: per CF, files bucketed by bytes/block and filter presence, with creation-time span
    by = defaultdict(list)
    for r in rows:
        if "error" not in r:
            by[r.get("rocksdb.column.family.name", "?")].append(r)
    for cf, rs in sorted(by.items(), key=lambda kv: -sum(x["size"] for x in kv[1])):
        buckets = defaultdict(lambda: [0, 0, 0, 10**12, 0, set()])
        for r in rs:
            nb = r.get("rocksdb.num.data.blocks", 0) or 1
            bpb = r.get("rocksdb.data.size", 0) / nb
            key = ("%5.0fB" % (round(bpb / 500) * 500), "filter" if r.get("rocksdb.filter.size", 0) else "nofilt", r.get("rocksdb.compression", "?")[:6])
            b = buckets[key]
            b[0] += 1
            b[1] += r["size"]
            b[2] += r.get("rocksdb.num.entries", 0)
            ct = r.get("rocksdb.creation.time", 0)
            b[3] = min(b[3], ct)
            b[4] = max(b[4], ct)
            b[5].add(r.get("rocksdb.creating.host.identity", "?")[:12])
        print("%s: %d files %.2f GB" % (cf, len(rs), sum(r["size"] for r in rs) / 1e9))
        for key, (n, sz, ne, t0, t1, hosts) in sorted(buckets.items(), key=lambda kv: -kv[1][1]):
            print("   %s %s %-6s  %5d files %8.2f GB %10.1fM entries  created %s .. %s  host %s" % (
                key[0], key[1], key[2], n, sz / 1e9, ne / 1e6, time.strftime("%Y-%m-%d", time.gmtime(t0)),
                time.strftime("%Y-%m-%d", time.gmtime(t1)), ",".join(sorted(hosts))))


main()
