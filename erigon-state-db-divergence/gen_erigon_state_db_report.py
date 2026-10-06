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


READ_ROWS = [c for c in ORDER if c not in ("control (no state work)", "warm query", "sload same key")]


def chart_reads(B):
    """Disk reads inside newPayload, per arm, every test of each row. Byte counts don't carry the
    sub-second timing noise, so both duration classes are pooled."""
    W, L, R, T = 760, 250, 130, 34
    rh = 17
    rows = [c for c in READ_ROWS if any(t["cat"] == c for t in B["tests"].values())]
    H = T + 12 + rh * len(rows) + 64
    sx = S.LogScale(0.001, 30, L, W - R)
    o = [S.label(0, 14, "GB counted inside newPayload, one dot per test, pair 1", "start", "big"),
         S.label(0, T + 4, "all tests", "start", "ax"),
         S.label(W - R + 8, T + 4, "jochemnet  s-a", "start", "tick")]
    top = T + 12
    for i, cat in enumerate(rows):
        y = top + rh * i + 9
        ts = [t for t in B["tests"].values() if t["cat"] == cat]
        o.append(S.label(L - 10, y + 4, ROW_LABEL.get(cat, cat), "end", "tick"))
        for k, var, off in (("joc_np_read_mb", "--db-c", -2), ("sa_np_read_mb", "--db-sa", 2)):
            for t in ts:
                o.append(S.dot(sx.to(max(0.001, min(30, t[k] / 1e3))), y + off, 2.2, var))
        o.append(S.label(W - R + 8, y + 4, "%5.2f  %5.2f" % (med(ts, "joc_np_read_mb") / 1e3,
                                                              med(ts, "sa_np_read_mb") / 1e3), "start", "tick"))
    ty = top + rh * len(rows) + 18
    for t in (0.001, 0.01, 0.1, 1, 10):
        o.append(S.label(sx.to(t), ty, "%g" % t, "middle", "tick"))
    ly = H - 8
    o.append(S.dot(L, ly - 4, 3, "--db-c"))
    o.append(S.label(L + 8, ly, "jochemnet", "start", "tick"))
    o.append(S.dot(L + 100, ly - 4, 3, "--db-sa"))
    o.append(S.label(L + 108, ly, "state-actor (median GB on the right)", "start", "tick"))
    return S.svg(W, H, "".join(o))


SOURCE_GROUPS = (("database", ("database",), "--db-u"),
                 ("account files", ("accounts files", "accounts indexes"), "--db-c"),
                 ("code files", ("code files", "code indexes"), "--db-sa"),
                 ("commitment files", ("commitment files", "commitment indexes"), "--accent"),
                 ("storage files", ("storage files", "storage indexes"), "--good-fg"))
TRACED = (("opcode_BALANCE", "account read"), ("EXISTING_CONTRACT_JUMPDEST", "call, jumpdest scan"),
          ("test_ether_transfers", "ether transfer"), ("test_sstore", "storage write"))


def traced(S0, arm):
    """Per traced test: the share of newPayload's page reads each source group served, and the total."""
    out = []
    for needle, label in TRACED:
        test = next(t for t in S0[arm]["tests"] if needle in t)
        b = S0[arm]["tests"][test]["bytes"]["engine_newPayload"]
        tot = sum(b.values())
        shares = {g: sum(b.get(c, 0) for c in cats) / tot for g, cats, _ in SOURCE_GROUPS}
        shares["other"] = max(0.0, 1 - sum(shares.values()))
        out.append((label, shares, tot))
    return out


def chart_sources(S0):
    """Where each traced test's newPayload reads came from, one bar per store."""
    W, L, R, T = 760, 250, 90, 34
    rh, gap = 16, 10
    tests = list(zip(traced(S0, "joc"), traced(S0, "sa")))
    H = T + len(tests) * (2 * rh + gap) + 56
    sx = S.Scale(0, 1, L, W - R)
    o = [S.label(0, 14, "share of the pages each test read inside newPayload, by file", "start", "big"),
         S.label(W - R + 8, T - 6, "read", "start", "tick")]
    colours = dict((g, v) for g, _, v in SOURCE_GROUPS) | {"other": "--muted"}
    y = T
    for (label, sj, tj), (_, ss, ts) in tests:
        for arm, shares, tot in (("jochemnet", sj, tj), ("state-actor", ss, ts)):
            o.append(S.label(L - 10, y + 11, f"{label}, {arm}", "end", "tick"))
            x = 0.0
            for g in list(colours):
                if shares.get(g, 0) > 0:
                    o.append(S.band(sx.to(x), sx.to(x + shares[g]), y + 2, y + rh - 2, colours[g], 0.85))
                    x += shares[g]
            o.append(S.label(W - R + 8, y + 11, f"{tot / 1e9:.2f} GB", "start", "tick"))
            y += rh
        y += gap
    for v in (0, 0.25, 0.5, 0.75, 1):
        o.append(S.label(sx.to(v), y + 8, f"{v:.0%}", "middle", "tick"))
    lx, ly = 0, H - 10
    for g in colours:
        o.append(S.band(lx, lx + 10, ly - 9, ly + 1, colours[g], 0.85))
        o.append(S.label(lx + 14, ly, g, "start", "tick"))
        lx += 14 + 8 * len(g) + 18
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
    # The headline: over a second the generated store's newPayload is up to ~2x slower, on the
    # transfers, while the code calls sit at parity; timed whole, it's ~3x faster.
    ex = {c: ge[c]["a"]["median"] for c in EXISTING if c in ge}
    lo_c = min(ex, key=ex.get)
    slow = 1.0 / ex[lo_c]
    at, bt = ge_all["a_total"]["median"], ge_all["b_total"]["median"]
    assert lo_c == "ether transfer" and 1.5 <= slow <= 2.5, "the slowest row over a second moved: %s %.2f" % (lo_c, slow)
    assert 2.5 <= at <= 3.5, "the whole-block median over a second moved: %.2f" % at
    calls = {c: ge[c]["a"]["median"] for c in ("code-exec DIFF_MAX", "code-exec JUMPDEST")}
    assert all(0.9 <= v <= 1.1 for v in calls.values()), "the code calls left parity: %r" % calls
    # The short clue (shown, not counted): contract-account reads and plain calls run at about half
    # speed or less, the controls don't.
    SHORT_SLOW = ("account row MINIMAL", "account row SAME_MAX", "account row JUMPDEST",
                  "account row DIFF_MAX", "code-exec MINIMAL", "code-exec SAME_MAX")
    short = {c: lt[c]["a"]["median"] for c in SHORT_SLOW}
    ctl = lt["control (no state work)"]["a"]["median"]
    assert max(short.values()) < 0.6 and ctl > 1.1, "the short clue moved: %r, controls %.2f" % (short, ctl)
    # The commit: jochemnet's forkchoiceUpdated takes seconds, state-actor's milliseconds.
    jf = [r["joc_fcu_ms"]["median"] for r in ge.values()]
    sf = [r["sa_fcu_ms"]["median"] for r in ge.values()]
    assert min(jf) > 3000 and max(sf) < 700 and min(jf) > 4 * max(sf), \
        "the commit gap moved: joc %r, sa %r" % (jf, sf)
    # The whole block: every row over a second favours state-actor, least on the code calls, most
    # on the transfers.
    tot = {c: r["a_total"]["median"] for c, r in ge.items()}
    assert min(tot.values()) > 1.5, "a row over a second no longer favours state-actor whole: %r" % tot
    assert min(tot, key=tot.get).startswith("code-exec") and max(tot, key=tot.get) == "ether transfer", \
        "the whole-block extremes moved: %r" % tot
    lt_tot = {c: r["a_total"]["median"] for c, r in lt.items()}
    lt_max_c = max(lt_tot, key=lt_tot.get)
    lt_ts = [t for t in tests.values() if t["cls"] == "lt1s" and t["cat"] == lt_max_c]
    assert lt_tot[lt_max_c] > 10 and med(lt_ts, "joc_fcu_ms") / 1e3 > 5 * med(lt_ts, "joc_secs"), \
        "the short state tests no longer swing toward state-actor on the commit"
    # Pair 2 agrees with pair 1, row by row, over a second.
    d_np = max(abs(r["a"]["median"] - r["b"]["median"]) for r in ge.values())
    d_tot = max(abs(r["a_total"]["median"] - r["b_total"]["median"]) for r in ge.values())
    assert d_np < 0.05 and d_tot < 0.2, "the two pairs disagree: %.3f / %.3f" % (d_np, d_tot)
    # The rule the page states: under a second one store can't agree with itself, over a
    # second it mostly does; timing the whole block doesn't change that.
    def share(r, k):
        return 100.0 * r[k]["within10"] / r[k]["n"]
    f_ge = [share(ge_all, k) for k in ("floor_sa", "floor_joc")]
    f_lt = [share(lt_all, k) for k in ("floor_sa", "floor_joc")]
    f_lt_tot = [share(lt_all, k) for k in ("floor_sa_total", "floor_joc_total")]
    assert min(f_ge) > 80 and max(f_lt) < 65 and max(f_lt_tot) < 75, \
        "the duration floors no longer separate: %r / %r / %r" % (f_ge, f_lt, f_lt_tot)
    floor_ge, meet_ge = share(ge_all, "floor_sa"), share(ge_all, "a")
    assert floor_ge > 95 and meet_ge < 50, "the floor figure's caption no longer holds: %.0f / %.0f" % (floor_ge, meet_ge)
    # Where the state lives.
    assert P["joc_files_end_block"] < P["snapshot_block"] and \
        P["head_after_prerun"] - P["snapshot_block"] == P["prerun_blocks"], \
        "the pre-run no longer lands after jochemnet's last frozen block"
    sa_db_gb, sa_files_gb = P["sa_mdbx_bytes"] / 1e9, P["sa_files_bytes"] / 1e9
    assert sa_files_gb > 100 * sa_db_gb and P["joc_mdbx_gb"] > 100 * sa_db_gb, \
        "the two stores no longer keep their state in different places"
    CONTRACT_ACCT = ("account row MINIMAL", "account row SAME_MAX", "account row JUMPDEST", "account row DIFF_MAX")
    acct = [t for t in tests.values() if t["cat"] in CONTRACT_ACCT]
    sa_rd, joc_rd = med(acct, "sa_np_read_mb"), med(acct, "joc_np_read_mb")
    assert sa_rd > 5 * joc_rd, "state-actor no longer reads several times the bytes: %.0f / %.0f" % (sa_rd, joc_rd)
    # Part 2, finding 1: where each store serves the benchmark's reads from, and why.
    S0 = D["step0"]
    db_blocks = P["db_blocks"]
    assert db_blocks == P["head_after_prerun"] - P["joc_files_end_block"] + 1 and \
        db_blocks == P["fork_db_blocks"] + P["prerun_blocks"] and \
        P["db_txs"] == P["fork_db_txs"] + P["prerun_txs"], "the database's block and transaction counts no longer add up"
    step_fill = (P["db_txs"] + 2 * db_blocks) / P["step_size"]
    assert 0.5 < step_fill < 1, "the database no longer holds one unfinished step: %.3f" % step_fill
    files_end_step = max(s[1] for s in S0["joc"]["domain_steps"]["accounts"])
    assert P["retire_domain_files"]["before"] == P["retire_domain_files"]["after"], "retire built state files"
    ms = P["mainnet_sample"]
    mn_density = ms["txs"] / ms["blocks"]
    fork_density = P["fork_db_txs"] / P["fork_db_blocks"]
    mn_bps = P["step_size"] / (mn_density + 2)
    assert mn_density > 10 * fork_density and mn_bps * 12 < 86400, "mainnet no longer fills a step within a day"
    joc_tr, sa_tr = traced(S0, "joc"), traced(S0, "sa")
    assert min(s["database"] for _, s, _ in joc_tr) >= 0.99, "a traced jochemnet test reads outside its database"
    assert max(s["database"] for _, s, _ in sa_tr) < 0.01, "a traced state-actor test reads its database"
    top = {label: max(s, key=s.get) for label, s, _ in sa_tr}
    assert top == {"account read": "account files", "call, jumpdest scan": "code files",
                   "ether transfer": "commitment files", "storage write": "commitment files"}, \
        "the state-actor files each traced test reads most have changed: %r" % top
    def rd_of(c):
        ts = [t for t in tests.values() if t["cat"] == c]
        return med(ts, "sa_np_read_mb") / med(ts, "joc_np_read_mb")
    # "On every row that touches a contract account, state-actor reads more; on EOAs and absent
    # accounts it reads less, and neither reads much."
    CONTRACT_ROWS = [c for c in ORDER if c.startswith(("account row", "code-exec")) and not c.endswith("EXISTING_EOA")]
    rd = {c: rd_of(c) for c in CONTRACT_ROWS}
    assert min(rd.values()) > 1.2, "a contract-account row no longer reads more on state-actor: %r" % rd
    LIGHT = ("account row EXISTING_EOA", "code-exec EXISTING_EOA", "absent account")
    assert max(rd_of(c) for c in LIGHT) < 1, "an EOA or absent-account row now reads more on state-actor"
    light_mb = max(med([t for t in tests.values() if t["cat"] == c], k) for c in LIGHT
                   for k in ("joc_np_read_mb", "sa_np_read_mb"))
    assert light_mb < 0.2 * joc_rd, "the EOA and absent-account rows no longer read little"

    # ----- page ------------------------------------------------------------------------------
    o = []
    w = o.append
    figs = {}

    def fig(name, svg, caption):
        figs[name] = svg
        return figure(svg, caption)

    title = (f"How can two Erigon databases holding the same state be {slow:.0f}&times; slower and "
             f"{at:.0f}&times; faster?")
    w("<!doctype html><html lang=en><head><meta charset=utf-8>")
    w('<meta name=viewport content="width=device-width,initial-scale=1">')
    w(f'<meta name="description" content="Identical EEST bloatnet runs put a generated Erigon store '
      f'{slow:.0f}x behind a mainnet snapshot on the benchmark&#39;s own clock and {at:.0f}x ahead '
      'once the whole block is timed.">')
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
      f"hold the same state. On the benchmark's own clock, the one generated from scratch ran "
      f"ether transfers {slow:.1f}&times; slower and contract calls at parity. But that clock "
      f"stops at newPayload. Erigon writes each block's state in the call that follows, and there "
      f"the snapshot spends {min(jf)/1e3:.0f} to {max(jf)/1e3:.0f} seconds a block. Timed whole, "
      f"the generated store is {at:.1f}&times; faster. Here's the baseline, and where it "
      f"points.</p>")

    # ---- part 1: the problem
    w(f"<h2>The problem: the same state, {slow:.0f}&times; slower and {at:.0f}&times; faster</h2>")
    w(f"<p>Two databases with the same accounts: a mainnet shadowfork snapshot at block "
      f"{thousands(P['snapshot_block'])} (we call it jochemnet), and the same state written from "
      f"scratch by <code>state-actor</code>. Same fixtures, same machine, same drive read with "
      f"direct I/O, page cache dropped between tests. Every number here is state-actor's "
      f"throughput divided by jochemnet's: 1.00 is parity, 0.50 means the generated store is "
      f"twice as slow.</p>")
    w(fig("fig_overview_newpayload",
          chart_overview(B, "a", "b", "newPayload throughput, state-actor / jochemnet, one dot "
                         "per test (band = \u00b110%)"),
          f"The benchmark as published: newPayload time, the {B['n']} tests at 160M and 240M gas, "
          f"two independent pairs. Over a second, {ge_all['a']['within10']} of {ge_all['a']['n']} "
          f"tests sit inside the band: the code calls at {calls['code-exec DIFF_MAX']:.2f} and "
          f"{calls['code-exec JUMPDEST']:.2f}, the transfers at {ex[lo_c]:.2f}."))
    w("<p>Each dot is one test, one colour per pair. The white tick is the category's median, and "
      "the numbers on the right are that median and how many of the category's tests land inside "
      "&plusmn;10%. The same rows and the same axis come back in the next figure.</p>")
    w(f"<p>Over a second, the calls that load a contract's code run at parity. Ether transfers run "
      f"at {ex[lo_c]:.2f}, close to half speed. The short tests point the same way, though they "
      f"don't count. Reads of contract accounts and plain calls sit at {min(short.values()):.2f} "
      f"to {max(short.values()):.2f}; the controls, which touch no state, sit at {ctl:.2f}. "
      f"Whatever separates the two stores is in looking up accounts, not in running code.</p>")
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
    w(f"<p>Over a second, every row favours the generated store once the commit counts: from "
      f"{min(tot.values()):.1f}&times; on the code calls to {max(tot.values()):.1f}&times; on the "
      f"transfers. The two numbers answer different questions, so this page shows both.</p>")
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
          f"Amber is state-actor measured twice, the best any comparison can do. Green is the two "
          f"stores, untreated. Over a second the floor is {floor_ge:.0f}%, and the two stores meet "
          f"on {meet_ge:.0f}% of tests."))
    w(f"<p><b>The last clue is where each store keeps its state.</b> Erigon has two places for "
      f"it: a database (MDBX) for recent writes, and immutable files for everything older. "
      f"Jochemnet's files end at block {thousands(P['joc_files_end_block'])}. Everything after "
      f"that is in its database, {P['joc_mdbx_gb']:.0f} GB of it. That includes the "
      f"{thousands(P['prerun_blocks'])} pre-run blocks that create the accounts the benchmark "
      f"reads. State-actor writes all of its state into files at genesis: a {sa_db_gb:.1f} GB "
      f"database beside {sa_files_gb:.0f} GB of files. On the tests that read contract accounts, "
      f"its newPayload reads {sa_rd/joc_rd:.0f}&times; the bytes jochemnet's does.</p>")
    w("<p>Same state, different shelves. That points at two things to test: reads from files "
      "against reads from the database, and a database big enough to slow every commit.</p>")

    # ---- part 2, finding 1
    ec = P["erigon_commit"]

    def src(path, line, text):
        return f'<a href="https://github.com/erigontech/erigon/blob/{ec}/{path}#L{line}">{text}</a>'
    w(f"<h2>1. The newest {thousands(db_blocks)} blocks never left jochemnet's database</h2>")
    w(fig("fig_reads", chart_reads(B),
          f"Disk reads inside newPayload as benchmarkoor counts them, pair 1, every test. The "
          f"counter adds up every layer of the storage stack, so only the ratio between the stores "
          f"means anything. On every row that touches a contract account, state-actor reads "
          f"{min(rd.values()):.1f} to {max(rd.values()):.1f} times what jochemnet does. On EOAs "
          f"and absent accounts it reads less, and neither reads much."))
    w(f"<p>Erigon keeps state in two places. Recent writes live in a database (MDBX). Older "
      f"history is frozen into immutable files one step at a time, {thousands(P['step_size'])} "
      f"transactions per step, and Erigon {src('db/state/aggregator.go', 2309, 'never freezes')} "
      f"a step that isn't full. A read asks the database first and walks the files, newest first, "
      f"only on a {src('db/state/domain.go', 1854, 'miss')}.</p>")
    sa_lbl = dict((label, s) for label, s, _ in sa_tr)
    w(fig("fig_sources", chart_sources(S0),
          f"Four of these tests, traced page by page with the page cache dropped first. Jochemnet "
          f"read at least {100 * min(s['database'] for _, s, _ in joc_tr):.0f}% from its database, "
          f"state-actor nothing. Totals count the pages the client asked for, which is less than the "
          f"disk traffic in the reads figure."))
    w(f"<p><b>We traced it.</b> We recorded which file every page came from while four of these "
      f"tests ran. On jochemnet, at least {100 * min(s['database'] for _, s, _ in joc_tr):.0f}% "
      f"of what newPayload read came from the database, on every one. On state-actor, none did. "
      f"The account read went to the account files and their indexes, and the jumpdest call "
      f"mostly to the code files "
      f"({100 * sa_lbl['call, jumpdest scan']['code files']:.0f}%). The transfer and the storage "
      f"write went mostly to the commitment files, the trie Erigon recomputes the state root "
      f"from.</p>")
    w(f"<p><b>Why jochemnet's state is in the database.</b> Its files end where step "
      f"{thousands(files_end_step)} begins, at block {thousands(P['joc_files_end_block'])}. The "
      f"{thousands(db_blocks)} blocks after that hold {thousands(P['db_txs'])} transactions. "
      f"Counted the way Erigon counts, with two bookkeeping entries per block, that's "
      f"{100 * step_fill:.0f}% of one step. So all of it sits in the database, on any node. "
      f"Erigon's own housekeeping can't move it: <code>erigon snapshots retire</code>, run on the "
      f"promoted image, built no state file ({P['retire_domain_files']['before']} domain files "
      f"before and after).</p>")
    w(f"<p>On mainnet a step fills fast. Just before the fork, mainnet blocks carried "
      f"{mn_density:.0f} transactions each, so a step took about {thousands(int(round(mn_bps, -2)))} "
      f"blocks, some {mn_bps * 12 / 3600:.0f} hours. The shadowfork's blocks carry "
      f"{fork_density:.0f}. One unfinished step stretched over all {thousands(db_blocks)} of them, "
      f"and everything written after block {thousands(P['joc_files_end_block'])}, the pre-run "
      f"included, landed in it.</p>")
    w(f"<p>State-actor does the opposite. It writes all "
      f"{(P['sa_eoas'] + P['sa_contracts']) / 1e6:.0f} million accounts straight into frozen "
      f"files, as if every one of them were old, and its database holds {sa_db_gb:.1f} GB against "
      f"{sa_files_gb:.0f} GB of files.</p>")
    w(f"<p><b>So jochemnet measures the best case, and state-actor the worst.</b> These benchmarks "
      f"exist to find what a cold state read costs at its worst. In Erigon, that's an account whose "
      f"only copy is in the oldest file: the lookup misses the database, passes every newer file and "
      f"lands at the bottom. State-actor's store is built that way. Jochemnet's isn't. The pre-run "
      f"creates the accounts the tests read, so they sit in the database, the first place Erigon "
      f"looks. It's the same thing the pre-run did to the "
      f'<a href="../nethermind-state-db-divergence/nethermind-state-db-report.html">Nethermind</a> '
      f'and <a href="../besu-state-db-divergence/besu-state-db-report.html">Besu</a> snapshots: it '
      f"makes the benchmark's accounts the newest data in the store.</p>")
    w(f"<p>The commit is skewed by the same cause. Jochemnet writes every block into a "
      f"{P['joc_mdbx_gb']:.0f} GB database; a running node keeps only its newest step there.</p>")
    w("<p><b>So the store to fix is jochemnet.</b> Its tested state has to move to the bottom of "
      "the files, and out of the database. Erigon's own housekeeping can't do it, as the retire run "
      "showed, so it takes a rewrite of the files. That's this study's next step.</p>")

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
    print(f"headline: newPayload {slow:.2f}x slower ({lo_c}), whole block {at:.2f}x faster")
    print(f"over 1 s: newPayload {ge_all['a']['median']:.3f}/{ge_all['b']['median']:.3f} "
          f"({ge_all['a']['within10']}/{ge_all['a']['n']}), whole block {at:.3f}/{bt:.3f}, "
          f"floor {ge_all['floor_sa']['within10']}/{ge_all['floor_sa']['n']}")


if __name__ == "__main__":
    main()
