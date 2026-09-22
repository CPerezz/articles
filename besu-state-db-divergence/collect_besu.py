#!/usr/bin/env python3
"""Collect every measurement the Besu report needs into one committed JSON.

The report generator must derive each printed number from this file, never from a literal, so
anything quoted in the prose has to appear here first.

Usage: collect_besu.py > report_data.json
"""
import glob
import json
import os
import re
import subprocess
import sys

CODE = {"EXTCODECOPY", "EXTCODEHASH", "EXTCODESIZE", "CALL", "CALLCODE",
        "DELEGATECALL", "STATICCALL"}
FIELDS = re.compile(
    r"opcode_(?P<opcode>[A-Z0-9]+)"
    r"|value_sent_(?P<value_sent>\d+)"
    r"|account_mode_AccountMode\.(?P<mode>[A-Z_]+)"
    r"|overhead_baseline_(?P<baseline>True|False)"
    r"|cache_strategy_CacheStrategy\.(?P<cache>[A-Z_]+)"
    r"|gas-value_(?P<gas>\d+)M"
)


def bucket(op, mode):
    if mode == "NON_EXISTING_ACCOUNT":
        return "absent"
    if mode == "EXISTING_EOA" or op == "BALANCE":
        return "leaf-only"
    return "code-reading" if op in CODE else "leaf-only"


def parse(tid):
    f = {}
    for m in FIELDS.finditer(tid):
        for k, v in m.groupdict().items():
            if v is not None:
                f[k] = v
    return f


def arm(results_dir):
    runs = sorted(d for d in glob.glob(os.path.join(results_dir, "runs", "*")) if os.path.isdir(d))
    if not runs:
        return []
    index = json.load(open(os.path.join(runs[-1], "result.json")))["tests"]
    out = []
    for tid, meta in index.items():
        agg = (meta.get("steps", {}).get("test") or {}).get("aggregated")
        if not agg:
            continue
        ns = agg.get("gas_used_time_total") or agg.get("time_total")
        gas = agg.get("gas_used_total")
        if not ns or not gas:
            continue
        f = parse(tid)
        if not all(k in f for k in ("opcode", "mode", "gas")):
            continue
        rt = agg.get("resource_totals", {})
        out.append(dict(
            opcode=f["opcode"], mode=f["mode"], gas=int(f["gas"]),
            value_sent=int(f.get("value_sent", -1)), baseline=f.get("baseline") == "True",
            bucket=bucket(f["opcode"], f["mode"]),
            mgas_s=gas / (ns / 1e9) / 1e6, gas_used=gas, wall_ns=ns,
            disk_read_bytes=rt.get("disk_read_bytes", 0),
            cpu_usec=rt.get("cpu_usec", 0),
        ))
    return out


def sh(*a):
    try:
        return subprocess.run(a, capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return ""


R = "/data/bench-results"
data = {}

# ---- full suites (three 22-hour arms, ~1,462 tests each) --------------------
full_src = json.load(open("/root/bench/arms-three.json"))
rename = {"untreated": "plain", "treated": "compacted", "state_actor": "state_actor"}
data["full"] = {}
for src, dst in rename.items():
    rows = []
    for r in full_src[src]:
        f = parse(r["test_id"])
        if not all(k in f for k in ("opcode", "mode", "gas")):
            continue
        rows.append(dict(
            opcode=f["opcode"], mode=f["mode"], gas=int(f["gas"]),
            value_sent=int(f.get("value_sent", -1)), baseline=f.get("baseline") == "True",
            bucket=bucket(f["opcode"], f["mode"]),
            mgas_s=r["mgas_s"], gas_used=r["gas_used"], wall_ns=r["wall_ns"],
            disk_read_bytes=r["disk_read_bytes"], cpu_usec=r.get("cpu_usec", 0),
        ))
    data["full"][dst] = rows

# ---- filtered confirmation arms (129 tests each) ---------------------------
data["filtered"] = {
    "plain":         arm(f"{R}/s3-plain"),
    "drained":       arm(f"{R}/s6-drained"),
    "compacted":     arm(f"{R}/s4-drained"),      # mislabelled dir; this arm is compacted
    "compacted_rep": arm(f"{R}/s5-compacted"),    # independent repeat of the same state
    "state_actor":   arm(f"{R}/s2-sa"),
    "compacted_alt": arm(f"{R}/s1-treated"),      # compacted, first lineage
}

# ---- account-read counters -------------------------------------------------
data["counters"] = {}
for label, path in (("compacted", "/root/bench/s1-joined.json"),
                    ("state_actor", "/root/bench/s2-joined.json")):
    if not os.path.exists(path):
        continue
    rows = []
    for r in json.load(open(path)):
        if "mode" not in r or not r.get("reads"):
            continue
        rows.append(dict(mode=r["mode"], value_sent=int(r.get("value_sent", -1)),
                         reads=r["reads"], reads_missing=r["reads_missing"],
                         reads_flat=r["reads_flat"],
                         disk_read_bytes=r["disk_read_bytes"]))
    data["counters"][label] = rows

# ---- store censuses --------------------------------------------------------
data["census"] = {
    "shipped": {"ssts": 6695, "sst_bytes": 382863226174, "blob_files": 26018,
                "blob_bytes": 760163958951, "wal_files": 21, "wal_bytes": 1258464804,
                "caches_files": 246, "caches_bytes": 6335076761,
                "note": "three independent extractions produced this census byte-identically"},
    # Two independent pre-run replays of the same extraction. Their WAL sizes differ, which is
    # itself evidence about the WAL; keep them apart rather than averaging them away.
    "after_prerun": {"ssts": 6699, "sst_bytes": 382737542760, "wal_files": 20,
                     "wal_bytes": 1329617075},
    "after_prerun_repeat": {"ssts": 6699, "sst_bytes": 382741424540,
                            "wal_bytes": 1224816684},
    # `flush (all cfs)` itself returned in 0.0s: RocksDB's open path had already recovered and
    # flushed the WAL, so the step's three seconds are open plus close.
    "after_flush": {"ssts": 6699, "wal_bytes": 23, "flush_seconds": 0.0, "step_seconds": 3,
                    "promote_bytes": 69e6, "promote_ms": 171},
    "after_compact": {"ssts": 5454, "sst_bytes": 360320146324, "wal_bytes": 23,
                      "seconds": 5437.0},
    # the generated store, for the "not comparable whole-store" point only
    "state_actor": {"ssts": 8450, "sst_bytes": 572008650893, "blob_files": 1,
                    "blob_bytes": 322, "wal_files": 1, "trielog_count": 0},
}
# Per column family, before and after the compaction. The entry drop is the direct evidence
# that the pre-run's writes were newer duplicate versions of keys sitting above older ones:
# a merge purges the obsolete versions, and only a store carrying them can lose entries.
data["entries_by_cf"] = {
    "06": {"name": "ACCOUNT_INFO_STATE", "plain": 365626139, "compacted": 354792873,
           "ssts_plain": 305, "ssts_compacted": 269},
    "08": {"name": "ACCOUNT_STORAGE_STORAGE", "plain": 1874093849, "compacted": 1822629119,
           "ssts_plain": 1461, "ssts_compacted": 1255},
    "09": {"name": "TRIE_BRANCH_STORAGE", "plain": 3098085111, "compacted": 3012961752,
           "ssts_plain": 4301, "ssts_compacted": 3351},
}
data["prerun_bundle_bytes"] = 10062313486

# Data-block cost of a fixture code read, modelled from each store's own cf07 by packing records
# the way RocksDB does. The fixture blobs compress to ~1% on BOTH stores, so a code read is not
# paying for the contract it reads -- it pays for whatever shares its 32 KiB block. Deflate
# stands in for LZ4 here: comparative, not RocksDB's own figure. Probe: BlockSim.java.
# Composition of the flat account keyspace. A Bonsai flat account is RLP(nonce, balance,
# storageRoot, codeHash); an EOA carries EMPTY_TRIE_ROOT and EMPTY_CODE_HASH, two shared
# constants that compress across a block where a contract's two unique hashes do not. Probe:
# AcctMix.java. Deflate stands in for LZ4 and exaggerates the gap, so RocksDB's own block
# figures stay authoritative for magnitude; this is here for composition.
data["account_mix"] = {
    "probe": "AcctMix.java, read-only open, 200 blocks sampled per store",
    "jochemnet": {"records": 89673, "mean_record": 73.2, "eoa_pct": 80.8,
                  "empty_root_pct": 92.9, "block_comp_deflate": 5590},
    "state_actor": {"records": 82360, "mean_record": 79.7, "eoa_pct": 68.6,
                    "empty_root_pct": 98.3, "block_comp_deflate": 9249},
}
data["code_block_sim"] = {
    "note": "Data-block cost of a fixture code read, modelled from each store's own cf07 by "
            "packing records the way RocksDB does (flush once uncompressed size passes "
            "block_size). Deflate stands in for LZ4: comparative, not RocksDB's own figure.",
    "probe": "BlockSim.java, read-only open, 200 blocks sampled per store",
    "fixture_bytes": 24576,
    "block_size": 32768,
    "jochemnet": {"fixture_deflate": 0.0109, "tenants": 2.4, "tenant_bytes": 7298,
                  "block_raw": 41726, "block_comp": 5912},
    "state_actor": {"fixture_deflate": 0.0070, "tenants": 32.5, "tenant_bytes": 352,
                    "block_raw": 36024, "block_comp": 10718},
    "small_block": {"block_size": 16384, "tenants": 0,
                    "jochemnet_comp": 267, "state_actor_comp": 173},
    "code_population": {
        "jochemnet": {"scanned": 3544, "fixture": 300, "other_ge_1kib_deflate": 0.449},
        "state_actor": {"scanned": 139034, "fixture": 300, "records_23b": 131138,
                        "other_ge_1kib_deflate": 1.002},
    },
}
data["treatment_seconds_by_cf"] = {"01": 414.4, "06": 313.6, "07": 90.4,
                                   "08": 1477.3, "09": 3103.8, "0a": 34.7}

# ---- provenance ------------------------------------------------------------
data["provenance"] = {
    "chain": "jochemnet", "block": 24402727, "chain_id": 1,
    "snapshot_producer": "hyperledger/besu:25.12.0",
    "snapshot_sync_mode": "SNAP",
    "benchmark_client": "ethpandaops/besu:glamsterdam-devnet-7 (26.8-develop-00d2f04)",
    "benchmark_sync_mode": "FULL",
    "storage_format": "BONSAI version 3",
    "state_actor_args": "--client=besu --target-size=350GB --seed=42 --fork=osaka "
                        "--gas-limit=1000000000",
    "state_actor_source": "e4cb205-dirty",
    "harness": "benchmarkoor, rollback_strategy=container-recreate, "
               "drop_memory_caches=steps, datadir method=schelk",
    "device": "md2 NVMe, both arms, same host",
    "compression": "kLZ4Compression", "block_size": 32768,
    "flat_read_share": 0.9983,
    # state-actor's own manifest; the item total is the inventory's, counted per entity class
    "state_actor_items": 6404913395, "state_actor_gib": 532,
    "state_actor_state_root":
        "0x5b305cc0f85f9ffaf5eca1e72cfe0c82f92e14f121aed163cc4c0e784aa3b6e7",
    "state_actor_accounts": 295804065, "state_actor_contracts": 134892673,
}
# ---- per-column-family geometry and per-level placement --------------------
# Both come from RocksDB's own table properties, read through a read-only open, so they are
# the store's account of itself rather than a filesystem guess.
def geom(path):
    out = {}
    for ln in open(path):
        p = ln.split()
        # "cf" is itself valid hex, so the header row has to be excluded by its second field
        if len(p) < 9 or not re.fullmatch(r"[0-9a-f]{2}", p[0]) or not p[1].isdigit():
            continue
        out[p[0]] = {"entries": int(p[1]), "ssts": int(p[2]), "data_bytes": int(p[3]),
                     "mean_record": float(p[4]), "block_bytes": float(p[5]),
                     "phys_over_logical": float(p[6]), "filter_bytes": int(p[7]),
                     "filter_policy": p[8]}
    assert out, f"no geometry rows parsed from {path}"
    return out


def levels(path):
    """levels.log holds a BEFORE block and an AFTER block of `cf level files bytes filter_B`."""
    out, cur = {}, None
    for ln in open(path):
        if "BEFORE" in ln:
            cur = out.setdefault("before", {})
        elif "AFTER" in ln:
            cur = out.setdefault("after", {})
        p = ln.split()
        if cur is None or len(p) != 5 or not re.fullmatch(r"[0-9a-f]{2}", p[0]) \
                or not p[1].isdigit():
            continue
        cur.setdefault(p[0], {})[p[1]] = {"files": int(p[2]), "bytes": int(p[3]),
                                          "filter_bytes": int(p[4])}
    for st in ("before", "after"):
        assert out.get(st), f"levels.log has no {st} block"
    return out


data["sst_props"] = {"jochemnet": geom("/root/bench/geom_jochemnet.txt"),
                     "state_actor": geom("/root/bench/geom_state_actor.txt")}
data["levels"] = levels("/root/bench/levels.log")

data["geth_reference"] = {
    "compression_ratio": 1.167, "block_size_ratio": 1.166,
    "bytes_ratio": 1.119, "time_ratio": 1.107,
    "residual_median_pct": 9.1, "residual_range": [1.031, 1.117],
    "worst_class_factor": 7.71,
    "state_actor_items": 6404913405, "state_actor_gib": 674.25,
    "journal_bytes": 398721024, "journal_layers": 4248,
}
# Upstream outcome. Every store-level number below carries the store it was measured on,
# because three different stores are in play: the 350 GB store this article measures
# (state_actor_source e4cb205-dirty, no filters, unique code hashes), a 350 GB rebuild used
# only for diagnosis, and a 4 GB store built from main after #137 and #138 landed.
data["status"] = {
    "prs": [
        {"n": 133, "sha": "11389bc", "merged": "2026-08-04", "ours": False,
         "title": "fix(besu): align generated RocksDB configuration"},
        {"n": 137, "sha": "c0e1162", "merged": "2026-09-17", "ours": True,
         "title": "autofill: 2% EIP-7702 delegation from a fixed 256-target pool"},
        {"n": 138, "sha": "95e5a10", "merged": "2026-09-17", "ours": True,
         "title": "autofill: share contract bytecode from a deterministic pool"},
    ],
    "measured_store_built": "2026-09-09",
    # After #137 and #138, on a 4 GB store built from main at 95e5a10.
    "after": {"store": "main-95e5a10 4 GB", "cf06_phys": 0.447, "per_bytecode": 32.0,
              "cf07_phys": 0.056, "record_deflate": 0.2147, "block_deflate": 0.1116},
    # Mainnet targets, from the snapshot.
    "target": {"cf06_phys": 0.434, "per_bytecode": 28.2, "cf07_phys": 0.371,
               "record_deflate": 0.443, "block_deflate": 0.329},
    # Absent-lookup cost, measured directly with a RocksDB probe on each store.
    "filters": {"unfiltered_blocks": 1.002, "filtered_blocks": 0.010,
                "snapshot_blocks": 0.038, "filter_useful": 0.990, "bits_per_key": 10.0},
    # One cold read of a DIFF_MAX contract, disk bytes from /proc/self/io, page cache
    # dropped first. Measured on the store this article measures; a later rebuild of the
    # same generator lineage gave 17,724, so the figure is not an accident of one build.
    # No wall time: the two stores sit on different devices, so only bytes compare.
    "code_read": {"store": "v1, the store this article measures", "sa_bytes": 17597,
                  "snap_bytes": 901, "corroborating_rebuild_bytes": 17724},
}

# The v3 arm: the same 1,100-workload suite against a store regenerated from main at 95e5a10,
# i.e. after #133, #137 and #138. Payloads had to be refilled, because an EEST stateful fixture
# is anchored to the genesis of the store it was built against. Produced by
# tools/besu-study/analyse-v3.py over /data/bench-results/v3-full; the control rows are the
# canary that says the archived compacted arm is still a legitimate reference.
data["status"]["v3"] = {
    "store": "v3-95e5a10",
    "tests": 1100,
    "measurement": 660,
    "control": 440,
    "success": 3432,
    "fail": 0,
    "control_ratio": 1.0164,
    "control_archived": 1.0187,
    "faster_rows": 314,
    "inband_rows": 447,
    "row_min": 0.915,
    "row_max": 1.536,
    "classes": {
        "absent": {
            "categories": 8,
            "rows": 110,
            "archived": 0.117,
            "v3": 1.002
        },
        "light": {
            "categories": 24,
            "rows": 330,
            "archived": 0.947,
            "v3": 0.985
        },
        "dark": {
            "categories": 16,
            "rows": 220,
            "archived": 0.828,
            "v3": 1.461
        }
    },
    "gradient": {
        "gas": [
            100,
            120,
            140,
            160,
            180,
            200,
            220,
            240,
            260,
            280,
            300
        ],
        "absent": [
            1.018,
            1.028,
            0.992,
            0.993,
            1.02,
            0.985,
            0.987,
            1.006,
            0.984,
            1.007,
            0.999
        ],
        "light": [
            0.979,
            0.984,
            0.995,
            0.99,
            0.992,
            0.988,
            0.984,
            0.984,
            0.983,
            0.98,
            0.977
        ],
        "dark": [
            1.364,
            1.396,
            1.43,
            1.448,
            1.469,
            1.48,
            1.491,
            1.494,
            1.497,
            1.505,
            1.512
        ],
        "control": [
            1.017,
            1.018,
            1.018,
            1.016,
            1.017,
            1.019,
            1.014,
            1.02,
            1.016,
            1.011,
            1.011
        ]
    }
}
# Per-category before and after, for the closing dumbbell:
# [class, opcode, account_mode, v1_ratio, v3_ratio], sorted by v3.
data["status"]["v3"]["categories"] = [["absent", "CALL", "NON_EXISTING_ACCOUNT", 0.4534, 0.9703], ["light", "CALLCODE", "EXISTING_CONTRACT_MINIMAL", 0.95, 0.9802], ["light", "EXTCODEHASH", "EXISTING_CONTRACT_SAME_MAX", 0.9454, 0.981], ["light", "EXTCODECOPY", "EXISTING_CONTRACT_SAME_MAX", 0.9472, 0.9811], ["light", "STATICCALL", "EXISTING_CONTRACT_SAME_MAX", 0.9474, 0.9812], ["light", "BALANCE", "EXISTING_CONTRACT_SAME_MAX", 0.9434, 0.9818], ["light", "CALLCODE", "EXISTING_CONTRACT_SAME_MAX", 0.948, 0.9821], ["light", "DELEGATECALL", "EXISTING_CONTRACT_MINIMAL", 0.9447, 0.9823], ["light", "BALANCE", "EXISTING_EOA", 0.9423, 0.9827], ["light", "EXTCODESIZE", "EXISTING_CONTRACT_SAME_MAX", 0.9437, 0.9833], ["light", "STATICCALL", "EXISTING_CONTRACT_MINIMAL", 0.9423, 0.9839], ["light", "STATICCALL", "EXISTING_EOA", 0.9545, 0.9839], ["light", "DELEGATECALL", "EXISTING_CONTRACT_SAME_MAX", 0.9393, 0.9841], ["light", "CALL", "EXISTING_CONTRACT_SAME_MAX", 0.939, 0.9842], ["light", "BALANCE", "EXISTING_CONTRACT_MINIMAL", 0.9515, 0.986], ["light", "EXTCODESIZE", "EXISTING_EOA", 0.9491, 0.986], ["light", "DELEGATECALL", "EXISTING_EOA", 0.9494, 0.9864], ["light", "EXTCODEHASH", "EXISTING_CONTRACT_MINIMAL", 0.9502, 0.9869], ["absent", "BALANCE", "NON_EXISTING_ACCOUNT", 0.1013, 0.9877], ["light", "CALLCODE", "EXISTING_EOA", 0.9605, 0.9882], ["light", "EXTCODESIZE", "EXISTING_CONTRACT_MINIMAL", 0.9478, 0.9883], ["light", "EXTCODEHASH", "EXISTING_EOA", 0.9499, 0.9893], ["light", "EXTCODECOPY", "EXISTING_CONTRACT_MINIMAL", 0.9517, 0.9905], ["light", "CALL", "EXISTING_CONTRACT_MINIMAL", 0.9392, 0.9926], ["light", "EXTCODECOPY", "EXISTING_EOA", 0.9494, 0.993], ["light", "CALL", "EXISTING_EOA", 0.9399, 0.9965], ["absent", "EXTCODEHASH", "NON_EXISTING_ACCOUNT", 0.1041, 1.0016], ["absent", "STATICCALL", "NON_EXISTING_ACCOUNT", 0.125, 1.0061], ["absent", "EXTCODESIZE", "NON_EXISTING_ACCOUNT", 0.1031, 1.0079], ["absent", "EXTCODECOPY", "NON_EXISTING_ACCOUNT", 0.1074, 1.0184], ["absent", "DELEGATECALL", "NON_EXISTING_ACCOUNT", 0.1131, 1.0205], ["absent", "CALLCODE", "NON_EXISTING_ACCOUNT", 0.1562, 1.0349], ["dark", "CALL", "EXISTING_CONTRACT_JUMPDEST", 0.8643, 1.2365], ["dark", "CALL", "EXISTING_CONTRACT_DIFF_MAX", 0.8769, 1.2511], ["dark", "CALLCODE", "EXISTING_CONTRACT_JUMPDEST", 0.8477, 1.3232], ["dark", "CALLCODE", "EXISTING_CONTRACT_DIFF_MAX", 0.8513, 1.3487], ["dark", "BALANCE", "EXISTING_CONTRACT_JUMPDEST", 0.8106, 1.459], ["dark", "EXTCODEHASH", "EXISTING_CONTRACT_DIFF_MAX", 0.8149, 1.4714], ["dark", "BALANCE", "EXISTING_CONTRACT_DIFF_MAX", 0.8101, 1.4758], ["dark", "STATICCALL", "EXISTING_CONTRACT_JUMPDEST", 0.8288, 1.4808], ["dark", "EXTCODECOPY", "EXISTING_CONTRACT_DIFF_MAX", 0.8233, 1.481], ["dark", "DELEGATECALL", "EXISTING_CONTRACT_JUMPDEST", 0.8229, 1.4816], ["dark", "EXTCODEHASH", "EXISTING_CONTRACT_JUMPDEST", 0.8181, 1.4852], ["dark", "EXTCODECOPY", "EXISTING_CONTRACT_JUMPDEST", 0.8231, 1.4865], ["dark", "STATICCALL", "EXISTING_CONTRACT_DIFF_MAX", 0.8237, 1.4875], ["dark", "DELEGATECALL", "EXISTING_CONTRACT_DIFF_MAX", 0.819, 1.4908], ["dark", "EXTCODESIZE", "EXISTING_CONTRACT_DIFF_MAX", 0.8237, 1.4909], ["dark", "EXTCODESIZE", "EXISTING_CONTRACT_JUMPDEST", 0.8237, 1.4917]]

# The v4 arm: the sixteen distinct-code categories only, refilled and rerun against a 350 GB
# store built from state-actor#141 (9b23eea), the corpus code pool. Besu filler, -k selected
# tests, all budgets; produced by /root/bench/analyse-v4.py over v4-armA (+ v4-armB).
data["status"]["v4"] = {"pr": 141, "branch": "autofill-code-corpus", "sha": "9b23eea", "partial": true, "budgets": [100, 200, 300], "tests": 124, "measurement": 64, "control": 60, "success": 248, "fail": 0, "control_ratio": 1.012, "control_archived": 1.019, "control_drift": 0.0011, "gas_identity_bad": 0, "faster_rows": 60, "inband_rows": 8, "row_min": 1.031, "row_max": 1.393, "classes": {"dark": {"categories": 16, "rows": 60, "archived": 0.828, "v3": 1.461, "v4": 1.309}}, "gradient": {"gas": [100, 200, 300], "dark": [1.214, 1.311, 1.367], "control": [1.012, 1.012, 1.011]}, "categories": [["dark", "BALANCE", "EXISTING_CONTRACT_DIFF_MAX", 0.8101, 1.4758, 1.3093], ["dark", "BALANCE", "EXISTING_CONTRACT_JUMPDEST", 0.8106, 1.459, 1.3114], ["dark", "CALL", "EXISTING_CONTRACT_DIFF_MAX", 0.8769, 1.2511, 1.1424], ["dark", "CALL", "EXISTING_CONTRACT_JUMPDEST", 0.8643, 1.2365, 1.1379], ["dark", "CALLCODE", "EXISTING_CONTRACT_DIFF_MAX", 0.8513, 1.3487, 1.1886], ["dark", "CALLCODE", "EXISTING_CONTRACT_JUMPDEST", 0.8477, 1.3232, 1.1823], ["dark", "DELEGATECALL", "EXISTING_CONTRACT_DIFF_MAX", 0.819, 1.4908, 1.3189], ["dark", "DELEGATECALL", "EXISTING_CONTRACT_JUMPDEST", 0.8229, 1.4816, 1.3132], ["dark", "EXTCODECOPY", "EXISTING_CONTRACT_DIFF_MAX", 0.8233, 1.481, 1.3142], ["dark", "EXTCODECOPY", "EXISTING_CONTRACT_JUMPDEST", 0.8231, 1.4865, 1.304], ["dark", "EXTCODEHASH", "EXISTING_CONTRACT_DIFF_MAX", 0.8149, 1.4714, 1.3106], ["dark", "EXTCODEHASH", "EXISTING_CONTRACT_JUMPDEST", 0.8181, 1.4852, 1.3181], ["dark", "EXTCODESIZE", "EXISTING_CONTRACT_DIFF_MAX", 0.8237, 1.4909, 1.3088], ["dark", "EXTCODESIZE", "EXISTING_CONTRACT_JUMPDEST", 0.8237, 1.4917, 1.3111], ["dark", "STATICCALL", "EXISTING_CONTRACT_DIFF_MAX", 0.8237, 1.4875, 1.3179], ["dark", "STATICCALL", "EXISTING_CONTRACT_JUMPDEST", 0.8288, 1.4808, 1.3326]], "categories_closer": 16, "disk": {"gas": [100, 200, 300], "v4_over_mainnet": [0.768, 0.75, 0.73], "v1_over_mainnet": [1.43, 1.46, 1.49], "v4_gb": [5.63, 10.57, 14.83], "mainnet_gb": [7.34, 14.09, 20.3]}, "band": 0.1, "verdict": "above", "spot": {"light": {"rows": 2, "v4_ratio": 0.9696, "v3_ratio": 0.979}, "absent": {"rows": 2, "v4_ratio": 0.9675, "v3_ratio": 1.018}}, "residual": {"per_lookup_kib": {"snapshot_compacted": {"100": 224.9, "200": 215.8, "300": 207.5}, "snapshot_plain": {"100": 40.7, "200": 22.2, "300": 14.9}, "v3": {"100": 156.6, "200": 145.7, "300": 138.6}, "v4": {"100": 172.2, "200": 161.7, "300": 151.3}}, "prefetched": {"snapshot_compacted": {"100": 31514, "200": 63010, "300": 94506}, "snapshot_plain": {"100": 31514, "200": 63010, "300": 94506}, "v3": {"100": 31889, "200": 63752, "300": 95616}, "v4": {"100": 31889, "200": 63752, "300": 95616}}, "cf_lookup": {"cf06": {"snapshot_plain_bytes": 22122, "v4_bytes": 17385, "snapshot_blocks": 1.28, "v4_blocks": 1.0}, "cf09": {"snapshot_plain_bytes": 32178, "v4_bytes": 22973, "snapshot_blocks": 1.295, "v4_blocks": 1.0}, "cf07": {"snapshot_plain_bytes": 901, "v4_bytes": 2457, "snapshot_blocks": 0.532, "v4_blocks": 0.712}}, "counted_reads_per_test": {"gas": 100, "reads": 1306, "bytes_gb": 7.38}, "work_mismatch": 0.0119, "ratio_v4_over_snapshot": 0.748, "ratio_v3_over_snapshot": 0.68, "compaction_swing": [5.5, 9.7, 13.9], "code_share_kib": 2.4}, "arm_b": {"tests": 320, "measurement": 160, "control": 160, "success": 640, "fail": 0, "control_ratio": 0.9893, "control_drift": 0.0186, "gas_identity_bad": 0, "budgets": [120, 140, 160, 180, 220, 240, 260, 280], "gradient": {"gas": [120, 140, 160, 180, 220, 240, 260, 280], "dark": [1.235, 1.256, 1.276, 1.294, 1.323, 1.337, 1.349, 1.357], "control": [1.007, 0.976, 0.99, 0.995, 0.971, 1.003, 0.987, 0.996]}, "disk": {"gas": [120, 140, 160, 180, 220, 240, 260, 280], "v4_over_mainnet": [0.765, 0.762, 0.758, 0.754, 0.746, 0.742, 0.738, 0.733], "v1_over_mainnet": [1.435, 1.442, 1.449, 1.455, 1.466, 1.474, 1.48, 1.485], "v4_gb": [6.68, 7.69, 8.68, 9.64, 11.47, 12.34, 13.19, 14.02], "mainnet_gb": [8.74, 10.11, 11.46, 12.78, 15.37, 16.63, 17.87, 19.1]}, "row_min": 1.032, "row_max": 1.382, "categories_closer": 16, "canary_ok": false}, "store": "v4-9b23eea", "store_gb": 350, "image_id": "a1221388ee7d", "store_root": "0x48d611bb839188317e983453705b31e1420b2c4416675f98d776ad8e130d51b8", "anchor": "0x0cb035288eb4e257f34f3d570ed4f43f9d2fc45c09f19db6c0392f60f4a68623", "corpus_contracts": 128, "store_geom": {"cf06": 0.429, "cf07": 0.495, "record_deflate": 0.4381, "packed": 0.4156}, "store_geom_spec": {"cf06": 0.421, "cf07": 0.089, "record_deflate": 0.436, "packed": 0.4279}, "mainnet_packed_same_probe": 0.4387, "mainnet_record_same_probe": 0.4428}

json.dump(data, sys.stdout)
print(f"full: {[ (k, len(v)) for k,v in data['full'].items() ]}", file=sys.stderr)
print(f"filtered: {[ (k, len(v)) for k,v in data['filtered'].items() ]}", file=sys.stderr)
print(f"counters: {[ (k, len(v)) for k,v in data['counters'].items() ]}", file=sys.stderr)
