#!/usr/bin/env python3
"""Build the Erigon state-DB divergence report from the collected run data.

Every number in the page is derived here from data/report_data.json; none is typed into the
prose. The oracles in main() fail generation if the data stops supporting a sentence the article
states as fact. Same page shape, palette and chart conventions as the Nethermind and Besu reports.

Usage: python3 gen_erigon_state_db_report.py
"""
import html
import json
import os
import re
from statistics import median

import report_svg as S
from crt_theme import CSS

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "report_data.json")
OUT = os.path.join(HERE, "erigon-state-db-report.html")
FIGDIR = os.path.join(HERE, "figures")
REPO = "https://github.com/CPerezz/articles/tree/main/erigon-state-db-divergence"

# Ratios throughout are state-actor / jochemnet, so 1.00 is parity and < 1 means the generated
# store is slower. "newPayload" is benchmarkoor's own number; "whole block" adds the
# forkchoiceUpdated call that follows, where erigon commits the block's state.


def esc(s):
    return html.escape(str(s))


def thousands(n):
    return f"{n:,}"


def figure(svg, caption=""):
    cap = f"<figcaption>{caption}</figcaption>" if caption else ""
    return f"<figure>{svg}{cap}</figure>"


def standalone(svg):
    """Wrap a chart so the .svg file renders on its own: it must carry the palette and a
    background, which the page would otherwise supply."""
    palette = "".join(f"{k}:{v};" for k, v in re.findall(
        r"(--[a-z-]+):\s*(#[0-9a-fA-F]{3,8})", CSS))
    style = (f"<style>svg{{{palette}font:11px 'IBM Plex Mono',ui-monospace,Menlo,monospace}}"
             "text{fill:var(--fg)}text.tick,text.ax{fill:var(--muted)}"
             "text.big{font-size:12px;font-weight:600}</style>")
    head, rest = svg.split(">", 1)
    return (f'{head} xmlns="http://www.w3.org/2000/svg">{style}'
            f'<rect width="100%" height="100%" fill="var(--bg)"/>{rest}')


ORDER = ["account row EXISTING_EOA", "account row MINIMAL", "account row SAME_MAX",
         "account row JUMPDEST", "account row DIFF_MAX",
         "code-exec EXISTING_EOA", "code-exec MINIMAL", "code-exec SAME_MAX",
         "code-exec JUMPDEST", "code-exec DIFF_MAX", "ether transfer", "storage slot",
         "absent account", "control (no state work)", "warm query", "sload same key"]
ROW_LABEL = {
    "account row EXISTING_EOA": "account row, EOA",
    "account row MINIMAL": "account row, minimal code",
    "account row SAME_MAX": "account row, reused contract",
    "account row JUMPDEST": "account row, jumpdest contract",
    "account row DIFF_MAX": "account row, distinct contract",
    "code-exec EXISTING_EOA": "call into an EOA",
    "code-exec MINIMAL": "call, minimal code",
    "code-exec SAME_MAX": "call, reused contract",
    "code-exec JUMPDEST": "call, jumpdest scan",
    "code-exec DIFF_MAX": "call, distinct contract",
    "ether transfer": "ether transfer",
    "storage slot": "storage slot",
    "absent account": "absent account",
    "control (no state work)": "control, no state work",
    "warm query": "warm query",
    "sload same key": "same slot, reloaded",
}
# Rows whose tests read accounts that already exist: the population the headline is about.
EXISTING = tuple(c for c in ORDER if c.startswith(("account row", "code-exec")) or c == "ether transfer")


def class_rows(B, cls):
    rows = {r["cat"]: r for r in B["rows"] if r["cls"] == cls}
    return [(c, rows[c]) for c in ORDER if c in rows]


AX_LO, AX_HI = 0.15, 40


def chart_overview(B, ka, kb, title):
    """Every test of the page's population as a dot on one log axis, split by duration class,
    one dot per pair. Drawn once per metric with the same rows and the same axis."""
    W, L, R, T = 760, 250, 112, 34
    rh, gap = 17, 30
    ge, lt = class_rows(B, "ge1s"), class_rows(B, "lt1s")
    H = T + 2 * 12 + rh * (len(ge) + len(lt)) + gap + 48
    sx = S.LogScale(AX_LO, AX_HI, L, W - R)

    def x(v):
        return sx.to(max(AX_LO, min(AX_HI, v)))

    o = [S.label(0, 14, title, "start", "big")]
    y0 = T
    for head, rows, cls in (("tests over a second", ge, "ge1s"),
                            ("tests under a second: shown, not counted", lt, "lt1s")):
        o.append(S.label(0, y0 + 4, head, "start", "ax"))
        if cls == "ge1s":
            o.append(S.label(W - R + 8, y0 + 4, "median  band", "start", "tick"))
        top = y0 + 12
        bot = top + rh * len(rows)
        o.append(S.band(sx.to(0.9), sx.to(1.1), top, bot, "--accent", 0.10))
        o.append(S.line(sx.to(1.0), top, sx.to(1.0), bot, "--green-muted", 1))
        for i, (cat, row) in enumerate(rows):
            y = top + rh * i + 9
            o.append(S.label(L - 10, y + 4, ROW_LABEL.get(cat, cat), "end", "tick"))
            for k, var, off in ((ka, "--db-u", -2), (kb, "--db-c", 2)):
                for t in B["tests"].values():
                    if t["cls"] == cls and t["cat"] == cat and t[k] is not None:
                        o.append(S.dot(x(t[k]), y + off, 2.2, var))
            s = row[ka]
            o.append(S.line(x(s["median"]), y - 7, x(s["median"]), y + 7, "--fg", 2))
            o.append(S.label(W - R + 8, y + 4, "%.2f  %d/%d" % (s["median"], s["within10"], s["n"]),
                             "start", "tick"))
        y0 = bot + gap
    ty = y0 - gap + 18
    for t in (0.2, 0.5, 1, 2, 5, 10, 25):
        o.append(S.label(sx.to(t), ty, "%g" % t, "middle", "tick"))
    ly = H - 8
    o.append(S.dot(L, ly - 4, 3, "--db-u"))
    o.append(S.label(L + 8, ly, "pair 1", "start", "tick"))
    o.append(S.dot(L + 80, ly - 4, 3, "--db-c"))
    o.append(S.label(L + 88, ly, "pair 2", "start", "tick"))
    o.append(S.line(L + 180, ly - 10, L + 180, ly + 2, "--fg", 2))
    o.append(S.label(L + 188, ly, "category median, pair 1", "start", "tick"))
    return S.svg(W, H, "".join(o))


BUCKETS = (("< 0.2 s", 0, 0.2), ("0.2 - 1 s", 0.2, 1), ("1 - 5 s", 1, 5), ("> 5 s", 5, 1e9))


def floor_buckets(B):
    out = []
    for label, lo, hi in BUCKETS:
        ts = [t for t in B["tests"].values() if lo <= t["joc_secs"] < hi]

        def pct(k):
            v = [t[k] for t in ts if t[k] is not None]
            return 100.0 * sum(1 for r in v if 0.9 <= r <= 1.1) / len(v) if v else None
        out.append((label, pct("floor_sa"), pct("a"), len(ts)))
    return out


def chart_floor(B):
    """How often a test lands within 10% of the number it is compared to, by how long it runs.

    The floor is one store measured twice, so a comparison can't do better than it."""
    W, L, R, T = 760, 96, 170, 52
    H = T + 34 * len(BUCKETS) + 52
    sx = S.Scale(0, 100, L, W - R)
    o = [S.label(L, T - 34, "tests inside \u00b110%, by how long the test runs (newPayload)",
                 "start", "big")]
    for v in (0, 25, 50, 75, 100):
        o.append(S.label(sx.to(v), T - 16, f"{v}%", "middle", "tick"))
    for i, (label, fp, cp, n) in enumerate(floor_buckets(B)):
        y = T + 34 * i + 10
        o.append(S.label(L - 8, y + 4, label, "end"))
        if fp is None or cp is None:
            continue
        o.append(S.line(sx.to(min(fp, cp)), y, sx.to(max(fp, cp)), y, "--green-muted", 2))
        o.append(S.dot(sx.to(fp), y, 4, "--db-u", f"same store twice: {fp:.0f}%"))
        o.append(S.dot(sx.to(cp), y, 4.5, "--accent", f"the two stores: {cp:.0f}%"))
        o.append(S.label(W - R + 10, y + 4, f"{cp:.0f}% of {n}, floor {fp:.0f}%", "start", "tick"))
    o.append(S.dot(L + 6, H - 28, 4, "--db-u"))
    o.append(S.label(L + 16, H - 24, "state-actor, measured twice", "start", "tick"))
    o.append(S.dot(L + 236, H - 28, 4.5, "--accent"))
    o.append(S.label(L + 246, H - 24, "the two stores, untreated", "start", "tick"))
    return S.svg(W, H, "".join(o))


def med(ts, k):
    return median(t[k] for t in ts)


def chart_reads(B):
    """Bytes each test read from disk inside newPayload, per arm, tests over a second. Same rows
    as the overview, so a row's read gap can be put beside its throughput gap."""
    W, L, R, T = 760, 250, 130, 34
    rh = 17
    rows = class_rows(B, "ge1s")
    H = T + 12 + rh * len(rows) + 64
    sx = S.LogScale(0.1, 60, L, W - R)
    o = [S.label(0, 14, "GB read from disk inside newPayload, one dot per test, pair 1", "start", "big"),
         S.label(0, T + 4, "tests over a second", "start", "ax"),
         S.label(W - R + 8, T + 4, "jochemnet  s-a", "start", "tick")]
    top = T + 12
    for i, (cat, _) in enumerate(rows):
        y = top + rh * i + 9
        ts = [t for t in B["tests"].values() if t["cls"] == "ge1s" and t["cat"] == cat]
        o.append(S.label(L - 10, y + 4, ROW_LABEL.get(cat, cat), "end", "tick"))
        for k, var, off in (("joc_np_read_mb", "--db-c", -2), ("sa_np_read_mb", "--db-sa", 2)):
            for t in ts:
                o.append(S.dot(sx.to(max(0.1, min(60, t[k] / 1e3))), y + off, 2.2, var))
        o.append(S.label(W - R + 8, y + 4, "%5.2f  %5.2f" % (med(ts, "joc_np_read_mb") / 1e3,
                                                              med(ts, "sa_np_read_mb") / 1e3), "start", "tick"))
    ty = top + rh * len(rows) + 18
    for t in (0.1, 0.25, 0.5, 1, 2.5, 5, 10, 25):
        o.append(S.label(sx.to(t), ty, "%g" % t, "middle", "tick"))
    ly = H - 8
    o.append(S.dot(L, ly - 4, 3, "--db-c"))
    o.append(S.label(L + 8, ly, "jochemnet", "start", "tick"))
    o.append(S.dot(L + 100, ly - 4, 3, "--db-sa"))
    o.append(S.label(L + 108, ly, "state-actor (median GB on the right)", "start", "tick"))
    return S.svg(W, H, "".join(o))


# --------------------------------------------------------------------------- page
def main():
    D = json.load(open(DATA))
    P, B = D["provenance"], D["baseline"]
    tests = B["tests"]
    ge, lt = dict(class_rows(B, "ge1s")), dict(class_rows(B, "lt1s"))
    ALL = {r["cls"]: r for r in B["rows"] if r["cat"] == "__all__"}
    ge_all, lt_all = ALL["ge1s"], ALL["lt1s"]

    # ----- oracles: every sentence below that states a fact has one ---------------------------
    # The population: both pairs ran the same 266 tests with the same gas, from four runs.
    assert B["n"] == 266 and B["complete"], "the page population is no longer the 266 tests at 160M/240M"
    assert B["gas_mismatches"] == 0, "the two stores no longer did the same work"
    assert len(set(B["runs"].values())) == 4, "a run is shared between the two pairs"
    for t in tests.values():
        assert None not in (t["a"], t["b"], t["a_total"], t["b_total"]), "a test lacks a ratio"
    # The headline: every existing-state row over a second is slower, the worst a contract call.
    ex = {c: ge[c]["a"]["median"] for c in EXISTING if c in ge}
    lo_c = min(ex, key=ex.get)
    factor = 1.0 / ex[lo_c]
    assert 4 <= factor <= 6, f"headline factor moved out of band: {factor:.2f}"
    assert lo_c.startswith("code-exec"), "the slowest row is no longer a contract call: %s" % lo_c
    ex_tests = [max(t["a"], t["b"]) for t in tests.values() if t["cls"] == "ge1s" and t["cat"] in EXISTING]
    assert max(ex_tests) < 0.9, "an existing-state test over a second is no longer slower in both pairs"
    # Clue 1: the client isn't slow, reading existing state is.
    ctl = lt["control (no state work)"]["a"]["median"]
    absent = ge["absent account"]["a"]["median"]
    assert ctl > 1.1, "the controls are no longer faster on the generated store: %.3f" % ctl
    assert abs(absent - 1) < 0.03, "absent-account lookups left parity: %.3f" % absent
    # The commit: jochemnet's forkchoiceUpdated takes seconds, state-actor's milliseconds.
    jf = [r["joc_fcu_ms"]["median"] for r in ge.values()]
    sf = [r["sa_fcu_ms"]["median"] for r in ge.values()]
    assert min(jf) > 3000 and max(sf) < 700 and min(jf) > 4 * max(sf), \
        "the commit gap moved: joc %r, sa %r" % (jf, sf)
    # The whole block: closer to parity overall, spread both ways by row.
    at, bt = ge_all["a_total"]["median"], ge_all["b_total"]["median"]
    assert ge_all["a"]["median"] < 0.4 and 0.7 < at < 0.95, "the whole-block median moved: %.3f" % at
    tot = {c: r["a_total"]["median"] for c, r in ge.items()}
    assert min(tot.values()) < 0.5 and max(tot.values()) > 1.2, "the whole-block rows no longer split"
    # "Calls and account reads stay slower; storage writes, absent-account calls and ether
    # transfers go the other way": the rows that flip are exactly those three.
    flips = {c for c, v in tot.items() if v > 1}
    assert flips == {"storage slot", "absent account", "ether transfer"}, \
        "the rows the whole block flips are no longer the three the page names: %r" % sorted(flips)
    lt_tot = {c: r["a_total"]["median"] for c, r in lt.items()}
    lt_max_c = max(lt_tot, key=lt_tot.get)
    lt_ts = [t for t in tests.values() if t["cls"] == "lt1s" and t["cat"] == lt_max_c]
    assert lt_tot[lt_max_c] > 10 and med(lt_ts, "joc_fcu_ms") / 1e3 > 5 * med(lt_ts, "joc_secs"), \
        "the short state tests no longer swing toward state-actor on the commit"
    # Pair 2 agrees with pair 1, row by row, over a second.
    d_np = max(abs(r["a"]["median"] - r["b"]["median"]) for r in ge.values())
    d_tot = max(abs(r["a_total"]["median"] - r["b_total"]["median"]) for r in ge.values())
    assert d_np < 0.02 and d_tot < 0.06, "the two pairs disagree: %.3f / %.3f" % (d_np, d_tot)
    # The rule the page states: under a second one store can't agree with itself, over a
    # second it nearly always does; timing the whole block doesn't change that.
    def share(r, k):
        return 100.0 * r[k]["within10"] / r[k]["n"]
    f_ge = [share(ge_all, k) for k in ("floor_sa", "floor_joc")]
    f_lt = [share(lt_all, k) for k in ("floor_sa", "floor_joc")]
    f_lt_tot = [share(lt_all, k) for k in ("floor_sa_total", "floor_joc_total")]
    assert min(f_ge) > 90 and max(f_lt) < 65 and max(f_lt_tot) < 70, \
        "the duration floors no longer separate: %r / %r / %r" % (f_ge, f_lt, f_lt_tot)
    assert ge_all["a"]["within10"] < 0.05 * ge_all["a"]["n"], "the two stores now meet over a second"
    # Where the state lives.
    assert P["joc_files_end_block"] < P["snapshot_block"] and \
        P["head_after_prerun"] - P["snapshot_block"] == P["prerun_blocks"], \
        "the pre-run no longer lands after jochemnet's last frozen block"
    sa_db_gb, sa_files_gb = P["sa_mdbx_bytes"] / 1e9, P["sa_files_bytes"] / 1e9
    assert sa_files_gb > 100 * sa_db_gb and P["joc_mdbx_gb"] > 100 * sa_db_gb, \
        "the two stores no longer keep their state in different places"
    acct = [t for t in tests.values() if t["cls"] == "ge1s" and t["cat"].startswith("account row")]
    sa_rd, joc_rd = med(acct, "sa_np_read_mb"), med(acct, "joc_np_read_mb")
    assert sa_rd > 5 * joc_rd, "state-actor no longer reads several times the bytes: %.0f / %.0f" % (sa_rd, joc_rd)
    # Part 2, finding 1: where each store keeps its state, and what the benchmark's flags do to it.
    fork_blocks = P["snapshot_block"] - P["joc_files_end_block"]
    db_blocks = P["head_after_prerun"] - P["joc_files_end_block"]
    assert {"--exec.no-background-maintenance", "--exec.no-prune=true"} <= set(P["benchmark_flags"]), \
        "the benchmark no longer switches erigon's housekeeping off"
    rd = {c: med([t for t in tests.values() if t["cls"] == "ge1s" and t["cat"] == c], "sa_np_read_mb") /
          med([t for t in tests.values() if t["cls"] == "ge1s" and t["cat"] == c], "joc_np_read_mb")
          for c in EXISTING if c in ge}
    assert min(rd.values()) > 1.5, "a row that reads existing accounts no longer reads more on state-actor: %r" % rd
    # "The one row where both read the same is the absent account."
    absent_ts = [t for t in tests.values() if t["cls"] == "ge1s" and t["cat"] == "absent account"]
    rd_absent = med(absent_ts, "sa_np_read_mb") / med(absent_ts, "joc_np_read_mb")
    assert abs(rd_absent - 1) < 0.1, "absent-account reads no longer match across stores: %.2f" % rd_absent
    assert all(abs(med([t for t in tests.values() if t["cls"] == "ge1s" and t["cat"] == c], "sa_np_read_mb") /
                   med([t for t in tests.values() if t["cls"] == "ge1s" and t["cat"] == c], "joc_np_read_mb") - 1) >= 0.1
               for c in ge if c != "absent account"), "another row now reads the same on both stores"

    # ----- page ------------------------------------------------------------------------------
    o = []
    w = o.append
    figs = {}

    def fig(name, svg, caption):
        figs[name] = svg
        return figure(svg, caption)

    hi = max(ex.values())
    title = f"How can two Erigon databases holding the same state differ {factor:.0f}&times;?"
    w("<!doctype html><html lang=en><head><meta charset=utf-8>")
    w('<meta name=viewport content="width=device-width,initial-scale=1">')
    w(f'<meta name="description" content="Identical EEST bloatnet runs reported a {factor:.0f}x '
      'throughput gap between two Erigon state databases, and only timed half of each block.">')
    w('<link rel="preconnect" href="https://fonts.googleapis.com">'
      '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
      '<link href="https://fonts.googleapis.com/css2?family=VT323&'
      'family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&display=swap" '
      'rel="stylesheet">')
    w("<title>Erigon state-DB divergence, benchmarkoor bloatnet runs</title>")
    w(f"<style>{CSS}</style></head><body>")
    w('<div class=topbar><a href="../">&larr; all articles</a>'
      '<span>EXECUTION &middot; STATE DB</span></div>')
    w('<div class=eyebrow>// REPORT</div>')
    w(f"<h1>{title}</h1>")
    w('<div class=meta><span class=tag>Ethereum &middot; erigon &middot; MDBX &middot; snapshot '
      'files &middot; benchmarking</span> &middot; 2026 &middot; '
      f'<a href="{REPO}">reproducible pipeline &amp; data &rarr;</a></div>')
    w(f"<p class=sub>We ran the same EEST bloatnet benchmarks against two Erigon databases that "
      f"hold the same state. On every test over a second that reads an existing account, the one "
      f"generated from scratch came out slower, up to {factor:.0f}&times; on contract calls. "
      f"That's what the benchmark reports, and it times only half of each block. Erigon writes a "
      f"block's state in the call that follows it, and there the gap runs the other way. Here's "
      f"the baseline, and where it points.</p>")

    # ---- part 1: the problem
    w("<h2>The problem: the same state, up to %d&times; apart</h2>" % round(factor))
    w(f"<p>Two databases with the same accounts: a mainnet shadowfork snapshot at block "
      f"{thousands(P['snapshot_block'])} (we call it jochemnet), and the same state written from "
      f"scratch by <code>state-actor</code>. Same fixtures, same machine, same drive, page cache "
      f"dropped between tests. Every number here is state-actor's throughput divided by "
      f"jochemnet's: 1.00 is parity, 0.20 means the generated store is five times slower.</p>")
    w(fig("fig_overview_newpayload",
          chart_overview(B, "a", "b", "newPayload throughput, state-actor / jochemnet, one dot "
                         "per test (band = \u00b110%)"),
          f"The benchmark as published: newPayload time, the {B['n']} tests at 160M and 240M gas, "
          f"two independent pairs. Over a second, {ge_all['a']['within10']} of {ge_all['a']['n']} "
          f"tests sit inside the band; the rows that read existing accounts sit at "
          f"{ex[lo_c]:.2f} to {hi:.2f}."))
    w("<p>Each dot is one test, one colour per pair. The white tick is the category's median, and "
      "the numbers on the right are that median and how many of the category's tests land inside "
      "&plusmn;10%. The same rows and the same axis come back in the next figure.</p>")
    w(f"<p>The tests that read existing accounts are {1/hi:.0f} to {factor:.0f} times slower on "
      f"the generated store. The controls run the same loop and touch no state, and they sit at "
      f"{ctl:.2f}: faster on the generated store, not slower. Calls that touch an account that "
      f"isn't there sit at {absent:.2f}. Whatever this is, it's about reading state that exists.</p>")
    w(f"<p><b>The benchmark times half of each block.</b> Its throughput counts only "
      f"<code>engine_newPayload</code>, where Erigon executes the block. Erigon writes the block's "
      f"state to disk in the <code>forkchoiceUpdated</code> call that follows. On jochemnet that "
      f"call takes {min(jf)/1e3:.1f} to {max(jf)/1e3:.1f} seconds per block. On state-actor it "
      f"takes {min(sf):.0f} to {max(sf):.0f} milliseconds. Add it to both sides and the picture "
      f"changes.</p>")
    w(fig("fig_overview_block",
          chart_overview(B, "a_total", "b_total", "whole-block throughput (newPayload + "
                         "forkchoiceUpdated), state-actor / jochemnet"),
          f"The same tests timed as the whole block. Same rows, same axis. Over a second the "
          f"median moves from {ge_all['a']['median']:.2f} to {at:.2f}. Under a second the state "
          f"tests swing as far as {lt_tot[lt_max_c]:.0f}&times; toward state-actor, where "
          f"jochemnet's commit outweighs the execution."))
    w(f"<p>Over a second, the rows now spread from {min(tot.values()):.2f} to "
      f"{max(tot.values()):.2f}. Calls and account reads stay slower on the generated store: what "
      f"it loses executing is more than jochemnet loses committing. Storage writes, calls to "
      f"absent accounts and ether transfers go the other way. The two numbers answer different "
      f"questions, so this page shows both.</p>")
    w("<table><tr><th>tests</th><th class=n>n</th><th class=n>newPayload</th>"
      "<th class=n>inside &plusmn;10%</th><th class=n>whole block</th>"
      "<th class=n>inside &plusmn;10%</th></tr>")
    for cls, label in (("ge1s", "over a second"), ("lt1s", "under a second")):
        w(f"<tr><td colspan=6><b>{label}</b></td></tr>")
        for cat, row in class_rows(B, cls):
            s, st = row["a"], row["a_total"]
            cells = []
            for v in (s, st):
                bad = " bad" if v["median"] < 0.5 else ""
                cells.append(f"<td class=\"n{bad}\">{v['median']:.3f}</td>"
                             f"<td class=n>{v['within10']}/{v['n']}</td>")
            w(f"<tr><td>{esc(ROW_LABEL.get(cat, cat))}</td><td class=n>{s['n']}</td>{''.join(cells)}</tr>")
    w(f"<caption>Median ratio per category, pair 1. Whole block adds each test's "
      f"forkchoiceUpdated time on both sides. Pair 2 repeats both stores with fresh runs, and its "
      f"medians land within {d_np:.3f} of pair 1's on every row over a second ({d_tot:.3f} for "
      f"the whole block).</caption></table>")
    w(f"<p><b>Two kinds of test.</b> A test that runs for ten seconds and one that runs for a "
      f"tenth of a second aren't measuring the same thing. Every test boots a fresh client, so "
      f"under a second we're timing a young process. Every view here is split at one second of "
      f"newPayload time on jochemnet. Under a second, one store measured twice lands only "
      f"{min(f_lt):.0f}% to {max(f_lt):.0f}% of its tests within &plusmn;10% of itself; over a "
      f"second, {min(f_ge):.0f}% to {max(f_ge):.0f}% do. Timing the whole block doesn't rescue "
      f"the short ones ({min(f_lt_tot):.0f}% to {max(f_lt_tot):.0f}%). Sub-second tests are "
      f"always shown and never counted as evidence.</p>")
    w(fig("fig_floor", chart_floor(B),
          "Amber is state-actor measured twice, the best any comparison can do. Green is the two "
          "stores, untreated. Over a second the floor is near 100%, and the two stores almost "
          "never meet."))
    w(f"<p><b>The last clue is where each store keeps its state.</b> Erigon has two places for "
      f"it: a database (MDBX) for recent writes, and immutable files for everything older. "
      f"Jochemnet's files end at block {thousands(P['joc_files_end_block'])}. Everything after "
      f"that is in its database, {P['joc_mdbx_gb']:.0f} GB of it. That includes the "
      f"{thousands(P['prerun_blocks'])} pre-run blocks that create the accounts the benchmark "
      f"reads. State-actor writes all of its state into files at genesis: a {sa_db_gb:.1f} GB "
      f"database beside {sa_files_gb:.0f} GB of files. On the account-row tests, its newPayload "
      f"reads {sa_rd/joc_rd:.0f}&times; the bytes jochemnet's does ({sa_rd/1e3:.2f} GB against "
      f"{joc_rd/1e3:.2f} GB).</p>")
    w("<p>Same state, different shelves. That points at two things to test: reads from files "
      "against reads from the database, and a database big enough to slow every commit.</p>")

    # ---- part 2, finding 1
    ec = P["erigon_commit"]

    def src(path, line, text):
        return f'<a href="https://github.com/erigontech/erigon/blob/{ec}/{path}#L{line}">{text}</a>'
    w(f"<h2>1. The newest {thousands(db_blocks)} blocks never left jochemnet's database</h2>")
    w(fig("fig_reads", chart_reads(B),
          f"Bytes each test read from disk inside newPayload, pair 1, tests over a second. On "
          f"every row that reads existing accounts, state-actor reads {min(rd.values()):.1f} to "
          f"{max(rd.values()):.1f} times what jochemnet does."))
    w(f"<p>Erigon keeps state in two places. Recent writes live in a database (MDBX). A "
      f"background job freezes each finished step of history into immutable files, then clears "
      f"it from the database. A read asks the database first and walks the files, newest first, "
      f"only on a {src('db/state/domain.go', 1854, 'miss')}.</p>")
    w(f"<p><b>The benchmark switches that job off.</b> Its erigon config passes "
      f"<code>--exec.no-background-maintenance</code>, which stops the client "
      f"{src('db/state/aggregator.go', 2233, 'building any file')}, and "
      f"<code>--exec.no-prune</code>, which stops it clearing the database. The flag's own help "
      f"{src('cmd/utils/flags.go', 1220, 'calls it')} &ldquo;NOT an operational setting&rdquo;. "
      f"Jochemnet's files end at block {thousands(P['joc_files_end_block'])}. Everything after "
      f"that is in its {P['joc_mdbx_gb']:.0f} GB database: {thousands(fork_blocks)} blocks of the "
      f"shadowfork, and the {thousands(P['prerun_blocks'])} pre-run blocks that create the "
      f"accounts the tests read.</p>")
    w(f"<p>State-actor does the opposite. It writes all "
      f"{(P['sa_eoas'] + P['sa_contracts']) / 1e6:.0f} million accounts straight into frozen "
      f"files, as if every one of them were old. Its database holds the chain's configuration "
      f"and little else, {sa_db_gb:.1f} GB against {sa_files_gb:.0f} GB of files. So a lookup that "
      f"the snapshot answers from its database has to miss there on the generated store and go to "
      f"the files. That's our explanation for the extra bytes in the figure, and the fix below "
      f"tests it. The one row where both read the same is the absent account "
      f"({med(absent_ts, 'joc_np_read_mb') / 1e3:.2f} GB against "
      f"{med(absent_ts, 'sa_np_read_mb') / 1e3:.2f} GB): a key that exists nowhere can't be "
      f"answered from the database on either store. It would also explain why the commit runs the "
      f"other way: one store writes every block into a {P['joc_mdbx_gb']:.0f} GB database, the "
      f"other into an empty one.</p>")
    w(f"<p><b>Which one is right?</b> Neither is exactly how a node runs. A node in normal "
      f"operation freezes every finished step and clears it from its database. So an account "
      f"created long ago, which is what these tests mean by an existing cold account, is read from "
      f"a file. State-actor gets that right. Its database lacks only the newest, unfinished step, "
      f"which Erigon {src('db/state/aggregator.go', 2309, 'never freezes')}. Jochemnet keeps "
      f"{thousands(db_blocks)} blocks there, all but the newest step of which a running node would "
      f"have frozen.</p>")
    w(f"<p><b>The fix</b> is Erigon's own housekeeping, run once on the promoted jochemnet image "
      f"with the client stopped. <code>erigon snapshots retire</code> "
      f"{src('cmd/utils/app/snapshots_cmd.go', 3542, 'builds the missing files')}, merges them "
      f"and {src('cmd/utils/app/snapshots_cmd.go', 3549, 'clears the database')}. Then "
      f"<code>mdbx_copy -c</code> {src('cmd/integration/Readme.md', 153, 'compacts it')}. No value "
      f"changes, so the head's state root stays the same; only where each value lives does. The "
      f"benchmark's flags stay on for the tests, so housekeeping still can't run while a test is "
      f"timed.</p>")
    w("<p>We change the snapshot and not the generated store for two reasons. The generated store "
      "is the closer of the two to a running node here. And Erigon does this itself, while moving "
      "state-actor's accounts into the database would take a change to the generator.</p>")
    w(f"<p><b>What it should do.</b> If this is the gap, jochemnet's newPayload slows on the "
      f"account and call tests, its commit drops under a second, and the ratio over a second moves "
      f"from {ge_all['a']['median']:.2f} toward 1.</p>")

    w("<p class=note>Every number on this page is computed from the collected run data when the "
      "page is built, and the build fails if the data stops supporting a sentence.</p>")
    w(f'<div class=endbar><a href="../">&larr; all articles</a><a href="{REPO}">'
      'source &amp; data &rarr;</a></div>')
    w('<span class=cursor style="position:fixed;bottom:1.4rem;right:1.4rem;z-index:6"></span>')
    w("</body></html>")

    html_text = "\n".join(o)
    with open(OUT, "w") as fh:
        fh.write(html_text)
    os.makedirs(FIGDIR, exist_ok=True)
    for old in os.listdir(FIGDIR):
        if old.endswith(".svg"):
            os.remove(os.path.join(FIGDIR, old))
    for name, svg in figs.items():
        with open(os.path.join(FIGDIR, name + ".svg"), "w") as fh:
            fh.write(standalone(svg) + "\n")
    print(f"wrote {os.path.relpath(OUT, HERE)} ({len(html_text):,} bytes), "
          f"{len(figs)} standalone figures")
    print(f"headline factor: {factor:.2f}x ({lo_c})")
    print(f"over 1 s: newPayload {ge_all['a']['median']:.3f}/{ge_all['b']['median']:.3f} "
          f"({ge_all['a']['within10']}/{ge_all['a']['n']}), whole block {at:.3f}/{bt:.3f}, "
          f"floor {ge_all['floor_sa']['within10']}/{ge_all['floor_sa']['n']}")


if __name__ == "__main__":
    main()
