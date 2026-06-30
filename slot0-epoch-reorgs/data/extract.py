#!/usr/bin/env python3
"""Orchestrator for the slot-0 epoch-boundary reorg study.

Reads the verified SQL in queries/, runs each through `panda` (via runner.py), and writes
one JSON dataset per query to this directory. Two query shapes:

  * window-parametrized  (q1,q2,q2b,q3,q4,q5,qattr1,qattr2): native ClickHouse binding of
    {start:DateTime}/{end:DateTime} -- passed through as params, never string-formatted.
  * target-list          (t3a,t3b,t3c,t3d): the RAW timing layer keyed to the CBT-derived
    orphaned slot-0 set. extract.py builds a validated ClickHouse `values(...)` expression
    from q1's output and str.replace()s it into the {…_targets} placeholder. (Cannot use
    str.format() -- the native {start:DateTime} placeholders would break it.)

Usage:
  python3 extract.py --probe                         # Phase 0 gate
  python3 extract.py --window 2026-01-01 2026-02-01 --label janspike   # one window
  python3 extract.py --scale 2024-09-01 2026-06-01   # host-side monthly windowing (scale)
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

import runner  # local module (same dir)

HERE = os.path.dirname(os.path.abspath(__file__))
QDIR = os.path.join(HERE, "queries")
_HEX_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$")
GENESIS = 1606824023          # mainnet beacon genesis (unix)
SECONDS_PER_SLOT = 12


def slot_of(dt_str: str) -> int:
    """Mainnet slot number containing UTC datetime 'YYYY-MM-DD[ HH:MM:SS]'."""
    s = dt_str if len(dt_str) > 10 else dt_str + " 00:00:00"
    ts = int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    return (ts - GENESIS) // SECONDS_PER_SLOT


def _dt_minus12(sdt: str) -> str:
    """slot_start_date_time of the parent slot (12s earlier)."""
    return (datetime.strptime(sdt, "%Y-%m-%d %H:%M:%S") - timedelta(seconds=12)).strftime("%Y-%m-%d %H:%M:%S")


def _sdt_set(sdts) -> str:
    """A ClickHouse IN-list of quoted, validated slot_start_date_time literals (seek bound).
    Empty -> a sentinel that matches nothing (keeps `IN (...)` valid)."""
    vals = sorted({s for s in sdts if s and _DT_RE.match(s)})
    return ", ".join(f"'{s}'" for s in vals) if vals else "'1970-01-01 00:00:00'"


def _relay_values(triples) -> str:
    """values(slot,kind,exec_hash) from [(slot, kind, exec_hash), ...]. exec_hash '' or 0x-hex."""
    out = []
    for slot, kind, exec_hash in triples:
        eh = exec_hash if (exec_hash and _HEX_RE.match(str(exec_hash))) else ""
        k = kind if kind in ("slot0", "slot31") else "slot0"
        out.append(f"({int(slot)},'{k}','{eh}')")
    spec = "slot UInt32, kind String, exec_hash String"
    return f"values('{spec}', " + ", ".join(out) + ")" if out else f"values('{spec}')"


def _sql(name: str) -> str:
    with open(os.path.join(QDIR, f"{name}.sql")) as fh:
        return fh.read()


def _cfg() -> dict:
    """Resolved datasource report from the probe (datasources.json)."""
    p = os.path.join(HERE, "datasources.json")
    if not os.path.exists(p):
        raise SystemExit("no datasources.json -- run `python3 extract.py --probe` first")
    return json.load(open(p))


def _write(name: str, rows: list, window: tuple | None = None) -> str:
    path = os.path.join(HERE, f"{name}.json")
    json.dump(rows, open(path, "w"), indent=2)
    sys.stderr.write(f"  wrote {name}.json ({len(rows)} rows)"
                     + (f"  [{window[0]}..{window[1]}]\n" if window else "\n"))
    return path


def _values_expr(rows: list, spec: str, cols: list) -> str:
    """Build a validated ClickHouse values('<spec>', (..),..) expression. Ints and 0x-hex only."""
    tuples = []
    for r in rows:
        parts = []
        for c, typ in cols:
            v = r[c]
            if typ == "int":
                parts.append(str(int(v)))
            elif typ == "hex":
                v = str(v)
                if not _HEX_RE.match(v):
                    raise ValueError(f"bad hash for {c}: {v!r}")
                parts.append(f"'{v}'")
            else:
                raise ValueError(f"unknown target col type {typ}")
        tuples.append("(" + ",".join(parts) + ")")
    if not tuples:
        # empty target set -> a typed empty values() so the query is still valid
        return f"values('{spec}')"
    return f"values('{spec}', " + ", ".join(tuples) + ")"


# --------------------------------------------------------------------------- #
# per-window extraction
# --------------------------------------------------------------------------- #
def extract_window(start: str, end: str, label: str, *, session: str | None = None, lean: bool = False) -> dict:
    cfg = _cfg()
    DS_RAW, DS_CBT = cfg["DS_RAW"], cfg.get("DS_CBT")
    params = {"start": start, "end": end}
    # CBT cluster enforces force_primary_key and its shards disagree on slot vs slot_start_date_time
    # -> filter on BOTH. min/max slot derived from the window bounds.
    cbt_params = {**params, "min_slot": slot_of(start), "max_slot": slot_of(end)}
    out = {}

    # reuse ONE sandbox session across all queries (avoids the 50-session cap).
    own_session = session is None
    if own_session:
        session = runner.create_session()
        sys.stderr.write(f"  session {session}\n")

    def rw(key, ds, sql, p, out_name):
        """Resilient run+write: a single query failing logs + continues (returns None)."""
        try:
            rows = runner.run_query(ds, sql, p, session=session)
        except Exception as e:
            sys.stderr.write(f"  [SKIP] {out_name}: {str(e)[:280]}\n")
            out[key] = None
            return None
        out[key] = rows
        _write(f"{out_name}_{label}", rows, (start, end))
        return rows

    # ---- CBT spine (headline + primary detector + attribution) ----
    q1 = []
    if DS_CBT:
        rw("q4", DS_CBT, _sql("q4_orphan_by_position"), cbt_params, "orphan_by_position")
        rw("blob_by_position", DS_CBT, _sql("q_blob_by_position"), cbt_params, "blob_by_position")
        q1 = rw("q1", DS_CBT, _sql("q1_slot0_orphan_detector"), cbt_params, "slot0_orphans") or []
        rw("qattr1", DS_CBT, _sql("qattr1_entity_victim_parent"), cbt_params, "entity_victim_parent")
        rw("qattr2", DS_CBT, _sql("qattr2_entity_excess"), cbt_params, "entity_excess")
        rw("daily", DS_CBT, _sql("q_daily_orphan_series"), cbt_params, "daily_orphan_series")
    else:
        sys.stderr.write("  CBT track OFF (DS_CBT unresolved) -- skipping CBT spine; raw-only fallback\n")

    # ---- missed slot-0 (CBT calendar anti-join) ----
    if DS_CBT:
        rw("q2b", DS_CBT, _sql("q2b_missed_slot0"), cbt_params, "missed_slot0")
    # ---- RAW coverage / corroboration (q3/q5 are full-range scans; skip at scale via --lean) ----
    if not lean:
        rw("q3", DS_RAW, _sql("q3_orphaned_blocks_timing"), params, "orphaned_blocks")
        rw("q5", DS_RAW, _sql("q5_chain_reorg_corroboration"), params, "chain_reorg")

    # ---- RAW timing/relay keyed to the slot-0 sets. Chunk the target lists: a sdt-IN list of
    #      thousands of literals overflows the sandbox script-staging arg limit. ----
    def run_timing(out_name, qname, token, rows, target_fn, sdt_fn, chunk=250):
        """Run a target-keyed timing query in batches of `chunk` rows; concatenate; write JSON."""
        acc, failed = [], 0
        for i in range(0, len(rows), chunk):
            chk = rows[i:i + chunk]
            sql = (_sql(qname).replace(token, target_fn(chk))
                   .replace("{sdt_set}", _sdt_set(sdt_fn(chk))))
            try:
                acc.extend(runner.run_query(DS_RAW, sql, params, session=session))
            except Exception as e:
                failed += 1
                sys.stderr.write(f"  [chunk-skip] {out_name} [{i}:{i+chunk}]: {str(e)[:160]}\n")
        # completeness guard: a silently-skipped chunk would undercount the dataset. Record the
        # expected target count + any chunk failures so analyze/QA can detect a short dataset.
        manifest = json.load(open(os.path.join(HERE, "manifest.json"))) if os.path.exists(os.path.join(HERE, "manifest.json")) else {}
        manifest[f"{out_name}_{label}"] = {"expected_targets": len(rows), "rows": len(acc), "chunks_failed": failed}
        json.dump(manifest, open(os.path.join(HERE, "manifest.json"), "w"), indent=2)
        if failed:
            sys.stderr.write(f"  [WARN] {out_name}: {failed} chunk(s) failed -> dataset is SHORT (expected "
                             f"~{len(rows)} targets, got {len(acc)} rows); see manifest.json\n")
        out[out_name] = acc
        _write(f"{out_name}_{label}", acc, (start, end))
        return acc

    def _slot_root(rows, slot_key, root_key):
        return _values_expr([{"slot": r[slot_key], "root": r[root_key]} for r in rows
                             if _HEX_RE.match(str(r.get(root_key) or ""))],
                            "slot UInt32, root String", [("slot", "int"), ("root", "hex")])

    if q1:
        has31 = [r for r in q1 if r.get("slot31") is not None]
        run_timing("slot31_lateness", "t3a_slot31_lateness", "{slot31_targets}", has31,
                   lambda c: _slot_root(c, "slot31", "slot31_block_root"),
                   lambda c: [_dt_minus12(r["slot_start_date_time"]) for r in c])
        run_timing("slot31_attest_support", "t3b_slot31_attestation_support", "{parent_roots}", has31,
                   lambda c: _slot_root(c, "slot31", "slot31_block_root"),
                   lambda c: [_dt_minus12(r["slot_start_date_time"]) for r in c])
        run_timing("slot0_propagation", "t3c_slot0_propagation", "{slot0_targets}", q1,
                   lambda c: _slot_root(c, "slot", "block_root"),
                   lambda c: [r["slot_start_date_time"] for r in c])
        run_timing("relay_bid_timing", "t3d_relay_bid_timing", "{relay_targets}", q1,
                   lambda c: _relay_values([(r["slot"], "slot0", r.get("exec_hash", "")) for r in c]
                                           + [(r["slot31"], "slot31", "") for r in c if r.get("slot31") is not None]),
                   lambda c: [r["slot_start_date_time"] for r in c]
                             + [_dt_minus12(r["slot_start_date_time"]) for r in c if r.get("slot31") is not None],
                   chunk=80)   # relay query is ~4x heavier (sdt-set embedded twice, 2x targets)

    # ---- CANONICAL slot-0 comparison cohort (propagation + relay baseline) ----
    if DS_CBT:
        canon = rw("canon_slot0", DS_CBT, _sql("q_canon_slot0"), cbt_params, "canon_slot0") or []
        if canon:
            run_timing("slot0_propagation_canon", "t3c_slot0_propagation", "{slot0_targets}", canon,
                       lambda c: _slot_root(c, "slot", "block_root"),
                       lambda c: [r["slot_start_date_time"] for r in c])
            run_timing("relay_bid_timing_canon", "t3d_relay_bid_timing", "{relay_targets}", canon,
                       lambda c: _relay_values([(r["slot"], "slot0", r.get("exec_hash", "")) for r in c]),
                       lambda c: [r["slot_start_date_time"] for r in c], chunk=120)

    if own_session:
        runner.destroy_session(session)   # free the slot (TTL would also reclaim it)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="slot-0 reorg extraction")
    ap.add_argument("--probe", action="store_true", help="run the Phase-0 capability probe")
    ap.add_argument("--window", nargs=2, metavar=("START", "END"), help="one [start,end) window")
    ap.add_argument("--label", default="window", help="dataset label suffix")
    ap.add_argument("--scale", nargs=2, metavar=("START", "END"), help="monthly windowing over range")
    ap.add_argument("--lean", action="store_true", help="skip full-range coverage scans q3/q5")
    args = ap.parse_args()

    if args.probe:
        runner._print_probe(runner.probe())
    elif args.window:
        extract_window(args.window[0] + " 00:00:00" if len(args.window[0]) == 10 else args.window[0],
                       args.window[1] + " 00:00:00" if len(args.window[1]) == 10 else args.window[1],
                       args.label, lean=args.lean)
    elif args.scale:
        # host-side monthly windowing; concatenate the headline (q4) across months as the example.
        sys.stderr.write("scale mode: monthly windows\n")
        for (s, e) in runner.month_windows(args.scale[0] + " 00:00:00", args.scale[1] + " 00:00:00"):
            extract_window(s, e, f"m_{s[:7]}")
    else:
        ap.print_help()
