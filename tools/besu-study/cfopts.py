#!/usr/bin/env python3
"""Per-column-family blob/compression settings from a RocksDB OPTIONS file.

Round 13 flagged a possible confound: jochemnet holds 760 GB in 26,018 blob files while the
generated store holds 322 bytes in one. If that were a live configuration difference between
the two arms, every cross-arm byte ratio would be meaningless. This prints the settings per CF
so the question is answered from the file rather than assumed.
"""
import re
import sys

path = sys.argv[1]
cur = None
out = {}
for line in open(path):
    line = line.strip()
    m = re.match(r'^\[CFOptions "(.+)"\]$', line)
    if m:
        cur = m.group(1)
        out[cur] = {}
    elif cur and "=" in line:
        k, v = line.split("=", 1)
        out[cur][k.strip()] = v.strip()

hdr = f'{"cf":>10}  {"blobs":>5}  {"min_blob":>9}  {"blob_comp":>16}  {"compression":>16}  {"block_size":>10}'
print(hdr)
for cf, o in out.items():
    # Besu names CFs with single binary bytes; render them as hex to match the other tools.
    name = cf if cf == "default" else cf.encode("latin-1", "replace").hex()
    print(
        f'{name:>10}  {o.get("enable_blob_files", "-"):>5}  {o.get("min_blob_size", "-"):>9}  '
        f'{o.get("blob_compression_type", "-"):>16}  {o.get("compression", "-"):>16}  '
        f'{o.get("block_size", o.get("table_factory.block_size", "-")):>10}'
    )
