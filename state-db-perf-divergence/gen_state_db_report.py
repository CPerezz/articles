#!/usr/bin/env python3
"""Generate state-db-perf-report.html from the three benchmarkoor bloatnet logs.

Stdlib only. No CLI args. Every path is resolved relative to this file, so the
article folder is self-contained and the script runs from any cwd:

    data/benchmarkoor_*.log   ->  state-db-perf-report.html   (the report)
                                  figures/fig_*.svg           (charts, standalone)
                                  data/report_data.json       (every computed value)
"""

import collections
import datetime
import html
import json
import os
import re
import sys

import report_svg as S

LOGS = [
    ("c", "compacted", "benchmarkoor_logs_compacted_db.log"),
    ("u", "uncompacted", "benchmarkoor_uncompacted_db.log"),
    ("sa", "state-actor", "benchmarkoor_logs_state_actor.log"),
]
KEYS = [k for k, _, _ in LOGS]
LABEL = {k: lab for k, lab, _ in LOGS}

# key -> (full label, css var name)
DB = {
    "c": ("compacted", "--db-c"),
    "u": ("uncompacted", "--db-u"),
    "sa": ("state-actor", "--db-sa"),
}
# db_headers() and every `for k in KEYS` cell loop emit columns in this one order.
assert list(DB) == KEYS
RUN_ID = {"c": "a20c0626", "u": "eb893b14", "sa": "9cef3be5"}
RUN_DATE = {"c": "2026-08-19", "u": "2026-08-18", "sa": "2026-08-21"}
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figures")
OUT = os.path.join(HERE, "state-db-perf-report.html")
JSON_OUT = os.path.join(DATA, "report_data.json")
VERDICT_IN = os.path.join(DATA, "drained_verdict.json")
INSPECT_IN = {k: os.path.join(DATA, f"db_inspect_{k}.txt")
              for k in ("jochemnet", "state_actor")}


def parse_db_inspect(path):
    """Rows of a `geth db inspect` table: (store, category, size, items).

    Sizes stay as printed ("56.22 GiB") so the report shows exactly what the
    tool said. Log lines and rule lines are skipped by the cell-count test.
    """
    rows = []
    with open(path) as fh:
        for line in fh:
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != 4 or cells[1] in ("Category", ""):
                continue
            rows.append(tuple(cells))
    assert len(rows) >= 8, f"{path}: parsed only {len(rows)} inspect rows"
    assert any(r[1] == "Total" for r in rows), f"{path}: no Total row"
    return rows


INSPECT = {k: parse_db_inspect(v) for k, v in INSPECT_IN.items()}

# The verdict run: the same cells measured on the original jochemnet baseline,
# on the drained + compacted one, and on state-actor. Collected by
# collect_verdict.py; the bands below fail loudly if that file is ever
# regenerated wrong.
with open(VERDICT_IN) as _fh:
    VERDICT = json.load(_fh)
assert len(VERDICT["cells"]) == 32, "verdict: expected 32 cells"
LEAF_OPS = ("BALANCE", "EXTCODEHASH")
_leaf = [c["drained"] / c["sa"] for c in VERDICT["cells"]
         if c["mode"].endswith("DIFF_MAX") and c["opcode"] in LEAF_OPS]
_code = [c["drained"] / c["sa"] for c in VERDICT["cells"]
         if c["mode"].endswith("DIFF_MAX") and c["opcode"] not in LEAF_OPS]
_ctrl = [c["drained"] / c["sa"] for c in VERDICT["cells"]
         if c["mode"].endswith("MINIMAL")]
assert all(1.05 <= r <= 1.25 for r in _leaf), f"verdict leaf band broke: {_leaf}"
assert all(1.10 <= r <= 1.30 for r in _code), f"verdict code band broke: {_code}"
assert all(1.05 <= r <= 1.20 for r in _ctrl), f"verdict control band broke: {_ctrl}"

# What the three database names mean; rendered once beside the legend because the
# prose below says "jochemnet" and nothing else defines it.
PROVENANCE = (
    "compacted and uncompacted are the same jochemnet mainnet shadowfork snapshot, with "
    "and without manual pebble compaction; state-actor is synthetically generated state."
)

# Facts mined from the three container_*.log files (geth's own stdout, 914/974/999
# container lifecycles). Embedded as verified constants for the same reason the rest of
# the container-log facts are: those logs are geth's testimony, not benchmarkoor's
# measurements, and the report parses only the latter. Source: investigation-log.md §6.
LOGMINE = [
    ("container lifecycles", "914", "974", "999"),
    ("journal at startup", "loaded", "loaded", 'FAILED — err="journal not found", 999/999'),
    ("journal at shutdown", "380.15 MiB, layers=4248", "380.15 MiB, layers=4248",
     "39.80 MiB, layers=3"),
    ("triecache / statecache / buffer", "1023.00 MiB / 0.00 B / 256.00 MiB",
     "1023.00 MiB / 0.00 B / 256.00 MiB", "1023.00 MiB / 0.00 B / 256.00 MiB"),
    ("trie memory caches", "clean 1023.00 MiB, dirty 1.00 GiB",
     "clean 1023.00 MiB, dirty 1.00 GiB", "clean 1023.00 MiB, dirty 1.00 GiB"),
    ("db cache / handles / format", "2.00 GiB / 536,870,908 / v1",
     "2.00 GiB / 536,870,908 / v1", "2.00 GiB / 536,870,908 / v1"),
    ("snapshot / flat-state lines", "0", "0", "0"),
    ("compaction / SST / level lines", "0", "0", "0"),
    ("Unclean shutdown detected", "9140", "9740", "0"),
]

# Hypothesis, verdict, and what settled it. Order: dead first, then survivors, so the
# report reads as elimination before explanation.
DISCARDED = [
    ("Larger or unique code takes a different read path", "dead",
     "Under BALANCE geth reads one fixed-shape leaf — nonce, balance, storage root, code "
     "hash. Code lives in a separate table and is never touched. Corroborated: the measured "
     "CODE delta is ≈7 ms/Mgas for JUMPDEST and DIFF_MAX in <em>all three</em> databases."),
    ("state-actor is missing the target accounts", "dead",
     "value_sent=1 gas pricing separates existing from non-existing <em>within</em> each "
     "database; compacted's own DIFF_MAX ÷ NON_EXISTING is 3.36/0.47 = 7.1×."),
    ("The three runs did different amounts of work", "dead",
     "<code>block.gas_used</code> is bit-identical across all three runs on 406/406 "
     "common tests."),
    ("CPU, thermal, or host contention", "dead",
     "overhead_baseline median <code>execution_ms</code> is 33.1 / 33.8 / 32.9 ms."),
    ("Time drift or warm-up over run position", "dead",
     "compacted ÷ uncompacted tracks the account class measured (0.24–1.22×), not run "
     "position."),
    ("The generator dropped the large classes on a size cap", "dead",
     "<code>specbuild/build.go:243</code> — the 2 GiB limit is a warning by design, the cap "
     "is 64 GiB, and the YAML creates every class at 150,000."),
    ("Different derived addresses between the two fixture bundles", "dead",
     "Addresses derive from fixed constants — the Bittrex CREATE-preimage chain, sequential "
     "EOAs from <code>0x1000</code>, <code>keccak256(\"random\")</code> — not from the "
     "bundle hash."),
    ("Snapshot / flat-state availability differs", "dead",
     "Zero matches for <code>snapshot</code>, <code>generat</code>, <code>Rebuilding</code> "
     "or <code>flat</code> in any of the three container logs, across windows spanning every "
     "file. All three run <code>scheme=path</code>; no snapshot layer is involved."),
    ("Trie cache sizing differs between the containers", "dead",
     "Every tunable is byte-identical across the three runs — see the table above. No second "
     "variant of either allocation line appears anywhere in 291,000 lines of log."),
    ("Unclean-shutdown recovery repopulates memory", "dead",
     "The counts are ten <em>static</em> 2025 timestamps replayed once per lifecycle "
     "(914×10≈9140, 974×10≈9740); <code>crashesToKeep = 10</code> caps the list. "
     "<code>NewShutdownTracker</code> is documented as having no side-effect and "
     "<code>MarkStartup</code> only reports. No repair follows."),
    ("On-disk layout changed by manual compaction", "parked",
     "All three logs contain zero compaction, SST or level lines, which was this "
     "hypothesis's stated kill condition. It survives as the only candidate for the "
     "compacted-vs-uncompacted deltas, but nothing available evidences it."),
]

MODES = [
    "NON_EXISTING_ACCOUNT",
    "EXISTING_EOA",
    "EXISTING_CONTRACT_MINIMAL",
    "EXISTING_CONTRACT_SAME_MAX",
    "EXISTING_CONTRACT_JUMPDEST",
    "EXISTING_CONTRACT_DIFF_MAX",
]
SHORT = {
    "NON_EXISTING_ACCOUNT": "NON_EXISTING",
    "EXISTING_EOA": "EOA",
    "EXISTING_CONTRACT_MINIMAL": "MINIMAL",
    "EXISTING_CONTRACT_SAME_MAX": "SAME_MAX",
    "EXISTING_CONTRACT_JUMPDEST": "JUMPDEST",
    "EXISTING_CONTRACT_DIFF_MAX": "DIFF_MAX",
}
OPCODES = ["BALANCE", "CALL", "CALLCODE"]
GAS_PER_ACCESS = 2600
US_PER_MS_MGAS = GAS_PER_ACCESS / 1000.0  # ms/Mgas -> us/lookup == * 2.6

CITE = {
    "new": "EEST <code>tests/benchmark/stateful/bloatnet/test_account_query.py:215-219</code> — "
           "<code>account_new</code> gas is budgeted only when <code>opcode == Op.CALL and "
           "value_sent &gt; 0 and account_mode == AccountMode.NON_EXISTING_ACCOUNT</code>.",
    "pattern": "state-actor <code>internal/templates/code_pattern.go:28-39</code> — max_same is one "
               "shared codeHash; max_diff is byte-unique 24,576 B per account.",
    "cap": "state-actor <code>internal/templates/code_pattern.go:80</code> — hard cap is 64 GiB.",
    "warncap": "state-actor <code>internal/specbuild/build.go:243</code> — the 2 GiB limit is a "
               "warning by design, not a rejection.",
}

MODE_DOC = {
    "NON_EXISTING_ACCOUNT":
        "<b>NON_EXISTING_ACCOUNT</b>“Empty account”. Targets are derived from "
        "<code>keccak256(\"random\")</code>, an address range that is never funded, so the "
        "account is absent from all three databases — nothing to read, nothing to lay out."
        "<span class=src>EEST <code>helper/account_creator.py:36,58</code> · no state-actor "
        "YAML entity, by design</span>",
    "EXISTING_EOA":
        "<b>EXISTING_EOA</b>“EOA with balance.” Plain account: balance and nonce, no code. "
        "state-actor creates 150,000 of them sequentially from <code>0x…1000</code>."
        "<span class=src>EEST <code>helper/account_creator.py:55</code> · state-actor "
        "<code>sequential_eoas</code></span>",
    "EXISTING_CONTRACT_MINIMAL":
        "<b>EXISTING_CONTRACT_MINIMAL</b>“Minimal contract: single STOP byte.” The account "
        "has code, but only one byte of it, so a call halts immediately and code loading is "
        "negligible."
        "<span class=src>EEST <code>helper/account_creator.py:43</code> · state-actor "
        "<code>create2_deploys</code> initcode <code>0x60016000f3</code>  runtime "
        "<code>0x00</code></span>",
    "EXISTING_CONTRACT_SAME_MAX":
        "<b>EXISTING_CONTRACT_SAME_MAX</b>“Max-size contract: byte-identical across copies.” "
        "24,576 B of runtime (EIP-170 limit): <code>STOP</code> at byte 0 then 24,575 "
        "<code>JUMPDEST</code>. Because no address is embedded, every copy hashes to the "
        "<em>same</em> code hash — one shared code blob for 150,000 accounts."
        "<span class=src>EEST <code>helper/account_creator.py:46</code> · state-actor "
        "<code>code_pattern.go:30-34</code></span>",
    "EXISTING_CONTRACT_DIFF_MAX":
        "<b>EXISTING_CONTRACT_DIFF_MAX</b>“Max-size contract: ADDRESS-embedded, each copy "
        "unique.” 24,576 B of runtime with the contract's own 20-byte address written at "
        "<code>0x0C..0x20</code>, so every account is byte-unique and gets its <em>own</em> "
        "code hash — 150,000 distinct 24 KB blobs."
        "<span class=src>EEST <code>helper/account_creator.py:49</code> · state-actor "
        "<code>code_pattern.go:36-39</code></span>",
    "EXISTING_CONTRACT_JUMPDEST":
        "<b>EXISTING_CONTRACT_JUMPDEST</b>“Max-size contract: exercises JUMPDEST analysis. "
        "The code is unique.” 24,576 B of runtime that enters with "
        "<code>PUSH2 0x5FFF; JUMP</code> and lands on a <code>JUMPDEST</code> at the very end, "
        "forcing the client to analyse the whole code section. Address embedded at "
        "<code>0x2C..0x40</code>, so it is byte-unique too."
        "<span class=src>EEST <code>helper/account_creator.py:52</code> · state-actor "
        "<code>code_pattern.go:17-28</code></span>",
}

METRIC_DOC = {
    "us": "Marginal cost of one cold account lookup. Taken as the category's "
          "<code>ms per 1M gas</code> slope × 2.6: a cold access costs 2600 gas, so 1M gas "
          "buys 384.6 lookups. Cold pricing is guaranteed because "
          "<code>access_warm=False</code> under <code>CacheStrategy.NO_CACHE</code>."
          "<span class=src>EEST <code>test_account_query.py:184</code></span>",
    "slope": "Ordinary-least-squares slope of <code>timing.total_ms</code> against the gas "
             "target in millions, fitted over the category's 11 gas levels (100M…300M). The "
             "slope drops the fixed per-block intercept, so it is the marginal cost of state "
             "work only — which is why slopes, not per-test ratios, are the sound comparison.",
}

# ------------------------------------------------------------------- oracles
# Expected (C, U, SA) values from the investigation. Deviations are reported as
# WARN lines on stdout; the report always carries the computed value.

ORACLE_US = {
    "NON_EXISTING": (14.3, 17.3, 15.7),
    "EOA": (15.1, 8.3, 16.7),
    "MINIMAL": (14.2, 3.2, 15.2),
    "SAME_MAX": (13.8, 2.6, 15.3),
    "JUMPDEST": (13.9, 3.1, 15.5),
    "DIFF_MAX": (2.1, 2.4, 16.3),
}

ORACLE_SLOPE = {
    ("BALANCE", "NON_EXISTING"): (5.50, 6.65, 6.03),
    ("BALANCE", "EOA"): (5.83, 3.21, 6.43),
    ("BALANCE", "MINIMAL"): (5.47, 1.22, 5.86),
    ("BALANCE", "SAME_MAX"): (5.32, 1.01, 5.87),
    ("BALANCE", "JUMPDEST"): (5.33, 1.21, 5.96),
    ("BALANCE", "DIFF_MAX"): (0.81, 0.94, 6.28),
    ("CALL", "NON_EXISTING"): (5.91, 7.06, 6.28),
    ("CALL", "EOA"): (5.83, 3.26, 6.41),
    ("CALL", "MINIMAL"): (5.71, 1.14, 5.90),
    ("CALL", "SAME_MAX"): (5.54, 1.37, 6.10),
    ("CALL", "JUMPDEST"): (13.14, 8.07, 13.65),
    ("CALL", "DIFF_MAX"): (8.41, 6.43, 13.00),
    ("CALLCODE", "MINIMAL"): (5.58, 1.32, 6.09),
    ("CALLCODE", "SAME_MAX"): (5.78, 1.43, 6.03),
    ("CALLCODE", "JUMPDEST"): (13.21, 8.46, 13.62),
    ("CALLCODE", "DIFF_MAX"): (8.78, 6.47, 13.04),
}

ORACLE_DELTA = {
    "NON_EXISTING": (0.40, 0.41, 0.25),
    "EOA": (-0.00, 0.05, -0.02),
    "MINIMAL": (0.24, -0.08, 0.05),
    "SAME_MAX": (0.22, 0.36, 0.23),
    "JUMPDEST": (7.80, 6.87, 7.69),
    "DIFF_MAX": (7.59, 5.49, 6.72),
}

# The four EXISTING_CONTRACT rows below are the plan's oracle; the logs give
# almost exactly 2x for them, so they WARN by design. NON_EXISTING and EOA agree.
ORACLE_VS1 = {
    "NON_EXISTING": (0.47, 0.67, 0.93),
    "EOA": (6.55, 4.80, 7.49),
    "MINIMAL": (3.17, 1.91, 3.87),
    "SAME_MAX": (3.31, 1.86, 3.79),
    "JUMPDEST": (4.37, 2.75, 4.95),
    "DIFF_MAX": (1.63, 1.69, 4.83),
}


def check_oracle(table, oracle, computed, tol):
    """Print a WARN per cell whose computed value misses the oracle by > tol."""
    for row, expected in oracle.items():
        got = computed.get(row)
        if got is None:
            print(f"WARN oracle mismatch {table} {row} row absent")
            continue
        for k, exp in zip(KEYS, expected):
            if got[k] is None or abs(got[k] - exp) > tol:
                print(f"WARN oracle mismatch {table} {row}/{k} "
                      f"expected {exp} got {fnum(got[k], 2)}")

# ------------------------------------------------------------------ parsing


def parse_params(test_id):
    m = re.search(r"opcode_([A-Z]+)-", test_id)
    opcode = m.group(1) if m else None
    m = re.search(r"account_mode_AccountMode\.([A-Z_]+)-", test_id)
    mode = m.group(1) if m else None
    m = re.search(r"value_sent_(\d+)-", test_id)
    value_sent = int(m.group(1)) if m else None
    m = re.search(r"overhead_baseline_(True|False)", test_id)
    baseline = (m.group(1) == "True") if m else None
    m = re.search(r"benchmark-gas-value_(\d+)M", test_id)
    gas = int(m.group(1)) if m else None
    return {
        "opcode": opcode, "mode": mode, "value_sent": value_sent,
        "baseline": baseline, "gas": gas,
    }


def parse_log(path):
    """-> (blocks, order) where blocks[test][phase] = [slow-block dicts]."""
    blocks = {}
    order = []
    test = None
    phase = None
    with open(path, errors="ignore") as fh:
        for line in fh:
            if "Executing test" in line:
                m = re.search(r"test=([^\s]+)", line)
                if m:
                    test = m.group(1)
                    phase = None
                    if test not in blocks:
                        blocks[test] = {"setup": [], "test": []}
                        order.append(test)
            elif "Running setup step" in line:
                phase = "setup"
            elif "Running test step" in line:
                phase = "test"
            elif '"msg":"Slow block"' in line:
                if test is None or phase is None:
                    continue
                try:
                    blocks[test][phase].append(
                        json.loads(line[line.find("{"):].strip()))
                except json.JSONDecodeError:
                    continue
    return blocks, order


def measured(blocks):
    """test -> first slow block of the test phase."""
    return {t: v["test"][0] for t, v in blocks.items() if v["test"]}


# -------------------------------------------------------------- computations


def fit(pairs):
    """OLS slope of y vs x."""
    n = len(pairs)
    if n < 2:
        return None
    sx = sum(x for x, _ in pairs)
    sy = sum(y for _, y in pairs)
    sxy = sum(x * y for x, y in pairs)
    sxx = sum(x * x for x, _ in pairs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    return (n * sxy - sx * sy) / denom


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def slope(tests, meas, key, P):
    pairs = [(P[t]["gas"], meas[key][t]["timing"]["total_ms"]) for t in tests]
    return fit(pairs)


def slopes_by_cat(tests, meas, opcode, value_sent, P):
    """(mode, opcode) -> {run: slope ms per 1M gas}."""
    out = {}
    for mode in MODES:
        sel = [t for t in tests
               if P[t]["opcode"] == opcode and P[t]["mode"] == mode
               and P[t]["value_sent"] == value_sent]
        out[mode] = ({k: slope(sel, meas, k, P) for k in KEYS} if sel
                     else {k: None for k in KEYS})
        out[mode]["n"] = len(sel)
    return out


# ------------------------------------------------------------------- HTML


def esc(s):
    return html.escape(str(s))


def tip(label, body):
    return f'<span class=tip tabindex=0>{label}<span class=bub>{body}</span></span>'


def mode_cell(m):
    return f"<td>{tip(esc(SHORT[m]), MODE_DOC[m])}</td>"


def fnum(v, nd=2):
    return "—" if v is None else f"{v:.{nd}f}"


def ratio_cls(r):
    if r is None:
        return ""
    if r > 1.25:
        return " bad"
    if r < 0.7:
        return " good"
    return ""


def bar(v, vmax, var):
    if v is None:
        return ""
    pct = max(0.0, min(100.0, 100.0 * v / vmax))
    return f'<div class=bar><i style="width:{pct:.1f}%;background:var({var})"></i></div>'


def db_headers(after="", numeric=True):
    cls = "n db" if numeric else "db"
    return "".join(
        f'<th class="{cls}" style="color:var({var});border-color:var({var})">{label}</th>{after}'
        for label, var in DB.values())


CSS = """
/* Site theme — mirrors build_site.py CRT_VARS and the ARTICLE stylesheet so the
   report reads as one of the site's pages. Dark-only, like the site. */
:root {
  --bg:#000000; --fg:#e2e6e2; --muted:#aab0aa; --dim:#5c645c; --line:#182818;
  --panel:#0a120a; --accent:#33ff33; --green-dim:#28d128; --green-muted:#1a5a1a;
  --bad-bg:#2a1214; --bad-fg:#ff9a9f; --good-bg:#0f2a12; --good-fg:#7fd98f;
  --barbg:#182818; --chip:#0f1f0f;
  --db-c:#6fb2e8; --db-u:#e8a83a; --db-sa:#b491f0;
  --glow:rgba(51,255,51,.30);
  --crt:'VT323',monospace; --mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--fg); max-width: 960px; margin: auto;
  padding: 28px 20px 80px; font: 15px/1.65 var(--mono);
  -webkit-font-smoothing: antialiased;
}
body::before { content:''; position:fixed; inset:0; z-index:100; pointer-events:none;
  background:repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(0,255,0,.006) 3px,rgba(0,255,0,.006) 6px); }
body::after { content:''; position:fixed; inset:0; z-index:101; pointer-events:none;
  background:radial-gradient(ellipse at center,transparent 62%,rgba(0,0,0,.45) 100%); }
::selection { background: rgba(51,255,51,.22); color:#fff; }
a { color: var(--green-dim); text-decoration: none; border-bottom: 1px solid rgba(51,255,51,.25); }
a:hover { color: var(--accent); border-bottom-color: var(--accent); text-shadow: 0 0 6px var(--glow); }
@media (prefers-reduced-motion: reduce){ *,*::before,*::after{animation-duration:.01ms!important} }
.topbar { display:flex; justify-content:space-between; font-family:var(--crt);
  font-size:1.05rem; color:var(--green-muted); margin-bottom:1.6rem; }
.topbar a { border:none; color:var(--green-muted); }
.topbar a:hover { color:var(--accent); }
.eyebrow { font-family:var(--crt); letter-spacing:.22em; color:var(--accent); opacity:.55;
  font-size:1rem; text-shadow:0 0 8px rgba(51,255,51,.2); margin-bottom:.5rem; }
h1 { font-family:var(--crt); font-weight:400; color:var(--accent); line-height:1.06;
  font-size:clamp(2rem,4.6vw,3rem); margin:0 0 6px;
  text-shadow:0 0 7px var(--glow),0 0 24px rgba(51,255,51,.08); }
.sub { color:var(--muted); font-size:13.5px; margin:0 0 4px; }
.meta { font-size:.72rem; letter-spacing:.05em; color:var(--dim); border-top:1px solid var(--line);
  border-bottom:1px solid var(--line); padding:.6rem 0; margin:14px 0 26px; }
.meta .tag { color:var(--muted); }
h2 { font-family:var(--mono); font-weight:700; color:var(--accent); font-size:19px;
  margin:40px 0 10px; text-shadow:0 0 5px rgba(51,255,51,.18); }
h2::after { content:''; display:block; height:1px; margin-top:.55rem; opacity:.3;
  background:linear-gradient(90deg,var(--green-muted),transparent 65%); }
h3 { font-weight:600; color:#d9ffd9; font-size:15.5px; margin:22px 0 8px; }
h3::before { content:':: '; color:var(--green-muted); }
code { font-family:var(--mono); font-size:.9em; background:rgba(51,255,51,.07);
  border:1px solid var(--line); border-radius:3px; padding:.05em .35em; color:#bfeecf; }
table { border-collapse:collapse; width:100%; margin:10px 0 6px; font-size:13.5px; line-height:1.55; }
th, td { border:1px solid var(--line); padding:6px 9px; text-align:left; vertical-align:middle; }
th { font-family:var(--crt); font-size:1.02rem; font-weight:400; letter-spacing:.05em;
  color:var(--accent); background:rgba(51,255,51,.05); text-shadow:0 0 5px rgba(51,255,51,.15); }
tr:nth-child(even) td { background:rgba(51,255,51,.02); }
tr:hover td { background:rgba(51,255,51,.045); }
td.n, th.n { text-align:right; font-variant-numeric:tabular-nums; }
td.bad { background:var(--bad-bg); color:var(--bad-fg); font-weight:600; }
td.good { background:var(--good-bg); color:var(--good-fg); font-weight:600; }
caption { caption-side:bottom; color:var(--muted); font-size:12.5px; text-align:left;
  padding:8px 0 0; line-height:1.55; }
.bar { background:var(--barbg); border-radius:2px; height:8px; width:110px;
  overflow:hidden; display:inline-block; }
.bar > i { display:block; height:100%; }
.legend { display:flex; gap:18px; flex-wrap:wrap; margin:14px 0 10px; font-size:13px; }
.legend b { font-weight:600; }
.sw { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; }
th.db { border-bottom-width:2px; }
details { border:1px solid var(--line); border-radius:2px; padding:4px 14px;
  margin:12px 0; background:var(--panel); }
details[open] { padding-bottom:12px; }
summary { cursor:pointer; font-weight:600; color:#d9ffd9; padding:9px 2px; }
summary::marker { color:var(--accent); }
.card { border:1px solid var(--line); border-left:3px solid var(--green-muted);
  border-radius:2px; padding:4px 18px 14px; margin:16px 0; background:var(--panel); }
.card details { background:var(--bg); }
.chip { display:inline-block; background:var(--chip); border:1px solid var(--green-muted);
  border-radius:3px; padding:2px 10px; font-size:12px; color:var(--muted);
  vertical-align:middle; margin-left:8px; }
.note { color:var(--muted); font-size:13px; }
ul.tight { list-style:none; padding-left:0; }
ul.tight li { position:relative; padding-left:1.3rem; margin:5px 0; }
ul.tight li::before { content:'▸'; position:absolute; left:0; color:var(--green-dim); }
ol.tight li { margin:5px 0; }
ol.tight li::marker { color:var(--green-dim); }
.tip { position:relative; border-bottom:1px dotted var(--muted); cursor:help; }
.tip > .bub { display:none; }
.tip:hover > .bub, .tip:focus > .bub, .tip:focus-within > .bub { display:block; }
.bub { position:absolute; left:0; top:1.7em; z-index:9; width:360px; max-width:70vw;
  background:#050805; color:var(--fg); border:1px solid var(--green-muted); border-radius:3px;
  padding:10px 12px; font-size:12.5px; line-height:1.5; font-weight:400; text-align:left;
  white-space:normal; box-shadow:0 0 18px rgba(51,255,51,.10); }
.bub b { display:block; margin-bottom:4px; font-family:var(--mono); }
.bub .src { display:block; margin-top:6px; color:var(--dim); font-size:11.5px; }
svg.chart { width:100%; height:auto; margin:6px 0 2px; overflow:visible; font:11px var(--mono); }
svg.chart text { fill:var(--fg); }
svg.chart text.tick, svg.chart text.ax { fill:var(--muted); }
svg.chart text.big { font-size:12px; font-weight:600; }
figure { margin:16px 0 8px; border:1px solid var(--line); background:#050805; padding:10px 12px; }
figure:hover { border-color:var(--green-muted); box-shadow:0 0 22px rgba(51,255,51,.06); }
figcaption { color:var(--muted); font-size:12.5px; margin-top:6px; line-height:1.55; }
pre.idpre { background:#050805; border:1px solid var(--line); border-radius:3px;
  padding:8px 10px; overflow-x:auto; font-size:11.5px; line-height:1.5;
  white-space:pre-wrap; word-break:break-all; }
.endbar { margin-top:48px; padding-top:1.2rem; border-top:1px solid var(--line);
  font-family:var(--crt); font-size:1rem; color:var(--green-muted);
  display:flex; justify-content:space-between; flex-wrap:wrap; gap:.6rem; }
.endbar a { border:none; }
.cursor { display:inline-block; width:.5em; height:.9em; background:var(--accent);
  vertical-align:-2px; margin-left:2px; animation:blink 1s step-end infinite; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
.deck { color:var(--muted); font-size:15.5px; line-height:1.6; margin:2px 0 14px; }
nav.toc { border:1px solid var(--line); background:var(--panel); padding:12px 16px;
  margin:18px 0 26px; font-size:13.5px; }
nav.toc .toch { color:var(--accent); letter-spacing:.08em; text-transform:uppercase;
  font-size:11.5px; margin-bottom:8px; }
nav.toc ul { list-style:none; margin:0; padding:0; }
nav.toc li { margin:3px 0; }
nav.toc li.sub { padding-left:20px; font-size:12.5px; }
nav.toc li.sub a { color:var(--muted); }
nav.toc a { text-decoration:none; }
nav.toc a:hover { text-decoration:underline; }
"""


# The standalone .svg files carry no page around them, so the chart variables and
# text rules have to travel inside each file. The palette is derived from CSS
# above rather than restated, so a colour change here cannot drift from the report.
def _css_vars(block):
    return dict(re.findall(r"(--[a-z-]+):\s*(#[0-9a-fA-F]{3,8})", block))


SVG_VARS = _css_vars(re.search(r":root \{(.*?)\}", CSS, re.S).group(1))
assert "--db-c" in SVG_VARS and "--accent" in SVG_VARS, \
    "chart palette no longer derivable from CSS"

SVG_TEXT_CSS = (
    "svg{font:11px 'IBM Plex Mono',ui-monospace,Menlo,monospace}"
    'text{fill:var(--fg)}text.tick,text.ax{fill:var(--muted)}'
    'text.big{font-size:12px;font-weight:600}'
)


def figure(svg, caption):
    return f"<figure>{svg}<figcaption>{caption}</figcaption></figure>"


def add_toc(doc):
    """Give every navigable heading an id and build the contents list.

    Headings inside a <details> are supporting material rather than
    navigation targets, so they are left alone.
    """
    entries = []

    def tag(m):
        level, inner = m.group(1), m.group(2)
        before = doc[:m.start()]
        if before.count("<details") > before.count("</details>"):
            return m.group(0)
        slug = re.sub(r"[^a-z0-9]+", "-",
                      html.unescape(re.sub(r"<[^>]+>", "", inner)).lower()).strip("-")
        entries.append((level, slug, inner))
        return f'<h{level} id="{slug}">{inner}</h{level}>'

    doc = re.sub(r"<h([23])>(.*?)</h\1>", tag, doc, flags=re.S)
    assert entries, "table of contents: no headings found"
    items = "".join(
        f'<li{" class=sub" if lvl == "3" else ""}><a href="#{slug}">{text}</a></li>'
        for lvl, slug, text in entries)
    nav = f'<nav class=toc><div class=toch>Contents</div><ul>{items}</ul></nav>'
    assert doc.count("<!--TOC-->") == 1, "table of contents: marker missing"
    return doc.replace("<!--TOC-->", nav)


def standalone_svg(svg):
    """Same chart markup, wrapped so the file renders on its own in any viewer.

    In the report the page supplies the background; a bare .svg does not, so the
    file carries its own background rect plus the site palette (dark, like the
    site — the report is dark-only).
    """
    vars_css = "".join(f"{k}:{v};" for k, v in SVG_VARS.items())
    style = f"<style>svg{{{vars_css}}}{SVG_TEXT_CSS}</style>"
    head, rest = svg.split(">", 1)
    return (f'{head} xmlns="http://www.w3.org/2000/svg">{style}'
            f'<rect width="100%" height="100%" fill="var(--bg)"/>{rest}')


def chart_verdict(v):
    """Cross-arm ratio per DIFF_MAX cell, before and after the fix."""
    cells = sorted((c for c in v["cells"] if c["mode"].endswith("DIFF_MAX")),
                   key=lambda c: (c["opcode"], c["gas"]))
    ctrl = [c["drained"] / c["sa"] for c in v["cells"]
            if c["mode"].endswith("MINIMAL")]
    W, LEFT, RIGHT, TOP = 760, 200, 46, 16
    H = TOP + 20 * len(cells) + 34
    lo, hi = 0.9, 30.0
    sc = S.LogScale(lo, hi, LEFT, W - RIGHT)
    body = [S.band(sc.to(min(ctrl)), sc.to(max(ctrl)), TOP - 6, H - 34, "--db-sa", 0.12),
            S.hgrid(sc, [1, 1.2, 2, 3, 5, 10, 23], TOP - 6, H - 34, lambda t: f"{t:g}x"),
            S.line(sc.to(1.0), TOP - 6, sc.to(1.0), H - 34, "--muted", 1, "3 3")]
    for i, c in enumerate(cells):
        y = TOP + 14 + 20 * i
        before, after = c["orig"] / c["sa"], c["drained"] / c["sa"]
        body.append(S.label(LEFT - 10, y + 4, f'{c["opcode"]}  {c["gas"]}', "end"))
        body.append(S.line(sc.to(after), y, sc.to(before), y, "--dim", 1.5))
        body.append(S.dot(sc.to(before), y, 4.5, "--db-u", f"before {before:.2f}x"))
        body.append(S.dot(sc.to(after), y, 6, "--accent", f"after {after:.2f}x"))
        body.append(S.label(sc.to(before) + 9, y + 4, f"{before:.1f}x", "start", "tick"))
    return (S.svg(W, H, "".join(body)),
            f"Cross-arm ratio (jochemnet \u00f7 state-actor) for every DIFF_MAX cell: "
            f"amber before the fix, green after. The shaded band is the MINIMAL "
            f"control ({min(ctrl):.2f}\u2013{max(ctrl):.2f}\u00d7), which the fix "
            f"leaves exactly where it was.")


def chart_ratio_dots(by_op):
    rows = [(op, m, by_op[op][m]["sa"] / by_op[op][m]["c"])
            for op in OPCODES for m in MODES if by_op[op][m]["n"]]
    W, LEFT, RIGHT, TOP = 760, 190, 30, 16
    H = TOP + 20 * len(rows) + 34
    lo, hi = 1.0, 8.5
    sc = S.LogScale(lo, hi, LEFT, W - RIGHT)
    non_dm = [r for _, m, r in rows if m != "EXISTING_CONTRACT_DIFF_MAX"]
    dm_n = len(rows) - len(non_dm)
    assert all(lo <= r <= hi for _, _, r in rows), \
        f"ratio outside chart-1 axis domain [{lo},{hi}]: {rows}"
    body = [S.band(sc.to(min(non_dm)), sc.to(max(non_dm)), TOP - 6,
                   H - 34, "--db-sa", 0.12)]
    body.append(S.hgrid(sc, [1, 1.1, 1.25, 1.5, 2, 4, 8], TOP - 6, H - 34,
                        lambda t: f"{t:g}x"))
    body.append(S.line(sc.to(1.0), TOP - 6, sc.to(1.0), H - 34, "--muted", 1, "3 3"))
    for i, (op, m, r) in enumerate(rows):
        y = TOP + 14 + 20 * i
        dm = m == "EXISTING_CONTRACT_DIFF_MAX"
        body.append(S.label(LEFT - 10, y + 4, f"{op}  {SHORT[m]}", "end",
                            "big" if dm else ""))
        body.append(S.dot(sc.to(r), y, 6 if dm else 4.5, "--accent", f"{r:.3f}x"))
        body.append(S.label(sc.to(r) + 10, y + 4, f"{r:.2f}x", "start",
                            "big" if dm else "tick"))
    return (S.svg(W, H, "".join(body)),
            f'state-actor ÷ compacted, ms per 1M gas, log axis. The shaded band '
            f'spans the {len(non_dm)} non-DIFF_MAX categories '
            f'({min(non_dm):.2f}x–{max(non_dm):.2f}x). '
            f'Only the {dm_n} DIFF_MAX categories leave it.')


def chart_dumbbell(us):
    W, LEFT, RIGHT, TOP = 760, 130, 40, 18
    H = TOP + 26 * len(MODES) + 34
    hi = max(v for m in MODES for v in us[m].values()) * 1.08
    sc = S.Scale(0, hi, LEFT, W - RIGHT)
    body = [S.hgrid(sc, [0, 4, 8, 12, 16], TOP - 8, H - 34, lambda t: f"{t:g} µs")]
    for i, m in enumerate(MODES):
        y = TOP + 16 + 26 * i
        u, c, sa = us[m]["u"], us[m]["c"], us[m]["sa"]
        body.append(S.label(LEFT - 10, y + 4, SHORT[m], "end"))
        body.append(S.line(sc.to(u), y, sc.to(c), y, "--line", 3))
        body.append(S.dot(sc.to(u), y, 5, "--db-u", f"uncompacted {u:.1f} µs"))
        body.append(S.dot(sc.to(c), y, 5, "--db-c", f"compacted {c:.1f} µs"))
        body.append(S.line(sc.to(sa), y - 8, sc.to(sa), y + 8, "--db-sa", 2))
        body.append(S.label(sc.to(max(u, c, sa)) + 12, y + 4,
                            f"{u:.1f} → {c:.1f}", "start", "tick"))
    dm, ne = "EXISTING_CONTRACT_DIFF_MAX", "NON_EXISTING_ACCOUNT"
    slowed = [m for m in MODES if us[m]["c"] > us[m]["u"]]
    u_lo, u_hi = min(us[m]["u"] for m in slowed), max(us[m]["u"] for m in slowed)
    c_lo, c_hi = min(us[m]["c"] for m in slowed), max(us[m]["c"] for m in slowed)
    assert dm not in slowed and ne not in slowed, \
        f"dumbbell caption direction inverted: slowed={slowed}"
    assert us[ne]["c"] < us[ne]["u"], "NON_EXISTING no longer faster on compacted"
    return (S.svg(W, H, "".join(body)),
            f'µs per lookup, BALANCE value_sent=0. Dot pairs run '
            f'<b>uncompacted → compacted</b>; the vertical bar is state-actor. Manual '
            f'compaction pushed {len(slowed)} classes from {fnum(u_lo,1)}–{fnum(u_hi,1)} µs up to '
            f'{fnum(c_lo,1)}–{fnum(c_hi,1)} µs, left DIFF_MAX at {fnum(us[dm]["u"],1)} → '
            f'{fnum(us[dm]["c"],1)} µs, and made NON_EXISTING faster '
            f'({fnum(us[ne]["u"],1)} → {fnum(us[ne]["c"],1)} µs).')


def chart_slope_lines(meas, P, clean, mode="EXISTING_CONTRACT_DIFF_MAX", opcode="BALANCE"):
    sel = sorted((t for t in clean if P[t]["mode"] == mode and P[t]["opcode"] == opcode),
                 key=lambda t: P[t]["gas"])
    W, H, LEFT, RIGHT, TOP, BOT = 760, 300, 62, 130, 16, 34
    gmin, gmax = P[sel[0]]["gas"], P[sel[-1]]["gas"]
    ymax = max(meas[k][t]["timing"]["total_ms"] for k in KEYS for t in sel) * 1.08
    sx = S.Scale(gmin, gmax, LEFT, W - RIGHT)
    sy = S.Scale(0, ymax, H - BOT, TOP)
    body = [S.hgrid(sx, [100, 150, 200, 250, 300], TOP, H - BOT, lambda t: f"{t}M")]
    for yv in (0, 500, 1000, 1500, 2000):
        if yv <= ymax:
            body.append(S.line(LEFT, sy.to(yv), W - RIGHT, sy.to(yv), "--line", 1))
            body.append(S.label(LEFT - 8, sy.to(yv) + 4, f"{yv}", "end", "tick"))
    end_labels = []
    for k, (lab, var) in DB.items():
        pts = [(sx.to(P[t]["gas"]), sy.to(meas[k][t]["timing"]["total_ms"])) for t in sel]
        body.append(S.polyline(pts, var, 2.4))
        for (x, y), t in zip(pts, sel):
            body.append(S.dot(x, y, 3, var,
                              f"{lab} {P[t]['gas']}M: "
                              f"{meas[k][t]['timing']['total_ms']:.0f} ms"))
        end_labels.append((pts[-1][0] + 10, pts[-1][1] + 4, lab))
    end_labels.sort(key=lambda row: row[1])
    line_h = 12  # text.big line height (gen_state_db_report.py CSS: svg.chart text.big font-size:12px)
    for i in range(1, len(end_labels)):
        x, y, lab = end_labels[i]
        prev_y = end_labels[i - 1][1]
        if y < prev_y + line_h:
            end_labels[i] = (x, prev_y + line_h, lab)
    for x, y, lab in end_labels:
        body.append(S.label(x, y, lab, "start", "big"))
    body.append(S.label(LEFT - 8, TOP + 4, "total_ms", "end", "ax"))
    return (S.svg(W, H, "".join(body)),
            f'{opcode}, {SHORT[mode]}, value_sent=0: measured block wall time '
            f'against gas target, all {len(sel)} levels. Both jochemnet databases stay nearly flat '
            f'while state-actor rises linearly — the divergence is a slope, not an '
            f'offset.')


def chart_convergence(gas_rows, slope_median, n_cat):
    W, H, LEFT, RIGHT, TOP, BOT = 760, 280, 62, 40, 16, 34
    gmin, gmax = gas_rows[0][0], gas_rows[-1][0]
    lo = min(min(r[3] for r in gas_rows), slope_median) * 0.97
    hi = max(r[4] for r in gas_rows) * 1.03
    sx = S.Scale(gmin, gmax, LEFT, W - RIGHT)
    sy = S.Scale(lo, hi, H - BOT, TOP)
    body = [S.hgrid(sx, [g for g, *_ in gas_rows], TOP, H - BOT, lambda t: f"{t}M")]
    for yv in (1.0, 1.1, 1.2, 1.3, 1.4):
        if lo <= yv <= hi:
            body.append(S.line(LEFT, sy.to(yv), W - RIGHT, sy.to(yv), "--line", 1))
            body.append(S.label(LEFT - 8, sy.to(yv) + 4, f"{yv:.1f}x", "end", "tick"))
    top = [(sx.to(g), sy.to(mx)) for g, _, _, _, mx in gas_rows]
    bottom = [(sx.to(g), sy.to(mn)) for g, _, _, mn, _ in reversed(gas_rows)]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in top + bottom)
    body.append(f'<polygon points="{pts}" fill="var(--db-sa)" opacity="0.14"/>')
    body.append(S.polyline([(sx.to(g), sy.to(md)) for g, _, md, _, _ in gas_rows],
                           "--db-sa", 2.4))
    for g, n, md, _, _ in gas_rows:
        body.append(S.dot(sx.to(g), sy.to(md), 3.5, "--db-sa", f"{g}M n={n}: {md:.3f}x"))
    body.append(S.line(LEFT, sy.to(slope_median), W - RIGHT, sy.to(slope_median),
                       "--accent", 2, "5 4"))
    body.append(S.label(W - RIGHT, sy.to(slope_median) - 8,
                        f"slope ratio {slope_median:.2f}x", "end", "big"))
    n_tests = sum(n for _, n, *_ in gas_rows)
    n_lo, n_hi = min(n for _, n, *_ in gas_rows), max(n for _, n, *_ in gas_rows)
    return (S.svg(W, H, "".join(body)),
            f'Per-test state-actor ÷ compacted <code>total_ms</code>, median with '
            f'min–max band per gas target over the {n_tests} clean non-DIFF_MAX tests '
            f'({n_lo}–{n_hi} per level, {n_cat} categories). The ratio decays from '
            f'{gas_rows[0][2]:.2f}x toward the dashed slope ratio as the gas target grows: '
            f'what is left at low gas is fixed per-block overhead, not state '
            f'cost.')


def main():
    missing = [f for _, _, f in LOGS if not os.path.exists(os.path.join(DATA, f))]
    if missing:
        for f in missing:
            print(f"error: missing input log: {os.path.join(DATA, f)}", file=sys.stderr)
        return 1

    raw, order = {}, {}
    for k, _, f in LOGS:
        raw[k], order[k] = parse_log(os.path.join(DATA, f))
    meas = {k: measured(raw[k]) for k in KEYS}

    common = [t for t in order["c"] if all(t in meas[k] for k in KEYS)]
    print(f"common tests: {len(common)}")
    assert len(common) == 406, f"expected 406 common tests, got {len(common)}"
    assert set(MODE_DOC) == set(MODES), "MODE_DOC must cover exactly the six account modes"

    P = {t: parse_params(t) for t in common}

    mismatch = [t for t in common
                if len({meas[k][t]["block"]["gas_used"] for k in KEYS}) != 1]
    print(f"gas mismatches: {len(mismatch)}")
    assert not mismatch, f"gas_used mismatch on {len(mismatch)} tests"

    baseline = [t for t in common if P[t]["baseline"]]
    clean = [t for t in common if not P[t]["baseline"] and P[t]["value_sent"] == 0]
    vs1 = [t for t in common if not P[t]["baseline"] and P[t]["value_sent"] == 1]
    print(f"baseline/clean/vs1: {len(baseline)}/{len(clean)}/{len(vs1)}")

    bal0 = slopes_by_cat(clean, meas, "BALANCE", 0, P)
    call0 = slopes_by_cat(clean, meas, "CALL", 0, P)
    ccode0 = slopes_by_cat(clean, meas, "CALLCODE", 0, P)
    call1 = slopes_by_cat(vs1, meas, "CALL", 1, P)
    by_op = {"BALANCE": bal0, "CALL": call0, "CALLCODE": ccode0}

    # headline: us per lookup, BALANCE vs=0
    us = {m: {k: (None if bal0[m][k] is None else bal0[m][k] * US_PER_MS_MGAS)
              for k in KEYS} for m in MODES}
    usmax = max(v for m in MODES for v in us[m].values() if v is not None)

    print("\nus per lookup — BALANCE, value_sent=0")
    print(f'{"account_mode":<26}{"C":>7}{"U":>7}{"SA":>7}{"SA/C":>8}')
    for m in MODES:
        r = (us[m]["sa"] / us[m]["c"]) if us[m]["c"] else None
        print(f"{m:<26}{fnum(us[m]['c'],1):>7}{fnum(us[m]['u'],1):>7}"
              f"{fnum(us[m]['sa'],1):>7}{fnum(r,2):>8}")

    check_oracle("us_per_lookup", ORACLE_US, {SHORT[m]: us[m] for m in MODES}, 0.1)

    # code delta: CALL slope - BALANCE slope
    delta = {m: {k: (None if (call0[m][k] is None or bal0[m][k] is None)
                     else call0[m][k] - bal0[m][k]) for k in KEYS} for m in MODES}

    # baseline stats
    base_slope = {k: slope(baseline, meas, k, P) for k in KEYS}
    base_exec = {k: median([meas[k][t]["timing"]["execution_ms"] for t in baseline])
                 for k in KEYS}

    # negative execution_ms in value-transfer blocks
    negs = {k: sum(1 for t in common if meas[k][t]["timing"]["execution_ms"] < 0)
            for k in KEYS}
    neg_c, neg_u, neg_sa = negs["c"], negs["u"], negs["sa"]
    neg_exec = sum(negs.values())
    assert all(P[t]["value_sent"] == 1
               for t in common
               if any(meas[k][t]["timing"]["execution_ms"] < 0 for k in KEYS)), \
        "negative execution_ms outside value-transfer tests"

    # per-test buckets over clean
    buckets = {"diffmax": [], "flat": [], "other": []}
    for t in clean:
        r = meas["sa"][t]["timing"]["total_ms"] / meas["c"][t]["timing"]["total_ms"]
        if P[t]["mode"] == "EXISTING_CONTRACT_DIFF_MAX":
            buckets["diffmax"].append(r)
        elif r <= 1.25:
            buckets["flat"].append(r)
        else:
            buckets["other"].append(r)
    print(f"buckets diffmax/flat/other: {len(buckets['diffmax'])}/"
          f"{len(buckets['flat'])}/{len(buckets['other'])} of {len(clean)}")

    # worst divergence ranking
    def mgas(k, t):
        return meas[k][t]["throughput"]["mgas_per_sec"]

    DM = "EXISTING_CONTRACT_DIFF_MAX"

    worst = sorted(clean, key=lambda t: mgas("sa", t) / mgas("c", t))[:15]

    worst_lead = 0
    for t in worst:
        if P[t]["mode"] == DM and P[t]["opcode"] == "BALANCE":
            worst_lead += 1
        else:
            break

    # vs=1 ratios vs own NON_EXISTING
    vs1_ratio = {}
    for k in KEYS:
        ne = call1["NON_EXISTING_ACCOUNT"][k]
        vs1_ratio[k] = {m: (None if (ne in (None, 0) or call1[m][k] is None)
                            else call1[m][k] / ne) for m in MODES}

    check_oracle("slope_ms_per_Mgas", ORACLE_SLOPE,
                 {(op, SHORT[m]): by_op[op][m] for op in OPCODES for m in MODES
                  if by_op[op][m]["n"]}, 0.02)
    check_oracle("code_delta", ORACLE_DELTA, {SHORT[m]: delta[m] for m in MODES}, 0.02)
    check_oracle("vs1_call_slope", ORACLE_VS1, {SHORT[m]: call1[m] for m in MODES}, 0.02)
    check_oracle("baseline", {"slope_ms_per_Mgas": (0.12, 0.15, 0.15),
                              "median_execution_ms": (33.1, 33.8, 32.9)},
                 {"slope_ms_per_Mgas": base_slope, "median_execution_ms": base_exec}, 0.05)

    # separation of EXISTING from NON_EXISTING under value_sent=1, per state-actor
    sep = [vs1_ratio["sa"][m] for m in MODES if m != "NON_EXISTING_ACCOUNT"]
    sep_lo, sep_hi = min(sep), max(sep)
    print(f"vs1 SA separation vs own NON_EXISTING: {sep_lo:.2f}-{sep_hi:.2f}x")

    # agreement outside DIFF_MAX: 13 categories vs the 3 DIFF_MAX exceptions
    agree, exceptions = [], []
    for op in OPCODES:
        for m in MODES:
            cat = by_op[op][m]
            if not cat["n"]:
                continue
            (exceptions if m == DM else agree).append(
                (op, m, cat["sa"] / cat["c"] if cat["c"] else None))
    agree_lo = min(r for _, _, r in agree)
    agree_hi = max(r for _, _, r in agree)
    agree_med = median([r for _, _, r in agree])

    per_gas = collections.defaultdict(list)
    for t in clean:
        if P[t]["mode"] == DM:
            continue
        per_gas[P[t]["gas"]].append(
            meas["sa"][t]["timing"]["total_ms"] / meas["c"][t]["timing"]["total_ms"])
    gas_rows = [(gv, len(v), median(v), min(v), max(v))
                for gv, v in sorted(per_gas.items())]

    # The same per-test ratio restricted to DIFF_MAX, so the gas sweep can be
    # compared like for like: the honest categories converge with gas, this one
    # does not.
    dm_per_gas = collections.defaultdict(list)
    for t in clean:
        if P[t]["mode"] != DM:
            continue
        dm_per_gas[P[t]["gas"]].append(
            meas["sa"][t]["timing"]["total_ms"] / meas["c"][t]["timing"]["total_ms"])
    dm_gas_rows = [(gv, median(v)) for gv, v in sorted(dm_per_gas.items())]
    assert len(dm_gas_rows) >= 8, f"DIFF_MAX gas sweep too sparse: {dm_gas_rows}"
    print(f"DIFF_MAX per-gas median ratio: {dm_gas_rows[0][1]:.2f}x at "
          f"{dm_gas_rows[0][0]}M -> {dm_gas_rows[-1][1]:.2f}x at {dm_gas_rows[-1][0]}M")

    assert len(agree) == 13 and len(exceptions) == 3
    assert agree_hi < 1.15, f"non-DIFF_MAX category exceeded 1.15x: {agree_hi:.3f}"
    print(f"agreement: {len(agree)} categories {agree_lo:.3f}-{agree_hi:.3f}x "
          f"(median {agree_med:.3f}); exceptions "
          + ", ".join(f"{op}/{SHORT[m]} {r:.2f}x" for op, m, r in exceptions))

    # why one gas level is short a test: derive the deficient level, the missing
    # (opcode, account_mode) cell, and which runs actually executed it.
    cells_at = collections.defaultdict(set)
    for t in clean:
        if P[t]["mode"] != DM:
            cells_at[P[t]["gas"]].add((P[t]["opcode"], P[t]["mode"]))
    typical = collections.Counter(n for _, n, *_ in gas_rows).most_common(1)[0][0]
    short_rows = [(gv, n) for gv, n, *_ in gas_rows if n != typical]
    assert len(short_rows) == 1, f"expected one deficient gas level, got {short_rows}"
    short_gas, short_n = short_rows[0]
    full_grid = max(cells_at.values(), key=len)
    missing = full_grid - cells_at[short_gas]
    assert len(missing) == 1, f"expected one missing cell at {short_gas}M, got {missing}"
    miss_op, miss_mode = next(iter(missing))

    def executed(k):
        """Did run k's log contain the missing cell at all? (order = every test the run
        logged, not just tests with a measured block — see measured())."""
        for t in order[k]:
            p = parse_params(t)
            if (p["opcode"], p["mode"], p["gas"], p["value_sent"], p["baseline"]) == \
                    (miss_op, miss_mode, short_gas, 0, False):
                return True
        return False

    miss_ran = [k for k in KEYS if executed(k)]
    miss_absent = [k for k in KEYS if k not in miss_ran]
    assert miss_absent == ["c"] and miss_ran == ["u", "sa"], (
        f"short-row mechanism changed: {miss_op}/{SHORT[miss_mode]} at {short_gas}M "
        f"ran in {miss_ran}, absent from {miss_absent}")

    # category census backing the test-id mapping section
    def population(p):
        return "overhead_baseline" if p["baseline"] else f"value_sent={p['value_sent']}"

    census = collections.defaultdict(list)
    for t in common:
        census[(population(P[t]), P[t]["opcode"], P[t]["mode"])].append(t)
    assert sum(len(v) for v in census.values()) == len(common)
    assert len(census) == 33, f"expected 33 parameter categories, got {len(census)}"
    prefix = os.path.commonprefix(common)
    assert len(prefix) == 125, f"id prefix changed: {len(prefix)}"
    levels = {k: len({P[t]["gas"] for t in v}) for k, v in census.items()}
    full_levels = collections.Counter(levels.values()).most_common(1)[0][0]
    # the one short category must be exactly the cell compacted never ran (derived above)
    short_cats = [k for k, n in levels.items() if n != full_levels]
    assert short_cats == [("value_sent=0", miss_op, miss_mode)], short_cats
    bl = {k: len(v) for k, v in census.items() if k[0] == "overhead_baseline"}
    bl_n = max(bl.values())
    bl_ops = sorted({op for (_, op, _), n in bl.items() if n == bl_n})
    cc_absent = [SHORT[m] for m in MODES
                 if not any(k[1] == "CALLCODE" and k[2] == m for k in census)]

    # C1: real min/max backing the "All N categories" summary (was hand-typed and wrong).
    sa_vals = [by_op[op][m]["sa"] for op in OPCODES for m in MODES if by_op[op][m]["n"]]
    cu_vals = [by_op[op][m][k] for op in OPCODES for m in MODES if by_op[op][m]["n"]
               for k in ("c", "u")]
    sa_slope_lo, sa_slope_hi = min(sa_vals), max(sa_vals)
    cu_slope_lo, cu_slope_hi = min(cu_vals), max(cu_vals)

    # I1: time-drift refutation, named metric — per-category median per-test throughput
    # ratio (MGas/s numerator over denominator; above 1 means the numerator is faster).
    # DIFF_MAX excluded from the state-actor/compacted band: it is the one category the
    # hypothesis under test does not cover (H2's memory-residency signature).
    drift = []
    for op in OPCODES:
        for m in MODES:
            sel = [t for t in clean if P[t]["opcode"] == op and P[t]["mode"] == m]
            if not sel:
                continue
            drift.append((op, m,
                          median([mgas("c", t) / mgas("u", t) for t in sel]),
                          median([mgas("sa", t) / mgas("c", t) for t in sel])))
    drift_cu_lo = min(r[2] for r in drift)
    drift_cu_hi = max(r[2] for r in drift)
    drift_sc = [r[3] for r in drift if r[1] != DM]
    drift_sc_lo, drift_sc_hi = min(drift_sc), max(drift_sc)
    # The categories where compacted actually beats uncompacted, derived rather than
    # asserted: "only NON_EXISTING" was false (DIFF_MAX beats it too, matching the
    # headline table's 2.1 vs 2.4 µs) and leaning on H2's RAM-residency inference to
    # excuse it would presuppose the very thing this report labels unmeasured.
    cu_faster = [(op, m, r) for op, m, r, _ in drift if r > 1.0]
    assert {(op, m) for op, m, _ in cu_faster} == {
        ("BALANCE", "NON_EXISTING_ACCOUNT"), ("CALL", "NON_EXISTING_ACCOUNT"),
        ("BALANCE", DM)}, \
        f"compacted-faster set changed: {[(op, SHORT[m], round(r, 3)) for op, m, r in cu_faster]}"
    cu_faster_txt = ", ".join(f"{op}&nbsp;{SHORT[m]} {r:.2f}&times;"
                              for op, m, r in cu_faster)
    print(f"time drift: c/u per-category median throughput ratio "
          f"{drift_cu_lo:.3f}-{drift_cu_hi:.3f}; sa/c excl DIFF_MAX "
          f"{drift_sc_lo:.3f}-{drift_sc_hi:.3f}; compacted faster on "
          + ", ".join(f"{op}/{SHORT[m]} {r:.3f}" for op, m, r in cu_faster))

    # ------------------------------------------------------------- emit HTML
    o = []
    w = o.append
    today = datetime.date.today().isoformat()
    dm = DM
    G = ("https://github.com/jochem-brouwer/go-ethereum/blob/4d92c8e0c05455a85dd29107b9d627150ab67f1e")
    PR_URL = "https://github.com/ethpandaops/benchmarkoor/pull/315"
    TOOL = ("https://github.com/CPerezz/articles/blob/1083280c829cd602fa10dfde76092f5c032056b2/tools/drainjournal-main.go")
    LEDGER = ("https://github.com/CPerezz/articles/blob/1083280c829cd602fa10dfde76092f5c032056b2/docs/superpowers/specs/2026-08-31-root-cause-ledger.md")

    w("<!doctype html><html lang=en><head><meta charset=utf-8>")
    w('<meta name=viewport content="width=device-width,initial-scale=1">')
    w('<meta name="description" content="Identical EEST bloatnet runs report wildly '
      'different MGas/s on three geth databases. Root cause: the benchmark\'s own '
      'pre-run leaves its last 4,248 blocks of state in geth\'s pathdb journal, so '
      'the accounts deployed last are served from RAM in every test. Draining and '
      'compacting the baseline removes the divergence entirely.">')
    w('<link rel="preconnect" href="https://fonts.googleapis.com">'
      '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
      '<link href="https://fonts.googleapis.com/css2?family=VT323&'
      'family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&display=swap" '
      'rel="stylesheet">')
    w("<title>How can two databases holding the same state differ 7\u00d7 in "
      "performance? — state-actor vs a mainnet snapshot</title>")
    w(f"<style>{CSS}</style></head><body>")

    # 1. header
    w('<div class=topbar><a href="../">&larr; all articles</a>'
      '<span>EXECUTION · STATE DB</span></div>')
    w('<div class=eyebrow>// REPORT</div>')
    w("<h1>How can two databases holding the same state differ 7&times; in "
      "performance?</h1>")
    w("<p class=deck>A case study on state-actor versus a mainnet-snapshot "
      "database &mdash; and on how a benchmark can measure its own setup.</p>")
    w('<div class=meta><span class=tag>Ethereum · geth · pathdb · benchmarking</span> · 2026 · '
      '<a href="https://github.com/CPerezz/articles/tree/main/state-db-perf-divergence">'
      'reproducible pipeline &amp; data &rarr;</a></div>')
    w(f"<p class=sub>{len(common)} tests common to all three runs · generated "
      f"{today} · updated with the root-cause investigation</p>")
    w('<!--TOC-->')
    w("<div class=legend>")
    for k, (label, var) in DB.items():
        w(f'<span><i class=sw style="background:var({var})"></i><b>{label}</b> '
          f'<code>{RUN_ID[k]}</code> {RUN_DATE[k]}</span>')
    w("</div>")
    w(f'<p class=note>{esc(PROVENANCE)}</p>')

    figs = {
        "ratio-dots": chart_ratio_dots(by_op),
        "compaction-dumbbell": chart_dumbbell(us),
        "cost-curves": chart_slope_lines(meas, P, clean),
        "convergence": chart_convergence(gas_rows, agree_med, len(agree)),
        "verdict": chart_verdict(VERDICT),
    }
    # The guard sees the geometry only: captions are prose and legitimately
    # contain words like "inference".
    for name, (svg, _) in figs.items():
        assert svg.count("<circle") >= 6, f"{name}: too few plotted points"
        assert "NaN" not in svg and "inf" not in svg, f"{name}: non-finite geometry"

    # 5. headline table
    w("<h2>The behaviour</h2>")
    w("<p>Three runs of the same EEST suite, on the same host, against three\n      geth state databases. Two of them are the same snapshot &mdash; one\n      compacted, one not; the third was generated from scratch by\n      state-actor. If the databases were equivalent, every category below\n      would sit near 1.0&times;. One family of categories does not, and the\n      rest of this report is the hunt for why.</p>".replace("\n     ", " "))
    w(f"<p class=note>{tip('µs per account lookup', METRIC_DOC['us'])}</p>")
    w("<table><tr><th>account_mode</th>"
      + db_headers(after="<th></th>")
      + "<th class=n>state-actor ÷ compacted</th></tr>")
    for m in MODES:
        r = (us[m]["sa"] / us[m]["c"]) if us[m]["c"] else None
        w(f"<tr>{mode_cell(m)}")
        for k, (_, var) in DB.items():
            w(f"<td class=n>{fnum(us[m][k],1)}</td><td>{bar(us[m][k], usmax, var)}</td>")
        w(f'<td class="n{ratio_cls(r)}">{fnum(r,2)}</td></tr>')
    spread = {k: max(us[m][k] for m in MODES) / min(us[m][k] for m in MODES) for k in KEYS}
    w("<caption>BALANCE, value_sent=0: identical cold lookups, identical iteration counts. "
      f"Spread within each database: compacted {spread['c']:.1f}&times;, "
      f"uncompacted {spread['u']:.1f}&times;, "
      f"state-actor {spread['sa']:.1f}&times;.</caption></table>")

    # 6. all 16 categories
    ncat = sum(1 for op in OPCODES for m in MODES if by_op[op][m]["n"])
    w(f"<details><summary>All {ncat} categories (ms per 1M gas) — state-actor "
      f"{sa_slope_lo:.2f}\u2013{sa_slope_hi:.2f}; jochemnet {cu_slope_lo:.2f}"
      f"\u2013{cu_slope_hi:.2f}</summary>")
    w("<table><tr><th>opcode</th><th>account_mode</th>"
      + db_headers()
      + "<th class=n>state-actor ÷ compacted</th></tr>")
    for op in OPCODES:
        for m in MODES:
            cat = by_op[op][m]
            if not cat["n"]:
                continue
            r = (cat["sa"] / cat["c"]) if cat["c"] else None
            w(f"<tr><td>{esc(op)}</td>{mode_cell(m)}"
              f"<td class=n>{fnum(cat['c'])}</td><td class=n>{fnum(cat['u'])}</td>"
              f"<td class=n>{fnum(cat['sa'])}</td>"
              f'<td class="n{ratio_cls(r)}">{fnum(r,2)}</td></tr>')
    w("<caption>Categories absent from the common set render “—”. NON_EXISTING and EOA under "
      "CALLCODE fall outside the common set.</caption></table>")

    w("<h3>CODE delta — CALL slope minus BALANCE slope</h3>")
    w(f"<p class=note>Unit: {tip('ms per 1M gas', METRIC_DOC['slope'])}</p>")
    w("<table><tr><th>account_mode</th>" + db_headers() + "</tr>")
    for m in MODES:
        w(f"<tr>{mode_cell(m)}" +
          "".join(f"<td class=n>{fnum(delta[m][k])}</td>" for k in KEYS) + "</tr>")
    w("<caption>JUMPDEST/DIFF_MAX code delta ≈7 ms/Mgas in all three DBs → code fetch is "
      "equivalent; the divergence is the leaf.</caption></table>")
    w(f"<p class=note>{CITE['pattern']}</p></details>")

    w("<p>Plotted, the shape of the problem is immediate. Every category is\n      one row: how much slower state-actor is than compacted jochemnet on\n      the same work.</p>".replace("\n     ", " "))
    w(figure(*figs["ratio-dots"]))
    w("<p>The next two ask what compaction did. Manual compaction rewrites\n      every SSTable on disk, so any fast path it destroys was on disk &mdash;\n      and any fast path that survives it was not.</p>".replace("\n     ", " "))
    w(figure(*figs["compaction-dumbbell"]))
    w(figure(*figs["cost-curves"]))

    # everything except DIFF_MAX agrees
    w(f"<h3>Outside DIFF_MAX, the two databases agree to within "
      f"{(agree_hi - 1) * 100:.0f}%</h3>")
    w(f"<p>Of the {len(agree) + len(exceptions)} slope categories in the common set, "
      f"<b>{len(agree)}</b> put state-actor between {agree_lo:.2f}x and {agree_hi:.2f}x of "
      f"compacted (median {agree_med:.2f}x) — a flat run-level offset, not a state-layout "
      f"effect. Only <b>{len(exceptions)}</b> categories fall outside, and all three are "
      f"DIFF_MAX:</p>")
    w("<table><tr><th>opcode</th><th>account_mode</th>"
      "<th class=n>state-actor ÷ compacted</th></tr>")
    for op, m, r in exceptions:
        w(f"<tr><td>{esc(op)}</td>{mode_cell(m)}"
          f'<td class="n{ratio_cls(r)}">{r:.2f}x</td></tr>')
    w("</table>")
    exc_hi = max(r for _, _, r in exceptions)
    exc_op = max(exceptions, key=lambda e: e[2])[0]
    w(f"<p>And it is not an artifact of one gas budget. Sweep the target from "
      f"{gas_rows[0][0]}M to {gas_rows[-1][0]}M and the honest categories converge on "
      f"the same place: per-test ratios start at {gas_rows[0][2]:.2f}x at the smallest "
      f"budget and fall monotonically to {gas_rows[-1][2]:.2f}x at the largest, heading "
      f"for the {agree_med:.2f}x slope value. That drift is not the state cost changing "
      f"&mdash; it is the fixed per-block overhead every test pays, shrinking as a share "
      f"of a bigger budget, and it is exactly the intercept the slope fit removes.</p>")
    w(f"<p>DIFF_MAX pays that same overhead and shows the same drift "
      f"({dm_gas_rows[0][1]:.1f}x at {dm_gas_rows[0][0]}M to {dm_gas_rows[-1][1]:.1f}x at "
      f"{dm_gas_rows[-1][0]}M) &mdash; but it never joins the band. At every single "
      f"budget it sits roughly half again above the honest categories, and once the "
      f"intercept is gone it is the <i>only</i> family outside the band at all, reaching "
      f"{exc_hi:.2f}x on {esc(exc_op)}. Whatever is happening is indifferent to how much "
      f"gas we spend, which already rules out a gas-accounting artifact and points at "
      f"something structural about these accounts.</p>")
    w(figure(*figs["convergence"]))
    w("<details><summary>Per-gas-target ratios behind that curve</summary>")
    w("<table><tr><th class=n>gas target</th><th class=n>tests</th>"
      "<th class=n>median</th><th class=n>min</th><th class=n>max</th></tr>")
    for gv, n, md, mn, mx in gas_rows:
        w(f"<tr><td class=n>{gv}M</td><td class=n>{n}</td><td class=n>{md:.3f}x</td>"
          f"<td class=n>{mn:.3f}x</td><td class=n>{mx:.3f}x</td></tr>")
    w(f"<caption>Per-test <code>total_ms</code> ratios, DIFF_MAX excluded. The "
      f"{short_gas}M row has {short_n} tests, not {typical}: the value_sent=0 "
      f"{esc(miss_op)}/{esc(SHORT[miss_mode])} cell is absent from the common set because "
      f"the {LABEL[miss_absent[0]]} run never executed it, while "
      + " and ".join(LABEL[k] for k in miss_ran)
      + " both did.</caption></table></details>")

    # 10. worst 15
    w(f"<details><summary>Worst 15 divergent tests (state-actor ÷ compacted throughput) — "
      f"the top {worst_lead} rows are DIFF_MAX + BALANCE</summary>")
    w("<table><tr><th>account_mode</th><th>opcode</th><th class=n>gas</th>"
      + "".join(f'<th class="n db" style="color:var({var});border-color:var({var})">'
                 f'MGas/s {label}</th>' for label, var in DB.values())
      + "<th class=n>state-actor ÷ compacted</th></tr>")
    for t in worst:
        r = mgas("sa", t) / mgas("c", t)
        w(f"<tr>{mode_cell(P[t]['mode'])}<td>{esc(P[t]['opcode'])}</td>"
          f"<td class=n>{P[t]['gas']}M</td>"
          f"<td class=n>{mgas('c',t):.0f}</td><td class=n>{mgas('u',t):.0f}</td>"
          f"<td class=n>{mgas('sa',t):.0f}</td>"
          f'<td class="n{ratio_cls(r)}">{r:.2f}</td></tr>')
    w("<caption>The worst offenders, ranked by state-actor throughput relative to "
      "compacted, over the "
      f"{len(clean)} value_sent=0 non-baseline common tests.</caption></table></details>")

    # test-id mapping
    w(f"<details><summary>Test-id mapping — which EEST tests back each ACCOUNT_MODE "
      f"({len(common)} common tests, {len(census)} parameter categories)</summary>")
    w("<p class=note>Every measured test is "
      "<code>benchmark/stateful/bloatnet/test_account_query.py::test_account_access</code>. "
      f"All ids share this {len(prefix)}-character prefix, elided as <code>…</code> "
      "below:</p>")
    w(f"<pre class=idpre>{esc(prefix)}</pre>")
    w("<table><tr><th>account_mode</th><th>opcode</th><th>population</th>"
      "<th class=n>tests</th><th class=n>gas levels</th></tr>")
    for pop, op, m in sorted(census, key=lambda x: (MODES.index(x[2]), x[1], x[0])):
        ts = census[(pop, op, m)]
        n_lv = levels[(pop, op, m)]
        w(f"<tr>{mode_cell(m)}<td>{esc(op)}</td><td>{esc(pop)}</td>"
          f"<td class=n>{len(ts)}</td>"
          f"<td class=n>{n_lv}{'' if n_lv == full_levels else ' &#9888;'}</td></tr>")
    w(f"<caption>&#9888; the value_sent=0 {esc(miss_op)}/{esc(SHORT[miss_mode])} category has "
      f"{full_levels - 1} gas levels, not {full_levels}: the {LABEL[miss_absent[0]]} run never "
      f"executed that cell at {short_gas}M, so it cannot enter the common set. The "
      f"{'/'.join(bl_ops)} overhead_baseline categories hold {bl_n} tests because the baseline "
      f"runs at both value_sent=0 and value_sent=1. CALLCODE never pairs with "
      f"{' or '.join(cc_absent)} in the common set.</caption></table>")
    for m in MODES:
        ids = sorted(t for t in common if P[t]["mode"] == m)
        w(f"<details><summary>{esc(SHORT[m])} — {len(ids)} test ids</summary>"
          f"<pre class=idpre>")
        for t in ids:
            w(esc(t[len(prefix):]))
        w("</pre></details>")
    w("</details>")

    # 7b. origin of the divergence
    w("<h2>What geth's own logs say</h2>")
    w("<p>Our first framing was backwards, and turning it around is what made the "
      "cause findable. state-actor is not the odd one out: it is the <em>uniform</em> run, "
      f"costing {fnum(min(us[m]['sa'] for m in MODES),1)}–"
      f"{fnum(max(us[m]['sa'] for m in MODES),1)}&nbsp;µs on every class including the "
      "address range that exists in no database. jochemnet is the run with a handful of "
      "suspiciously <em>fast</em> classes. So the question was never why state-actor is "
      "slow. It is why jochemnet is fast &mdash; and why compaction took away some of "
      "that speed but not all of it.</p>")
    w("<p>Before measuring anything, one deduction clears most of the field. Under "
      "BALANCE geth reads a single account leaf — nonce, balance, storage root, code "
      "hash — and that leaf has the same shape whether the account's code is one byte, "
      "a 24 KB blob shared by 150,000 accounts, or a byte-unique 24 KB blob. Code lives "
      "in a different table, one BALANCE never opens. <b>Identical leaves cannot differ "
      "7× because of what they point at</b> — so whatever is going on, it is about "
      "<i>which storage tier answers the read</i>. That is the thread we pulled.</p>")
    w("<table><tr><th>observation</th>" + db_headers(numeric=False) + "</tr>")
    for row in LOGMINE:
        w("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>")
    w("<caption>Mined from the three <code>container_*.log</code> files — geth's own "
      "stdout across 914 / 974 / 999 container lifecycles. Every tunable matches. In the "
      "whole corpus there is exactly one configuration-level difference between the runs: "
      "whether a journal is found at startup.</caption></table>")
    w("<h2>What we ruled out first</h2>")
    w("<p>Before the journal there were plainer suspects, and each one had to die "
      "on its own evidence. What follows is one subsection per suspect: why it "
      "looked plausible, what we measured, and what the measurement said. None of "
      "them survived — but each one narrowed where the answer could be hiding.</p>")

    w("<h3>The databases themselves</h3>")
    w("<p>The dullest explanation is that the two stores simply hold different "
      "things, or hold them differently. That is what <code>geth db inspect</code> "
      "is for, so we ran it on both and put the key-value stores side by side "
      "(state-actor keeps everything there; more on its empty freezer in a "
      "moment):</p>")
    kv = {}
    for store, rows in INSPECT.items():
        for db_, cat, size, items in rows:
            if db_.startswith("Key-Value") or cat == "Total":
                kv.setdefault(cat, {})[store] = (size, items)
    w("<table><tr><th>category</th><th class=n>jochemnet size</th>"
      "<th class=n>jochemnet items</th><th class=n>state-actor size</th>"
      "<th class=n>state-actor items</th></tr>")
    shown = 0
    for cat, per in kv.items():
        j = per.get("jochemnet", ("&mdash;", "&mdash;"))
        a = per.get("state_actor", ("&mdash;", "&mdash;"))
        if j[0] in ("0.00 B", "&mdash;") and a[0] in ("0.00 B", "&mdash;"):
            continue
        shown += 1
        strong = cat == "Total"
        cell = (lambda v: f"<b>{esc(v)}</b>") if strong else (lambda v: esc(v))
        w(f"<tr><td>{cell(cat)}</td><td class=n>{cell(j[0])}</td>"
          f"<td class=n>{cell(j[1])}</td><td class=n>{cell(a[0])}</td>"
          f"<td class=n>{cell(a[1])}</td></tr>")
    w(f"<caption>Raw output committed as <code>data/db_inspect_*.txt</code>; "
      f"{shown} categories shown, all-zero rows omitted. jochemnet&rsquo;s Total "
      f"includes its 700&nbsp;GiB frozen chain; state-actor&rsquo;s ancient store "
      f"is 36&nbsp;KB, because a generator writes state, not history &mdash; all "
      f"of its data is in the key-value store. The jochemnet store was inspected "
      f"after the fix described below, so ~380&nbsp;MiB of trie state now sits in "
      f"the key-value store rather than in the journal file.</caption></table>")
    w("<p>Both stores hold billions of trie nodes and hundreds of gigabytes of "
      "state, with the same table shapes and totals of the same order. There are "
      "real differences &mdash; different generators make different tries &mdash; "
      "but nothing here is the kind of difference that makes <i>one account class</i> "
      "twenty times faster while its five siblings stay flat. Bulk composition was "
      "not the answer.</p>")

    w("<h3>Trie shape</h3>")
    w("<p>The next suspect is depth. A deeper path means more node reads per "
      "lookup, so if DIFF_MAX addresses happened to sit shallower in jochemnet's "
      "trie, they would be cheaper for entirely boring reasons. "
      "<code>eth_getProof</code> hands you the actual path, so we asked it for a "
      "target from every class, on both databases. Every class came back at "
      "<b>8&ndash;9 nodes</b>, DIFF_MAX included. Same depth, same work. Depth was "
      "not the answer either.</p>")

    w("<h3>What the fixtures actually touch</h3>")
    w("<p>Maybe the fast class was not doing the same work: fewer distinct targets, "
      "a tighter loop, some accidental address reuse. We decoded the setup and "
      "benchmark transactions of all six account modes straight from the fixture "
      "bundle. They use the same factory contract, the same CREATE2 salt walk over "
      "the same range, and the same 64-byte calldata; the only thing that differs "
      "is the code each receiver is given, which is the entire point of the "
      "parameter. And the accounts really are what their names claim &mdash; the "
      "value_sent=1 pricing below separates existing from non-existing accounts "
      "inside each database on its own:</p>")
    # 9. existence proof
    w("<details><summary>Existence proof — value_sent=1 pricing separates existing from "
      "non-existing accounts inside every database</summary>")
    w("<table><tr><th>account_mode</th>"
      + db_headers()
      + "<th class=n>state-actor ÷ its own NON_EXISTING</th></tr>")
    for m in MODES:
        cat = call1[m]
        w(f"<tr>{mode_cell(m)}" +
          "".join(f"<td class=n>{fnum(cat[k])}</td>" for k in KEYS) +
          f"<td class=n>{fnum(vs1_ratio['sa'][m],2)}</td></tr>")
    w(f"<caption>CALL slopes, value_sent=1, ms per 1M gas. A value-bearing CALL to a "
      "<em>non-existent</em> account additionally pays account-creation gas, so its loop "
      "iterates far fewer times per 1M gas — the low NON_EXISTING slope is the signature of a "
      f"genuinely absent account, and every other class differs from it by {sep_lo:.1f}–"
      f"{sep_hi:.1f}&times; on "
      "state-actor.</caption></table>")
    w(f"<p class=note>Unit: {tip('ms per 1M gas', METRIC_DOC['slope'])}</p>")
    w(f"<p class=note>{CITE['new']} If state-actor's targets were absent, all rows would "
      "collapse to ≈1.0.</p></details>")


    w("<h3>The 380 MiB file inside the snapshot</h3>")
    w("<p>By now the logs had pointed at the journal, and the jochemnet snapshot "
      "ships one: <code>triedb/merkle.journal</code>, 380.15&nbsp;MiB, right there "
      "in the tarball. The obvious story wrote itself &mdash; the image was "
      "captured from a node that still held unflushed state, and the benchmark had "
      "been re-warming that captured memory ever since. It is a good story. It is "
      "also wrong, and proving it wrong is what actually cracked the case.</p>")
    w("<p>We measured the journal at the promoted head, after the pre-run: "
      "<b>380.15&nbsp;MiB across 4,248 layers</b> &mdash; the published pair, to "
      "the digit, on a file the pre-run had just rewritten from scratch. The "
      "shipped artifact is not the cause: it is a coincidence of size, reproduced "
      "deterministically by the pipeline itself. Which meant the culprit was not "
      "something baked into a tarball months ago, but something the benchmark does "
      "to itself on every run &mdash; and that is a much better kind of bug, "
      "because it is one we can go and reproduce.</p>")

    w("<h3>Broken meters</h3>")
    w("<p>A benchmark can also lie through its instruments, and this harness has "
      "real defects: negative <code>execution_ms</code> on value-transfer blocks, "
      "cache counters frozen at zero, <code>state_reads</code> that never move. So "
      "before trusting any ratio we counted the defects per arm. They appear at the "
      "same rates on both sides &mdash; the appendix lists them. A meter that is "
      "broken identically for every contestant cannot change the ranking between "
      "them: a confound to disclose, not the cause we were hunting.</p>")

    w("<h3>Where the data sits in the LSM tree</h3>")
    w("<p>The last plain suspect was on-disk layout. Compaction alone moves these "
      "numbers by 3&times; &mdash; that is the whole compacted-versus-uncompacted "
      "spread above &mdash; so perhaps DIFF_MAX simply occupied a lucky corner of "
      "the LSM tree. We patched the harness to run a full pebble compaction "
      "<i>between every test's setup and its measurement</i>, which flattens exactly "
      "that kind of advantage, and re-ran. The anomaly stood. Layout turned out to "
      "matter, but as an accomplice rather than the principal &mdash; it comes back "
      "in the fix, and we did not see why until we knew what the journal was "
      "doing.</p>")

    w("<h2>The root cause: the pathdb journal</h2>")
    w(f"<p>Geth's path-based state database keeps recent trie changes in memory: "
      f"up to <a href='{G}/triedb/pathdb/config.go#L70'>128 diff layers</a> plus an "
      f"aggregated write buffer that only reaches disk "
      f"<a href='{G}/triedb/pathdb/disklayer.go#L423'>once it fills</a>. Whatever is "
      f"still in memory at shutdown is written to <code>triedb/merkle.journal</code> "
      f"(<a href='{G}/triedb/pathdb/journal.go#L321'>Journal</a>) and loaded straight "
      f"back into that buffer on the next start. A pre-run that never fills a 1&nbsp;GiB "
      f"buffer therefore ends with the trie writes of its last <b>4,248 blocks</b> living "
      f"in exactly one place: the journal file.</p>")
    w(f"<p>That matters because of the order the read path tries tiers. "
      f"<a href='{G}/triedb/pathdb/journal.go'>journal.go</a> forks on one condition &mdash; "
      f"journal loads, you get the reconstructed layer stack; journal fails, you get "
      f"<code>Failed to load journal, discard it</code> and a single disk layer with an "
      f"empty buffer. <code>disklayer.go</code> then reads buffer, then clean state cache, "
      f"then disk. The measured <code>statecache</code> is <b>0.00&nbsp;B in all three "
      f"runs</b>, so the journal-restored buffer is the <i>only</i> warm tier that exists. "
      f"With a journal, some reads never reach the disk. Without one, all of them do.</p>")
    w("<p>Now the part that makes it a per-class effect: <b>deploy order</b>. The EEST "
      "setup deploys receiver contracts class by class, and DIFF_MAX &mdash; the most "
      "expensive class to construct &mdash; goes <b>last</b>, in blocks "
      "24,406,595&ndash;24,410,441 of a chain ending at 24,410,463. The persisted disk "
      "layer stops at 24,406,217. Every DIFF_MAX account the benchmark reads was created "
      "<i>inside the journal window</i>. Every other class was deployed thousands of "
      "blocks earlier and had long since been flushed to disk.</p>")
    w("<p>The pipeline then hands that journal to every single test: <code>promote</code> "
      "bakes it into the golden baseline, and each per-test <code>restore</code> serves it "
      "back, so geth reloads it into memory 1,463 times. To check this rather than assume "
      "it, we ran 150 cold <code>eth_getBalance</code> calls per class with the OS page "
      "cache dropped, reading geth's own I/O accounting from <code>/proc</code> &mdash; "
      "first with the journal in place, then with the file deleted:</p>")
    w("<table><tr><th>account class</th><th class=n>disk read, journal present</th>"
      "<th class=n>disk read, journal deleted</th>"
      "<th class=n>code size after deletion</th></tr>")
    for cls, a, b, c in (("MINIMAL", "3.5 MB", "7.2 MB", "1 B"),
                         ("SAME_MAX", "2.9 MB", "6.5 MB", "24,576 B"),
                         ("JUMPDEST", "2.8 MB", "6.8 MB", "24,576 B"),
                         ("<b>DIFF_MAX</b>", "<b>0.0 MB</b>", "5.2 MB",
                          "<b>0 B &mdash; the accounts are gone</b>"),
                         ("EOA", "2.6 MB", "7.4 MB", "0 B (balance &gt; 0)"),
                         ("NON_EXISTING", "2.5 MB", "9.7 MB", "0 B")):
        w(f"<tr><td>{cls}</td><td class=n>{a}</td><td class=n>{b}</td>"
          f"<td class=n>{c}</td></tr>")
    w(f"<caption>Probes A and B from the <a href='{LEDGER}'>investigation ledger</a>. "
      f"With the journal, DIFF_MAX reads <b>zero bytes</b> from disk while its siblings "
      f"each pull megabytes. Delete the journal and geth rewinds to block 24,406,217 "
      f"&mdash; the disk layer, exactly where the window arithmetic says it should &mdash; "
      f"and the DIFF_MAX accounts <i>stop existing</i>. Their whole lives were "
      f"journal-resident.</caption></table>")
    w("<p><b>So why only these accounts, and not all of them?</b> Because journal "
      "residency is recency, and recency here is deploy order. Only state written in the "
      "pre-run's final 4,248 blocks is still in memory at shutdown, and that is precisely "
      "the DIFF_MAX receivers &mdash; plus the tail of the SAME_MAX salt range, whose "
      "addresses this benchmark never reads: the salts it does read were deployed "
      "thousands of blocks below the window. Same trie, same depth, same fixtures, same "
      "client. Different birthday.</p>")
    w("<h2>The fix, and the proof</h2>")
    w(f"<p>If journal residency is the cause, the fix writes itself: after the "
      f"pre-run and before the baseline is promoted, <b>drain the journal into the "
      f"disk layer</b> &mdash; flatten every diff layer and push the write buffer "
      f"into the key-value store. Geth already has the code path "
      f"(<code>tree.cap(root,&nbsp;0)</code>); we packaged it as a small tool, "
      f"<a href='{TOOL}'>drainjournal</a>, built against the exact client commit "
      f"these runs used, and wired it into the harness as a post-pre-run hook "
      f"(<a href='{PR_URL}'>draft PR</a>). The head does not move; only <i>where "
      f"the state lives</i> changes.</p>")
    sm = VERDICT["smoke_drain_only"][0]["mgas_s"]
    b160 = next(c for c in VERDICT["cells"] if c["opcode"] == "BALANCE"
                and c["gas"] == "160M" and c["mode"].endswith("DIFF_MAX"))
    w(f"<p>Draining alone was not enough, and the way it failed is instructive. "
      f"BALANCE/DIFF_MAX at 160M gas fell from {b160['orig']:.0f} to "
      f"{sm:.0f}&nbsp;MGas/s &mdash; better, nowhere near fixed. The drain had "
      f"written all that state into about a hundred fresh, densely packed SSTables, "
      f"and in an LSM tree recency <i>is</i> physical locality: the class had simply "
      f"traded a memory advantage for an on-disk one. One "
      f"<code>geth db compact</code> later, those leaves were merged into the same "
      f"cold strata as everybody else's, and the number landed at "
      f"{b160['drained']:.1f} &mdash; against state-actor's {b160['sa']:.1f}. Both "
      f"legs are needed: {b160['orig']:.0f} &rarr; {sm:.0f} (drain) &rarr; "
      f"{b160['drained']:.1f} (compact).</p>")
    w(figure(*figs["verdict"]))
    leaf = [c for c in VERDICT["cells"] if c["mode"].endswith("DIFF_MAX")
            and c["opcode"] in LEAF_OPS]
    code = [c for c in VERDICT["cells"] if c["mode"].endswith("DIFF_MAX")
            and c["opcode"] not in LEAF_OPS]
    ctrl = [c for c in VERDICT["cells"] if c["mode"].endswith("MINIMAL")]
    rr = lambda rows, f: (min(f(c) for c in rows), max(f(c) for c in rows))
    b4 = lambda c: c["orig"] / c["sa"]
    af = lambda c: c["drained"] / c["sa"]
    w(f"<p>Across all {len(VERDICT['cells'])} cells of the verdict run &mdash; every "
      f"opcode, two gas budgets, the anomalous class and a control class that was "
      f"never journal-resident:</p>")
    w("<table><tr><th>group</th><th class=n>cells</th><th class=n>before (orig \u00f7 SA)</th>"
      "<th class=n>after (drained \u00f7 SA)</th></tr>")
    for name, rows in (("DIFF_MAX, leaf-reading opcodes", leaf),
                       ("DIFF_MAX, code-reading opcodes", code),
                       ("MINIMAL control", ctrl)):
        lo1, hi1 = rr(rows, b4)
        lo2, hi2 = rr(rows, af)
        w(f"<tr><td>{name}</td><td class=n>{len(rows)}</td>"
          f"<td class=n>{lo1:.2f}&ndash;{hi1:.2f}&times;</td>"
          f"<td class=n>{lo2:.2f}&ndash;{hi2:.2f}&times;</td></tr>")
    w("<caption>The control does not move: the fix is not a global slowdown. "
      "The anomaly does.</caption></table>")
    w(f"<details><summary>All {len(VERDICT['cells'])} verdict cells (MGas/s)</summary>")
    w("<table><tr><th>opcode</th><th>account_mode</th><th class=n>gas</th>"
      "<th class=n>jochemnet orig</th><th class=n>jochemnet drained</th>"
      "<th class=n>state-actor</th><th class=n>orig \u00f7 SA</th>"
      "<th class=n>drained \u00f7 SA</th></tr>")
    for c in sorted(VERDICT["cells"], key=lambda c: (c["mode"], c["opcode"], c["gas"])):
        short = "DIFF_MAX" if c["mode"].endswith("DIFF_MAX") else "MINIMAL"
        w(f"<tr><td>{esc(c['opcode'])}</td><td>{short}</td>"
          f"<td class=n>{c['gas']}</td><td class=n>{c['orig']:.1f}</td>"
          f"<td class=n>{c['drained']:.1f}</td><td class=n>{c['sa']:.1f}</td>"
          f"<td class=n>{b4(c):.2f}&times;</td>"
          f'<td class="n{ratio_cls(af(c))}">{af(c):.2f}&times;</td></tr>')
    w(f"<caption>value_sent=0, overhead_baseline=False, the primary measurement. "
      f"Source: <code>data/drained_verdict.json</code>, collected by "
      f"<code>collect_verdict.py</code>; baseline drained with "
      f"<a href='{TOOL}'>drainjournal</a> then compacted, and promoted through "
      f"the harness exactly as the original baseline was.</caption></table></details>")

    # 12. instrumentation defects
    # 13. conclusion
    w("<h2>Benchmark worst cases on generated state</h2>")
    w("<p>The lesson generalises well beyond one account class. A worst-case "
      "benchmark is a claim about <i>cold</i> performance, and a baseline built by "
      "replaying blocks cannot help carrying its own history with it: whatever was "
      "written last is still warm &mdash; in the journal, in the write buffer, in "
      "the youngest levels of the LSM tree. None of that appears in a config file. "
      "Here it was worth 23&times; on exactly the workload the suite was built to "
      "stress, and it took three rounds of measurement to find.</p>")
    w("<p>state-actor avoids the entire class of problem by construction. It "
      "generates the whole state up front, before any benchmark runs, so no account "
      "is more recent than any other: nothing is journal-resident, nothing sits in a "
      "privileged stratum, and a cold read costs what a cold read costs &mdash; the "
      "same for every class. That uniformity is exactly what the numbers above show "
      "the replayed snapshot lacked, and it is why generated state is the right way "
      "to benchmark a client's worst case. The one caveat is the mirror image of the "
      "same point: generated state is uniform, so it tells you nothing about how a "
      "real node's aged, fragmented store behaves. It is the right tool for "
      "worst-case bounds, not for typical-case fidelity.</p>")
    w("<p>If a replayed snapshot is unavoidable, this report is the checklist: drain "
      "the journal, compact the store, promote, and only then believe the numbers. "
      "Otherwise the benchmark measures the order in which the fixtures were "
      "deployed.</p>")

    w("<h2>Appendix &mdash; instrumentation defects found</h2><ul class=tight>")
    w(f"<li><code>timing.execution_ms</code> is a derived field and goes negative in "
      f"{neg_exec} of the {3*len(common)} measured blocks ({neg_c}/{neg_u}/{neg_sa} per run) — "
      "every one of them a value-transfer block. Unusable as a measurement; all timing in this "
      "report uses <code>timing.total_ms</code>.</li>")
    w("<li><code>state_reads</code> / <code>state_writes</code> / cache counters are constant "
      "per block shape (<code>accounts=4, code=0</code>) even for a CALL into 24 KB of code, so "
      "they cannot be used to attribute cost.</li>")
    w("<li>benchmarkoor logs the cgroup path but never samples utilization, so host contention "
      "cannot be ruled out from the logs alone.</li>")
    w("</ul>")


    w('<div class=endbar><a href="../">&larr; all articles</a>'
      '<a href="https://github.com/CPerezz/articles/tree/main/state-db-perf-divergence">'
      'source &amp; data</a></div>')
    w('<span class=cursor style="position:fixed;bottom:1.4rem;right:1.4rem;z-index:6"></span>')
    w("</body></html>")

    def rel(path):
        return os.path.relpath(path, HERE)

    with open(OUT, "w") as fh:
        fh.write(add_toc("\n".join(o)))
    print(f"\nwrote {rel(OUT)} ({os.path.getsize(OUT)} bytes)")

    os.makedirs(FIGS, exist_ok=True)
    for name, (svg, _) in figs.items():
        path = os.path.join(FIGS, f"fig_{name.replace('-', '_')}.svg")
        with open(path, "w") as fh:
            fh.write(standalone_svg(svg) + "\n")
        print(f"wrote {rel(path)} ({os.path.getsize(path)} bytes)")

    data = {
        "generated": today,
        "runs": {k: {"label": lab, "run_id": RUN_ID[k], "date": RUN_DATE[k],
                     "log": os.path.join("data", f)}
                 for (k, lab, f) in LOGS},
        "counts": {"common": len(common), "baseline": len(baseline),
                   "clean": len(clean), "value_sent_1": len(vs1),
                   "gas_mismatches": len(mismatch)},
        "us_per_lookup": {SHORT[m]: {DB[k][0]: us[m][k] for k in KEYS} for m in MODES},
        "slope_ms_per_Mgas": {op: {SHORT[m]: {DB[k][0]: by_op[op][m][k] for k in KEYS}
                                   for m in MODES if by_op[op][m]["n"]}
                              for op in OPCODES},
        "code_delta_ms_per_Mgas": {SHORT[m]: {DB[k][0]: delta[m][k] for k in KEYS}
                                   for m in MODES},
        "vs1_call_slope": {SHORT[m]: {DB[k][0]: call1[m][k] for k in KEYS} for m in MODES},
        "vs1_ratio_vs_own_non_existing": {SHORT[m]: vs1_ratio["sa"][m] for m in MODES},
        "baseline": {"slope_ms_per_Mgas": {DB[k][0]: base_slope[k] for k in KEYS},
                     "median_execution_ms": {DB[k][0]: base_exec[k] for k in KEYS}},
        "agreement": {
            "metric": "state-actor / compacted, slope ms per 1M gas",
            "categories": [{"opcode": op, "account_mode": SHORT[m], "ratio": r}
                           for op, m, r in agree],
            "exceptions": [{"opcode": op, "account_mode": SHORT[m], "ratio": r}
                           for op, m, r in exceptions],
            "range": [agree_lo, agree_hi], "median": agree_med,
        },
        "per_gas_ratio": [{"gas_M": gv, "tests": n, "median": md, "min": mn, "max": mx}
                          for gv, n, md, mn, mx in gas_rows],
        "per_test_buckets": {k: len(v) for k, v in buckets.items()},
        "worst_15": [{"account_mode": SHORT[P[t]["mode"]], "opcode": P[t]["opcode"],
                      "gas_M": P[t]["gas"],
                      "mgas_per_sec": {DB[k][0]: mgas(k, t) for k in KEYS},
                      "ratio": mgas("sa", t) / mgas("c", t)} for t in worst],
        "census": {f"{pop}/{op}/{SHORT[m]}": len(ts)
                   for (pop, op, m), ts in sorted(census.items(),
                                                  key=lambda kv: (kv[0][0], kv[0][1],
                                                                  MODES.index(kv[0][2])))},
        "test_id_prefix": prefix,
        "test_ids": {SHORT[m]: sorted(t for t in common if P[t]["mode"] == m) for m in MODES},
    }
    with open(JSON_OUT, "w") as fh:
        json.dump(data, fh, indent=1, sort_keys=False)
        fh.write("\n")
    print(f"wrote {rel(JSON_OUT)} ({os.path.getsize(JSON_OUT)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
