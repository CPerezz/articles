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


def regroup(S, by):
    """S's tests grouped by category under `by`'s duration classes, so a before/after pair compares
    the same tests on one split."""
    g = {}
    for t, r in S["tests"].items():
        cls = by["tests"][t]["cls"]
        g.setdefault((cls, r["cat"]), []).append(r)
        g.setdefault((cls, "__all__"), []).append(r)
    return g


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
          ("EXISTING_CONTRACT_DIFF_MAX", "call, distinct contract"),
          ("test_ether_transfers", "ether transfer"), ("test_sstore", "storage write"))


def traced(S0, arm):
    """Per traced test: the share of newPayload's page reads each source group served, and the total.
    Tests a trace didn't run are skipped (the distinct-contract call joined in T2)."""
    out = []
    for needle, label in TRACED:
        test = next((t for t in S0[arm]["tests"] if needle in t), None)
        if test is None:
            continue
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

def chart_commit(series):
    """The forkchoiceUpdated call after each measured block, median per row, one marker per store
    state. `series` is (legend, colour, dataset, per-test key)."""
    W, L, R, T = 760, 250, 40, 34
    rh = 17
    rows = [c for c in ORDER if any(t["cat"] == c for t in series[0][2]["tests"].values())]
    H = T + 12 + rh * len(rows) + 78
    lo, hi = 1, 20000
    sx = S.LogScale(lo, hi, L, W - R)
    o = [S.label(0, 14, "forkchoiceUpdated per measured block, ms, median of each row (pair 1)",
                 "start", "big")]
    top = T + 12
    o.append(S.line(sx.to(1000), top - 4, sx.to(1000), top + rh * len(rows), "--green-muted", 1))
    for i, cat in enumerate(rows):
        y = top + rh * i + 9
        o.append(S.label(L - 10, y + 4, ROW_LABEL.get(cat, cat), "end", "tick"))
        for j, (legend, var, ds, k) in enumerate(series):
            v = med([t for t in ds["tests"].values() if t["cat"] == cat], k)
            dy = 2.4 * (j - (len(series) - 1) / 2)  # equal medians would hide each other
            o.append(S.dot(sx.to(max(lo, min(hi, v))), y + dy, 3.2, var, f"{legend}: {v:,.0f} ms"))
    ty = top + rh * len(rows) + 18
    for t in (1, 10, 100, 1000, 10000):
        o.append(S.label(sx.to(t), ty, f"{t:,}", "middle", "tick"))
    for j, (legend, var, _, _) in enumerate(series):
        lx, ly = L + 250 * (j % 2), H - 30 + 18 * (j // 2)
        o.append(S.dot(lx, ly - 4, 3.2, var))
        o.append(S.label(lx + 10, ly, legend, "start", "tick"))
    return S.svg(W, H, "".join(o))


def inband(v):
    return 0.9 <= v <= 1.1


MAX_CODE = 24576  # EIP-170: every test contract here is exactly this long
WORDS = dict(enumerate("zero one two three four five six seven eight nine".split()))
# The fixture patterns in codespan's terms: first four bytes @ where the contract's own address sits.
CODE_GROUPS = (("615fff56@44", "jumpdest contract"), ("00000000@12", "distinct contract"),
               ("005b5b5b@-1", "reused contract"))


def chart_codefile(CL):
    """One test contract in each code file: its bytes on disk, on a log axis, and the 4 KB pages that
    reading its key and value touches."""
    W, L, R, T = 760, 250, 130, 40
    rh, gap, head = 16, 12, 16
    arms = (("jochemnet", "joc", "--db-c"), ("state-actor, as generated", "sa", "--db-sa"),
            ("state-actor, re-encoded", "sa_recoded", "--accent"))
    H = T + len(CODE_GROUPS) * (head + len(arms) * rh + gap) + 40
    lo, hi = 100, 40000
    sx = S.LogScale(lo, hi, L, W - R)
    o = [S.label(0, 14, "one test contract in the code file: bytes on disk, and 4 KB pages per read",
                 "start", "big"),
         S.label(W - R + 64, T - 4, "on disk", "end", "tick"), S.label(W - R + 118, T - 4, "pages", "end", "tick")]
    y = T
    for g, name in CODE_GROUPS:
        o.append(S.label(0, y + 12, name, "start", "ax"))
        y += head
        for label, arm, var in arms:
            s = CL[arm]["groups"][g]
            o.append(S.label(L - 10, y + 11, label, "end", "tick"))
            o.append(S.band(sx.to(lo), sx.to(s["bytes_p50"]), y + 2, y + rh - 2, var, 0.85))
            o.append(S.label(W - R + 64, y + 11, f"{s['bytes_p50']:,} B", "end", "tick"))
            o.append(S.label(W - R + 118, y + 11, f"{s['pages_kv']:.2f}", "end", "tick"))
            y += rh
        y += gap
    page = sx.to(4096)
    o.append(S.line(page, T + head, page, y - gap, "--green-muted", 1, "3 3"))
    o.append(S.label(page, y - gap + 14, "one page", "middle", "tick"))
    for t in (100, 1000, 10000):
        o.append(S.label(sx.to(t), y - gap + 30, f"{t:,}", "middle", "tick"))
    return S.svg(W, H, "".join(o))


STAGES = (("untreated", "--db-u"), ("1. rebuilt", "--db-sa"), ("2. code cache emptied", "--db-c"),
          ("3. code file re-encoded", "--accent"))


def chart_progress(stage_rows, rows):
    """Every row over a second after each step: pair 1's median, the steps joined in order, all on
    the final store's one-second split. stage_rows[i][cat] is row cat's median after step i."""
    W, L, R, T = 760, 250, 40, 34
    rh = 20
    H = T + 12 + rh * len(rows) + 74
    lo, hi = 0.3, 5
    sx = S.LogScale(lo, hi, L, W - R)

    def x(v):
        return sx.to(max(lo, min(hi, v)))
    o = [S.label(0, 14, "newPayload over a second, state-actor / jochemnet, after each step (pair 1)",
                 "start", "big")]
    top, bot = T + 12, T + 12 + rh * len(rows)
    o.append(S.band(sx.to(0.9), sx.to(1.1), top, bot, "--accent", 0.10))
    o.append(S.line(sx.to(1.0), top, sx.to(1.0), bot, "--green-muted", 1))
    for i, cat in enumerate(rows):
        y = top + rh * i + 10
        o.append(S.label(L - 10, y + 4, ROW_LABEL.get(cat, cat), "end", "tick"))
        pts = [(x(sr[cat]), y + 2.6 * (j - 1.5)) for j, sr in enumerate(stage_rows)]
        o.append(S.polyline(pts, "--dim", 1))
        for (px, py), (name, var), sr in zip(pts, STAGES, stage_rows):
            o.append(S.dot(px, py, 3, var, f"{name}: {sr[cat]:.2f}"))
    for t in (0.3, 0.5, 1, 2, 4):
        o.append(S.label(sx.to(t), bot + 16, "%g" % t, "middle", "tick"))
    for j, (name, var) in enumerate(STAGES):
        lx, ly = L + 250 * (j % 2), H - 30 + 18 * (j // 2)
        o.append(S.dot(lx, ly - 4, 3.2, var))
        o.append(S.label(lx + 10, ly, name, "start", "tick"))
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
    # Finding 1's fix: jochemnet rebuilt into one bottom file per domain, checked, and re-run.
    RB, E, S1 = P["rebuild"], D["after_layout"], D["step0_after"]
    G, FIN, S2 = D["cache_emptied"], D["final"], D["step0_final"]
    assert RB["new_step_size"] == RB["head_txnum"] + 1 and RB["head_block"] == P["head_after_prerun"], \
        "the rebuilt files no longer end at the head block"
    assert RB["rpc_identical"] and min(RB["rpc_samples_db_accounts"], RB["rpc_samples_db_slots"]) > 0, \
        "the rebuild's RPC check no longer covers database-only state, or found a difference"
    assert RB["mdbx_after_bytes"] / 1e9 < 0.02 * P["joc_mdbx_gb"], "the database didn't shrink"
    for S_ in (E, G, FIN):
        assert S_["n"] == B["n"] and S_["complete"] and S_["gas_mismatches"] == 0, \
            "a later series isn't the same 266 tests at the same gas"
    all_runs = [r for S_ in (B, E, G, FIN) for r in S_["runs"].values()]
    assert len(all_runs) == len(set(all_runs)) == 16, "two series share a run, or one isn't four runs"
    joc_tr1, sa_tr1 = traced(S1, "joc"), traced(S1, "sa")
    assert max(s["database"] for _, s, _ in joc_tr1) < 0.01, "a traced test still reads jochemnet's database"
    gap1 = {lj: abs(ts / tj - 1) for (lj, _, tj), (_, _, ts) in zip(joc_tr1, sa_tr1)}
    odd = max(gap1, key=gap1.get)
    near1 = max(v for k, v in gap1.items() if k != odd)
    assert odd == "call, jumpdest scan" and near1 < 0.07, "the traced byte totals no longer match: %r" % gap1
    code_x = dict((l, s["code files"] * t) for l, s, t in sa_tr1)[odd] / \
        dict((l, s["code files"] * t) for l, s, t in joc_tr1)[odd]
    assert code_x > 4, "state-actor's jumpdest call no longer reads several times the code pages: %.1f" % code_x
    # From here on every series is grouped on the final store's one-second split, so a row means
    # the same tests at every step. Stages: D untreated, E rebuilt, G code cache emptied, H code
    # file re-encoded.
    ST = {"D": regroup(B, FIN), "E": regroup(E, FIN), "G": regroup(G, FIN), "H": regroup(FIN, FIN)}

    def rm(s, cat, k="a", cls="ge1s"):
        return med(ST[s][(cls, cat)], k)

    def tin(s, k="a"):
        return sum(inband(t[k]) for t in ST[s][("ge1s", "__all__")])
    GE_CATS = [c for c in ORDER if ("ge1s", c) in ST["H"]]

    def differs(s, k="a", kb="b"):
        return [c for c in GE_CATS if not inband(rm(s, c, k)) and not inband(rm(s, c, kb))]
    n_before, n_after = ge_all["a"]["n"], len(ST["H"][("ge1s", "__all__")])
    NOSTATE = ("control (no state work)", "warm query", "sload same key")

    def joc_state_secs(S_):
        return med([t for t in S_["tests"].values() if t["cat"] not in NOSTATE], "joc_secs")
    assert n_after > n_before and joc_state_secs(FIN) > 1.5 * joc_state_secs(B), \
        "the rebuilt jochemnet is no longer slower on state tests, with more tests over a second"
    np_b, np_a, np_a2 = rm("D", "__all__"), rm("E", "__all__"), rm("E", "__all__", "b")
    wb_b, wb_a = rm("D", "__all__", "a_total"), rm("E", "__all__", "a_total")
    assert np_b < 0.6 and 0.85 <= min(np_a, np_a2) and max(np_a, np_a2) <= 1.0, \
        "newPayload over a second no longer moves from about half to just under parity: %.2f -> %.2f/%.2f" % (np_b, np_a, np_a2)
    assert wb_b > 2.5 and 0.85 <= wb_a <= 1.1, "the whole block no longer moves from ~3x to parity: %.2f -> %.2f" % (wb_b, wb_a)
    acct_b, acct_a = [rm("D", c) for c in CONTRACT_ACCT], [rm("E", c) for c in CONTRACT_ACCT]
    tr_b, tr_a = rm("D", "ether transfer"), rm("E", "ether transfer")
    assert max(acct_b) < 0.5 and min(acct_a) > 0.85 and max(acct_a) < 1, "the account rows' move changed: %r -> %r" % (acct_b, acct_a)
    assert tr_b < 0.6 and tr_a > 0.9, "the transfers' move changed: %.2f -> %.2f" % (tr_b, tr_a)
    DIFF, JUMP, SAME = "code-exec DIFF_MAX", "code-exec JUMPDEST", "code-exec SAME_MAX"
    CODE_CALLS = (DIFF, JUMP)
    cc_b = {c: rm("D", c) for c in CODE_CALLS}
    cc_a = {c: max(rm("E", c), rm("E", c, "b")) for c in CODE_CALLS}
    assert all(inband(v) for v in cc_b.values()) and max(cc_a.values()) < 0.7, \
        "the code calls no longer flip from parity: %r -> %r" % (cc_b, cc_a)
    # The set that differs, step by step: rows over a second outside the band in both pairs, and
    # tests inside it (pair 1), on both clocks.
    diff_np = {s: differs(s) for s in "DEGH"}
    diff_wb = {s: differs(s, "a_total", "b_total") for s in "DEGH"}
    in_np, in_wb = {s: tin(s) for s in "DEGH"}, {s: tin(s, "a_total") for s in "DEGH"}
    assert in_np["D"] < in_np["E"] < in_np["G"] < in_np["H"] and in_wb["D"] < in_wb["E"] < in_wb["G"] <= in_wb["H"], \
        "the tests inside the band no longer grow at every step: %r / %r" % (in_np, in_wb)
    assert set(diff_np["D"]) == set(GE_CATS) - set(CODE_CALLS) and set(diff_wb["D"]) == set(GE_CATS), \
        "untreated, the rows that differ are no longer every row but the code calls (all of them whole)"
    assert set(CODE_CALLS) <= set(diff_np["E"]) and set(diff_np["G"]) == set(CODE_CALLS), \
        "after the first two fixes, the rows that differ are no longer the code calls"
    assert diff_np["H"] == [] and diff_wb["H"] == [], "after the third fix a row still differs: %r / %r" % (diff_np["H"], diff_wb["H"])
    nd = [len(diff_np[s]) for s in "DEGH"]
    assert nd == sorted(nd, reverse=True), "the rows that differ didn't shrink at every step: %r" % nd
    # Finding 2: the code cache, and the forkchoiceUpdated split behind it.
    FS, CC = D["fcu_split"], P["code_cache"]
    assert CC["joc_rows"] > 0 and CC["sa_rows"] == 0, "the two stores' code caches no longer differ"

    def fs(tag, k, cat=None):
        return [v[k] for t, v in FS[tag]["tests"].items() if cat is None or tests[t]["cat"] == cat]
    commit_d, commit_e, commit_s = (median(fs(t, "commit_s")) for t in ("joc-D1", "joc-E1", "sa-E1"))
    xfer_prune = median(fs("joc-E1", "prune_s", "ether transfer"))
    assert commit_d >= 2 and commit_e < 0.05 and commit_s < 0.05, \
        "the measured commit no longer goes from seconds to milliseconds: %r" % ((commit_d, commit_e, commit_s),)
    prune_e, prune_g = median(fs("joc-E1", "first_prune_s")), max(fs("joc-G1", "first_prune_s"))
    assert prune_e >= 2 and prune_g < 0.01 and max(fs("sa-E1", "first_prune_s")) < 0.01, \
        "the first prune no longer tracks the code cache: %.3f -> %.4f" % (prune_e, prune_g)
    single = {tests[t]["cat"] for t, v in FS["joc-E1"]["tests"].items() if v["fcus"] == 1}
    assert single == {"ether transfer"}, "the single-block tests aren't exactly the transfers: %r" % single
    assert xfer_prune >= 2 and min(fs("joc-E1", "prune_s", "ether transfer")) > 100 * prune_g, \
        "the transfers' measured block no longer pays the scan: median %.2f s" % xfer_prune

    def xf(S_, k):
        return med([t for t in S_["tests"].values() if t["cat"] == "ether transfer"], k)
    xfe, xfg, xfs = xf(E, "joc_fcu_ms"), xf(G, "joc_fcu_ms"), xf(G, "sa_fcu_ms")
    assert xfe > 3000 and xfg < 1.5 * xfs, "the transfers' call no longer drops to state-actor's: %.0f -> %.0f vs %.0f" % (xfe, xfg, xfs)
    xw_e, xw_g = rm("E", "ether transfer", "a_total"), rm("G", "ether transfer", "a_total")
    assert xw_e > 1.5 and 0.8 <= xw_g <= 1.15, "the transfers' whole block no longer drops to parity: %.2f -> %.2f" % (xw_e, xw_g)

    def moved(s0, s1, rows):
        """Rows whose median moved more than 0.05, the same way, in both pairs."""
        out = set()
        for c in rows:
            d = [rm(s1, c, k) - rm(s0, c, k) for k in ("a", "b")]
            if min(map(abs, d)) > 0.05 and d[0] * d[1] > 0:
                out.add(c)
        return out
    assert moved("E", "G", GE_CATS) == {DIFF}, "the rows that moved with the cache changed: %r" % moved("E", "G", GE_CATS)
    joc_drop = 1 - rm("G", DIFF, "joc_mgas") / rm("E", DIFF, "joc_mgas")
    sa_drop = 1 - rm("G", DIFF, "sa_mgas") / rm("E", DIFF, "sa_mgas")
    assert joc_drop > 0.05 and joc_drop > 3 * abs(sa_drop), \
        "the distinct-contract move is no longer jochemnet slowing: %.3f / %.3f" % (joc_drop, sa_drop)
    d_slow = {c for c, r in class_rows(B, "ge1s") + class_rows(B, "lt1s") if med(
        [t for t in tests.values() if t["cat"] == c], "joc_fcu_ms") > 1000}
    assert set(ORDER) - d_slow == {"control (no state work)", "warm query", "sload same key"}, \
        "the untreated store's slow calls are no longer every row but the three no-state ones"
    # Finding 3: state-actor's code file. The two distinct-code rows are the slow ones after two
    # fixes; the reused contract, same size, isn't.
    CL, RC = P["code_layout"], P["recode"]
    assert max(rm("G", DIFF), rm("G", JUMP)) < 0.7 and rm("G", SAME) > 0.9, \
        "after two fixes the distinct-code calls are no longer the slow ones"
    jg, sg, rg = (CL[a]["groups"] for a in ("joc", "sa", "sa_recoded"))
    for g, _ in CODE_GROUPS:
        both = CL["both"][g]
        assert both["identical"] == both["n_both"] == jg[g]["n"] > 0, "a test contract differs between the stores: %s" % g
        assert jg[g]["bytes_max"] < 0.01 * MAX_CODE and rg[g]["bytes_max"] < 0.01 * MAX_CODE, "a store no longer compresses %s" % g
        assert sg[g]["bytes_min"] > MAX_CODE and sg[g]["pages_kv"] >= 7, "state-actor's raw %s is no longer 7 pages" % g
        assert max(jg[g]["pages_kv"], rg[g]["pages_kv"]) < 1.1, "a compressed %s no longer fits a page" % g
    assert all(int(g.split("@")[1]) >= 0 for g, _ in CODE_GROUPS[:2]), "a distinct test contract no longer carries its address"
    assert CL["sa"]["pattern_dict_bytes"] == 0 < min(CL["joc"]["pattern_dict_bytes"], CL["sa_recoded"]["pattern_dict_bytes"]), \
        "the code files' dictionaries changed"
    # Ranges over every distinct and jumpdest test contract, not the groups' medians.
    span = lambda gs: [min(gs[g]["bytes_min"] for g, _ in CODE_GROUPS[:2]), max(gs[g]["bytes_max"] for g, _ in CODE_GROUPS[:2])]
    j_bytes, rc_b = span(jg), span(rg)
    sa_b = sg[CODE_GROUPS[1][0]]["bytes_p50"]
    assert all(sg[g]["bytes_min"] == sg[g]["bytes_max"] == sa_b for g, _ in CODE_GROUPS), \
        "state-actor's raw test contracts no longer all take the same bytes"
    j_pages = max(jg[g]["pages_kv"] for g, _ in CODE_GROUPS[:2])
    # Every raw test contract costs the same whole number of pages, the one the prose spells out.
    sa_pages = round(sg[CODE_GROUPS[1][0]]["pages_kv"])
    assert all(abs(sg[g]["pages_kv"] - sa_pages) < 0.05 for g, _ in CODE_GROUPS) and sa_pages in WORDS, \
        "state-actor's raw test contracts no longer cost one whole number of pages"
    # The test: re-encoded with Erigon's own compressor, same content, same answers.
    assert RC["stream_sha256"] == CL["sa"]["stream_sha256"] == CL["sa_recoded"]["stream_sha256"] and \
        RC["keys"] == CL["sa"]["keys"] == CL["sa_recoded"]["keys"], "the re-encode changed the code file's content"
    assert RC["answers_identical"] and 0 < RC["rpc_fixture_samples"] < RC["rpc_samples"], "the eth_getCode check moved"
    assert CL["sa_recoded"]["file_bytes"] < CL["sa"]["file_bytes"], "the re-encoded file didn't shrink"
    joc_tr2, sa_tr2 = traced(S2, "joc"), traced(S2, "sa")
    assert len(joc_tr2) == len(sa_tr2) == len(TRACED), "the final trace no longer covers the five tests"
    assert max(s["database"] for tr in (joc_tr2, sa_tr2) for _, s, _ in tr) < 0.01, "a final trace reads a database"
    gap2 = {lj: abs(ts / tj - 1) for (lj, _, tj), (_, _, ts) in zip(joc_tr2, sa_tr2)}
    assert max(gap2.values()) < 0.25, "the final traced totals no longer match: %r" % gap2
    dm_g, jd_g = rm("G", DIFF), rm("G", JUMP)
    dm_h, dm_h2, jd_h, jd_h2 = rm("H", DIFF), rm("H", DIFF, "b"), rm("H", JUMP), rm("H", JUMP, "b")
    assert all(inband(v) for v in (dm_h, dm_h2, jd_h, jd_h2)), "the code calls didn't close: %r" % ((dm_h, dm_h2, jd_h, jd_h2),)
    # Besides the code calls, only account reads of the two distinct-contract kinds moved, one up and
    # one down. They read accounts, not code, and one store measured twice keeps only part of their
    # four tests within ±10% of itself.
    others = sorted(moved("G", "H", [c for c in GE_CATS if c not in CODE_CALLS]))
    assert others == ["account row DIFF_MAX", "account row JUMPDEST"], "the other rows that moved changed: %r" % others
    o_shift = [rm("H", c) - rm("G", c) for c in others]
    assert min(o_shift) < 0 < max(o_shift), "the other rows no longer moved in opposite directions: %r" % o_shift
    fin_ge = dict(class_rows(FIN, "ge1s"))
    o_floor = [fin_ge[c][k]["within10"] for c in others for k in ("floor_sa", "floor_joc")]
    o_n = {fin_ge[c]["a"]["n"] for c in others}
    assert len(o_n) == 1 and 1 <= min(o_floor) and max(o_floor) < min(o_n), \
        "the moved account rows' floors changed: %r of %r" % (o_floor, o_n)
    o_n = o_n.pop()
    # Where it stands: the final pairs, on their own split.
    ge_h, ALL_H = dict(class_rows(FIN, "ge1s")), {r["cls"]: r for r in FIN["rows"] if r["cat"] == "__all__"}
    ga, gb, gfl = ALL_H["ge1s"]["a"], ALL_H["ge1s"]["b"], ALL_H["ge1s"]["floor_sa"]
    assert ga["within10"] == in_np["H"] and ga["n"] == n_after, "the final row set and the staged one disagree"
    assert 0.9 <= min(ga["median"], gb["median"]) and max(ga["median"], gb["median"]) <= 1.05, \
        "the final newPayload median left the band: %.3f / %.3f" % (ga["median"], gb["median"])
    # The two stores agree about as well as each one agrees with itself.
    jfl = ALL_H["ge1s"]["floor_joc"]
    cross, floors = (ga["within10"], gb["within10"]), (gfl["within10"], jfl["within10"])
    assert min(cross) >= min(floors) - 0.05 * ga["n"] and max(cross) <= max(floors) + 0.05 * ga["n"] \
        and min(floors) > 0.8 * ga["n"], "the pairs no longer agree as well as one store with itself: %r / %r" % (cross, floors)
    d_rows = {c: abs(r["a"]["median"] - r["b"]["median"]) for c, r in ge_h.items()}
    d_np_h = max(d_rows.values())
    assert abs(ga["median"] - gb["median"]) < 0.02 and d_np_h < 0.15 and max(d_rows, key=d_rows.get).startswith("account row"), \
        "the final pairs disagree: %.3f / %r" % (abs(ga["median"] - gb["median"]), d_rows)
    acct_h = [ge_h[c]["a"]["median"] for c in CONTRACT_ACCT]
    plain_h = [ge_h["code-exec " + m]["a"]["median"] for m in ("EXISTING_EOA", "MINIMAL", "SAME_MAX")]
    assert min(acct_h + plain_h) > 0.85 and max(acct_h + plain_h) < 1.1, "the account rows or plain calls left the band's edge"
    off = {c for c, r in ge_h.items() if r["a"]["within10"] == r["b"]["within10"] == 0
           and r["floor_sa"]["within10"] > 0.8 * r["floor_sa"]["n"]}
    assert not off, "a row is still beyond the floor: %r" % off
    wb_h = ALL_H["ge1s"]["a_total"]["median"]
    assert abs(wb_h - ga["median"]) < 0.1, "the whole block no longer agrees with newPayload: %.3f / %.3f" % (wb_h, ga["median"])
    lt_h = ALL_H["lt1s"]
    assert max(share(lt_h, k) for k in ("floor_sa", "floor_joc")) < 65, "the final sub-second floors reproduce now"
    # "Most of that is the harness", except one offset: blocks with no state work run well above the
    # band on state-actor in both pairs, while one store measured twice centres them near parity. It
    # was there untreated; jochemnet's extra time per block, at the median, is ~1% of a block over a
    # second.
    ns_rows = [r for c, r in class_rows(FIN, "lt1s") if c in NOSTATE]
    ns_med = [r[k]["median"] for r in ns_rows for k in ("a", "b")]
    ns_floor = [r[k]["median"] for r in ns_rows for k in ("floor_sa", "floor_joc")]
    assert len(ns_rows) == len(NOSTATE) and min(ns_med) > 1.15 and 0.95 < min(ns_floor) and max(ns_floor) < 1.05, \
        "the no-state offset under a second changed: %r / %r" % (ns_med, ns_floor)
    ns_tests = [t for t in FIN["tests"].values() if t["cls"] == "lt1s" and t["cat"] in NOSTATE]
    ns_ms = [1e3 * median(t["joc_secs"] - t["joc_secs"] / t[k] for t in ns_tests) for k in ("a", "b")]
    assert 10 < min(ns_ms) and max(ns_ms) < 25, "jochemnet's extra time per no-state block moved: %r ms" % ns_ms
    ns_share = ns_ms[0] / 1e3 / med([t for t in FIN["tests"].values() if t["cls"] == "ge1s"], "joc_secs")
    assert 0.005 < ns_share < 0.015, "the per-block offset is no longer about 1%% of a block over a second: %.4f" % ns_share
    ns_d = [rm("D", c, cls="lt1s") for c in NOSTATE]
    assert min(ns_d) > 1.15, "the no-state offset wasn't there untreated: %r" % ns_d
    # "Over a second, state-actor still runs 3-4% slower": both pairs sit below both replica floors'
    # centres, most misses fall low, and state-actor reads more pages on every traced test.
    lean = [round(100 * (1 - g["median"])) for g in (ga, gb)]
    assert max(ga["median"], gb["median"]) < min(gfl["median"], jfl["median"]) - 0.01 and 2 <= min(lean) and max(lean) <= 5, \
        "the over-a-second lean changed: %r against floors %.3f / %.3f" % (lean, gfl["median"], jfl["median"])
    lows = [(sum(t[k] < 0.9 for t in ST["H"][("ge1s", "__all__")]), sum(not inband(t[k]) for t in ST["H"][("ge1s", "__all__")]))
            for k in ("a", "b")]
    assert all(lo > 0.8 * n for lo, n in lows), "the misses no longer fall low: %r" % lows
    more = [ts / tj - 1 for (_, _, tj), (_, _, ts) in zip(joc_tr2, sa_tr2)]
    assert min(more) > 0.01 and max(more) < 0.08, "state-actor no longer reads a few percent more on every traced test: %r" % more
    n_sa_acc, n_joc_acc = P["sa_eoas"] + P["sa_contracts"], RB["keys"]["accounts"]
    assert 1.15 < n_sa_acc / n_joc_acc < 1.25, "state-actor no longer holds about a fifth more accounts"
    # What's left.
    assert all(v == [[0, 1]] for arm in ("joc", "sa") for v in S2[arm]["domain_steps"].values()), \
        "the two stores no longer keep each domain in one step-0 file"
    # "The test contracts are cheaper than real ones": jochemnet's other maximum-size contracts (real
    # mainnet code) take most of their size on disk and several pages; a test contract takes one.
    JR = CL["joc_real_max"]
    assert JR["n"] > 0 and JR["bytes_p50"] > 0.9 * MAX_CODE and JR["pages_p50"] >= 6 > 2 * j_pages, \
        "jochemnet's real maximum-size contracts no longer cost several pages: %r" % JR
    assert RC["minutes"] > 60, "the re-encode no longer takes hours: %d min" % RC["minutes"]
    assert P["state_actor_code_pool_min_bytes"] % 1024 == 0 < P["state_actor_code_pool_min_bytes"], \
        "the code pool's floor is no longer a whole number of KiB"
    # "On the untreated store the commit was most of each block": jochemnet's FCU share of its own
    # block time, over a second.
    fcu_share = median(t["joc_fcu_ms"] / (t["joc_fcu_ms"] + 1e3 * t["joc_secs"])
                       for t in tests.values() if t["cls"] == "ge1s")
    assert fcu_share > 0.5, "the untreated commit is no longer most of jochemnet's block: %.2f" % fcu_share

    # ----- page ------------------------------------------------------------------------------
    o = []
    w = o.append
    figs = {}

    def fig(name, svg, caption):
        figs[name] = svg
        return figure(svg, caption)

    title = (f"How can two Erigon databases holding the same state be {slow:.0f}&times; slower and "
             f"{at:.0f}&times; faster, and then agree?")
    w("<!doctype html><html lang=en><head><meta charset=utf-8>")
    w('<meta name=viewport content="width=device-width,initial-scale=1">')
    w(f'<meta name="description" content="Identical EEST bloatnet runs put a generated Erigon store '
      f'{slow:.0f}x behind a mainnet snapshot on the benchmark&#39;s own clock and {at:.0f}x ahead '
      'once the whole block is timed. Three fixes to how the stores were built bring both clocks '
      'to parity.">')
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
      f"ether transfers {slow:.1f}&times; slower. Timed through the commit that follows each "
      f"block, it was {at:.1f}&times; faster. It was neither. Three things about how the two "
      f"stores were built made both gaps. Fix them one at a time and the tests that run over a "
      f"second land at a median of {ga['median']:.2f} on newPayload and {wb_h:.2f} whole, "
      f"{ga['within10']} of {ga['n']} inside &plusmn;10%. Here's each one, what it did to the "
      f"numbers, and what's left.</p>")

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
          f"tests sit inside the band: the code calls at {calls[DIFF]:.2f} and "
          f"{calls[JUMP]:.2f}, the transfers at {ex[lo_c]:.2f}."))
    w("<p>Each dot is one test, one colour per pair. The white tick is the category's median; the "
      "numbers on the right are that median and how many of its tests land inside &plusmn;10%. "
      "The same rows and axis come back at the end.</p>")
    w(f"<p>Over a second, the calls that load a contract's code run at parity, and ether transfers "
      f"at {ex[lo_c]:.2f}, about half speed. The short tests point the same way, though they don't "
      f"count: reads of contract accounts and plain calls sit at {min(short.values()):.2f} to "
      f"{max(short.values()):.2f}, while the controls, which touch no state, sit at {ctl:.2f}. "
      f"Whatever separates the two stores is in looking up accounts.</p>")
    w(f"<p><b>The benchmark times half of each block.</b> Its throughput counts only "
      f"<code>engine_newPayload</code>, where Erigon executes the block. Erigon writes the block's "
      f"state in the <code>forkchoiceUpdated</code> call that follows. On jochemnet that call takes "
      f"{min(jf)/1e3:.1f} to {max(jf)/1e3:.1f} seconds a block; on state-actor, {min(sf):.0f} to "
      f"{max(sf):.0f} milliseconds. Add it to both sides and the picture flips.</p>")
    w(fig("fig_overview_block",
          chart_overview(B, "a_total", "b_total", "whole-block throughput (newPayload + "
                         "forkchoiceUpdated), state-actor / jochemnet"),
          f"The same tests timed as the whole block. Same rows, same axis. Over a second the "
          f"median moves from {ge_all['a']['median']:.2f} to {at:.2f}. Under a second the state "
          f"tests swing as far as {lt_tot[lt_max_c]:.0f}&times; toward state-actor, where "
          f"jochemnet's commit outweighs the execution."))
    w(f"<p>Over a second, every row favours the generated store once the commit counts, from "
      f"{min(tot.values()):.1f}&times; on the code calls to {max(tot.values()):.1f}&times; on the "
      f"transfers. The two clocks answer different questions, so this page shows both.</p>")
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
      f"Jochemnet's files end at block {thousands(P['joc_files_end_block'])}, and everything after "
      f"that is in its database, {P['joc_mdbx_gb']:.0f} GB of it, including the "
      f"{thousands(P['prerun_blocks'])} pre-run blocks that create the accounts the benchmark "
      f"reads. State-actor writes all of its state into files: a {sa_db_gb:.1f} GB database beside "
      f"{sa_files_gb:.0f} GB of files. On the tests that read contract accounts, its newPayload "
      f"reads {sa_rd/joc_rd:.0f}&times; the bytes jochemnet's does.</p>")
    w("<p>Three things made the gaps:</p><ol>"
      "<li>the benchmark's state never left jochemnet's database;</li>"
      "<li>jochemnet carried a code cache into every boot;</li>"
      "<li>Erigon compresses a contract's code, and state-actor writes it raw.</li></ol>")

    # ---- part 2, finding 1
    ec, sac = P["erigon_commit"], P["state_actor_commit"]

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
      f"files, as if every one of them were old.</p>")
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
    w("<p><b>So the store to fix is jochemnet.</b> We could have gone the other way, and written the "
      "tested accounts into state-actor's database as an unfinished step. Then both stores would "
      "measure the best case: a lookup that ends in the first place Erigon looks. That isn't the "
      "read these benchmarks exist to price, and it isn't the one a node makes for cold state. On "
      "a node, everything older than the newest step is in files. So jochemnet's tested state moves "
      "down, out of the database and into the bottom file, and state-actor stays as it is.</p>")
    w(f"<p><b>The fix is a rebuild.</b> Erigon won't freeze the unfinished step, so we wrote the "
      f"files with Erigon's own code. A small tool reads the latest value of every key, from the "
      f"database and the files alike. It writes one file per domain, covering everything up to the "
      f"head block: {RB['keys']['accounts'] / 1e6:.0f} million accounts, "
      f"{RB['keys']['storage'] / 1e9:.2f} billion storage slots, "
      f"{RB['keys']['code'] / 1e6:.0f} million code entries and the commitment trie. The step "
      f"size becomes the head's last transaction number plus one, "
      f"{thousands(RB['new_step_size'])}, so the file ends exactly at block "
      f"{thousands(RB['head_block'])}. That's how state-actor's store is laid out too: one file "
      f"per domain, all of it step 0. Then the database's state tables are emptied, and it shrinks "
      f"from {P['joc_mdbx_gb']:.0f} GB to {RB['mdbx_after_bytes'] / 1e9:.1f} GB.</p>")
    w(f"<p><b>Nothing moved but the shelf.</b> Before and after, we asked the node the same "
      f"{thousands(RB['rpc_samples'])} questions: balances, nonces, storage, code, and Merkle "
      f"proofs that walk the state trie. {thousands(RB['rpc_samples_db_accounts'])} accounts and "
      f"{thousands(RB['rpc_samples_db_slots'])} slots among them had lived only in the database. "
      f"Every answer came back byte for byte the same.</p>")
    w(fig("fig_sources_after", chart_sources(S1),
          f"The same four tests after the rebuild. Jochemnet was traced again; state-actor's store "
          f"didn't change, so its bars are the earlier trace. Jochemnet now reads its files, and "
          f"three of the four totals land within {100 * near1:.0f}% of state-actor's. The jumpdest "
          f"call is the odd one out: state-actor reads {code_x:.0f}&times; the code-file pages."))
    w(f"<p><b>What it did.</b> The rebuilt jochemnet is slower, so {n_after} tests now run over a "
      f"second, against {n_before} before; every step from here on is compared on that split. Over "
      f"a second, {in_np['E']} of {n_after} tests now sit inside the band, against "
      f"{in_np['D']}; timed whole, {in_wb['E']} against {in_wb['D']}. newPayload went from "
      f"{np_b:.2f} to {np_a:.2f} ({np_a2:.2f} in the second pair), and the whole block from "
      f"{wb_b:.2f} to {wb_a:.2f}. Account reads went from {min(acct_b):.2f}&ndash;"
      f"{max(acct_b):.2f} to {min(acct_a):.2f}&ndash;{max(acct_a):.2f}, and ether transfers from "
      f"{tr_b:.2f} to {tr_a:.2f}.</p>")
    w(f"<p><b>Two rows went the other way.</b> The distinct-contract and jumpdest calls were at "
      f"parity and now sit at {rm('E', DIFF):.2f} and {rm('E', JUMP):.2f}. They had agreed for the "
      f"wrong reason, and finding 3 is why.</p>")

    # ---- finding 2
    w("<h2>2. Jochemnet carried a code cache into every boot</h2>")
    w(fig("fig_commit", chart_commit([("jochemnet, untreated", "--db-u", B, "joc_fcu_ms"),
                                      ("jochemnet, rebuilt", "--accent", E, "joc_fcu_ms"),
                                      ("rebuilt, code cache emptied", "--db-c", G, "joc_fcu_ms"),
                                      ("state-actor", "--db-sa", G, "sa_fcu_ms")]),
          "The call that follows each measured block. Untreated, jochemnet spends seconds on every "
          "row except the three that do no new state work. Rebuilt, only the transfers do. With "
          "its code cache emptied, they don't either."))
    w(f"<p><b>Erigon's own log splits that call in two:</b> writing the block, and pruning. We "
      f"matched each line to its test. On the untreated store, the measured block's write took "
      f"{commit_d:.0f} s at the median. That's finding 1's database. After the rebuild it takes "
      f"{commit_e * 1e3:.0f} ms, and state-actor's {commit_s * 1e3:.0f} ms.</p>")
    w(f"<p><b>The transfers kept {xfe / 1e3:.1f} seconds,</b> {xfer_prune:.0f} of them in the "
      f"prune. A fresh Erigon process sizes its code cache on its first prune, by reading the whole "
      f"table {src('execution/cache/code_store.go', 128, 'once')}. That table holds contract code "
      f"Erigon has already decompressed, so a hit skips the code files. Jochemnet's held "
      f"{thousands(CC['joc_rows'])} contracts' code. The rebuild left it alone, because it isn't "
      f"state. State-actor's is empty. Every test boots a fresh client, so jochemnet pays the read "
      f"once per test. Most tests send a setup block first, and that block pays it. A transfer "
      f"test sends one block, so the measured one does.</p>")
    w(f"<p><b>The fix</b> is to empty the table. On a miss Erigon reads the code files, which is "
      f"what state-actor does on every call, so an empty cache is the worst case again. <b>What "
      f"it did:</b> the first prune went from {prune_e:.0f} s to under {int(prune_g * 1e3) + 1} ms "
      f"on every test. The transfers' call dropped from {xfe / 1e3:.2f} s to {xfg:.0f} ms, against "
      f"state-actor's {xfs:.0f} ms, and their whole block from {xw_e:.2f} to {xw_g:.2f}. Timed "
      f"whole, {in_wb['G']} of {n_after} tests over a second now sit inside the band, against "
      f"{in_wb['E']}.</p>")
    w(f"<p>Inside newPayload, one row over a second moved by more than 0.05 in both pairs: the "
      f"distinct-contract call, from {rm('E', DIFF):.2f} to {rm('G', DIFF):.2f} "
      f"({rm('G', DIFF, 'b'):.2f} in the second pair). Jochemnet ran it {100 * joc_drop:.0f}% "
      f"slower, and state-actor {100 * sa_drop:.0f}%. So the cache had been serving some of those "
      f"contracts' code: the pre-run deployed them, and Erigon caches code "
      f"{src('execution/cache/code_store.go', 97, 'as it deploys it')}. The jumpdest call didn't "
      f"move; its code came from the files all along, as the trace showed.</p>")

    # ---- finding 3
    n_fix = sum(jg[g]["n"] for g, _ in CODE_GROUPS)
    w("<h2>3. Erigon compresses a contract's code; state-actor writes it raw</h2>")
    w(fig("fig_codefile", chart_codefile(CL),
          f"One test contract in each store's code file. Erigon's writer compresses it against a "
          f"dictionary of repeated byte patterns, to {min(j_bytes)}&ndash;{max(j_bytes)} bytes in "
          f"one 4 KB page. State-actor's writer has no dictionary and stores all {sa_b:,} bytes, "
          f"{WORDS[sa_pages]} pages. Re-encoded with Erigon's compressor, state-actor's file holds each in "
          f"{min(rc_b)}&ndash;{max(rc_b)} bytes."))
    w(f"<p>After the first two fixes, two rows were still slow: calls into a different "
      f"maximum-size contract every time, at {dm_g:.2f} for a distinct contract and {jd_g:.2f} for "
      f"the jumpdest one. Calls into a reused contract of the same size ran at "
      f"{rm('G', SAME):.2f}.</p>")
    w(f"<p><b>Only distinct contracts reach the disk.</b> Erigon looks up code by its hash first, "
      f"in memory and then in the cache table from finding 2, and "
      f"{src('db/state/execctx/domain_shared.go', 1537, 'reads the code file')} only on a miss. A "
      f"reused contract has one hash, so each fresh client reads it from disk once. A distinct "
      f"contract is a new hash every call, and every call reads the file.</p>")
    w(f"<p><b>The contracts are the same; the files aren't.</b> Every test contract is "
      f"{MAX_CODE:,} bytes, almost all of it one repeated opcode; the distinct ones carry their own "
      f"address inside. All {thousands(n_fix)} that jochemnet holds are on state-actor too, byte "
      f"for byte. Erigon's writer "
      f"{src('db/state/statecfg/state_schema.go', 251, 'compresses code')} against a dictionary of "
      f"repeated byte patterns: jochemnet's code file carries "
      f"{CL['joc']['pattern_dict_bytes'] / 1e3:.0f} KB of them, and a test contract takes "
      f"{min(j_bytes)}&ndash;{max(j_bytes)} bytes, one page for its key and value "
      f"({j_pages:.2f} on average). State-actor writes Erigon's file format with "
      f'<a href="https://github.com/ethereum/state-actor/blob/{sac}/internal/erigon/seg/compressor.go#L45">'
      f"its own encoder</a>, which has no dictionary path. Its dictionary is empty, and every test "
      f"contract takes all {sa_b:,} bytes, {WORDS[sa_pages]} pages, on every call.</p>")
    w(f"<p><b>Why the rows agreed before.</b> Before the rebuild, jochemnet's test contracts sat "
      f"in its database, which {src('db/state/domain.go', 533, 'keeps values as written')}: all "
      f"{MAX_CODE // 1024} KB of each, like state-actor's file. Both stores paid for whole contracts, "
      f"and the rows sat at {cc_b[DIFF]:.2f} and {cc_b[JUMP]:.2f}. Finding 1's rebuild wrote them "
      f"the way Erigon writes every file, and the gap showed.</p>")
    w(f"<p><b>The test</b> is to write state-actor's code file the way Erigon does. We re-encoded "
      f"it with Erigon's own compressor and the code domain's own settings. Every key and value "
      f"stays: the file's {thousands(RC['keys'])} entries hash the same before and after, and "
      f"{thousands(RC['rpc_samples'])} <code>eth_getCode</code> answers, "
      f"{thousands(RC['rpc_fixture_samples'])} of them test contracts, came back byte for byte the "
      f"same. The file went from {CL['sa']['file_bytes'] / 1e9:.1f} GB to "
      f"{CL['sa_recoded']['file_bytes'] / 1e9:.1f} GB.</p>")
    w(fig("fig_sources_final", chart_sources(S2),
          f"Five tests traced on both stores in their final state: jochemnet rebuilt with its cache "
          f"emptied, state-actor with its code file re-encoded. Both read only their files, and "
          f"every total lands within {100 * max(gap2.values()):.0f}% of the other store's."))
    w(f"<p><b>What it did.</b> The distinct-contract call went from {dm_g:.2f} to {dm_h:.2f} "
      f"({dm_h2:.2f} in the second pair), and the jumpdest call from {jd_g:.2f} to {jd_h:.2f} "
      f"({jd_h2:.2f}). Two other rows moved: account reads on the same two kinds of contract, one up "
      f"and one down. They don't read code, and one store measured twice keeps only "
      f"{min(o_floor)}&ndash;{max(o_floor)} of their {o_n} tests within 10% of itself. Over a "
      f"second, {in_np['H']} of {n_after} tests now sit inside the band, against "
      f"{in_np['G']}.</p>")
    w("<p>The fix belongs in the generator: its Erigon writer has to hand each domain to Erigon's own "
      "compressor, at Erigon's own settings.</p>")

    # ---- part 3
    w("<h2>Where it stands</h2>")
    w(fig("fig_overview_after",
          chart_overview(FIN, "a", "b", "newPayload throughput after the three fixes, "
                         "state-actor / jochemnet (band = \u00b110%)"),
          "The same tests after all three fixes, two independent pairs. Compare it with the first "
          "figure: same rows, same axis."))
    stage_rows = [{c: rm(s, c) for c in GE_CATS} for s in "DEGH"]
    w(fig("fig_progress", chart_progress(stage_rows, GE_CATS),
          f"Every row over a second after each step, pair 1, on the final split. Untreated, "
          f"{nd[0]} of {len(GE_CATS)} rows sat outside the band in both pairs. After the rebuild, "
          f"{nd[1]}; after the code cache, {nd[2]}; after the code file, none."))
    w("<table><tr><th>tests</th><th class=n>n</th><th class=n>untreated</th><th class=n>1</th>"
      "<th class=n>2</th><th class=n>3, now</th><th class=n>inside &plusmn;10%</th>"
      "<th class=n>same store twice</th><th class=n>whole block, untreated</th>"
      "<th class=n>whole block, now</th></tr>")
    for cls, label in (("ge1s", "over a second"), ("lt1s", "under a second")):
        w(f"<tr><td colspan=10><b>{label}</b></td></tr>")
        for cat, row in class_rows(FIN, cls):
            cells = "".join(f'<td class="n{" bad" if cls == "ge1s" and cat in diff_np[s] else ""}">'
                            f"{rm(s, cat, 'a', cls):.3f}</td>" for s in "DEGH")
            a_, fl = row["a"], row["floor_sa"]
            w(f"<tr><td>{esc(ROW_LABEL.get(cat, cat))}</td><td class=n>{a_['n']}</td>{cells}"
              f"<td class=n>{a_['within10']}/{a_['n']}</td><td class=n>{fl['within10']}/{fl['n']}</td>"
              f"<td class=n>{rm('D', cat, 'a_total', cls):.3f}</td><td class=n>{row['a_total']['median']:.3f}</td></tr>")
    w("<tr><td colspan=2><b>rows over a second outside the band</b></td>"
      + "".join(f"<td class=n>{len(diff_np[s])}</td>" for s in "DEGH")
      + f"<td colspan=2></td><td class=n>{len(diff_wb['D'])}</td><td class=n>{len(diff_wb['H'])}</td></tr>")
    w("<tr><td colspan=2><b>tests over a second inside &plusmn;10%</b></td>"
      + "".join(f"<td class=n>{in_np[s]}</td>" for s in "DEGH")
      + f"<td></td><td class=n>{gfl['within10']}</td><td class=n>{in_wb['D']}</td><td class=n>{in_wb['H']}</td></tr>")
    w("<caption>Median ratio per category, pair 1, after each step: 1 the rebuild, 2 the emptied "
      "code cache, 3 the re-encoded code file. Every column uses the final store's one-second "
      "split; shaded cells are rows outside the band in both pairs. Same store twice is "
      "state-actor measured twice, the best any row can do.</caption></table>")
    w(f"<p>Over a second, {ga['within10']} of {ga['n']} tests now sit inside the band (median "
      f"{ga['median']:.3f}), and {gb['within10']} in the second pair ({gb['median']:.3f}). One store "
      f"measured twice manages {gfl['within10']} for state-actor and {jfl['within10']} for "
      f"jochemnet. The two stores now agree about as well as each agrees with itself. Account reads "
      f"sit at {min(acct_h):.2f} to {max(acct_h):.2f}. Calls into an EOA, a minimal contract or a "
      f"reused one sit at {min(plain_h):.2f} to {max(plain_h):.2f}, and into a distinct or jumpdest "
      f"contract at {dm_h:.2f} and {jd_h:.2f}. Transfers are at "
      f"{ge_h['ether transfer']['a']['median']:.2f}. Timed whole, the block says the same: "
      f"{wb_h:.3f}. No row is further from parity than the floor explains.</p>")
    w(f"<p><b>Pair 2</b> repeats both stores with fresh runs, and its median lands within "
      f"{abs(ga['median'] - gb['median']):.3f} of pair 1's. Rows move by up to {d_np_h:.2f}, the most "
      f"on the four-test account rows. Under a second, "
      f"{lt_h['a']['within10']} of {lt_h['a']['n']} tests land in the band, and the same store "
      f"measured twice manages only {lt_h['floor_sa']['within10']} "
      f"({lt_h['floor_joc']['within10']} for jochemnet). Most of that is the harness. One offset "
      f"isn't, and it's in what's left.</p>")

    # ---- part 4
    w("<h2>What's left, and why</h2><ul>")
    w(f"<li><b>State-actor's Erigon writer can't compress yet.</b> Until it hands each domain to "
      f"Erigon's compressor, every Erigon store it builds needs a re-encode like the one above, which "
      f"took {RC['minutes'] / 60:.0f} hours for the code file alone. We re-encoded only that file. "
      f"State-actor's storage and commitment files still store their keys raw, where Erigon "
      f"compresses them ({src('db/state/statecfg/state_schema.go', 229, 'storage')}, "
      f"{src('db/state/statecfg/state_schema.go', 274, 'commitment')}).</li>")
    w(f"<li><b>Over a second, state-actor still runs {min(lean)}&ndash;{max(lean)}% slower.</b> Both "
      f"pairs sit below parity, at {ga['median']:.3f} and {gb['median']:.3f}, where one store measured "
      f"twice centres on {min(gfl['median'], jfl['median']):.2f} to "
      f"{max(gfl['median'], jfl['median']):.2f}. Of the tests that miss the band, {lows[0][0]} of "
      f"{lows[0][1]} miss it low ({lows[1][0]} of {lows[1][1]} in the second pair). On every traced "
      f"test, state-actor reads {round(100 * min(more))}&ndash;{round(100 * max(more))}% more pages. "
      f"Two known differences could explain some of it: the raw keys above, and a fifth more "
      f"accounts ({n_sa_acc / 1e6:.0f} million against {n_joc_acc / 1e6:.0f} million). We haven't "
      f"tested either.</li>")
    w(f"<li><b>Under a second, one offset is real.</b> Blocks that do no state work, warm queries and "
      f"reloads of one slot run {min(ns_med):.2f}&ndash;{max(ns_med):.2f} times faster on "
      f"state-actor, in both pairs. One store measured twice centres those rows on "
      f"{min(ns_floor):.2f} to {max(ns_floor):.2f}, so it isn't the harness. At the median, jochemnet "
      f"spends about {ns_ms[0]:.0f} ms more per block. Over a second that's about 1% of a block. It "
      f"was there before any fix, at {min(ns_d):.2f}&ndash;{max(ns_d):.2f}, and we haven't traced "
      f"it.</li>")
    w(f"<li><b>The test contracts are cheaper than real ones.</b> Each is {MAX_CODE // 1024} KB of one "
      f"repeated opcode, so Erigon stores it in about {round(max(j_bytes), -2):.0f} bytes, one page. "
      f"Jochemnet also holds {thousands(JR['n'])} real mainnet contracts of the same size, and the "
      f"median one takes {JR['bytes_p50']:,} bytes, {WORDS[JR['pages_p50']]} pages. So the distinct-code rows "
      f"price a cheap code read, not the worst one. That's a question for the fixtures, not the "
      f"stores.</li>")
    w(f'<li><b>Distinct code is still open on the other clients.</b> On <a href="../nethermind-'
      f'state-db-divergence/nethermind-state-db-report.html">Nethermind</a> and <a href="../besu-'
      f'state-db-divergence/besu-state-db-report.html">Besu</a> the same rows end with the generated '
      f"store faster, not slower. There state-actor writes code through the client's own RocksDB "
      f"settings, so the encoding matches; what differs is the code packed around each test "
      f"contract. State-actor's shared code pool keeps every record at "
      f"{P['state_actor_code_pool_min_bytes'] // 1024} KiB or more, and the Nethermind article "
      f"traces the overshoot to that floor. The pool feeds every client, so changing it changes "
      f"every generated store's state root.</li>")
    w("<li><b>Both stores keep each domain in one file.</b> On a node, files come in merged ranges, "
      "and a cold lookup checks each newer file before it reaches the oldest. Neither store here "
      "pays that walk. It's the same on both sides, so the ratio holds, but a node's worst case "
      "costs more than either store measures.</li>")
    w("<li><b>Sub-second tests can't be compared on this harness yet.</b> Every test boots a fresh "
      "client, and under a second the measurement is mostly that client starting up. A discarded "
      "burn-in block before the measured one would fix it. Until then, those numbers are shown and "
      "not counted.</li>")
    w("<li><b>benchmarkoor's clock still stops at newPayload.</b> With all three fixes the two "
      "clocks agree, so this comparison doesn't depend on it. But on the untreated store the commit "
      "was most of each block, and a newPayload-only number hid it. For Erigon, the harness should "
      "report the whole block beside newPayload.</li></ul>")
    w("<p>None of these is a reason to distrust the generated store on tests over a second, once its "
      "code file is written the way Erigon writes it. Two are generator work, two are still open, one "
      "is a question for the fixtures, and three are about the method and the harness.</p>")

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
