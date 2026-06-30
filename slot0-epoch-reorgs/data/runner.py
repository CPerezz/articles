#!/usr/bin/env python3
"""Host-side runner for the slot-0 epoch-boundary reorg study.

Executes ClickHouse SQL against ethPandaOps Xatu through the `panda` hosted proxy,
and persists results as JSON for the figure pipeline (plot.py).

Design (see ../../../slot0-reorg-methodology.md §1):
  * Primary path = `panda execute --file <body>` running in-sandbox Python that calls
    `from ethpandaops import clickhouse; clickhouse.query_raw(ds, sql, params)`.
    - native ClickHouse parameter binding ({name:Type} + {"name": value}) -> injection-safe
    - query_raw (raw str tuples) preserves hash / UInt256 / large-UInt64 precision that
      pandas type-inference would silently corrupt.
  * Transport sandbox->host = a stdout SENTINEL envelope (the sandbox /workspace is
    ephemeral and does not sync to this repo). The body prints  SENTINEL + json.dumps(rows).
  * Datasource NAMES are resolved at runtime (the v0.21->v0.36 upgrade renames the
    clusters: xatu/xatu-cbt -> clickhouse-raw/clickhouse-refined). Never hardcode them.
  * Scale-out = host-side windowing (run_windows): one `panda execute` per time window,
    concatenated host-side. Short sandbox lifetime, independent retries.

Prereqs (host shell, once): Docker running; `panda upgrade && panda init && panda auth login`.
Quick check:  python3 runner.py --probe
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SENTINEL = "<<<PANDA_JSON>>>"
# strict allowlist for the only values ever interpolated into a body literal (the resolved
# datasource name); query VALUES go through native binding, never string interpolation.
_DS_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$")


# --------------------------------------------------------------------------- #
# transport
# --------------------------------------------------------------------------- #
def _panda_execute(body_path: str, timeout_s: int, session: str | None) -> str:
    cmd = ["panda", "execute", "--file", body_path, "--timeout", str(timeout_s),
           "--log-level", "error"]
    if session:
        cmd += ["--session", session]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        # surface the sandbox error tail in the message so callers can log it; RuntimeError
        # (not SystemExit) so a single failing query can be caught and skipped.
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError(f"panda execute failed (exit {proc.returncode}): "
                           + (tail[-1] if tail else "no output"))
    return proc.stdout


def create_session() -> str:
    """Create one reusable sandbox session and return its id. Reusing a session across a run
    avoids the 50-session cap (each plain `panda execute` otherwise leaks a session)."""
    proc = subprocess.run(["panda", "session", "create", "-o", "json"],
                          capture_output=True, text=True, check=False)
    blob = (proc.stdout or "") + (proc.stderr or "")
    try:
        d = json.loads(proc.stdout)
        sid = d.get("id") if isinstance(d, dict) else (d[0].get("id") if d else None)
        if sid:
            return sid
    except Exception:
        pass
    m = re.search(r"[0-9a-f]{12,}", blob)
    if not m:
        raise RuntimeError(f"could not create session: {blob[:300]}")
    return m.group(0)


def destroy_session(sid: str) -> None:
    subprocess.run(["panda", "session", "destroy", sid], capture_output=True, text=True, check=False)


def run_body(sandbox_body: str, timeout_s: int = 300, session: str | None = None):
    """Run one in-sandbox Python body; return the parsed JSON payload it printed."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tf:
        tf.write(sandbox_body)
        body_path = tf.name
    try:
        out = _panda_execute(body_path, timeout_s, session)
        m = re.search(re.escape(SENTINEL) + r"(.*)", out, re.S)
        if not m:
            raise RuntimeError("no JSON sentinel in stdout (stray prints? oversized result? "
                               "switch to storage.upload for this window)")
        return json.loads(m.group(1))
    finally:
        os.unlink(body_path)


# --------------------------------------------------------------------------- #
# body construction
# --------------------------------------------------------------------------- #
def make_body(ds: str, sql: str, params: dict | None = None) -> str:
    """Build an in-sandbox body that runs `sql` (with native-bound `params`) against
    datasource `ds` and prints SENTINEL + JSON rows. Stdout becomes JSON-only."""
    if not _DS_RE.match(ds):
        raise ValueError(f"refusing to interpolate unsafe datasource name: {ds!r}")
    params = params or {}
    # ClickHouse HTTP query params are strings; the client formats ints via %g and corrupts
    # large values (14609598 -> '1.4609598e+07'). Stringify ints so they pass verbatim.
    params = {k: (str(v) if isinstance(v, int) and not isinstance(v, bool) else v)
              for k, v in params.items()}
    for k, v in params.items():
        # datetimes are the common case; enforce the strict shape so a templated value
        # can never smuggle SQL even though native binding already protects us.
        if isinstance(v, str) and ("date" in k or k in ("start", "end")) and not _DT_RE.match(v):
            raise ValueError(f"param {k}={v!r} is not a valid datetime literal")
    return (
        "import json, warnings\n"
        "warnings.filterwarnings('ignore')\n"
        "from ethpandaops import clickhouse\n"
        f"DS = {json.dumps(ds)}\n"
        f"SQL = {json.dumps(sql)}\n"
        f"PARAMS = {json.dumps(params)}\n"
        "rows, cols = clickhouse.query_raw(DS, SQL, PARAMS or None)\n"
        "def _nn(v):\n"
        "    return None if v == '\\\\N' else v\n"   # TabSeparated NULL token -> JSON null
        f"print({json.dumps(SENTINEL)} + json.dumps([dict(zip(cols, [_nn(v) for v in r])) for r in rows], default=str))\n"
    )


def run_query(ds: str, sql: str, params: dict | None = None,
              timeout_s: int = 300, session: str | None = None):
    """Convenience: build body + run + return rows (list[dict])."""
    return run_body(make_body(ds, sql, params), timeout_s=timeout_s, session=session)


# --------------------------------------------------------------------------- #
# host-side windowing (the default for the 12-24mo scale-out)
# --------------------------------------------------------------------------- #
def run_windows(make_window_body, windows, out_name: str, timeout_s: int = 300,
                session: str | None = None) -> str:
    """For each (start, end) window run one execute and concatenate the rows.

    make_window_body(start, end) -> sandbox body string.
    Writes <out_name>.json in this dir and returns the path.
    """
    rows: list = []
    for (start, end) in windows:
        chunk = run_body(make_window_body(start, end), timeout_s=timeout_s, session=session)
        rows.extend(chunk)
        sys.stderr.write(f"  window {start}..{end}: +{len(chunk)} (cumulative {len(rows)})\n")
    path = os.path.join(HERE, f"{out_name}.json")
    with open(path, "w") as fh:
        json.dump(rows, fh, indent=2)
    sys.stderr.write(f"wrote {path} ({len(rows)} rows)\n")
    return path


def month_windows(start_date: str, end_date: str):
    """Yield (start, end) datetime-string pairs, one UTC calendar month each, [start, end)."""
    for s in (start_date, end_date):
        if not _DT_RE.match(s):
            raise ValueError(f"bad window bound {s!r}")
    y, m = int(start_date[:4]), int(start_date[5:7])
    ey, em = int(end_date[:4]), int(end_date[5:7])
    while (y, m) <= (ey, em):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        yield (f"{y:04d}-{m:02d}-01 00:00:00", f"{ny:04d}-{nm:02d}-01 00:00:00")
        y, m = ny, nm


# --------------------------------------------------------------------------- #
# Phase-0 capability probe (the gate — see methodology §1.1 / plan U1-U4,U7)
# --------------------------------------------------------------------------- #
_PROBE_BODY = (
    "import json, warnings\n"
    "warnings.filterwarnings('ignore')\n"
    "from ethpandaops import clickhouse\n"
    "out = {}\n"
    "ds = clickhouse.list_datasources()\n"
    "names = [d.get('name') for d in ds]\n"
    "out['datasources'] = names\n"
    "DS_RAW = next((n for n in ('clickhouse-raw','xatu') if n in names), None)\n"
    "DS_CBT = next((n for n in ('clickhouse-refined','xatu-cbt') if n in names), None)\n"
    "out['DS_RAW'] = DS_RAW; out['DS_CBT'] = DS_CBT\n"
    "# U2: native parameter binding works?\n"
    "try:\n"
    "    r, c = clickhouse.query_raw(DS_RAW, 'SELECT {x:UInt32} AS v', {'x': 7})\n"
    "    out['param_binding_ok'] = (str(r[0][0]) == '7')\n"
    "except Exception as e:\n"
    "    out['param_binding_ok'] = False; out['param_binding_err'] = str(e)\n"
    "# U3: CBT mainnet.* exposed to this group?\n"
    "out['cbt_tables'] = None\n"
    "if DS_CBT:\n"
    "    try:\n"
    "        r, c = clickhouse.query_raw(DS_CBT, 'SHOW TABLES FROM mainnet')\n"
    "        out['cbt_tables'] = sorted(x[0] for x in r)\n"
    "    except Exception as e:\n"
    "        out['cbt_err'] = str(e)\n"
    "# server-side stats libs (U14)\n"
    "libs = {}\n"
    "for mod in ('numpy','scipy','pandas','statsmodels','sklearn'):\n"
    "    try:\n"
    "        __import__(mod); libs[mod] = True\n"
    "    except Exception:\n"
    "        libs[mod] = False\n"
    "out['sandbox_libs'] = libs\n"
    f"print({json.dumps(SENTINEL)} + json.dumps(out, default=str))\n"
)

_REQUIRED_CBT = [
    "fct_block", "fct_block_proposer_entity", "fct_block_proposer_head",
    "fct_block_first_seen_by_node", "fct_block_mev", "fct_block_blob_count",
    "canonical_beacon_elaborated_attestation", "dim_validator_pubkey",
]


def probe(timeout_s: int = 120) -> dict:
    """Resolve datasource names + capability report. Writes datasources.json. Fails loudly
    if the raw cluster is missing. Returns the report dict."""
    rep = run_body(_PROBE_BODY, timeout_s=timeout_s)
    if not rep.get("DS_RAW"):
        raise SystemExit(f"FATAL: raw ClickHouse cluster not found in {rep.get('datasources')}")
    rep["cbt_available"] = bool(rep.get("DS_CBT"))
    cbt = set(rep.get("cbt_tables") or [])
    rep["cbt_missing_required"] = [t for t in _REQUIRED_CBT if t not in cbt] if cbt else _REQUIRED_CBT
    with open(os.path.join(HERE, "datasources.json"), "w") as fh:
        json.dump(rep, fh, indent=2)
    return rep


def _print_probe(rep: dict) -> None:
    print("=== panda / Xatu capability probe ===")
    print(f"datasources      : {rep.get('datasources')}")
    print(f"DS_RAW           : {rep.get('DS_RAW')}")
    print(f"DS_CBT           : {rep.get('DS_CBT')}  (CBT track {'ON' if rep.get('cbt_available') else 'OFF -> raw-only fallback'})")
    print(f"param_binding_ok : {rep.get('param_binding_ok')}  {rep.get('param_binding_err','')}")
    miss = rep.get("cbt_missing_required")
    print(f"CBT required tbls: {'all present' if not miss else 'MISSING ' + ', '.join(miss)}")
    print(f"sandbox libs     : {rep.get('sandbox_libs')}")
    print("wrote datasources.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="slot-0 reorg study runner")
    ap.add_argument("--probe", action="store_true", help="run the Phase-0 capability probe and exit")
    args = ap.parse_args()
    if args.probe:
        _print_probe(probe())
    else:
        ap.print_help()
