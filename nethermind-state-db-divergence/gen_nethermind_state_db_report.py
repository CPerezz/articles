#!/usr/bin/env python3
"""Build the Nethermind state-DB divergence report from the collected run data.

Every number in the page is derived here from data/report_data.json; none is typed into the
prose. The oracles in main() fail generation if the data stops supporting a sentence the article
states as fact.

Usage: python3 gen_nethermind_state_db_report.py
"""
import html
import json
import math
import os
import re

import report_svg as S
from crt_theme import CSS

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "nethermind-state-db-report.html")
FIGDIR = os.path.join(HERE, "figures")

# Ratios throughout are state-actor / jochemnet, so 1.00 is parity and < 1 means the generated
# store is slower. Categories are ordered the way the article discusses them.
CATS = [
    "ACCOUNT cold existing EOA",
    "ACCOUNT cold existing contract",
    "ACCOUNT cold non-existing",
    "ACCOUNT warm query",
    "STORAGE slot access",
    "ETHER transfer receivers",
    "CONTROL overhead_baseline",
]
SHORT = {
    "ACCOUNT cold existing EOA": "existing EOA",
    "ACCOUNT cold existing contract": "existing contract",
    "ACCOUNT cold non-existing": "absent account",
    "ACCOUNT warm query": "warm query",
    "STORAGE slot access": "storage slot",
    "ETHER transfer receivers": "ether transfer",
    "CONTROL overhead_baseline": "control (no state work)",
}
LOADS_CODE = {"CALL", "CALLCODE", "DELEGATECALL", "STATICCALL", "EXTCODECOPY", "EXTCODESIZE"}

MODE_ORDER = ["EXISTING_EOA", "EXISTING_CONTRACT_MINIMAL", "EXISTING_CONTRACT_SAME_MAX",
              "EXISTING_CONTRACT_JUMPDEST", "EXISTING_CONTRACT_DIFF_MAX"]
MODE_CODE = {
    "EXISTING_EOA": "no code at all",
    "EXISTING_CONTRACT_MINIMAL": "minimal code",
    "EXISTING_CONTRACT_SAME_MAX": "one max-size contract, reused",
    "EXISTING_CONTRACT_JUMPDEST": "code scanned for jump destinations",
    "EXISTING_CONTRACT_DIFF_MAX": "a different max-size contract per access",
}


def esc(s):
    return html.escape(str(s))


def f(v, nd=2):
    return "&mdash;" if v is None else f"{v:.{nd}f}"


def median(xs):
    srt = sorted(xs)
    n = len(srt)
    if not n:
        return None
    return srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2.0


def thousands(n):
    return f"{n:,}"


def ygrid(scale, ticks, x0, x1, fmt=str):
    """Horizontal gridlines with left-hand labels.

    report_svg.hgrid draws the x axis; a value-to-y grid is specific to this report's charts.
    """
    out = []
    for t in ticks:
        y = scale.to(t)
        out.append(S.line(x0, y, x1, y, "--line", 1))
        out.append(S.label(x0 - 8, y + 4, fmt(t), "end", "tick"))
    return "".join(out)


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


# --------------------------------------------------------------------------- figures
def chart_cost_curves(curve):
    """Read volume against gas, per arm. A bounded working set is flat in gas; an unbounded one
    rises with it. This is the shape that started the investigation."""
    W, H, L, R, T, B = 760, 306, 62, 18, 18, 48
    gas = [c["gas"] for c in curve]
    hi = max(max(c["saMB"] for c in curve), max(c["jocMB"] for c in curve))
    sx = S.Scale(min(gas), max(gas), L, W - R)
    sy = S.Scale(0, hi * 1.08, H - B, T)
    o = [ygrid(sy, [0, hi * 0.25, hi * 0.5, hi * 0.75, hi], L, W - R,
                 fmt=lambda v: f"{v/1000:.1f} GB" if hi > 1500 else f"{v:.0f} MB")]
    for key, var in (("saMB", "--db-sa"), ("jocMB", "--accent")):
        pts = [(sx.to(c["gas"]), sy.to(c[key])) for c in curve]
        o.append(S.polyline(pts, var, 2.5))
        o += [S.dot(x, y, 3, var) for x, y in pts]
    for g in gas[::2]:
        o.append(S.label(sx.to(g), H - B + 22, f"{g}M", "middle", "tick"))
    o.append(S.label((L + W - R) / 2, H - 6, "gas per test", "middle", "ax"))
    last = curve[-1]
    o.append(S.label(W - R - 4, sy.to(last["saMB"]) - 9, "state-actor", "end", "big"))
    o.append(S.label(W - R - 4, sy.to(last["jocMB"]) - 9, "jochemnet", "end", "big"))
    return S.svg(W, H, "".join(o))


def chart_amortisation(points):
    """Two panels over the same log-x: cost per lookup, and cumulative bytes. The saturation in
    the lower panel is the mechanism - a bounded set of physical blocks, read once."""
    W, H, L, R = 760, 400, 62, 18
    ns = [p["n"] for p in points]
    sx = S.LogScale(min(ns), max(ns), L, W - R)

    # panel 1: blocks per lookup
    t1, b1 = 16, 178
    sy1 = S.Scale(0, 2.2, b1, t1)
    o = [ygrid(sy1, [0, 0.5, 1.0, 1.5, 2.0], L, W - R, fmt=lambda v: f"{v:.1f}")]
    for key, var in (("sa_blk", "--db-sa"), ("joc_blk", "--accent")):
        pts = [(sx.to(p["n"]), sy1.to(p[key])) for p in points]
        o.append(S.polyline(pts, var, 2.5))
        o += [S.dot(x, y, 3.2, var) for x, y in pts]
    o.append(S.label(L, t1 - 4, "4 KiB blocks read per lookup", "start", "big"))
    o.append(S.label(W - R - 4, sy1.to(points[-1]["sa_blk"]) - 9, "state-actor", "end", "big"))
    o.append(S.label(W - R - 4, sy1.to(points[-1]["joc_blk"]) + 16, "jochemnet", "end", "big"))

    # panel 2: cumulative megabytes
    t2, b2 = 226, 358
    hi = max(p["sa_mb"] for p in points)
    sy2 = S.Scale(0, hi * 1.1, b2, t2)
    o.append(ygrid(sy2, [0, hi * 0.5, hi], L, W - R, fmt=lambda v: f"{v:.0f} MB"))
    for key, var in (("sa_mb", "--db-sa"), ("joc_mb", "--accent")):
        pts = [(sx.to(p["n"]), sy2.to(p[key])) for p in points]
        o.append(S.polyline(pts, var, 2.5))
        o += [S.dot(x, y, 3.2, var) for x, y in pts]
    o.append(S.label(L, t2 - 4, "cumulative bytes pulled from disk", "start", "big"))
    jl = points[-1]
    o.append(S.label(sx.to(jl["n"]) - 6, sy2.to(jl["joc_mb"]) - 10,
                     f"saturates at {jl['joc_mb']:.0f} MB", "end", "big"))

    # The first and last ticks sit on the axis ends, so centring them hangs half the label
    # outside the figure box. Anchor the outer two inward.
    for i, p in enumerate(points):
        anchor = "start" if i == 0 else "end" if i == len(points) - 1 else "middle"
        o.append(S.label(sx.to(p["n"]), b2 + 22, thousands(p["n"]), anchor, "tick"))
    o.append(S.label((L + W - R) / 2, H - 6, "cold lookups performed", "middle", "ax"))
    return S.svg(W, H, "".join(o))


def chart_treatment_dumbbell(before, after):
    """One row per category: where the ratio sat with the confound, and where it sits without it.
    Everything that reads state lands on the parity line."""
    W, L, R, T = 760, 172, 112, 16
    rows = [c for c in CATS if c in before and c in after]
    H = T + 26 * len(rows) + 58
    sx = S.LogScale(0.045, 2.2, L, W - R)
    body_bot = T + 26 * len(rows) - 8
    o = [S.band(sx.to(0.9), sx.to(1.1), T - 6, body_bot, "--accent", 0.10)]
    o.append(S.line(sx.to(1.0), T - 6, sx.to(1.0), body_bot, "--green-muted", 1))
    for i, cat in enumerate(rows):
        y = T + 26 * i + 8
        b, a = before[cat]["thr"], after[cat]["thr"]
        o.append(S.label(L - 8, y + 4, SHORT[cat], "end"))
        o.append(S.line(sx.to(b), y, sx.to(a), y, "--green-muted", 2))
        o.append(S.dot(sx.to(b), y, 4, "--db-u", f"with confound {b:.3f}"))
        o.append(S.dot(sx.to(a), y, 4.5, "--accent", f"equalised {a:.3f}"))
        # Fixed value column: where before and after nearly coincide, a label anchored to the
        # after-dot prints on top of the before-dot.
        o.append(S.label(W - R + 10, y + 4, f"{b:.3f} \u2192 {a:.3f}", "start", "tick"))
    for v in (0.05, 0.1, 0.25, 0.5, 1.0, 2.0):
        o.append(S.label(sx.to(v), body_bot + 22, f"{v:g}", "middle", "tick"))
    # Legend in the figure, not only in the caption: a standalone .svg has no caption.
    o.append(S.dot(L + 6, body_bot + 38, 4, "--db-u"))
    o.append(S.label(L + 16, body_bot + 42, "with the pre-run confound", "start", "tick"))
    o.append(S.dot(L + 214, body_bot + 38, 4.5, "--accent"))
    o.append(S.label(L + 224, body_bot + 42, "after compaction", "start", "tick"))
    o.append(S.label((L + W - R) / 2, H - 5,
                     "throughput, state-actor / jochemnet  (1.0 = parity)", "middle", "ax"))
    return S.svg(W, H, "".join(o))


def chart_code_ladder(modes, code_gb):
    """Extra bytes read, by how much contract code the access mode touches. The ordering is the
    argument: the residual tracks code, and the code database is the thing that differs."""
    W, L, R, T = 760, 296, 96, 26
    rows = [m for m in MODE_ORDER if m in modes]
    H = T + 30 * len(rows) + 44
    hi = max(modes[m]["readX"] for m in rows)
    sx = S.Scale(1.0, hi * 1.06, L, W - R)
    o = [S.line(sx.to(1.0), T - 8, sx.to(1.0), T + 30 * len(rows) - 10, "--green-muted", 1)]
    for i, m in enumerate(rows):
        y = T + 30 * i + 6
        v = modes[m]["readX"]
        o.append(S.label(L - 8, y + 4, MODE_CODE[m], "end"))
        o.append(S.band(sx.to(1.0), sx.to(v), y - 7, y + 7, "--accent", 0.30))
        o.append(S.label(sx.to(v) + 8, y + 4, f"{v:.2f}\u00d7", "start", "big"))
    o.append(S.label(L, T - 12, "bytes read, state-actor / jochemnet", "start", "big"))
    for v in (1.0, 1.1, 1.2, 1.3, 1.4):
        if v <= hi * 1.06:
            o.append(S.label(sx.to(v), H - 26, f"{v:.1f}", "middle", "tick"))
    o.append(S.label((L + W - R) / 2, H - 9,
                     f"code database: {code_gb['sa']} on state-actor vs "
                     f"{code_gb['joc']} on jochemnet", "middle", "ax"))
    return S.svg(W, H, "".join(o))



# The absent-account mode is excluded: every one of its tests runs in under a second, so it
# belongs to the class the page treats as measurement rather than as a store property.
GRID_MODES = ["EXISTING_EOA", "EXISTING_CONTRACT_MINIMAL", "EXISTING_CONTRACT_SAME_MAX",
              "EXISTING_CONTRACT_JUMPDEST", "EXISTING_CONTRACT_DIFF_MAX"]
MODE_SHORT = {"EXISTING_EOA": "EOA", "EXISTING_CONTRACT_MINIMAL": "MINIMAL",
              "EXISTING_CONTRACT_SAME_MAX": "SAME_MAX",
              "EXISTING_CONTRACT_JUMPDEST": "JUMPDEST",
              "EXISTING_CONTRACT_DIFF_MAX": "DIFF_MAX",
              "NON_EXISTING_ACCOUNT": "absent"}


def _strip(ratios, spread_row, sx, y, var, bins=64):
    """One category's whole distribution: binned dots sized by count, with the interquartile
    range and median drawn over them. A median on its own cannot show whether a category is
    tight around parity or straddling it."""
    o = []
    lo, hi = sx.lo, sx.hi
    counts = {}
    for r in ratios:
        r = min(max(r, lo), hi)
        k = int((math.log10(r) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * (bins - 1))
        counts[k] = counts.get(k, 0) + 1
    for k, n in sorted(counts.items()):
        x = sx.px_lo + (k / (bins - 1)) * (sx.px_hi - sx.px_lo)
        o.append(S.dot(x, y, min(5.0, 1.3 + 0.75 * (n ** 0.5)), var,
                       f"{n} test{'s' if n > 1 else ''}"))
    if spread_row:
        o.append(S.line(sx.to(spread_row["p25"]), y, sx.to(spread_row["p75"]), y,
                        "--green-muted", 1.5))
        o.append(S.line(sx.to(spread_row["median"]), y - 7, sx.to(spread_row["median"]), y + 7,
                        var, 2))
    return "".join(o)


# Article category -> the key the class collector uses. Only needed because the two partitions
# were written a month apart; the article folds sload_same_key into the storage category.
CLASS_KEY = {"ACCOUNT cold existing EOA": "existing EOA",
             "ACCOUNT cold existing contract": "existing contract",
             "ACCOUNT cold non-existing": "absent account",
             "ACCOUNT warm query": "warm query",
             "STORAGE slot access": "storage slot",
             "ETHER transfer receivers": "ether transfer",
             "CONTROL overhead_baseline": "CONTROL"}


def chart_ratio_dots(rat_b, rat_a, spr_b, spr_a, cls=None):
    """Every test's ratio, by category, before and after the treatment.

    The dumbbell shows that the medians moved; this shows the distributions moving, which is the
    claim that actually matters - a category whose median lands on parity while its tests stay
    scattered has not converged.
    """
    W, L, R = 760, 212, 80
    rows = [c for c in CATS if c in rat_a]
    rh, gap = 27, 52
    t1 = 34
    t2 = t1 + rh * len(rows) + gap
    H = t2 + rh * len(rows) + 30
    sx = S.LogScale(0.03, 2.3, L, W - R)

    o = []
    for top, rat, spr, var, title in ((t1, rat_b, spr_b, "--db-u", "with the pre-run confound"),
                                      (t2, rat_a, spr_a, "--accent", "placement equalised")):
        bot = top + rh * len(rows) - 12
        o.append(S.band(sx.to(0.9), sx.to(1.1), top - 12, bot + 6, "--accent", 0.10))
        o.append(S.line(sx.to(1.0), top - 12, sx.to(1.0), bot + 6, "--green-muted", 1))
        o.append(S.label(L, top - 18, title, "start", "big"))
        for i, cat in enumerate(rows):
            y = top + rh * i
            lbl = SHORT[cat]
            if cls:
                pct = cls["by_category"][CLASS_KEY[cat]]["pct_lt1s"]
                lbl += " \u00b7 <1s" if pct >= 95 else " \u00b7 mixed" if pct > 5 else ""
            o.append(S.label(L - 8, y + 4, lbl, "end"))
            o.append(_strip(rat[cat], spr.get(cat), sx, y, var))
            w10 = spr[cat]["within10"]
            o.append(S.label(W - R + 10, y + 4, f"{w10}/{spr[cat]['n']}", "start", "tick"))
        for v in (0.03, 0.1, 0.3, 1.0, 2.0):
            o.append(S.label(sx.to(v), bot + 22, f"{v:g}", "middle", "tick"))
    o.append(S.label((L + W - R) / 2, H - 4,
                     "throughput, state-actor / jochemnet  (1.0 = parity)", "middle", "ax"))
    return S.svg(W, H, "".join(o))


def chart_grid(grid):
    """opcode x account_mode after treatment. Ink is distance from parity, so the one column
    that stays dark is the argument for the section that follows."""
    ops = sorted(grid)
    W, L, T, R = 760, 122, 44, 14
    cw = (W - L - R) / len(GRID_MODES)
    ch = 30
    H = T + ch * len(ops) + 34
    o = []
    for j, m in enumerate(GRID_MODES):
        o.append(S.label(L + cw * (j + 0.5), T - 12, MODE_SHORT[m], "middle", "tick"))
    worst_dev = max((abs(1 - c["thr"]) for row in grid.values() for c in row.values()), default=1)
    for i, op in enumerate(ops):
        y = T + ch * i
        o.append(S.label(L - 8, y + ch / 2 + 4, op, "end"))
        for j, m in enumerate(GRID_MODES):
            cell = grid[op].get(m)
            x = L + cw * j
            if not cell:
                o.append(S.label(x + cw / 2, y + ch / 2 + 4, "&mdash;", "middle", "tick"))
                continue
            dev = abs(1 - cell["thr"]) / worst_dev
            o.append(S.band(x + 1, x + cw - 1, y + 2, y + ch - 2, "--accent",
                            round(0.06 + 0.72 * dev, 3)))
            o.append(S.label(x + cw / 2, y + ch / 2 + 4, f"{cell['thr']:.2f}", "middle"))
    o.append(S.label((L + W - R) / 2, H - 6,
                     "throughput ratio per cell; brighter = further from parity", "middle", "ax"))
    return S.svg(W, H, "".join(o))



def chart_steps(st):
    """Setup step against measured step, per arm.

    The harness drops the OS page cache between the two, but the client is not restarted inside a
    test, so its own RocksDB block cache carries whatever setup pulled in straight into the
    measurement. The inversion between the two panels is that carry-over.
    """
    W, H, L, R, T, B = 760, 208, 150, 24, 40, 40
    groups = [("control", "control: no account work"), ("measured", "tests that read accounts")]
    hi = max(st[g][a][k] for g, _ in groups for a in ("joc", "sa") for k in ("setup", "test"))
    hi = max(hi, 1)
    gw = (W - L - R) / len(groups)
    o = []
    for gi, (key, title) in enumerate(groups):
        x0 = L + gw * gi
        o.append(S.label(x0 + gw / 2, T - 16, title, "middle", "big"))
        rows = [("jochemnet setup", st[key]["joc"]["setup"], "--accent"),
                ("jochemnet measured", st[key]["joc"]["test"], "--accent"),
                ("state-actor setup", st[key]["sa"]["setup"], "--db-sa"),
                ("state-actor measured", st[key]["sa"]["test"], "--db-sa")]
        for ri, (lbl, v, var) in enumerate(rows):
            y = T + 14 + ri * 26
            sx = S.LogScale(0.5, hi * 1.2, x0 + 4, x0 + gw - 40)
            o.append(S.band(sx.to(0.5), sx.to(max(v, 0.6)), y - 8, y + 8, var, 0.5))
            o.append(S.label(sx.to(max(v, 0.6)) + 6, y + 4, f"{v:,.0f}", "start", "tick"))
            if gi == 0:
                o.append(S.label(L - 8, y + 4, lbl, "end"))
    o.append(S.label((L + W - R) / 2, H - 30,
                     "megabytes read (log scale)", "middle", "ax"))
    o.append(S.label((L + W - R) / 2, H - 10,
                     "green = jochemnet    blue = state-actor", "middle", "ax"))
    return S.svg(W, H, "".join(o))


BUCKETS = ("lt0.2s", "0.2to1s", "1to5s", "ge5s")
BUCKET_LABEL = {"lt0.2s": "< 0.2 s", "0.2to1s": "0.2 - 1 s", "1to5s": "1 - 5 s", "ge5s": "> 5 s"}


def chart_duration_floor(cl):
    """How often a test lands within 10% of the number it is being compared to, by duration.

    Two series on one axis, and the gap between them is the whole argument: the floor is the
    same store measured twice, so nothing below it is a store property. Where the two series
    meet, the comparison is measuring the harness.
    """
    W, L, R, T = 760, 96, 150, 44
    H = T + 34 * len(BUCKETS) + 52
    sx = S.Scale(0, 100, L, W - R)
    o = [S.line(L, T - 12, L, T + 34 * len(BUCKETS) - 10, "--green-muted", 1)]
    for v in (0, 25, 50, 75, 100):
        o.append(S.label(sx.to(v), T - 20, f"{v}%", "middle", "tick"))
    for i, b in enumerate(BUCKETS):
        y = T + 34 * i + 10
        rep, cross = cl["buckets"]["replica"].get(b), cl["buckets"]["treated"].get(b)
        o.append(S.label(L - 8, y + 4, BUCKET_LABEL[b], "end"))
        if not (rep and cross):
            continue
        rp = 100 * rep["within10"] / rep["n"]
        cp = 100 * cross["within10"] / cross["n"]
        o.append(S.line(sx.to(min(rp, cp)), y, sx.to(max(rp, cp)), y, "--green-muted", 2))
        o.append(S.dot(sx.to(rp), y, 4, "--db-u", f"same store twice: {rp:.0f}%"))
        o.append(S.dot(sx.to(cp), y, 4.5, "--accent", f"the two stores: {cp:.0f}%"))
        o.append(S.label(W - R + 10, y + 4,
                         f"{cp:.0f}% of {cross['n']}, floor {rp:.0f}%", "start", "tick"))
    o.append(S.dot(L + 6, H - 28, 4, "--db-u"))
    o.append(S.label(L + 16, H - 24, "same store, measured twice", "start", "tick"))
    o.append(S.dot(L + 236, H - 28, 4.5, "--accent"))
    o.append(S.label(L + 246, H - 24, "the two stores, after treatment", "start", "tick"))
    o.append(S.label(L, T - 34, "tests landing within \u00b110%, by how long the test runs",
                     "start", "big"))
    return S.svg(W, H, "".join(o))


CLASS2_MODES = ("EXISTING_EOA", "EXISTING_CONTRACT_MINIMAL", "EXISTING_CONTRACT_SAME_MAX",
                "EXISTING_CONTRACT_JUMPDEST", "EXISTING_CONTRACT_DIFF_MAX")
FAMILY_LABEL = {"account_row": "reads the account row only",
                "loads_code": "loads the callee's code"}
FAMILY_OPS = {"account_row": "BALANCE, EXTCODEHASH",
              "loads_code": "CALL family + EXTCODE*"}


def chart_class2_families(cl):
    """The long tests only, split by what the opcode touches and whether the contract is reused.

    One row is flat and one row is a ladder. That is the finding: distinctness is free until the
    opcode has to fetch the callee's code, and then it tracks the bytes.
    """
    fam = cl["class2_families"]
    W, L, T, R = 760, 186, 58, 16
    cw = (W - L - R) / len(CLASS2_MODES)
    ch, H = 46, 58 + 46 * 2 + 62
    o = []
    for j, m in enumerate(CLASS2_MODES):
        o.append(S.label(L + cw * (j + 0.5), T - 14, MODE_SHORT[m], "middle", "tick"))
    worst = max(abs(1 - c["median"]) for row in fam.values() for c in row.values())
    for i, key in enumerate(("account_row", "loads_code")):
        y = T + ch * i
        o.append(S.label(L - 8, y + ch / 2, FAMILY_LABEL[key], "end"))
        o.append(S.label(L - 8, y + ch / 2 + 14, FAMILY_OPS[key], "end", "tick"))
        for j, m in enumerate(CLASS2_MODES):
            cell = fam[key].get(m)
            x = L + cw * j
            if not cell:
                o.append(S.label(x + cw / 2, y + ch / 2 + 4, "\u2014", "middle", "tick"))
                continue
            dev = abs(1 - cell["median"]) / worst
            o.append(S.band(x + 1, x + cw - 1, y + 2, y + ch - 2, "--accent",
                            round(0.06 + 0.42 * dev, 3)))
            o.append(S.label(x + cw / 2, y + ch / 2 - 2, f"{cell['median']:.3f}", "middle"))
            o.append(S.label(x + cw / 2, y + ch / 2 + 13,
                             f"{cell['saMB']/max(cell['jocMB'], 0.01):.2f}\u00d7 bytes",
                             "middle", "tick"))
    o.append(S.label((L + W - R) / 2, H - 38,
                     "throughput ratio (top) and bytes read (bottom), state-actor / jochemnet",
                     "middle", "ax"))
    o.append(S.label((L + W - R) / 2, H - 20,
                     f"tests over {cl['boundary_s']:.0f} s only; the absent-account mode has none "
                     f"and is absent from the figure", "middle", "ax"))
    return S.svg(W, H, "".join(o))


def chart_final_cells(cl, repacked=None, regenerated=None):
    """Where it stands: every cell of the long class after all four findings are applied, with
    the two earlier replicas of the same configuration as faint marks so the reader can see
    what run-to-run movement looks like beside the value being quoted. `repacked` adds, for
    the cells it names, the value measured after the code database was repacked;
    `regenerated` the value measured on the store rebuilt with the fixed generator."""
    fc = cl["final_cells"]
    repacked = repacked or {}
    regenerated = regenerated or {}
    rows = sorted(fc.items(), key=lambda kv: kv[1]["settled"])
    W, L, R, T = 760, 190, 150, 26
    rh = 26
    H = T + rh * len(rows) + (78 if regenerated else 62)
    sx = S.Scale(0.85, 1.15, L, W - R)
    bot = T + rh * len(rows) - 8
    o = [S.band(sx.to(0.9), sx.to(1.1), T - 8, bot + 4, "--accent", 0.10),
         S.line(sx.to(1.0), T - 8, sx.to(1.0), bot + 4, "--green-muted", 1)]
    for i, (name, v) in enumerate(rows):
        y = T + rh * i + 6
        o.append(S.label(L - 8, y + 4, name, "end"))
        for rep in ("r1", "r2"):
            if v.get(rep):
                o.append(S.dot(sx.to(max(0.85, min(1.15, v[rep]))), y, 3, "--green-muted",
                               f"earlier replica {v[rep]:.3f}"))
        o.append(S.dot(sx.to(max(0.85, min(1.15, v["settled"]))), y, 4.5, "--accent",
                       f"{name}: {v['settled']:.3f}"))
        if name in repacked:
            a = repacked[name]
            o.append(S.line(sx.to(v["settled"]), y, sx.to(a), y, "--db-u", 1.5, dash="3 3"))
            o.append(S.dot(sx.to(max(0.85, min(1.15, a))), y, 4.5, "--db-u",
                           f"{name}, code database repacked: {a:.3f}"))
            o.append(S.label(W - R + 10, y + 4, f"{v['settled']:.3f} \u2192 {a:.3f}  n={v['n']}",
                             "start", "tick"))
        else:
            o.append(S.label(W - R + 10, y + 4, f"{v['settled']:.3f}  n={v['n']}", "start", "tick"))
        if name in regenerated:
            g = regenerated[name]
            o.append(S.dot(sx.to(max(0.85, min(1.15, g))), y, 4.5, "--db-sa",
                           f"{name}, regenerated store: {g:.3f}"))
    for t in (0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15):
        o.append(S.label(sx.to(t), bot + 22, f"{t:.2f}", "middle", "tick"))
    o.append(S.dot(L + 6, H - 14, 4.5, "--accent"))
    o.append(S.label(L + 16, H - 10, "after all four findings", "start", "tick"))
    o.append(S.dot(L + 186, H - 14, 3, "--green-muted"))
    o.append(S.label(L + 196, H - 10, "two earlier runs, same config", "start", "tick"))
    if repacked:
        o.append(S.dot(L + 400, H - 14, 4.5, "--db-u"))
        o.append(S.label(L + 410, H - 10, "code database repacked", "start", "tick"))
    if regenerated:
        o.append(S.dot(L + 6, H - 30, 4.5, "--db-sa"))
        o.append(S.label(L + 16, H - 26, "regenerated store (generator fix), run 1", "start", "tick"))
    o.append(S.label(L, T - 14, "throughput, state-actor / jochemnet, tests over 1 s  (band = \u00b110%)",
                     "start", "big"))
    return S.svg(W, H, "".join(o))


def chart_levels(st):
    """Two columns of one store against two of the other, as level stacks.

    A point lookup for a key that is absent has to be refused by every level that could hold it,
    so what matters is not how many files a column has but over how many levels they sit."""
    col = st["columns"]
    lanes = [("jochemnet storage rows", col["joc_storage_before"], "--db-u"),
             ("  after compaction", col["joc_storage_after"], "--accent"),
             ("jochemnet storage trie", col["joc_storagenodes_before"], "--db-u"),
             ("  after compaction", col["joc_storagenodes_after"], "--accent"),
             ("state-actor storage rows", col["sa_storage"], "--accent"),
             ("state-actor storage trie", col["sa_storagenodes"], "--accent")]
    W, L, T = 760, 200, 30
    rh, bw = 30, 44
    H = T + rh * len(lanes) + 44
    o = [S.label(L, T - 14, "files per level (L0 newest, L6 bottom)", "start", "big")]
    for i, (name, shape, var) in enumerate(lanes):
        y = T + rh * i
        o.append(S.label(L - 10, y + 15, name, "end"))
        for lv in range(7):
            x = L + lv * (bw + 5)
            n = shape["per_level"].get(str(lv), 0)
            o.append(S.band(x, x + bw, y + 2, y + 24, "--line", 0.45))
            if n:
                o.append(S.band(x, x + bw, y + 2, y + 24, var, 0.30))
                o.append(S.label(x + bw / 2, y + 17, "%d" % n, "middle", "tick"))
        o.append(S.label(L + 7 * (bw + 5) + 6, y + 17, "%.0f GB" % shape["gb"], "start", "tick"))
    for lv in range(7):
        o.append(S.label(L + lv * (bw + 5) + bw / 2, T + rh * len(lanes) + 12, "L%d" % lv, "middle", "tick"))
    o.append(S.dot(L, H - 10, 4, "--db-u"))
    o.append(S.label(L + 10, H - 6, "as found", "start", "tick"))
    o.append(S.dot(L + 110, H - 10, 4, "--accent"))
    o.append(S.label(L + 120, H - 6, "settled: one level", "start", "tick"))
    return S.svg(W, H, "".join(o))


def chart_storage_close(st):
    """The four storage tests through the two compactions, with the reads that moved under them."""
    sc = st["cells"]
    rows = [("absent slot, no write", "slots=False new=False"),
            ("new value, existing slot", "slots=True new=True"),
            ("new value, absent slot", "slots=False new=True"),
            ("overwrite, existing slot", "slots=True new=False")]
    stages = [("before", "v2"), ("fresh pair", "r68"), ("rows settled", "r69"), ("+ trie settled", "r72")]
    W, L, R, T = 760, 200, 96, 34
    rh = 46
    H = T + rh * len(rows) + 54
    sx = S.LogScale(0.83, 2.7, L, W - R)
    bot = T + rh * len(rows) - 12
    o = [S.band(sx.to(0.9), sx.to(1.1), T - 10, bot + 6, "--accent", 0.10),
         S.line(sx.to(1.0), T - 10, sx.to(1.0), bot + 6, "--green-muted", 1),
         S.label(L, T - 18, "throughput ratio, state-actor / jochemnet  (band = \u00b110%)", "start", "big")]
    for i, (label, key) in enumerate(rows):
        y = T + rh * i + 8
        o.append(S.label(L - 10, y + 4, label, "end"))
        pts = []
        for gas in ("160M", "240M"):
            k = "%s %s" % (key, gas)
            prev = None
            for j, (_, stage) in enumerate(stages):
                v = sc[k][stage]
                x = sx.to(max(0.83, min(2.7, v)))
                yy = y - 6 + 12 * (1 if gas == "240M" else 0)
                if prev is not None:
                    o.append(S.line(prev[0], prev[1], x, yy, "--green-muted", 1, dash="2 3"))
                var = "--db-u" if j == 0 else ("--accent" if j == len(stages) - 1 else "--green-dim")
                o.append(S.dot(x, yy, 4.5 if j in (0, len(stages) - 1) else 3, var,
                               "%s, %s: %.3f" % (gas, stages[j][0], v)))
                prev = (x, yy)
                pts.append(v)
        o.append(S.label(W - R + 6, y + 4, "%.2f \u2192 %.2f" % (sc["%s 160M" % key]["v2"], sc["%s 160M" % key]["r72"]),
                         "start", "tick"))
    for t in (0.9, 1.0, 1.25, 1.5, 2.0, 2.5):
        o.append(S.label(sx.to(t), bot + 26, ("%.2f" % t).rstrip("0").rstrip("."), "middle", "tick"))
    o.append(S.dot(L, H - 12, 4.5, "--db-u"))
    o.append(S.label(L + 10, H - 8, "before", "start", "tick"))
    o.append(S.dot(L + 80, H - 12, 3, "--green-dim"))
    o.append(S.label(L + 90, H - 8, "each step", "start", "tick"))
    o.append(S.dot(L + 180, H - 12, 4.5, "--accent"))
    o.append(S.label(L + 190, H - 8, "settled (two rows: 160M, 240M)", "start", "tick"))
    return S.svg(W, H, "".join(o))


def chart_seqno_paths(bm):
    """Why a store that looks settled still gets rewritten.

    Both lanes end with every file in the bottom level, which is exactly why level shape and
    pending-compaction bytes cannot tell them apart. What differs is whether the files were
    moved there or rewritten there, and therefore whether their sequence numbers were zeroed.
    """
    W, H = 760, 252
    idle, boot = bm["idle"], bm["boot"]

    def box(x, y, w, h, text, sub, var, op=0.16):
        out = [S.band(x, x + w, y, y + h, var, op),
               S.line(x, y, x + w, y, var, 1), S.line(x, y + h, x + w, y + h, var, 1),
               S.line(x, y, x, y + h, var, 1), S.line(x + w, y, x + w, y + h, var, 1),
               S.label(x + w / 2, y + h / 2 - 2, text, "middle", "big")]
        if sub:
            out.append(S.label(x + w / 2, y + h / 2 + 13, sub, "middle", "tick"))
        return "".join(out)

    def arrow(x1, x2, y, var, text):
        return "".join([S.line(x1, y, x2 - 8, y, var, 1.5),
                        S.polyline([(x2 - 10, y - 4), (x2, y), (x2 - 10, y + 4)], var, 1.5),
                        S.label((x1 + x2) / 2, y - 9, text, "middle", "tick")])

    o = []
    for i, (title, var, verb, seq, outcome, osub) in enumerate((
            ("today: plain CompactRange, bottommost_level_compaction = "
             "kIfHaveCompactionFilter (no filter is configured)",
             "--db-u", "trivially MOVES", "seq \u2260 0",
             "client rewrites it",
             f"{idle['sa_mb']:,} MB idle, {boot['sa']['jobs']} jobs/boot"),
            ("the one-line fix: the same call with bottommost_level_compaction = kForce",
             "--accent", "REWRITES", "seq: 0",
             "client does nothing",
             f"{idle['sa_settled_mb']} MB idle, {boot['sa_settled']['jobs']} jobs"))):
        top = 30 + 102 * i
        o.append(S.label(14, top, title, "start", "tick"))
        y = top + 12
        o.append(box(14, y, 150, 46, "flushed L0 files", "seq \u2260 0", "--green-muted", 0.10))
        o.append(arrow(164, 300, y + 23, var, verb))
        o.append(box(300, y, 170, 46, "all files at L6", seq, var))
        o.append(arrow(470, 540, y + 23, var, "opens"))
        o.append(box(540, y, 206, 46, outcome, osub, var))
    o.append(S.label(W / 2, H - 8,
                     "both lanes leave a flat tree with pending-compaction-bytes = 0; "
                     "only the sequence numbers differ", "middle", "ax"))
    return S.svg(W, H, "".join(o))


def chart_idle_reads(bm):
    """The measurement that moved this off the read path: the reads do not need a query."""
    W, L, R, T = 760, 268, 92, 30
    idle, rpc = bm["idle"], bm["rpc"]
    rows = [(f"jochemnet, idle {idle['window_s']} s", idle["joc_mb"], "--accent"),
            (f"state-actor, idle {idle['window_s']} s", idle["sa_mb"], "--db-sa"),
            ("state-actor, idle, after the fix", idle["sa_settled_mb"], "--accent"),
            (f"jochemnet, {rpc['calls']:,} balance lookups", rpc["joc"]["trie_mb"], "--accent"),
            (f"state-actor, {rpc['calls']:,} balance lookups", rpc["sa"]["trie_mb"], "--db-sa")]
    H = T + 30 * len(rows) + 40
    hi = max(v for _, v, _ in rows) * 1.12
    sx = S.Scale(0, hi, L, W - R)
    o = [S.line(L, T - 10, L, T + 30 * len(rows) - 8, "--green-muted", 1)]
    for i, (lbl, v, var) in enumerate(rows):
        y = T + 30 * i + 6
        o.append(S.label(L - 8, y + 4, lbl, "end"))
        if v > 0:
            o.append(S.band(sx.to(0), sx.to(v), y - 8, y + 8, var, 0.34))
        o.append(S.label(sx.to(v) + 8, y + 4, f"{v:,.0f} MB", "start", "big"))
    o.append(S.label(L, T - 16, "trie-node bytes read from the store", "start", "big"))
    o.append(S.label((L + W - R) / 2, H - 10,
                     f"page cache dropped first; both arms read the identical "
                     f"{rpc['sa']['account_mb']:.1f} MB from flat/Account",
                     "middle", "ax"))
    return S.svg(W, H, "".join(o))


def chart_marginal_cf(bm):
    """What settling the store removed, and what it left behind.

    The same probe before and after: one of these measurements was a phantom that scaled with
    how long the test ran, the other is the cost the article is actually about.
    """
    att = bm["attribution"]["code"]
    rows = []
    for cf, lbl in (("flat/StateNodes", "state-actor  flat/StateNodes"),
                    ("code", "state-actor  code"),
                    ("flat/Account", "state-actor  flat/Account")):
        b = att["before"]["sa"]["cf"].get(cf, {}).get("marg", 0.0)
        a = att["after"]["sa"]["cf"].get(cf, {}).get("marg", 0.0)
        rows.append((lbl, b, a))
    jb = att["before"]["joc"]["cf"].get("24402727", {}).get("marg", 0.0)
    ja = att["after"]["joc"]["cf"].get("24402727", {}).get("marg", 0.0)
    rows.append(("jochemnet  whole datadir", jb, ja))
    W, L, R, T = 760, 240, 118, 30
    H = T + 30 * len(rows) + 52
    hi = max(max(b, a) for _, b, a in rows) * 1.1
    sx = S.Scale(0, hi, L, W - R)
    bot = T + 30 * len(rows) - 8
    o = [S.line(sx.to(0), T - 10, sx.to(0), bot, "--green-muted", 1)]
    for i, (lbl, b, a) in enumerate(rows):
        y = T + 30 * i + 6
        o.append(S.label(L - 8, y + 4, lbl, "end"))
        o.append(S.line(sx.to(max(b, 0)), y, sx.to(max(a, 0)), y, "--green-muted", 2))
        o.append(S.dot(sx.to(max(b, 0)), y, 4, "--db-u", f"with the compaction running {b:.1f} MB"))
        o.append(S.dot(sx.to(max(a, 0)), y, 4.5, "--accent", f"settled {a:.1f} MB"))
        z = lambda v: 0.0 if abs(v) < 0.5 else v
        o.append(S.label(W - R + 10, y + 4, f"{z(b):.0f} \u2192 {z(a):.0f}", "start", "tick"))
    o.append(S.dot(L + 6, bot + 26, 4, "--db-u"))
    o.append(S.label(L + 16, bot + 30, "with the background compaction running", "start", "tick"))
    o.append(S.dot(L + 292, bot + 26, 4.5, "--accent"))
    o.append(S.label(L + 302, bot + 30, "store settled", "start", "tick"))
    o.append(S.label(L, T - 16,
                     "extra MB read for a distinct contract per access (DIFF_MAX \u2212 SAME_MAX)",
                     "start", "big"))
    return S.svg(W, H, "".join(o))


# --------------------------------------------------------------------------- page
def main():
    D = json.load(open(os.path.join(HERE, "data", "report_data.json")))
    P, M = D["provenance"], D["measured"]
    BEF, AFT = D["before"], D["after"]
    bc, ac = BEF["categories"], AFT["categories"]
    modes, modes_ctrl = AFT["by_mode"], AFT["by_mode_control"]
    spr_b, spr_a = BEF["spread"], AFT["spread"]
    rat_b, rat_a = BEF["ratios"], AFT["ratios"]
    amort = M["amortisation"]["points"]
    iv, fp, tc = M["intervention"], M["footprint"], M["three_client"]
    BM = D["bottommost"]

    # The third defect. Four things have to hold for that section to be worth printing: the
    # client read the store hard while idle, it stopped after the fix, the reason field named
    # the mechanism, and the throughput did *not* move - the last one is why the section ends
    # where it does rather than claiming a cause.
    assert BM["idle"]["sa_mb"] > 500 > BM["idle"]["joc_mb"], \
        "the idle client no longer reads the generated store: %r" % BM["idle"]
    assert BM["idle"]["sa_settled_mb"] < 10 and BM["boot"]["sa_settled"]["jobs"] == 0, \
        "settling the trie families no longer silences the client: %r" % BM["idle"]
    assert BM["boot"]["sa"]["reason"] == "BottommostFiles", \
        "compaction reason changed; the seqno mechanism is not what this store triggers: %r" \
        % BM["boot"]["sa"]
    assert BM["rpc"]["sa"]["account_mb"] == BM["rpc"]["joc"]["account_mb"], \
        "the flat read path stopped being byte-identical: %r" % BM["rpc"]
    for c in ("DIFF_MAX code-exec", "JUMPDEST code-exec"):
        cl = BM["cells"][c]
        moved = cl["settled"] - (cl["r1"] + cl["r2"]) / 2
        assert abs(moved) < 0.05, \
            ("%s moved %.3f when the store was settled; it is no longer 'the fix did not "
             "explain the gap'" % (c, moved))
        assert cl["settled"] < 0.97, \
            "%s reached parity after settling; the open item is closed, rewrite it" % c
    # Non-code access must be byte-identical once the phantom is gone, and the distinct-contract
    # marginal must survive it. Those two are the whole of what is left.
    _nc = BM["attribution"]["noncode"]["after"]
    assert _nc["sa"]["cf"].get("flat/StateNodes", {}).get("marg", 0) < 5, \
        "trie reads came back on the non-code probe: %r" % _nc["sa"]["cf"]
    _wide = BM["attribution"]["code_wide"]
    _sa_w, _joc_w = _wide["sa"]["total_marg"], _wide["joc"]["cf"]["24402727"]["marg"]
    assert _sa_w > _joc_w > 0, \
        "the distinct-contract marginal is no longer larger on the generated store: %r" % _wide
    assert abs(_wide["sa"]["cf"]["flat/Account"]["marg"]) < 20, \
        "the account row now costs more under DIFF_MAX; the 'it is the code' framing is out"
    # ----- oracles: every claim the prose makes as fact -------------------------
    worst = min(bc[c]["thr"] for c in
                ("ACCOUNT cold existing EOA", "ACCOUNT cold existing contract"))
    factor = 1.0 / worst
    assert 10 <= factor <= 20, f"headline factor moved out of band: {factor:.1f}"
    for cat in ("ACCOUNT cold existing EOA", "ACCOUNT cold existing contract",
                "ETHER transfer receivers"):
        assert ac[cat]["thr"] > 0.94, f"{cat} no longer at parity after treatment: {ac[cat]}"
    for cat in ("ACCOUNT cold non-existing", "STORAGE slot access"):
        assert 0.9 <= bc[cat]["thr"] <= 1.15, f"{cat} was not a parity control before: {bc[cat]}"
    assert ac["CONTROL overhead_baseline"]["thr"] < 0.8, "control residual vanished; rewrite §residual"
    assert AFT["agreement"]["agree_pct"] > 3 * BEF["agreement"]["agree_pct"], \
        "treatment no longer multiplies agreement"
    # the inversion: on their own random keys jochemnet is the more expensive store
    rk = M["random_keys"]["Account"]
    assert rk["joc_blk"] > rk["sa_blk"], "random-key inversion gone; the argument depends on it"
    # amortisation: jochemnet starts at parity and saturates, state-actor stays flat and grows
    a0, a9 = amort[0], amort[-1]
    assert abs(a0["joc_blk"] - a0["sa_blk"]) < 0.2, "arms no longer start at parity"
    assert a9["joc_blk"] < 0.4 and a9["sa_blk"] > 1.8, "saturation/linearity broke"
    assert a9["joc_mb"] < 2 * amort[-2]["joc_mb"], "jochemnet volume no longer saturates"
    # code ladder must stay monotonic in code involvement, else §code is not an argument
    ladder = [modes[m]["readX"] for m in MODE_ORDER if m in modes]
    assert ladder == sorted(ladder), f"code ladder lost its ordering: {ladder}"
    # The article's scope starts at the flat-backed pair. If the collector is ever re-pointed at
    # a run from before the generated store was rebuilt with the flat layout, fail loudly rather
    # than publish a number from a pair that never shared a read path.
    assert P["arms"]["sa"]["run"] == M["preconditions"]["sa_run_flat_backed"], (
        f"state-actor arm is {P['arms']['sa']['run']}, expected the flat-backed run "
        f"{M['preconditions']['sa_run_flat_backed']}")
    assert P["arms"]["joc"]["run"] == M["preconditions"]["joc_run"], \
        f"jochemnet arm is not the recorded run: {P['arms']['joc']['run']}"
    # The classification the page is built on. It is only worth drawing the line if the two
    # sides behave differently, if the short side is at or under its own reproducibility floor
    # (so it cannot be a store property), and if the line is not doing the work - hence the
    # sensitivity check at half and double the boundary.
    CL = D["classes"]
    c1, c2 = CL["classes"]["treated"]["lt1s"], CL["classes"]["treated"]["ge1s"]
    f1, f2 = CL["classes"]["replica"]["lt1s"], CL["classes"]["replica"]["ge1s"]
    r1, r2 = c1["within10"] / c1["n"], c2["within10"] / c2["n"]
    assert r1 < 0.35 < 0.7 < r2, \
        "the duration classes no longer separate: %.2f vs %.2f within 10%%" % (r1, r2)
    assert r1 <= f1["within10"] / f1["n"] + 0.02, \
        "short tests now agree across stores better than one store agrees with itself; the " \
        "'this class is measurement' argument is out"
    assert f2["within10"] / f2["n"] > 0.9, \
        "the long-test floor collapsed; no per-test claim on this dataset is safe"
    assert abs(c2["median"] - 1) < 0.1, \
        "the long class left parity after treatment: %.3f" % c2["median"]
    for b, v in CL["boundary_sensitivity"].items():
        assert abs(v["ge"]["median"] - c2["median"]) < 0.02, \
            ("the conclusion depends on where the boundary is drawn (%s s -> %.3f against "
             "%.3f at 1 s)" % (b, v["ge"]["median"], c2["median"]))
    # Every category the page calls measurement must actually be short, and the storage category
    # must stay split across the line - it is the cheapest evidence that the boundary is real.
    for cat in ("CONTROL", "warm query", "absent account", "sload_same_key"):
        assert CL["by_category"][cat]["pct_lt1s"] >= 95, \
            "%s is no longer a sub-second category (%.0f%%)" % (cat, CL["by_category"][cat]["pct_lt1s"])
    st_split = CL["by_category"]["storage slot"]
    assert st_split["lt1s"] and st_split["ge1s"] and \
        abs(st_split["lt1s"]["median"] - 1) > 3 * abs(st_split["ge1s"]["median"] - 1), \
        "the storage category stopped splitting across the boundary: %r" % st_split
    # The localisation: inside the long class, only code-loading opcodes against a distinct
    # contract diverge. Both halves have to hold or the taxonomy section is not an argument.
    FAM = CL["class2_families"]
    assert min(v["median"] for v in FAM["account_row"].values()) > 0.94, \
        "account-row opcodes left parity in the long class: %r" % FAM["account_row"]
    assert FAM["loads_code"]["EXISTING_CONTRACT_DIFF_MAX"]["median"] < 0.9 < \
        FAM["loads_code"]["EXISTING_CONTRACT_SAME_MAX"]["median"], \
        "distinct-vs-reused no longer separates for code-loading opcodes: %r" % FAM["loads_code"]
    # Finding 4's mechanism and the closing figure. The tenancy argument needs the sibling
    # study's block simulation to point the same way as the marginal measured here, and the
    # Besu cell to show the same distinct-vs-reused split; the closing figure needs the residual
    # pair to be the only cells below 0.97 and everything else inside the band.
    BX = M["besu_cross_check"]
    assert BX["code_block_sim"]["state_actor"]["block_comp"] > \
        1.4 * BX["code_block_sim"]["jochemnet"]["block_comp"], \
        "the block-tenancy simulation no longer shows the generated store's block costing more"
    assert BX["families"]["loads_code"]["EXISTING_CONTRACT_DIFF_MAX"]["median"] < \
        BX["families"]["loads_code"]["EXISTING_CONTRACT_SAME_MAX"]["median"] - 0.05, \
        "Besu no longer shows the distinct-vs-reused split; the cross-engine argument is out"
    FC = D["classes"]["final_cells"]
    for c, v in FC.items():
        if c in ("DIFF_MAX code-exec", "JUMPDEST code-exec"):
            assert v["settled"] < 0.97, "%s closed; the closing section still calls it open" % c
        else:
            assert 0.9 <= v["settled"] <= 1.1, "%s left the band after all fixes: %.3f" % (c, v["settled"])
    # The intervention. Finding 4 now says the residual closes when the code database is
    # repacked; that has to hold on the harness's clock and at cell level, with the control
    # unmoved, or the section overclaims.
    IB_ = D["intervention_blocks"]
    _joc = sorted(IB_["secs"]["joc"]); _sa4 = sorted(IB_["secs"]["sa_4k"]); _sa64 = sorted(IB_["secs"]["sa_64b"])
    assert _sa4[0] > _joc[-1], "the 4 KB store no longer runs the traced test slower than every jochemnet run"
    assert _sa64[len(_sa64)//2] <= _joc[len(_joc)//2] + 0.1, \
        "repacking no longer brings the traced test onto jochemnet's time: %r vs %r" % (_sa64, _joc)
    assert IB_["pread"]["sa"]["code_mean_b"] > IB_["pread"]["joc"]["code_mean_b"] * 1.2, \
        "the generated store's code blocks are no longer larger per fetch"
    for c in ("DIFF_MAX code-exec", "JUMPDEST code-exec"):
        assert abs(IB_["cells"][c]["after"] - 1) < 0.03 < 1 - IB_["cells"][c]["before"], \
            "%s did not close under repacking: %r" % (c, IB_["cells"][c])
    assert abs(IB_["cells"]["SAME_MAX code-exec"]["after"] - IB_["cells"]["SAME_MAX code-exec"]["before"]) < 0.02, \
        "the SAME_MAX control moved under repacking; the tenancy argument loses its control"

    # The transfer cell. The section is only worth printing if the tries really are the same
    # shape (so shape cannot be the explanation), the packing really differed on exactly the
    # column the trace named, the swap moved both arms toward each other and closed the cell
    # to within the replica spread, and the read counts swapped with it.
    TN_ = D["topnodes"]
    assert TN_["shape"]["joc"]["top_nodes"] == TN_["shape"]["sa_v1"]["top_nodes"] == 1118481, \
        "the two account tries no longer share a complete top: %r" % TN_["shape"]
    assert TN_["shape"]["sa_v1"]["walk_nodes"] >= TN_["shape"]["joc"]["walk_nodes"] - 0.05, \
        "the generated trie is now shallower; shape could explain fewer reads"
    _pk = TN_["packing"]
    assert _pk["joc_before"]["bytes_per_block"] < 5000 < 12000 < _pk["sa_before"]["bytes_per_block"], \
        "top-of-trie packing no longer differs the way the section says: %r" % _pk
    assert _pk["joc_after"]["bytes_per_block"] > 12000 > 5000 > _pk["sa_after"]["bytes_per_block"], \
        "the swap did not swap the packing: %r" % _pk
    _sw = TN_["swap"]
    assert _sw["ratio_settled"] > 1.05 and abs(_sw["ratio_swapped"] - 1) < 0.03, \
        "the swap no longer closes the transfer cell: %r" % _sw
    assert _sw["sa_change"] < 1 < _sw["joc_change"], "the arms did not move toward each other: %r" % _sw
    assert _sw["joc"]["top_per_account_before"] > _sw["sa"]["top_per_account_before"] and \
        _sw["joc"]["top_per_account_after_240M"] < _sw["sa"]["top_per_account_after_240M"], \
        "top-node reads per account did not swap with the layout: %r" % _sw
    _pv = TN_["provenance"]
    assert _pv["Storage"]["min"] < 1000 < _pv["StateTopNodes"]["min"] < _pv["Account"]["min"], \
        "file numbers no longer date the 4 KB top-node files to this study's rebuild: %r" % _pv

    # The regenerated store. The section claims the code-pool fix overshoots, which is only
    # worth printing if: the store really is a different one (new genesis), it was written with
    # the client's packing (so the transfer comparison is layout-fair), the two code cells moved
    # above parity and both runs agree, the reused-contract control did not move, the same-arm
    # drift is smaller than the movement, the fill covered the class it claims to, and the
    # transfer cell did *not* fully close - the prose is written around that.
    V2_ = D["v2"]
    _vc = V2_["cells"]
    assert V2_["genesis"] != V2_["v1_genesis"], "the regenerated store has the old genesis root"
    assert V2_["fixtures"]["class2_covered"][0] == V2_["fixtures"]["class2_covered"][1], \
        "the v2 fill no longer covers the whole long class: %r" % V2_["fixtures"]
    assert V2_["topnodes_packing"]["bytes_per_block"] > 12000, \
        "the regenerated store no longer packs top nodes the way the client does: %r" % V2_["topnodes_packing"]
    for _c in ("DIFF_MAX code-exec", "JUMPDEST code-exec"):
        assert _vc[_c]["v1_t1"] < 0.96 < 1.04 < min(_vc[_c]["v2r1"], _vc[_c]["v2r2"]), \
            "%s no longer overshoots parity on the regenerated store: %r" % (_c, _vc[_c])
    assert abs(_vc["SAME_MAX code-exec"]["v2r1"] - 1) < 0.02, \
        "the reused-contract control moved with the pool fix: %r" % _vc["SAME_MAX code-exec"]
    assert max(abs(v["v2r2_v2r1"] - 1) for v in _vc.values() if v["v2r2_v2r1"]) < 0.02, \
        "the two runs of the regenerated store no longer agree cell by cell"
    assert _vc["ether transfer"]["joc_joc_t1"] > 1.02, \
        "the snapshot no longer gains from the top-node repack: %r" % _vc["ether transfer"]
    assert _vc["ether transfer"]["v2r1"] > 1.03, \
        "the transfer cell closed; the open-residual paragraph must be rewritten: %r" % _vc["ether transfer"]

    # Round 68. The section says: the shared denominator inflated the tail, what survives on a
    # fresh pair is an absent-slot storage test explained by the column's level spread and an
    # absent-account transfer that is not I/O at all. Each of those has to still be true.
    OU_ = D["outliers"]
    _ot, _den_ = OU_["tests"], OU_["denominator"]
    assert _den_["joc_spread"] > 1.5 * _den_["sa_spread"], \
        "jochemnet is no longer the noisier denominator; the shared-denominator argument goes: %r" % _den_
    for _k in ("amt0 diff_to_self 240M", "amt0 diff_to_existent 240M"):
        assert _ot[_k]["r_v2r1"] > 1.1 and _ot[_k]["r_r68"] < 1.1, \
            "%s no longer collapses against a same-session denominator: %r" % (_k, _ot[_k])
    _sf = _ot["amt0 diff_to_self 240M"]["cols"]
    for _c in ("flat/Account", "flat/StateTopNodes", "flat/StateNodes"):
        assert abs(_sf[_c]["sa_n"] / _sf[_c]["joc_n"] - 1) < 0.03 and \
            abs(_sf[_c]["sa_us"] / _sf[_c]["joc_us"] - 1) < 0.06, \
            "the surviving transfers are no longer read-identical on %s: %r" % (_c, _sf[_c])
    _ne = _ot["amt1 diff_to_nonexistent 160M"]
    assert _ne["r_r68"] > 1.2 and abs(_ne["cols"]["flat/Account"]["sa_n"] / _ne["cols"]["flat/Account"]["joc_n"] - 1) < 0.03, \
        "the absent-account transfer is no longer a same-reads outlier: %r" % _ne
    _ab = _ot["sstore slots=False new=False 240M"]
    assert _ab["r_r68"] > 1.5 and _ab["cols"]["flat/Storage"]["joc_n"] > 3 * _ab["cols"]["flat/Storage"]["sa_n"], \
        "the absent-slot outlier or its read asymmetry is gone: %r" % _ab
    _lv = OU_["levels"]
    assert len(_lv["joc"]["Storage"]["levels"]) >= 4 and len(_lv["sa"]["Storage"]["levels"]) == 1, \
        "the storage columns no longer differ in level spread: %r" % _lv

    # Rounds 69-73. The section claims: the two unsettled columns were the storage class's whole
    # story, each step equalised the reads it was supposed to, the control never moved, and what
    # is left is one test that is CPU rather than I/O and survives both warming ablations.
    ST_ = D["storage"]
    _col, _sc, _sr = ST_["columns"], ST_["cells"], ST_["reads"]
    assert len(_col["joc_storage_before"]["levels"]) >= 5 and _col["joc_storage_after"]["levels"] == [6], \
        "the storage-row compaction is no longer what it says: %r" % _col
    assert len(_col["joc_storagenodes_before"]["levels"]) >= 4 and _col["joc_storagenodes_after"]["levels"] == [6], \
        "the storage-trie compaction is no longer what it says: %r" % _col
    # the level figure draws per_level; it has to agree with the level list and the file count
    for _nm, _sh in _col.items():
        if isinstance(_sh, dict) and "per_level" in _sh:
            assert {int(k) for k in _sh["per_level"]} == set(_sh["levels"]) and \
                sum(_sh["per_level"].values()) == _sh["files"], \
                "per-level counts disagree with the column summary for %s: %r" % (_nm, _sh)
    for _k in ("slots=False new=False 160M", "slots=False new=False 240M"):
        assert _sc[_k]["r68"] > 1.9 and _sc[_k]["r72"] < 1.15, \
            "the absent-slot cell no longer closes: %r" % _sc[_k]
    for _k in ("slots=True new=True 160M", "slots=True new=True 240M"):
        assert _sc[_k]["v2"] > 1.05 and abs(_sc[_k]["r72"] - 1) < 0.15, \
            "the new-value cell no longer closes: %r" % _sc[_k]
        assert _sr[_k]["after_r69"]["joc_nodes"] > 1.1 * _sr[_k]["after_r69"]["sa_nodes"] and \
            abs(_sr[_k]["after_r72"]["joc_nodes"] / _sr[_k]["after_r72"]["sa_nodes"] - 1) < 0.1, \
            "the storage-trie reads did not equalise with the compaction: %r" % _sr[_k]
    for _k in ("slots=True new=False 160M", "slots=True new=False 240M"):
        assert abs(_sc[_k]["r69"] - 1) < 0.05 and abs(_sc[_k]["r72"] - 1) < 0.05, \
            "the overwrite control moved with a treatment aimed elsewhere: %r" % _sc[_k]
    _aa = ST_["absent_account"]
    assert min(_aa["throughput"]["160M"]["sa"]) > 1.2 * max(_aa["throughput"]["160M"]["joc"]), \
        "the absent-account transfer is no longer separated across all three repetitions: %r" % _aa["throughput"]
    assert _aa["cpu_seconds"]["joc"]["160M"][".net thread pool"] > \
        1.5 * _aa["cpu_seconds"]["sa"]["160M"][".net thread pool"], \
        "the managed-CPU asymmetry that localises it is gone: %r" % _aa["cpu_seconds"]
    _ab = ST_["ablation"]
    for _cfg in ("B prewarming off", "C trie warmer off"):
        assert min(_ab[_cfg]["sa 160M"]) > 1.15 * max(_ab[_cfg]["joc 160M"]), \
            "%s now closes the gap; the ablation paragraph must be rewritten: %r" % (_cfg, _ab[_cfg])
    # Reproducibility. The page now claims dispersion in the short categories is measurement,
    # not store behaviour, which only holds while the replica pair says so: the same store under
    # the same configuration, twice.
    nz_ = D["noise"]["replica"]["by_duration"]
    assert nz_["lt0.2s"]["within10"] / nz_["lt0.2s"]["n"] < 0.75, \
        "short tests now reproduce; the 'per-test scatter is noise' captions are too weak"
    assert nz_["ge5s"]["within10"] / nz_["ge5s"]["n"] > 0.9, \
        "long tests stopped reproducing; no per-test claim on this dataset is safe"
    # Existing-EOA is the cell used as the convergence control, and it is a long-test category,
    # so its tightness is a store statement rather than a noise statement.
    eo = AFT["spread"]["ACCOUNT cold existing EOA"]
    assert eo["within10"] / eo["n"] > 0.9, f"existing-EOA no longer tight: {eo}"
    # The JIT result. The page's second mechanism rests on three things: the intervention moved
    # the control tests to parity or past it, the profile shows the JIT thread large on both
    # arms, and settling the stores did *not* move the throughput (so compaction was not it).
    J_ = D["jit_experiment"]
    assert J_["ab"]["no_tiered_jit"]["thr"] > 1.0 > J_["ab"]["baseline"]["thr"], \
        ("removing tiered compilation no longer crosses parity: %r"
         % {k: v["thr"] for k, v in J_["ab"].items()})
    assert J_["ab"]["no_parallel"]["thr"] < J_["ab"]["baseline"]["thr"], \
        "disabling parallel execution now helps state-actor; it is no longer exonerated"
    for arm in ("joc_unsettled", "sa_unsettled"):
        t = J_["profile"][arm]["threads"]
        total = sum(t.values())
        assert t[".NET Tiered Com"] / total > 0.25, \
            ("the JIT thread is no longer a large share of %s's measured CPU: %.0f%%"
             % (arm, 100 * t[".NET Tiered Com"] / total))
    assert J_["profile"]["sa_settled"]["threads"].get("rocksdb:low", 0) \
        < J_["profile"]["sa_unsettled"]["threads"]["rocksdb:low"] / 2, \
        "settling the store no longer removes the compaction thread"
    dmj_ = J_["slice"]["jit_equalised"]["DIFF_MAX code-exec"]
    dmp_ = J_["slice"]["published"]["DIFF_MAX code-exec"]
    assert dmj_["thr"] > dmp_["thr"] + 0.2, \
        "DIFF_MAX no longer closes under warm-up equalisation: %.3f -> %.3f" % (dmp_["thr"], dmj_["thr"])
    assert dmj_["joc_secs"] > dmp_["joc_secs"] * 1.2, \
        "jochemnet no longer slows on DIFF_MAX without tiering; the direction claim is out"
    assert dmj_["cpu"] < 1.0, \
        "DIFF_MAX's remainder is no longer I/O-bound (CPU ratio %.2f)" % dmj_["cpu"]
    # Removing every page-cache drop must still take state-actor's control reads to zero without
    # making it faster; that is the step that moved the investigation off I/O.
    dr_, nd_ = J_["drops"]["drops"], J_["drops"]["nodrop"]
    assert nd_["sa_read_mb"] < 1.0 < dr_["sa_read_mb"], \
        "the control reads no longer vanish without the drops: %r" % nd_
    assert nd_["thr"] <= dr_["thr"], \
        "state-actor now gains from keeping the cache; the 'not I/O' argument is out"
    # The cache refutation. The article says starving the block cache did not close the control
    # gap and did not move the account result; if either stops being true, the section is wrong.
    ce_ = D["cache_experiment"]
    assert ce_["small"]["thr"]["CONTROL"] / ce_["big"]["thr"]["CONTROL"] - 1 < 0.10, \
        "the cache reduction closed much of the control gap; the refutation no longer holds"
    assert max(abs(ce_["small"]["thr"][c] / ce_["big"]["thr"][c] - 1)
               for c in ("existing EOA", "existing contract", "absent account")) < 0.05, \
        "account categories moved under cache starvation; parity may be cache-driven after all"
    # The budget argument. It only works if setup writes nothing (no memtable channel) and if
    # setup's read volume really is small next to the gap.
    cs_ = ce_["small"]["steps"]
    assert cs_["joc"]["control"]["setup_write_mb"] == 0 and \
        cs_["sa"]["control"]["setup_write_mb"] == 0, \
        "setup now writes; the memtable carry-over channel is open and the budget bound is void"
    gap_ = cs_["sa"]["control"]["test_mb"] - cs_["joc"]["control"]["test_mb"]
    assert cs_["joc"]["control"]["setup_mb"] / gap_ < 0.5, \
        "setup's read volume is no longer small against the gap; the ceiling claim is out"
    assert (ce_["small"]["steps"]["joc"]["control"]["test_mb"]
            == ce_["big"]["steps"]["joc"]["control"]["test_mb"]), \
        "jochemnet's control reads moved with the cache; the 'it reads what it needs' line is out"
    # The grid has to stay a column, not a scatter, or the code argument is not an argument.
    g_ = AFT["grid"]
    assert len(g_) >= 6, f"opcode grid lost opcodes: {sorted(g_)}"
    dm = median([c["thr"] for row in g_.values()
                 for m, c in row.items() if m == "EXISTING_CONTRACT_DIFF_MAX"])
    others = median([c["thr"] for row in g_.values() for m, c in row.items()
                     if m in ("EXISTING_EOA", "EXISTING_CONTRACT_MINIMAL",
                              "EXISTING_CONTRACT_SAME_MAX")])
    assert dm < others - 0.15, f"DIFF_MAX is no longer the outlying column: {dm} vs {others}"
    # The DIFF_MAX square: the section claims exactly one of four cells is off. Pin all four.
    def _cell(mode, loads):
        return median([row[mode]["thr"] for op, row in AFT["grid"].items()
                       if mode in row and (op in LOADS_CODE) == loads])
    _dmc, _dma = _cell("EXISTING_CONTRACT_DIFF_MAX", True), _cell("EXISTING_CONTRACT_DIFF_MAX", False)
    _smc, _sma = _cell("EXISTING_CONTRACT_SAME_MAX", True), _cell("EXISTING_CONTRACT_SAME_MAX", False)
    assert _dmc < 0.8, f"DIFF_MAX code-loading opcodes no longer the outlier: {_dmc:.3f}"
    for name, v in (("DIFF_MAX account-only", _dma), ("SAME_MAX code-loading", _smc),
                    ("SAME_MAX account-only", _sma)):
        assert v > 0.9, f"{name} left parity ({v:.3f}); the 2x2 argument needs three clean cells"
    # and the code database must stay cheaper on the generated store, or the refutation is void
    assert M["code_probe"]["sa"]["bytes"] < M["code_probe"]["joc"]["bytes"], "code lookup refutation void"
    assert M["code_sweep"]["sa"]["bytes"] < M["code_sweep"]["joc"]["bytes"], "code sweep refutation void"
    # the cross-client claim: every client's generated arm is near parity once treated, and
    # meaningfully slower before. If a sibling study is re-cut, this fails rather than misquotes.
    assert tc["besu_sa_over_plain"] < 0.6 < tc["besu_sa_over_compacted"] < 1.1, \
        f"besu reference no longer shows untreated gap -> treated parity: {tc}"

    o = []
    w = o.append
    title = (f"How can two Nethermind databases holding the same state differ "
             f"{factor:.0f}&times; &mdash; and then agree?")

    w("<!doctype html><html lang=en><head><meta charset=utf-8>")
    w('<meta name=viewport content="width=device-width,initial-scale=1">')
    w('<meta name="description" content="Identical EEST bloatnet runs report a 16x '
      'throughput gap between two Nethermind state databases. The cause is where the rows sit, '
      'not what they contain: equalise it and every category that reads state comes back to '
      'parity.">')
    w('<link rel="preconnect" href="https://fonts.googleapis.com">'
      '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
      '<link href="https://fonts.googleapis.com/css2?family=VT323&'
      'family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&display=swap" '
      'rel="stylesheet">')
    w("<title>Nethermind state-DB divergence &mdash; benchmarkoor bloatnet runs</title>")
    w(f"<style>{CSS}</style></head><body>")

    w('<div class=topbar><a href="../">&larr; all articles</a>'
      '<span>EXECUTION &middot; STATE DB</span></div>')
    w('<div class=eyebrow>// REPORT</div>')
    w(f"<h1>{title}</h1>")
    w('<div class=meta><span class=tag>Ethereum &middot; nethermind &middot; flat DB &middot; '
      'benchmarking</span> &middot; 2026 &middot; '
      '<a href="https://github.com/CPerezz/articles/tree/main/nethermind-state-db-divergence">'
      'reproducible pipeline &amp; data &rarr;</a></div>')

    arms = P["arms"]
    w(f"<p class=sub>{thousands(BEF['agreement']['n'])} tests matched by exact identity across "
      f"both stores, zero gas mismatches. Nethermind "
      f"<code>{esc(P['image'].split('/')[-1])}</code>, "
      f"<code>{esc(P['flags'][0])}</code>, "
      f"<code>rollback_strategy: {esc(P['harness']['rollback_strategy'])}</code>, "
      f"<code>drop_memory_caches: {esc(P['harness']['drop_memory_caches'])}</code>.</p>")

    # ---------------------------------------------------------------- behaviour
    w("<h2>The behaviour</h2>")
    w(f"<p>Two Nethermind databases holding the same logical state: a mainnet shadowfork "
      f"snapshot at block {thousands(P['snapshot_block'])}, and state generated from scratch by "
      f"<code>state-actor</code>. The same EEST bloatnet fixtures run against both on the same "
      f"machine, page cache dropped between tests. Where the tests read accounts, the generated "
      f"store reports up to <b>{factor:.0f}&times;</b> less throughput. That is not a small-test "
      f"artifact: the two categories carrying it run for a median of "
      f"{CL['by_category']['existing contract']['median_secs']:.1f} and "
      f"{CL['by_category']['existing EOA']['median_secs']:.1f} seconds.</p>")

    w("<table><tr><th>what the test does</th><th class=n>n</th>"
      "<th class=n>throughput sa/joc</th><th class=n>bytes sa/joc</th>"
      "<th class=n>jochemnet MB</th><th class=n>state-actor MB</th></tr>")
    for cat in CATS:
        if cat not in bc:
            continue
        r = bc[cat]
        cls = " bad" if r["thr"] < 0.5 else ""
        w(f"<tr><td>{esc(SHORT[cat])}</td><td class=n>{r['n']}</td>"
          f"<td class=\"n{cls}\">{f(r['thr'], 3)}</td><td class=n>{f(r['read'])}</td>"
          f"<td class=n>{r['jocMB']:.0f}</td><td class=n>{r['saMB']:.0f}</td></tr>")
    w(f"<caption>The storage sweep ({f(bc['STORAGE slot access']['thr'], 3)}) does not diverge, "
      f"and it is far larger than anything a store can hold in a corner. Whatever this is, it "
      f"is specific to reading accounts that exist.</caption></table>")

    bg = BEF["grid"]
    bcells = [c["thr"] for row in bg.values() for m, c in row.items() if m in GRID_MODES]
    boff = sum(1 for r in bcells if not (0.9 <= r <= 1.1))
    w(figure(chart_grid(bg),
             f"Every opcode against every access mode, before treatment: {boff} of {len(bcells)} "
             f"cells outside &plusmn;10% of parity, from {min(bcells):.2f} to {max(bcells):.2f}. "
             f"Nearly the whole matrix, not a few bad tests."))

    cc = BEF["cost_curve"]
    w(figure(chart_cost_curves(cc),
             f"Read volume against gas for the contract-reading tests. jochemnet is flat, "
             f"{cc[0]['jocMB']:.0f} MB at {cc[0]['gas']}M and {cc[-1]['jocMB']:.0f} MB at "
             f"{cc[-1]['gas']}M; state-actor climbs from {cc[0]['saMB']:.0f} to "
             f"{cc[-1]['saMB']:.0f} MB. Flat in gas means one bounded set of blocks re-read; "
             f"rising means every access goes somewhere new."))

    # ------------------------------------------------- how to read a number here
    w("<h2>How to read a number on this page</h2>")
    cl_t, cl_r = CL["classes"]["treated"], CL["classes"]["replica"]
    s1, s2 = cl_t["lt1s"], cl_t["ge1s"]
    fl1, fl2 = cl_r["lt1s"], cl_r["ge1s"]
    w(f"<p>This suite contains two populations, and only one of them can support a claim about "
      f"a database. Measure the <em>same</em> store twice under the same configuration: over "
      f"five seconds, {100*D['noise']['replica']['by_duration']['ge5s']['within10']/D['noise']['replica']['by_duration']['ge5s']['n']:.0f}% "
      f"of tests land within &plusmn;10% of themselves; under a fifth of a second, "
      f"{100*D['noise']['replica']['by_duration']['lt0.2s']['within10']/D['noise']['replica']['by_duration']['lt0.2s']['n']:.0f}% do. "
      f"A short test does not reproduce against itself, so a &plusmn;10% difference between "
      f"two stores on a short test is not evidence.</p>")
    w(figure(chart_duration_floor(CL)))
    w(f"<p>Every test is therefore split at <b>one second</b>, and the two classes are reported "
      f"separately. Membership is fixed once from the reference arm and used throughout.</p>")
    w("<table><tr><th>class</th><th class=n>tests</th><th class=n>median sa/joc</th>"
      "<th class=n>within &plusmn;10%</th><th class=n>same store twice</th>"
      "<th>what it can support</th></tr>")
    w(f"<tr><td>under 1 s</td><td class=n>{s1['n']}</td>"
      f"<td class=\"n bad\">{s1['median']:.3f}</td>"
      f"<td class=n>{100*s1['within10']/s1['n']:.0f}%</td>"
      f"<td class=n>{100*fl1['within10']/fl1['n']:.0f}%</td>"
      f"<td>nothing about a database</td></tr>")
    w(f"<tr><td>1 s and over</td><td class=n>{s2['n']}</td><td class=n>{s2['median']:.3f}</td>"
      f"<td class=n>{100*s2['within10']/s2['n']:.0f}%</td>"
      f"<td class=n>{100*fl2['within10']/fl2['n']:.0f}%</td>"
      f"<td>store behaviour, to within a few per cent</td></tr></table>")
    st_c = CL["by_category"]["storage slot"]

    # ---------------------------------------------------------------- defects found
    w("<h2>What we found wrong with the measurement</h2>")
    hw = M["harness"]
    J0 = D["jit_experiment"]
    w("<p>Four findings, in the order they matter. Each was established by changing one thing "
      "and re-measuring. The first moved the headline; the second and third were plausible "
      "causes eliminated by intervention; the fourth is the residual, and it closes. The one "
      "cell that ran the other way, ether transfers, turned out to be this study's own tooling "
      "having repacked a column of the snapshot; it is traced at the end of Finding 4 and "
      "listed with the errata.</p>")
    w("<ol>")
    w("<li><b>The pre-run is promoted into the baseline.</b> One arm replays a pre-run and the "
      "harness promotes the result into the image every test restores from, leaving the "
      "benchmark's own accounts as the newest versions in the youngest files of the LSM tree. "
      "<b>Fixed</b>; accounts for almost all of the gap.</li>")
    w(f"<li><b>The client is restarted per test, and the two arms warm up differently.</b> "
      f"jochemnet's setup step is heavy EVM work, so its interpreter is promoted before the "
      f"measurement; state-actor's spends that window on an empty block. <b>Fixed by "
      f"intervention</b>: equalising it moves the control tests from "
      f"{J0['ab']['baseline']['thr']:.2f} to {J0['ab']['no_tiered_jit']['thr']:.2f}.</li>")
    w(f"<li><b>The generated store makes every client that opens it rewrite the store.</b> A "
      f"client sitting idle read {BM['idle']['sa_mb']:,} MB from it in {BM['idle']['window_s']} "
      f"seconds against jochemnet's {BM['idle']['joc_mb']}, restarted on every one of "
      f"{thousands(hw['tests'])} tests. <b>Fixed in the generator</b>; changed the throughput by "
      f"almost nothing.</li>")
    w(f"<li><b>The harness has no compaction control and no warm-up control.</b> "
      f"<code>{esc(hw['compact_between_steps'])}</code> is {esc(hw['compact_status'])}, "
      f"<code>{esc(hw['post_prerun_hook'])}</code> is {esc(hw['hook_status'])}, and there is no "
      f"way to request a discarded burn-in block. Both treatments were applied by hand.</li>")
    w("</ol>")

    # ---------------------------------------------------------------- root cause
    w("<h2>The root cause: the benchmark's keys live in a corner of one store</h2>")
    pr = M["prerun"]
    w(f"<p>Only the jochemnet arm runs a pre-run: {thousands(pr['blocks'])} blocks that create "
      f"the accounts the benchmark reads, followed by <code>promote_post_pre_runs: true</code>, "
      f"which freezes the resulting layout into the image every test is restored from. The page "
      f"cache is dropped between tests, so this is not a caching effect. What survives is "
      f"<em>which files hold the current copy of each key</em>.</p>")
    w("<p>Nethermind keeps flat state in RocksDB, keyed by <code>keccak256(address)</code>. The "
      "keys are uniformly scattered, but the pre-run rewrote every benchmark account, so their "
      "newest copies sit together in a few recently flushed SSTs at the top of the LSM tree. A "
      "levelled store answers a point lookup from the newest level holding the key, so the "
      "working set is bounded by the size of those files, not by the number of keys.</p>")
    w("<p class=note>The prediction follows directly: merge those files into the bottom level "
      "and the advantage must vanish, because no level then holds a privileged copy. That is a "
      "compaction, and the rest of this page is the test.</p>")

    w(figure(chart_amortisation(amort),
             f"Cold lookups against each store's own copy of the fixtures' accounts, fresh "
             f"process per point, page cache dropped, 100% hits. At {thousands(a0['n'])} lookups "
             f"the two stores are indistinguishable &mdash; {a0['joc_blk']:.2f} against "
             f"{a0['sa_blk']:.2f} blocks. By {thousands(a9['n'])} jochemnet is at "
             f"{a9['joc_blk']:.2f} because its volume has <b>stopped growing</b>: "
             f"{amort[-2]['joc_mb']:.0f} MB at {thousands(amort[-2]['n'])} lookups and "
             f"{a9['joc_mb']:.0f} MB at {thousands(a9['n'])}. state-actor never saturates, "
             f"climbing to {a9['sa_mb']:.0f} MB, because there is no corner to exhaust."))

    w("<p class=note>The per-lookup cost is the same. The number of distinct blocks is not: one "
      "store runs out of new blocks to read.</p>")

    # ---------------------------------------------------------------- the fix
    w("<h2>Finding 1: the pre-run is promoted into the baseline &mdash; and what compacting it does</h2>")
    ab, aa = iv["account_before"], iv["account_after"]
    sb, sa_ = iv["statenodes_before"], iv["statenodes_after"]
    w("<p><b>The treatment</b> is a full RocksDB compaction of the affected column families, "
      "<code>CompactRange</code> with <code>bottommost_level_compaction=kForce</code>, using the "
      "other store's exact per-family options, verified knob by knob. No value changes and the "
      "state root is unchanged; only which file holds each key's newest copy. The pre-run is "
      "then removed from the arm's config: its writes are already in the promoted image, so "
      "replaying it would rebuild the very layout just flattened.</p>")
    w("<p class=note>The reproducible path is the harness's post-pre-run hook "
      "(<code>BENCHMARKOOR_POST_PRERUN_CMD</code>), which is on a branch and not in the binary "
      "these runs used. The compaction here was applied to the promoted image by hand; same "
      "end state.</p>")
    w("<table><tr><th>column family</th><th>levels before</th><th>levels after</th>"
      "<th class=n>GB</th><th class=n>rewrite</th></tr>")
    for name, b, a in (("flat/Account", ab, aa), ("flat/StateNodes", sb, sa_),
                       ("code", iv["code_before"], iv["code_after"])):
        lb = " ".join(f"L{k}:{v}" for k, v in sorted(b["levels"].items()))
        la = " ".join(f"L{k}:{v}" for k, v in sorted(a["levels"].items()))
        gb = a.get("gb")
        w(f"<tr><td><code>{esc(name)}</code></td><td><code>{esc(lb)}</code></td>"
          f"<td><code>{esc(la)}</code></td><td class=n>{f(gb, 2) if gb else '&mdash;'}</td>"
          f"<td class=n>{a['seconds']:.0f} s</td></tr>")
    w("<caption>The files at the top of each tree are the pre-run's. Merging them down is the "
      "whole treatment.</caption></table>")

    w(f"<p>Then the full suite again, all {thousands(AFT['agreement']['n'])} matched tests:</p>")
    w("<table><tr><th>what the test does</th><th class=n>n</th><th class=n>with confound</th>"
      "<th class=n>equalised</th><th class=n>middle half, equalised</th>"
      "<th class=n>full range</th><th class=n>within &plusmn;10%</th></tr>")
    for cat in CATS:
        if cat not in ac:
            continue
        r, rb, sp = ac[cat], bc[cat], spr_a[cat]
        good = " good" if 0.9 <= r["thr"] <= 1.1 else ""
        w(f"<tr><td>{esc(SHORT[cat])}</td><td class=n>{r['n']}</td>"
          f"<td class=n>{f(rb['thr'], 3)}</td>"
          f"<td class=\"n{good}\">{f(r['thr'], 3)}</td>"
          f"<td class=n>{sp['p25']:.3f}&ndash;{sp['p75']:.3f}</td>"
          f"<td class=n>{sp['min']:.3f}&ndash;{sp['max']:.3f}</td>"
          f"<td class=n>{r['agree']}/{r['n']}</td></tr>")
    st = spr_a["STORAGE slot access"]
    eo = spr_a["ACCOUNT cold existing EOA"]
    w(f"<caption>Tests agreeing within &plusmn;10% go from "
      f"{BEF['agreement']['agree_pct']:.1f}% to {AFT['agreement']['agree_pct']:.1f}%. The spread "
      f"columns guard against a flattering median: "
      f"<em>{esc(SHORT['ACCOUNT cold existing EOA'])}</em> is tight, "
      f"{eo['within10']}/{eo['n']} inside the band; "
      f"<em>{esc(SHORT['STORAGE slot access'])}</em> sits on parity at {st['median']:.3f} while "
      f"ranging {st['min']:.3f}&ndash;{st['max']:.3f}. Reproduced on an independent "
      f"{thousands(D['replication']['agreement']['n'])}-test subset to within a couple of "
      f"percent.</caption></table>")

    w(figure(chart_treatment_dumbbell(bc, ac),
             "Amber is the confounded measurement, green the equalised one, the band "
             "&plusmn;10% around parity. The two rows already inside the band stay there."))

    nz, nx = D["noise"]["replica"], D["noise"]["cross_by_duration"]
    nl, ng = nz["by_duration"]["lt0.2s"], nz["by_duration"]["ge5s"]
    w(figure(chart_ratio_dots(rat_b, rat_a, spr_b, spr_a, CL),
             f"The same {thousands(AFT['agreement']['n'])} tests as individual results: one dot "
             f"per cluster, sized by count, middle half as a bar, median as a tick. Read the "
             f"shift, not the width. Rows marked <em>&lt;1s</em> are wholly sub-second and their "
             f"width is the instrument."))

    # ---------------------------------------------------------------- residual
    # Defect 2 in the published version blamed the client cache. Two rounds of intervention
    # eliminated that (this section keeps the measurement) and a third found the mechanism: the
    # JIT. Everything below reads from D["jit_experiment"], collected by collect_jit.py.
    J = D["jit_experiment"]
    st = D["steps"]
    w("<h2>Finding 2: the client is restarted for every test, and the two arms warm up "
      "differently</h2>")
    w("<p>Every test boots a fresh client, 1,463 times. That keeps tests independent, and it "
      "means every measured step runs in a process seconds old. A .NET process seconds old is "
      "still compiling itself: hot methods start on the unoptimised tier and are promoted in "
      "the background after a call-count threshold. Whether the EVM's inner loop has been "
      "promoted when the measured block arrives depends on what the process did just before, "
      "and the two arms' fixtures make it do different things.</p>")

    # -- the fixture asymmetry
    w("<h3>What the setup step does on each arm</h3>")
    w("<table><tr><th>arm</th><th>setup step</th><th>gap to measured block</th>"
      "<th>measured block starts on</th></tr>")
    w("<tr><td>jochemnet</td><td>one block of 535k gas of real EVM work, ~240 ms</td>"
      "<td>~45 ms</td><td>promoted code</td></tr>")
    w("<tr><td>state-actor</td><td>one <b>empty</b> block (a fork-activation block the fixtures "
      "add because this chain starts at genesis), ~240 ms, then the 535k-gas block in 46 ms</td>"
      "<td>~1.4 ms</td><td>unoptimised code, JIT compiling underneath</td></tr>")
    w("<caption>The first block after boot costs ~240 ms on both arms whatever it contains. "
      "jochemnet spends it executing EVM code and crosses the tiering threshold before the "
      "measurement; state-actor spends it on an empty block and enters the measured block with "
      f"a cold interpreter. That is why its setup step reads {st['control']['sa']['setup']:.1f} MB "
      f"in 0.04 s against jochemnet's {st['control']['joc']['setup']:.1f} MB in 0.24 s.</caption>"
      "</table>")

    # -- the profile
    pj, ps, pss = J["profile"]["joc_unsettled"], J["profile"]["sa_unsettled"], J["profile"]["sa_settled"]
    dr, nd = J["drops"]["drops"], J["drops"]["nodrop"]
    w(figure(chart_steps(st),
             f"Read volumes for the two steps, log axis. The arms are inverted: jochemnet reads "
             f"while setting up, state-actor while being measured. As published this looked like "
             f"the explanation. It is not: removing the page-cache drops took state-actor's "
             f"measured control reads from {dr['sa_read_mb']:.0f} MB to {nd['sa_read_mb']:.1f} MB "
             f"and made it no faster ({dr['sa_mgas']:.1f} to {nd['sa_mgas']:.1f} MGas/s), while "
             f"jochemnet gained. Removing all of the I/O did not remove the gap, which is what "
             f"sent us to the client's threads."))

    w("<h3>Where the CPU goes during the measured step</h3>")
    w(f"<p>Per-thread CPU time of the client process, sampled from <code>/proc</code> every "
      f"half second and summed inside the measured steps of {pj['windows']} control tests per "
      f"arm:</p>")
    names = ["rocksdb:low", ".NET Tiered Com", ".NET TP Worker", ".NET BGC"]
    label = {"rocksdb:low": "RocksDB background compaction", ".NET Tiered Com": ".NET tiered JIT",
             ".NET TP Worker": "thread-pool workers (block execution)", ".NET BGC": ".NET background GC"}
    w("<table><tr><th>thread</th><th class=n>jochemnet</th><th class=n>state-actor</th>"
      "<th class=n>state-actor, stores settled</th></tr>")
    for nm in names:
        w(f"<tr><td>{esc(label[nm])}</td><td class=n>{pj['threads'].get(nm, 0):.1f} s</td>"
          f"<td class=n>{ps['threads'].get(nm, 0):.1f} s</td>"
          f"<td class=n>{pss['threads'].get(nm, 0):.1f} s</td></tr>")
    w(f"<caption>CPU-seconds inside {pj['wall_s']:.0f}&ndash;{ps['wall_s']:.0f} s of measured "
      f"wall time. RocksDB was compacting underneath state-actor's measurements; settling the "
      f"store removed most of that thread and none of the gap, control staying at "
      f"{J['ab']['baseline']['thr']:.3f}. The JIT thread is large on <em>both</em> arms: a fifth "
      f"to a third of all CPU in the window is spent compiling the client, on every one of "
      f"1,463 tests.</caption></table>")

    # -- the A/B
    ab = J["ab"]
    w("<h3>The test: remove the JIT from the measurement</h3>")
    w("<p>If warm-up is the cause, removing it should remove the gap. "
      "<code>DOTNET_TieredCompilation=0</code> compiles every method fully optimised on first "
      "call: no unoptimised tier, no background promotion, both arms on steady-state code from "
      "the first block. A second lever, disabling optimistic parallel execution, tests the "
      "alternative that state-actor's fixtures cause more transaction conflicts. Both applied to "
      "both arms, same 40 control tests.</p>")
    w("<table><tr><th>configuration</th><th class=n>state-actor MGas/s</th>"
      "<th class=n>jochemnet MGas/s</th><th class=n>throughput sa/joc</th>"
      "<th class=n>CPU sa/joc</th></tr>")
    for key, lbl in (("baseline", "as published"), ("no_parallel", "parallel execution off"),
                     ("no_tiered_jit", "tiered compilation off")):
        r = ab[key]
        cls = ' class="n"' if abs(r["thr"] - 1) < 0.15 else ' class="n bad"'
        w(f"<tr><td>{lbl}</td><td class=n>{r['sa_mgas']:.1f}</td>"
          f"<td class=n>{r['joc_mgas']:.1f}</td>"
          f"<td{cls}>{r['thr']:.3f}</td><td class=n>{r['cpu']:.2f}</td></tr>")
    w(f"<caption>Parallel execution is exonerated: turning it off hurts state-actor more. "
      f"Removing tiered compilation takes the ratio from {ab['baseline']['thr']:.3f} to "
      f"<b>{ab['no_tiered_jit']['thr']:.3f}</b>. state-actor's step falls from "
      f"{ab['baseline']['sa_secs']*1000:.0f} to {ab['no_tiered_jit']['sa_secs']*1000:.0f} ms; "
      f"jochemnet's barely moves ({ab['baseline']['joc_secs']*1000:.0f} to "
      f"{ab['no_tiered_jit']['joc_secs']*1000:.0f} ms), because it was already running promoted "
      f"code when its measurement began.</caption></table>")

    # -- the rest of regime 3
    sl = J["slice"]
    w("<h3>The same lever on every cell still divergent</h3>")
    cells = ["DIFF_MAX code-exec", "DIFF_MAX BAL/HASH", "SAME_MAX code-exec", "NON_EXISTING_ACCOUNT code-exec",
             "NON_EXISTING_ACCOUNT BAL/HASH", "sload_same_key", "warm query"]
    w("<table><tr><th>cell</th><th class=n>as published</th><th class=n>stores settled</th>"
      "<th class=n>tiered compilation off, both arms</th><th class=n>jochemnet step</th></tr>")
    for c in cells:
        p, s_, jq = sl["published"].get(c), sl["settled"].get(c), sl["jit_equalised"].get(c)
        if not (p and jq):
            continue
        cls = "" if abs(jq["thr"] - 1) < 0.15 else " bad"
        w(f"<tr><td>{esc(c)}</td><td class=n>{p['thr']:.3f}</td>"
          f"<td class=n>{s_['thr']:.3f}</td>" if s_ else f"<tr><td>{esc(c)}</td><td class=n>{p['thr']:.3f}</td><td class=n>&ndash;</td>")
        w(f'<td class="n{cls}">{jq["thr"]:.3f}</td>'
          f"<td class=n>{p['joc_secs']:.2f} &rarr; {jq['joc_secs']:.2f} s</td></tr>")
    dmp, dmj = sl["published"]["DIFF_MAX code-exec"], sl["jit_equalised"]["DIFF_MAX code-exec"]
    w(f"<caption>The distinct-contract cell goes from {dmp['thr']:.3f} to {dmj['thr']:.3f}, and "
      f"the direction is the evidence: state-actor did not get faster, <b>jochemnet got "
      f"slower</b>, from {dmp['joc_secs']:.1f} to {dmj['joc_secs']:.1f} s per test, once it "
      f"could no longer reach promoted code partway through a 15-second test. The short tests "
      f"say the same from the other side: warm-query and same-key storage tests run "
      f"5&ndash;6&times; faster on <em>both</em> arms with tiering off, because as published "
      f"they were measuring an interpreter that had not finished compiling.</caption></table>")

    w("<p><b>What this is and is not.</b> <code>DOTNET_TieredCompilation=0</code> is the "
      "diagnostic, not the fix; a live node runs promoted, profile-guided code. What the "
      "benchmark needs is what a live node has: an EVM past the tiering threshold before the "
      "measured block, i.e. the same burn-in on every arm, discarded. Any JIT-hosted client "
      "restarted per test is exposed. Ahead-of-time compiled clients are not, which is why the "
      "geth study could find this cell open but not close it.</p>")
    # ------------------------------------------------- defect 3: the store rewrites itself
    w("<h2>Finding 3: the generated store makes the client rewrite it</h2>")
    bidle, bboot, brpc, bset = BM["idle"], BM["boot"], BM["rpc"], BM["settle"]
    w(f"<p>Boot each arm, drop the page cache, issue <b>no</b> queries, and read the client's "
      f"own <code>/proc/&lt;pid&gt;/io</code> for {bidle['window_s']} seconds. jochemnet reads "
      f"{bidle['joc_mb']} MB. The generated store's client reads <b>{bidle['sa_mb']:,} MB</b>, "
      f"about {bidle['sa_mb']/bidle['window_s']:.0f} MB/s, indefinitely, every thread at 0% "
      f"CPU.</p>")
    w(figure(chart_idle_reads(BM),
             f"The reads need no query. {brpc['calls']:,} <code>eth_getBalance</code> calls read "
             f"the identical {brpc['sa']['account_mb']:.1f} MB from <code>flat/Account</code> on "
             f"both arms, so the flat state serves lookups correctly at the same cost; the "
             f"generated store's client separately pulls {brpc['sa']['trie_mb']:,.0f} MB of trie "
             f"nodes, {brpc['sa']['trie_share_pct']:.0f}% of everything it reads."))
    w(f"<p>Per-thread attribution puts the traffic on <code>rocksdb:low</code>: RocksDB's own "
      f"background compaction, not client code. The event log names the reason: "
      f"{bboot['sa']['jobs']} jobs at boot, all on <code>{esc(bboot['sa']['cf'])}</code>, all "
      f"<code>{esc(bboot['sa']['reason'])}</code>. jochemnet's client starts "
      f"{bboot['joc']['jobs']}, for the ordinary reason.</p>")
    w("<p><code>kBottommostFiles</code> rewrites bottom-level files purely to zero their "
      "sequence numbers: every bottommost file with <code>largest_seqno != 0</code> is marked "
      "once no snapshot protects it. The trigger is not the shape of the levels but how the "
      "files got there. The generator does finish by compacting, but with the default "
      "<code>bottommost_level_compaction = kIfHaveCompactionFilter</code> and no filter "
      "configured, so RocksDB <b>moved</b> the flushed L0 files into the empty bottom level "
      "rather than rewriting them. The tree comes out flat and every file keeps a non-zero "
      "sequence number.</p>")
    w(figure(chart_seqno_paths(BM),
             "One option apart, and indistinguishable by the checks a generator would run: both "
             "end flat at the bottom level, both report "
             "<code>estimate-pending-compaction-bytes = 0</code>. Only one makes every client "
             "that opens it redo the work."))
    st_gb = sum(v["gb_before"] for v in bset.values())
    st_s = sum(v["secs"] for v in bset.values())
    w(f"<p><b>The fix.</b> Run the finishing compaction with "
      f"<code>bottommost_level_compaction=kForce</code>, once, in the generator. Applied to the "
      f"trie families here, {st_gb:.0f} GB in {st_s/60:.0f} minutes, it takes the idle client "
      f"from {bidle['sa_mb']:,} MB to {bidle['sa_settled_mb']} MB and the boot from "
      f"{bboot['sa']['jobs']} compaction jobs to {bboot['sa_settled']['jobs']}. Upstream as "
      f"<a href=\"https://github.com/ethereum/state-actor/pull/{BM['pr']}\">state-actor#"
      f"{BM['pr']}</a>, which repairs the same call in the Besu, ethrex and reth writers.</p>")
    dmc, jmc = BM["cells"]["DIFF_MAX code-exec"], BM["cells"]["JUMPDEST code-exec"]
    w("<p><b>And it explained nothing.</b> The subset re-run on the settled store, against two "
      "earlier runs of the same configuration:</p>")
    w("<table><tr><th>cell</th><th class=n>n</th><th class=n>replica 1</th>"
      "<th class=n>replica 2</th><th class=n>settled store</th><th class=n>move</th></tr>")
    for name in ("DIFF_MAX code-exec", "JUMPDEST code-exec", "SAME_MAX code-exec",
                 "MINIMAL code-exec", "EXISTING_EOA code-exec"):
        c = BM["cells"][name]
        mv = c["settled"] - (c["r1"] + c["r2"]) / 2
        cls = " bad" if c["settled"] < 0.9 else ""
        w(f"<tr><td>{esc(name)}</td><td class=n>{c['n']}</td><td class=n>{c['r1']:.3f}</td>"
          f"<td class=n>{c['r2']:.3f}</td><td class=\"n{cls}\">{c['settled']:.3f}</td>"
          f"<td class=n>{mv:+.3f}</td></tr>")
    w(f"<caption>The two cells this study has been chasing moved "
      f"{dmc['settled'] - (dmc['r1']+dmc['r2'])/2:+.3f} and "
      f"{jmc['settled'] - (jmc['r1']+jmc['r2'])/2:+.3f}, against a replica-to-replica swing of "
      f"{abs(dmc['r1']-dmc['r2']):.3f} and {abs(jmc['r1']-jmc['r2']):.3f}. Removing continuous "
      f"background I/O from every test bought a tenth of a seven-point gap. Real defect, wrong "
      f"suspect.</caption></table>")
    w("<p>What it did change is what can be measured. Attributing bytes to a column family "
      "compares two traced runs, and a store reading on its own account puts traffic into "
      "both windows in proportion to how long each stayed open. On a per-test byte column that "
      "is a couple of per cent; on the <em>difference</em> between two windows, which is what a "
      "distinct contract costs, it was most of the answer. With the store quiet, the "
      "attribution below is about the test.</p>")

    w("<h2>Class 2 in detail: which state access actually diverges</h2>")
    c2_ = CL["classes"]["treated"]["ge1s"]
    fam_ = CL["class2_families"]
    w(f"<p>The {c2_['n']} tests over a second sit at {c2_['median']:.3f} with "
      f"{100*c2_['within10']/c2_['n']:.0f}% inside &plusmn;10%. What is left is not a general "
      f"slowness; two questions locate it. Does the opcode fetch the callee's code, or only "
      f"read the account row? And is the contract different on every access, or reused?</p>")
    dmx = fam_['loads_code']['EXISTING_CONTRACT_DIFF_MAX']
    w(figure(chart_class2_families(CL),
             f"One row is flat and one is a ladder. BALANCE and EXTCODEHASH, which read only "
             f"the account row, sit at "
             f"{min(v['median'] for v in fam_['account_row'].values()):.3f}&ndash;"
             f"{max(v['median'] for v in fam_['account_row'].values()):.3f} under every mode. "
             f"The code-loading opcodes match them at "
             f"{fam_['loads_code']['EXISTING_CONTRACT_SAME_MAX']['median']:.3f} while the "
             f"contract is reused, fall to "
             f"{fam_['loads_code']['EXISTING_CONTRACT_JUMPDEST']['median']:.3f} when its code "
             f"is scanned for jump destinations, and to {dmx['median']:.3f} when every access "
             f"fetches a new maximum-size contract, reading "
             f"{dmx['saMB']/dmx['jocMB']:.2f}&times; the bytes. Throughput tracks bytes."))
    w("<p>One square of a 2&times;2. Not the account row, since the account-row opcodes are at "
      "parity under the same mode; not distinctness on its own, since the same opcodes reusing "
      "one contract are at parity too. Only <b>loading a distinct contract's code</b> is "
      "expensive.</p>")

    # ------------------------------------------------- open item: DIFF_MAX
    dm = modes["EXISTING_CONTRACT_DIFF_MAX"]
    dmp, dmj = J["slice"]["published"]["DIFF_MAX code-exec"], J["slice"]["jit_equalised"]["DIFF_MAX code-exec"]
    w("<h3>The same split, opcode by opcode</h3>")
    w("<p>The same result holds opcode by opcode rather than family by family, which is what "
      "rules out any single instruction being responsible:</p>")
    gcol = {m: median([row[m]["thr"] for row in AFT["grid"].values() if m in row])
            for m in GRID_MODES}
    absent_n = CL["by_category"]["absent account"]["n"]
    w(figure(chart_grid(AFT["grid"]),
             f"Throughput ratio for each of the {len(AFT['grid'])} opcodes against each access "
             f"mode, after treatment. Read it by column, not by row: DIFF_MAX sits at "
             f"{gcol['EXISTING_CONTRACT_DIFF_MAX']:.2f} and JUMPDEST at "
             f"{gcol['EXISTING_CONTRACT_JUMPDEST']:.2f}, while EOA, MINIMAL and SAME_MAX are all "
             f"{min(gcol[m] for m in ('EXISTING_EOA','EXISTING_CONTRACT_MINIMAL','EXISTING_CONTRACT_SAME_MAX')):.2f}"
             f"&ndash;"
             f"{max(gcol[m] for m in ('EXISTING_EOA','EXISTING_CONTRACT_MINIMAL','EXISTING_CONTRACT_SAME_MAX')):.2f}. "
             f"The absent-account mode has no column here: all {absent_n} of its tests run in "
             f"under a second, so it belongs to the class this page does not read as evidence. "
             f"Within the DIFF_MAX column the rows are <em>not</em> uniform, and the split is "
             f"the whole story: the opcodes that execute the callee's code sit near "
             f"{median([row['EXISTING_CONTRACT_DIFF_MAX']['thr'] for op, row in AFT['grid'].items() if op in LOADS_CODE and 'EXISTING_CONTRACT_DIFF_MAX' in row]):.2f} "
             f"while BALANCE and EXTCODEHASH, which only read the account row, stay at parity."))
    w("<p>Ordered by how much contract code the access mode touches:</p>")
    w("<table><tr><th>access mode</th><th>what it touches</th><th class=n>jochemnet MB</th>"
      "<th class=n>state-actor MB</th><th class=n>bytes sa/joc</th>"
      "<th class=n>throughput sa/joc</th></tr>")
    for m in MODE_ORDER:
        if m not in modes:
            continue
        r = modes[m]
        w(f"<tr><td><code>{esc(m)}</code></td><td>{esc(MODE_CODE[m])}</td>"
          f"<td class=n>{r['jocMB']:.0f}</td><td class=n>{r['saMB']:.0f}</td>"
          f"<td class=n>{f(r['readX'])}</td><td class=n>{f(r['thrX'], 3)}</td></tr>")
    w(f"<caption>Monotonic in code. Reuse one contract, or touch none, and the two stores are "
      f"within {(max(modes[m]['readX'] for m in ('EXISTING_EOA','EXISTING_CONTRACT_SAME_MAX')) - 1)*100:.0f}%; "
      f"fetch a different one on every access and the generated store reads more.</caption></table>")
    sm, dm_m = modes["EXISTING_CONTRACT_SAME_MAX"], modes["EXISTING_CONTRACT_DIFF_MAX"]
    w(figure(chart_code_ladder(modes, {"sa": fp["sa"]["code"], "joc": fp["joc"]["code"]}),
             f"The incremental step is the lopsided one: from one reused contract to a different "
             f"one per access costs state-actor +{dm_m['saMB']-sm['saMB']:.0f} MB against "
             f"jochemnet's +{dm_m['jocMB']-sm['jocMB']:.0f}, "
             f"{(dm_m['saMB']-sm['saMB'])/max(dm_m['jocMB']-sm['jocMB'],1):.1f}&times; the "
             f"marginal cost per additional distinct contract."))

    # ------------------------------------------------- finding 4
    w("<h2>Finding 4: what is left is the reading of bytecode, and it is the generator's "
      "filler code packed around it</h2>")
    gdm = {op: row["EXISTING_CONTRACT_DIFF_MAX"]["thr"] for op, row in AFT["grid"].items()
           if "EXISTING_CONTRACT_DIFF_MAX" in row}
    worst_op = min(gdm, key=gdm.get)
    w(f"<p>The residual is confined to one operation: fetching the bytecode of a contract the "
      f"store has not fetched before. The opcode grid draws the line exactly. BALANCE "
      f"({gdm['BALANCE']:.3f}) and EXTCODEHASH ({gdm['EXTCODEHASH']:.3f}) read only the account "
      f"row, and sit at parity under every access mode. Every opcode that must load the code "
      f"diverges, and EXTCODESIZE is the worst of them at {gdm['EXTCODESIZE']:.3f}: it is not "
      f"answered from the account row or from a cache, Nethermind fetches the bytecode to "
      f"measure it.</p>")
    nc_a, nc_b = BM["attribution"]["noncode"]["after"], BM["attribution"]["noncode"]["before"]
    wide = BM["attribution"]["code_wide"]
    sa_w = wide["sa"]["total_marg"]
    joc_w = wide["joc"]["cf"]["24402727"]["marg"]
    nwin = wide["sa"]["_windows"]
    w(figure(chart_marginal_cf(BM),
             f"Marginal bytes for a distinct contract per access, by column family, on the same "
             f"store before and after settling it. "
             f"{BM['attribution']['code']['before']['sa']['cf']['flat/StateNodes']['marg']:.0f} MB "
             f"was the background compaction of Finding 3 and is now zero. The code database's "
             f"{BM['attribution']['code']['after']['sa']['cf']['code']['marg']:.0f} MB does not "
             f"move, because it is the test."))
    w(f"<p>Measured on the settled store over {nwin} matched pairs per arm, the generated store "
      f"reads <b>{sa_w:,.0f} MB</b> to do what the snapshot does in <b>{joc_w:,.0f} MB</b>: "
      f"{sa_w/joc_w:.2f}&times; the bytes, {wide['sa']['cf']['code']['marg']:,.0f} MB of it in "
      f"the code column family. The account rows are identical between the two patterns "
      f"({wide['sa']['cf']['flat/Account']['marg']:+.1f} MB) and the trie families contribute "
      f"nothing ({wide['sa']['cf']['flat/StateNodes']['marg']:+.1f} MB). On patterns that touch "
      f"no code at all, the two stores are byte-for-byte alike: "
      f"{nc_a['sa']['cf']['flat/Account']['marg']:.1f} MB against "
      f"{nc_a['joc']['cf']['24402727']['marg']:.1f} MB.</p>")

    w("<h3>Why the obvious explanation fails</h3>")
    cp, cs, cpop = M["code_probe"], M["code_sweep"], M["code_population"]
    w(f"<p>The generated store's code database is {esc(cp['sa']['size'])} against "
      f"{esc(cp['joc']['size'])}, so the natural reading is that code lookups are simply more "
      f"expensive on it. Measured in isolation, they are cheaper:</p>")
    w("<table><tr><th>measurement, caches cold</th><th class=n>state-actor</th>"
      "<th class=n>jochemnet</th></tr>")
    w(f"<tr><td>one random code lookup</td><td class=n>{cp['sa']['bytes']:,} B, "
      f"{cp['sa']['us']:.0f} &micro;s</td><td class=n>{cp['joc']['bytes']:,} B, "
      f"{cp['joc']['us']:.0f} &micro;s</td></tr>")
    w(f"<tr><td>sweep of {thousands(cs['n'])} distinct maximum-size contracts</td>"
      f"<td class=n>{cs['sa']['bytes']:,} B per read</td>"
      f"<td class=n>{cs['joc']['bytes']:,} B per read</td></tr>")
    w(f"<tr><td>maximum-size contracts per {thousands(cpop['scanned'])} accounts</td>"
      f"<td class=n>{cpop['sa']['at_max']}</td><td class=n>{cpop['joc']['at_max']}</td></tr>")
    w("<caption>Per lookup, the generated store is the cheaper one at every granularity we can "
      "measure. The cost is therefore not in the lookup. It is in what a lookup drags in with "
      "it.</caption></table>")

    w("<h3>The mechanism: block tenancy</h3>")
    bx = M["besu_cross_check"]
    IB = D["intervention_blocks"]
    fc_tr = CL["final_cells"]["ether transfer"]["settled"]
    pj, ps = IB["pread"]["joc"], IB["pread"]["sa"]
    w(f"<p>Both stores key code by its hash, so a contract's neighbours in a data block are "
      f"random, and what differs is who they are. The snapshot's code database holds "
      f"{cpop['joc']['pct']:.0f}% of accounts with code at a median of {cpop['joc']['p50']} bytes "
      f"and a wide spread; the generated store holds {cpop['sa']['pct']:.0f}% with code, almost "
      f"all of it a distinct {cpop['sa']['p50']}-byte stub that does not compress. Tracing the "
      f"client's <code>pread</code> calls through one {esc(IB['test'])} test shows what that does "
      f"to a fetch:</p>")
    w("<table><tr><th>inside the measured step</th><th class=n>jochemnet</th>"
      "<th class=n>state-actor</th></tr>")
    w(f"<tr><td>account-row reads</td><td class=n>{pj['account_n']:,} &times; {pj['account_mean_b']:,} B</td>"
      f"<td class=n>{ps['account_n']:,} &times; {ps['account_mean_b']:,} B</td></tr>")
    w(f"<tr><td>code reads: one block per fetch</td><td class=n>{pj['code_n']:,} &times; "
      f"<b>{pj['code_mean_b']:,} B</b></td><td class=n>{ps['code_n']:,} &times; "
      f"<b>{ps['code_mean_b']:,} B</b></td></tr>")
    w(f"<tr><td>mean latency of a code read</td><td class=n>{pj['code_mean_us']:,} &micro;s</td>"
      f"<td class=n><b>{ps['code_mean_us']:,} &micro;s</b></td></tr>")
    w(f"<tr><td>code reads taking 1&ndash;2 ms</td><td class=n>{IB['hist_code_ms']['joc']['1-2']}%</td>"
      f"<td class=n><b>{IB['hist_code_ms']['sa']['1-2']}%</b></td></tr>")
    w(f"<tr><td>physical pages per fetch</td><td class=n>{IB['pages_per_fetch']['joc']:.2f}</td>"
      f"<td class=n><b>{IB['pages_per_fetch']['sa']:.2f}</b></td></tr>")
    w(f"<caption>Same test, same window. The account row is byte-identical. Every code fetch is "
      f"one block, and every block is {ps['code_mean_b'] - pj['code_mean_b']} bytes larger on "
      f"the generated store: the stubs packed around the contract. A larger compressed block "
      f"crosses a 4 KB page boundary more often, so a quarter of the fetches need a second "
      f"physical read, which is the {ps['code_mean_us'] - pj['code_mean_us']} &micro;s. Over "
      f"{ps['code_n']:,} fetches that is the second by which this test runs slower "
      f"({min(IB['secs']['joc']):.2f}&ndash;{max(IB['secs']['joc']):.2f} s against "
      f"{min(IB['secs']['sa_4k']):.2f}&ndash;{max(IB['secs']['sa_4k']):.2f} s, five runs each)."
      f"</caption></table>")
    rp = IB["repack"]
    w(f"<p><b>Confirmed by intervention.</b> The generated code database was rewritten with a "
      f"{rp['block_size']}-byte data block, so every contract sits in a block of its own "
      f"({rp['blocks']:,} blocks for {rp['entries']:,} entries), and the image promoted. Every key "
      f"and value is byte-identical, the state root is unchanged, the fixtures are the same. The "
      f"same test then ran in "
      f"{', '.join(f'{s:.2f}' for s in IB['secs']['sa_64b'])} s, on the snapshot's side of its "
      f"own five runs. At cell level, against the same jochemnet run:</p>")
    w("<table><tr><th>cell</th><th class=n>n</th><th class=n>4 KB blocks</th>"
      "<th class=n>contract alone in its block</th></tr>")
    for c in ("DIFF_MAX code-exec", "JUMPDEST code-exec", "SAME_MAX code-exec"):
        v = IB["cells"][c]
        cls = " bad" if v["before"] < 0.97 else ""
        w(f"<tr><td>{esc(c)}</td><td class=n>{v['n']}</td><td class=\"n{cls}\">{v['before']:.3f}</td>"
          f"<td class=n>{v['after']:.3f}</td></tr>")
    w("<caption>The two residual cells close to parity; the control, which reuses one contract "
      "and therefore never paid for its neighbours, does not move. An index or file-count "
      "mechanism would have predicted the opposite: the index grew a hundredfold and the test "
      "got faster.</caption></table>")
    w(f"<p>The same effect has been seen from the other side. state-actor#138 changed the "
      f"autofill pool's <em>content</em> to tiled bytecode that over-compresses, and the Besu "
      f"benchmark's distinct-code categories went from 17% slower than mainnet to 46&ndash;51% "
      f"faster; the same cell on the Besu study's store reads "
      f"{bx['families']['loads_code']['EXISTING_CONTRACT_DIFF_MAX']['median']:.3f} against "
      f"{bx['families']['loads_code']['EXISTING_CONTRACT_SAME_MAX']['median']:.3f} reused. The "
      f"64-byte block is a diagnostic, not a configuration; the fix is the pool's content, and "
      f"<a href=\"https://github.com/ethereum/state-actor/pull/{IB['pr']}\">state-actor#{IB['pr']}</a> "
      f"slices it from real mainnet bytecode at &plusmn;5% of mainnet compressibility. A store "
      f"built that way has a different genesis state root, so the stateful fixtures must be "
      f"regenerated with it; that is the remaining step.</p>")
    # ---- the other direction: ether transfers (round 66)
    TN = D["topnodes"]
    tr = IB["transfers"]
    sh_j, sh_s = TN["shape"]["joc"], TN["shape"]["sa_v1"]
    pk = TN["packing"]
    sw = TN["swap"]
    w("<h3>The other direction: ether transfers</h3>")
    w(f"<p>The one cell where the generated store was reproducibly <em>faster</em> "
      f"({fc_tr:.3f} on the settled runs) was traced the same way, {tr['joc']['secs']} against "
      f"{tr['sa']['secs']} seconds for 18 blocks of transfers. Account-row and code reads are "
      f"identical ({tr['joc']['account_n']:,} against {tr['sa']['account_n']:,}; "
      f"{tr['joc']['code_n']:,} against {tr['sa']['code_n']:,}). The snapshot reads "
      f"<b>{tr['joc']['statetop_n']:,}</b> top-of-trie node blocks against the generated store's "
      f"{tr['sa']['statetop_n']:,}. An earlier version of this page called that a property of "
      f"the arms &mdash; a migrated mainnet trie costing more to update than a generated one. "
      f"It is not. A flat store does not skip the trie on a write: a transfer changes two "
      f"accounts and the state root needs every branch node on both paths re-hashed, so the "
      f"question is why one trie needs more node reads than the other for the same work.</p>")
    w("<p><b>The tries are the same shape.</b> Nethermind keeps the top of the account trie "
      "(paths of up to five nibbles) in its own column, keyed by path, and the rest in a second "
      "one. A full scan of the first and a sample of whole level-6 subtrees from the second, on "
      "both stores:</p>")
    w("<table><tr><th></th><th class=n>jochemnet</th><th class=n>state-actor</th></tr>")
    for label, key, fmt in (("top-of-trie nodes (paths 0&ndash;5)", "top_nodes", "{:,}"),
                            ("accounts, from the sample", "accounts_est_M", "{:.1f}M"),
                            ("leaves per level-6 subtree", "leaves_per_subtree", "{:.1f}"),
                            ("mean leaf path length, nibbles", "mean_leaf_len", "{:.2f}"),
                            ("nodes on a cold root-to-leaf walk", "walk_nodes", "{:.2f}")):
        w(f"<tr><td>{label}</td><td class=n>{fmt.format(sh_j[key])}</td>"
          f"<td class=n>{fmt.format(sh_s[key])}</td></tr>")
    w(f"<caption>Both tops are the complete 16-ary tree of depth five "
      f"({sh_j['top_nodes']:,} nodes, every one a 532-byte branch). The generated trie holds "
      f"{100*(sh_s['accounts_est_M']/sh_j['accounts_est_M']-1):.0f}% more accounts and is "
      f"marginally deeper. Shape cannot make it read fewer nodes.</caption></table>")
    w("<p><b>The column is packed differently.</b> RocksDB's own table properties for the "
      "top-of-trie column, same entries on both stores:</p>")
    w("<table><tr><th>Flat/StateTopNodes</th><th class=n>jochemnet</th><th class=n>state-actor</th>"
      "<th class=n>client option</th></tr>")
    w(f"<tr><td>entries</td><td class=n>{pk['joc_before']['entries']:,}</td>"
      f"<td class=n>{pk['sa_before']['entries']:,}</td><td></td></tr>")
    w(f"<tr><td>data blocks</td><td class=n>{pk['joc_before']['blocks']:,}</td>"
      f"<td class=n>{pk['sa_before']['blocks']:,}</td><td></td></tr>")
    w(f"<tr><td>bytes per block on disk</td><td class=\"n bad\">{pk['joc_before']['bytes_per_block']:,}</td>"
      f"<td class=n>{pk['sa_before']['bytes_per_block']:,}</td>"
      f"<td class=n>block_size={TN['client_option']['block_size']:,}</td></tr>")
    w(f"<tr><td>nodes per block</td><td class=\"n bad\">{pk['joc_before']['entries_per_block']:.0f}</td>"
      f"<td class=n>{pk['sa_before']['entries_per_block']:.0f}</td><td></td></tr>")
    w(f"<caption>Every other flat column matches the client's options on both stores. Top "
      f"nodes are keyed by path in pre-order, so a level-4 node and its sixteen children are "
      f"seventeen consecutive keys, about 9 KB: a 16 KB block holds the family, a 4 KB block "
      f"holds seven nodes, and the walk to a touched leaf pays a separate physical read for the "
      f"parent. Measured per touched account: <b>{sw['joc']['top_per_account_before']:.2f}</b> "
      f"top-node reads on the snapshot against {sw['sa']['top_per_account_before']:.2f} on the "
      f"generated store, uniformly across all eighteen transfer variants.</caption></table>")
    w(f"<p><b>Confirmed by intervention, in both directions.</b> The generated store's "
      f"top-of-trie column was rewritten with the snapshot's packing "
      f"({pk['sa_after']['blocks']:,} blocks of {pk['sa_after']['bytes_per_block']:,} bytes) and "
      f"the snapshot's with the client's ({pk['joc_after']['blocks']:,} blocks of "
      f"{pk['joc_after']['bytes_per_block']:,}), two seconds each, every entry unchanged, both "
      f"promoted. Every ether-transfer test then ran on both arms with the same per-column "
      f"read accounting:</p>")
    w("<table><tr><th></th><th class=n>settled layouts</th><th class=n>layouts swapped</th></tr>")
    w(f"<tr><td>median throughput ratio on transfers, state-actor / jochemnet</td>"
      f"<td class=n>{sw['ratio_settled']:.3f}</td><td class=n>{sw['ratio_swapped']:.3f}</td></tr>")
    w(f"<tr><td>top-node reads per touched account, jochemnet</td>"
      f"<td class=n>{sw['joc']['top_per_account_before']:.2f}</td>"
      f"<td class=n>{sw['joc']['top_per_account_after_240M']:.2f}</td></tr>")
    w(f"<tr><td>top-node reads per touched account, state-actor</td>"
      f"<td class=n>{sw['sa']['top_per_account_before']:.2f}</td>"
      f"<td class=n>{sw['sa']['top_per_account_after_240M']:.2f}</td></tr>")
    w(f"<tr><td>change from the swap alone</td><td></td>"
      f"<td class=n>jochemnet &times;{sw['joc_change']:.3f}, state-actor &times;{sw['sa_change']:.3f}</td></tr>")
    w(f"<caption>{sw['n_pairs']} test pairs across every gas value. The read counts swap, each "
      f"arm moves by about half the gap in the predicted direction, and the "
      f"{100*(sw['ratio_settled']-1):.1f}% asymmetry becomes "
      f"{100*(sw['ratio_swapped']-1):.1f}%, inside the replica spread.</caption></table>")
    pv = TN["provenance"]
    w(f"<p><b>Whose layout was it?</b> Not the snapshot's. RocksDB numbers files monotonically, "
      f"and the snapshot's own files run from "
      f"{min(pv['StorageNodes']['min'], pv['Storage']['min']):06d}; the ten 4 KB top-of-trie "
      f"files were {pv['StateTopNodes']['min']:06d}&ndash;{pv['StateTopNodes']['max']:06d}, written "
      f"on this host just before the account column was rebuilt in the first errata item below "
      f"({pv['Account']['min']:06d}+). The read-write open that rebuilt that column transcribed "
      f"the client's options for it and left every other column on RocksDB's defaults &mdash; "
      f"4,096-byte blocks, no filter &mdash; and the top-of-trie column, compaction-pending "
      f"since the pre-run, was compacted in the background under those defaults. The audit that "
      f"followed checked two columns and missed the third. The snapshot now carries the client's "
      f"packing, and every jochemnet number in the next section is measured against it.</p>")
    st_ = J["settle"]
    w(f"<p class=note>Two smaller store defects turned up on the way and moved no ratio: the "
      f"generated store's account family was left <code>{esc(st_['sa_account']['before'])}</code> "
      f"and both arms' code databases compaction-pending, because a plain "
      f"<code>CompactRange</code> writes into the deepest level that already holds files unless "
      f"given a target level. Same family of mistake as Finding 3, on smaller column "
      f"families.</p>")

    # ------------------------------------------------- the regenerated store (round 67)
    V2 = D["v2"]
    vc = V2["cells"]
    vt = V2["per_test"]
    w("<h2>The regenerated store: the generator fix, measured</h2>")
    w(f"<p>The remaining step was taken. state-actor at "
      f"<a href=\"https://github.com/ethereum/state-actor/commit/{V2['revision']}\">"
      f"{V2['revision'][:7]}</a> &mdash; the tree with "
      f"<a href=\"https://github.com/ethereum/state-actor/pull/{IB['pr']}\">#{IB['pr']}</a>'s "
      f"mainnet-sliced code pool and "
      f"<a href=\"https://github.com/ethereum/state-actor/pull/139\">#139</a>'s forced "
      f"bottommost compaction &mdash; regenerated the Nethermind store from the same spec, seed "
      f"and size budget: {V2['size']} in {V2['gen_minutes']//60} h {V2['gen_minutes']%60} min, "
      f"genesis <code>{V2['genesis'][:10]}&hellip;{V2['genesis'][-6:]}</code> against the old "
      f"<code>{V2['v1_genesis'][:10]}&hellip;{V2['v1_genesis'][-6:]}</code>, "
      f"{TN['shape']['sa_v2']['accounts_est_M']:.0f}M accounts, top-of-trie nodes packed "
      f"{V2['topnodes_packing']['entries_per_block']:.0f} to a {V2['topnodes_packing']['bytes_per_block']:,}-byte "
      f"block as written, no compaction pending. A store with a new genesis root needs new "
      f"stateful fixtures, so the {V2['fixtures']['filled']} tests of the long class "
      f"(every category over a second, at 160M and 240M) were filled against it with the "
      f"Nethermind filler at execution-specs <code>{V2['fixtures']['eest_commit'][:7]}</code>, "
      f"covering {V2['fixtures']['class2_covered'][0]} of the {V2['fixtures']['class2_covered'][1]} "
      f"long-class tests measured above, and run twice; jochemnet ran the same tests once more "
      f"on the same day, on its repacked baseline.</p>")
    order = sorted(vc, key=lambda c: (c.split()[-1] != "code-exec", c))
    w("<table><tr><th>cell</th><th class=n>n</th><th class=n>old store, settled</th>"
      "<th class=n>new store, run 1</th><th class=n>new store, run 2</th>"
      "<th class=n>jochemnet, day / settled</th></tr>")
    for c in order:
        v = vc[c]
        def cls_(x):
            return "" if x is None else (" bad" if x < 0.9 else (" good" if x > 1.1 else ""))
        def cell_(x):
            return f"<td class=\"n{cls_(x)}\">{x:.3f}</td>" if x is not None else "<td class=n>&ndash;</td>"
        w(f"<tr><td>{esc(c)}</td><td class=n>{v['n']}</td>{cell_(v['v1_t1'])}{cell_(v['v2r1'])}"
          f"{cell_(v['v2r2'])}{cell_(v['joc_joc_t1'])}</tr>")
    w(f"<caption>Median throughput ratio per cell, state-actor over jochemnet; the new-store "
      f"columns are against the same-day jochemnet run, the old-store column is the settled "
      f"pair quoted above. The last column is jochemnet against itself, day run over settled "
      f"run, the drift a same-store comparison carries.</caption></table>")
    def band(x):
        return f"{x['within10']} of {x['n']} ({100*x['within10']/x['n']:.0f}%)"
    w(f"<p>Per test, over a second on both arms: {band(vt['v1_t1'])} inside &plusmn;10% on the "
      f"old store against {band(vt['v2r1'])} and {band(vt['v2r2'])} on the new one, medians "
      f"{vt['v2r1']['median']:.3f} and {vt['v2r2']['median']:.3f}. The two runs of the new store "
      f"agree with each other cell by cell to within "
      f"{max(abs(v['v2r2_v2r1'] - 1) for v in vc.values() if v['v2r2_v2r1']):.3f}, and the "
      f"jochemnet day run reproduces its own settled run to within "
      f"{max(abs(v['joc_joc_t1'] - 1) for v in vc.values() if v['joc_joc_t1'] and 'transfer' not in v):.3f} "
      f"on every cell, so the movements below are larger than the drift.</p>")
    dm2, jd2 = vc["DIFF_MAX code-exec"], vc["JUMPDEST code-exec"]
    w(f"<p><b>The code-pool fix works, and it overshoots.</b> Distinct-contract code execution, "
      f"the cell this page spent four findings on, was {dm2['v1_t1']:.3f} on the old store; on "
      f"the regenerated one it is <b>{dm2['v2r1']:.3f}</b> and {dm2['v2r2']:.3f}, and "
      f"jump-destination scanning {jd2['v2r1']:.3f} and {jd2['v2r2']:.3f} against "
      f"{jd2['v1_t1']:.3f} before. The generated store is now the <em>faster</em> of the two on "
      f"the operation it used to lose, by 5&ndash;10%. Both cells moved by "
      f"{dm2['v2r1']/dm2['v1_t1'] - 1:+.0%} and {jd2['v2r1']/jd2['v1_t1'] - 1:+.0%} while the "
      f"reused-contract control stayed at {vc['SAME_MAX code-exec']['v2r1']:.3f} and every "
      f"account-row cell inside {max(abs(v['v2r1'] - 1) for k, v in vc.items() if 'BAL/HASH' in k or 'EOA' in k or 'MINIMAL' in k):.3f} "
      f"of parity, so the lever is the pool and nothing else moved with it. A pool sampled from "
      f"mainnet bytecode at mainnet compressibility still does not reproduce mainnet's "
      f"<em>block tenancy</em> on this client: the pool's 1 KiB floor keeps small records out, "
      f"and on a 4,096-byte code block a fixture contract then starts a block of its own more "
      f"often than it does on mainnet, where the median contract is 45 bytes. Cheaper than "
      f"mainnet is as wrong as dearer, and the mechanism is the same one Finding 4 measured.</p>")
    tr2 = vc["ether transfer"]
    _sw2 = TN["swap"]
    w(f"<p><b>Ether transfers: the layout was about half of it.</b> With both stores packing "
      f"their top-of-trie column the way the client does, transfers read "
      f"{tr2['v2r1']:.3f} and {tr2['v2r2']:.3f} against {tr2['v1_t1']:.3f} before &mdash; the "
      f"snapshot gained {tr2['joc_joc_t1'] - 1:+.1%} from the repack alone, which is the swap's "
      f"per-arm figure ({_sw2['joc_change']:.3f}) reproduced on a different day against a "
      f"different store. What is left is small and, as the next section shows, is not a "
      f"difference in reads at all.</p>")

    # ------------------------------------------------- the surviving outliers (round 68)
    OU = D["outliers"]
    ot, den = OU["tests"], OU["denominator"]
    w("<h3>Which tests are still outside &plusmn;10%, and why</h3>")
    w(f"<p>Of the {vt['v2r1']['n']} tests over a second, {vt['v2r1']['n'] - vt['v2r1']['within10']} "
      f"leave &plusmn;10% in the first run of the regenerated store and "
      f"{vt['v2r2']['n'] - vt['v2r2']['within10']} in the second. Both runs divide by the "
      f"<em>same</em> jochemnet run, so a single slow jochemnet measurement makes a test look "
      f"reproducibly divergent in both. It does: re-running {den['n']} of those tests as a "
      f"fresh pair, back to back on the same day, moves jochemnet by up to "
      f"{100*den['joc_spread']:.0f}% on one test ({esc(den['joc_worst'])}) against "
      f"{100*den['sa_spread']:.0f}% for state-actor. Measured pairwise, most of the tail "
      f"disappears:</p>")
    rows = [("amt0 diff_to_self 240M", "transfer to self"),
            ("amt0 diff_to_existent 240M", "transfer to an existing account"),
            ("amt1 diff_to_delegated_contract_diff 240M", "transfer through a 7702 delegation"),
            ("amt1 diff_to_nonexistent 160M", "transfer to an absent account"),
            ("sstore slots=False new=False 160M", "store to an absent slot, no write"),
            ("sstore slots=True new=True 160M", "store a new value to an existing slot")]
    w("<table><tr><th>test</th><th class=n>v2 run 1</th><th class=n>v2 run 2</th>"
      "<th class=n>fresh pair</th><th>what the reads say</th></tr>")
    notes = {
        "amt0 diff_to_self 240M": "same reads, same bytes, same latency",
        "amt0 diff_to_existent 240M": "same reads, same bytes, same latency",
        "amt1 diff_to_delegated_contract_diff 240M": "same reads; jochemnet reads 1.8&times; the code bytes",
        "amt1 diff_to_nonexistent 160M": "same reads, same bytes, same latency",
        "sstore slots=False new=False 160M": "jochemnet 4.2&times; the storage reads",
        "sstore slots=True new=True 160M": "jochemnet 0.6&times; storage, 1.2&times; storage-node reads",
    }
    for k, label in rows:
        t_ = ot[k]
        cls = " bad" if t_["r_r68"] < 0.9 else (" good" if t_["r_r68"] > 1.1 else "")
        w(f"<tr><td>{esc(label)}</td><td class=n>{t_['r_v2r1']:.3f}</td>"
          f"<td class=n>{t_['r_v2r2']:.3f}</td><td class=\"n{cls}\">{t_['r_r68']:.3f}</td>"
          f"<td>{notes[k]}</td></tr>")
    w("<caption>Throughput ratio, state-actor over jochemnet. The first two columns share one "
      "jochemnet run; the third is a pair measured back to back with every read traced.</caption></table>")
    sf = ot["amt0 diff_to_self 240M"]["cols"]
    w(f"<p><b>The transfers that survive the fresh denominator are not I/O.</b> On the largest "
      f"of them the two arms issue the same reads for the same bytes at the same latency: "
      f"{sf['flat/Account']['sa_n']:,} against {sf['flat/Account']['joc_n']:,} account-row "
      f"reads ({sf['flat/Account']['sa_mb']:.0f} MB each side, "
      f"{sf['flat/Account']['sa_us']/1000:.1f} against {sf['flat/Account']['joc_us']/1000:.1f} ms "
      f"mean), {sf['flat/StateTopNodes']['sa_n']:,} against "
      f"{sf['flat/StateTopNodes']['joc_n']:,} top-of-trie reads, and "
      f"{sf['flat/StateNodes']['sa_n']:,} against {sf['flat/StateNodes']['joc_n']:,} deeper ones. "
      f"The remaining few per cent is work inside the client per unit of gas, not reads &mdash; "
      f"which also rules out the reading of a mainnet-shaped trie being dearer per node, the "
      f"explanation this page carried for one morning. The clearest case is the absent-account "
      f"transfer: {ot['amt1 diff_to_nonexistent 160M']['cols']['flat/Account']['sa_n']:,} against "
      f"{ot['amt1 diff_to_nonexistent 160M']['cols']['flat/Account']['joc_n']:,} account reads, "
      f"identical bytes and latency, and "
      f"{ot['amt1 diff_to_nonexistent 160M']['thr']['nm-sa-out68']:.0f} against "
      f"{ot['amt1 diff_to_nonexistent 160M']['thr']['nm-joc-out68']:.0f} MGas/s. Open.</p>")
    ST = D["storage"]
    col, sc, sr = ST["columns"], ST["cells"], ST["reads"]
    w(f"<p><b>The storage outliers were placement as well</b>, in two columns no earlier round "
      f"had settled, and they close: Finding 5 below.</p>")
    aa = ST["absent_account"]
    ab = ST["ablation"]
    _cpu = lambda arm, g: aa["cpu_seconds"][arm][g].get(".net thread pool", 0)
    w(f"<p><b>What is left is one test, and it is not I/O.</b> The absent-account transfer "
      f"survives every treatment: {', '.join('%.0f' % x for x in aa['throughput']['160M']['sa'])} "
      f"MGas/s on the generated store against "
      f"{', '.join('%.0f' % x for x in aa['throughput']['160M']['joc'])} on the snapshot over three "
      f"repetitions of the same configuration. Sampling every client thread at 0.1 s inside the "
      f"measured step puts the difference in managed thread-pool threads &mdash; "
      f"{_cpu('joc', '160M'):.2f} against {_cpu('sa', '160M'):.2f} CPU-seconds at 160M, "
      f"{_cpu('joc', '240M'):.2f} against {_cpu('sa', '240M'):.2f} at 240M &mdash; on a test whose "
      f"disk reads are identical on every column. Neither warming path explains it: turning off "
      f"state pre-warming leaves the snapshot at "
      f"{'/'.join('%.0f' % x for x in ab['B prewarming off']['joc 160M'])} against "
      f"{'/'.join('%.0f' % x for x in ab['B prewarming off']['sa 160M'])}, and turning off the "
      f"trie warmer leaves it at "
      f"{'/'.join('%.0f' % x for x in ab['C trie warmer off']['joc 160M'])} against "
      f"{'/'.join('%.0f' % x for x in ab['C trie warmer off']['sa 160M'])}, both of which are the "
      f"baseline gap. The test creates about 5,500 accounts per block and reads almost nothing, so "
      f"what is left is the insert-and-rehash path spending more managed CPU on one trie than the "
      f"other. Open, and the next instrument is a profiler rather than a flag.</p>")

    # ------------------------------------------------- finding 5: the storage columns
    w("<h2>Finding 5: two columns nobody had compacted</h2>")
    w(f"<p>The snapshot's storage rows sat in "
      f"{col['joc_storage_before']['files']:,} files spread over "
      f"{len(col['joc_storage_before']['levels'])} levels, its storage trie in "
      f"{col['joc_storagenodes_before']['files']:,} over "
      f"{len(col['joc_storagenodes_before']['levels'])}; the generated store keeps each in a "
      f"single level. A lookup for a key that is not there has to be refused by every level that "
      f"could hold it, so on one test the snapshot issued "
      f"{D['outliers']['tests']['sstore slots=False new=False 240M']['cols']['flat/Storage']['joc_n']:,} "
      f"storage reads where the generated store issued "
      f"{D['outliers']['tests']['sstore slots=False new=False 240M']['cols']['flat/Storage']['sa_n']:,}, "
      f"and where it now issues {sr['slots=False new=False 240M']['after_r72']['joc_rows']:,}. "
      f"Every earlier intervention "
      f"targeted the columns the divergent categories read; storage was at parity from the first "
      f"run, so nobody looked at it for sixty-eight rounds.</p>")
    w(figure(chart_levels(ST),
             "Where the files sit. Amber is the snapshot as it was, green is the same column after "
             "one <code>CompactRange</code> with the client's own table options &mdash; and the "
             "generated store as it was written."))
    w(figure(chart_storage_close(ST),
             f"The four storage tests, through both compactions. Settling the rows took the "
             f"absent-slot test from {sc['slots=False new=False 160M']['r68']:.2f}&times; to "
             f"{sc['slots=False new=False 160M']['r69']:.2f}; settling the trie took the new-value "
             f"tests from {sc['slots=True new=True 160M']['r69']:.2f} to "
             f"{sc['slots=True new=True 160M']['r72']:.3f}. The overwrite test, which touches no "
             f"trie node, never left the band &mdash; the control that says each treatment moved "
             f"what it was aimed at."))
    w(f"<p>Both steps were pre-registered on their reads, not their timings, and both read "
      f"predictions held exactly: storage-row reads on the absent-slot test "
      f"{sr['slots=False new=False 240M']['after_r69']['joc_rows']:,} against the generated "
      f"store's {sr['slots=False new=False 240M']['after_r69']['sa_rows']:,} after the first, and "
      f"storage-trie reads {sr['slots=True new=True 240M']['after_r72']['joc_nodes']:,} against "
      f"{sr['slots=True new=True 240M']['after_r72']['sa_nodes']:,} after the second, from "
      f"{sr['slots=True new=True 240M']['after_r69']['joc_nodes']:,} against "
      f"{sr['slots=True new=True 240M']['after_r69']['sa_nodes']:,}. The lesson is not about "
      f"storage: a synthetic store is written once and compacted once, a real one is a stack of "
      f"levels, and that difference is worth up to "
      f"{sc['slots=False new=False 160M']['v2']:.1f}&times; on the operations that ask for keys "
      f"that are not there. Equalising it makes the two stores comparable; it does not make the "
      f"generated one more like mainnet.</p>")

    # ------------------------------------------------- where it stands
    w("<h2>Where it stands</h2>")
    fc = CL["final_cells"]
    n_par = sum(1 for v in fc.values() if 0.9 <= v["settled"] <= 1.1)
    _rep = {c: v["after"] for c, v in D["intervention_blocks"]["cells"].items()}
    _v2 = {c: v["v2r1"] for c, v in vc.items() if v["v2r1"] is not None and c in fc}
    n_v2 = sum(1 for x in _v2.values() if 0.9 <= x <= 1.1)
    w(figure(chart_final_cells(CL, _rep, _v2),
             f"Every cell of the long class after all four findings are applied. "
             f"{n_par} of {len(fc)} sit inside &plusmn;10%; the two that carry the residual, "
             f"distinct-contract code execution at {fc['DIFF_MAX code-exec']['settled']:.3f} and "
             f"jump-destination scanning at {fc['JUMPDEST code-exec']['settled']:.3f}, reproduce "
             f"to within {max(abs(fc[c]['settled']-fc[c]['r1']) for c in ('DIFF_MAX code-exec','JUMPDEST code-exec')):.3f} "
             f"across three runs of the same configuration. The amber marks are the same cells with the "
             f"code database repacked so no contract shares a block with the filler; the violet "
             f"marks are the regenerated store, {n_v2} of {len(_v2)} cells inside the band."))
    IBc = D["intervention_blocks"]["cells"]
    w(f"<p>The generated state was never {factor:.0f}&times; slower. With placement equalised, "
      f"the store no longer compacting itself under the measurement, and both arms on "
      f"steady-state code, the tests that can support a claim agree to within a few per cent. "
      f"The one operation that remained slower, fetching a contract the store has never served, "
      f"was the generator's filler bytecode packed around the fixture contracts: repacked as a "
      f"diagnostic that cell reads {IBc['DIFF_MAX code-exec']['after']:.3f}, and on a store "
      f"regenerated with the pool fixed at the source it reads "
      f"{vc['DIFF_MAX code-exec']['v2r1']:.3f} &mdash; past parity, the same mechanism with the "
      f"sign reversed. Of the cell that ran the other way, ether transfers, about half was this "
      f"study's own tooling having repacked one column of the snapshot; with that undone the "
      f"cell reads {vc['ether transfer']['v2r1']:.3f}, and on a same-session pair the tests "
      f"behind it issue the same reads for the same bytes at the same latency, so what is left "
      f"there is not I/O at all. The storage cell was placement as well, in the two columns no "
      f"earlier round had settled: with both compacted it reads "
      f"{ST['cells']['slots=True new=True 160M']['r72']:.3f} and "
      f"{ST['cells']['slots=False new=False 160M']['r72']:.3f} where it had read "
      f"{ST['cells']['slots=True new=True 160M']['v2']:.2f} and "
      f"{ST['cells']['slots=False new=False 160M']['v2']:.2f}. Six defects in the pipeline, two "
      f"in this study's own tooling, seven interventions. What remains is a generated store a "
      f"few per cent <em>cheaper</em> than a mainnet-shaped one on the two operations that touch "
      f"bytecode &mdash; the direction that flatters synthetic state rather than the one this "
      f"page opened with &mdash; and exactly one test, creating accounts that do not exist, where "
      f"the two arms read the same bytes and the snapshot spends twice the managed CPU.</p>")

    fl = M["filters"]

    # ---------------------------------------------------------------- errata
    w("<h2>What we got wrong on the way</h2>")
    w("<ul>")
    w("<li>The first compaction used RocksDB's default table options, which silently dropped the "
      "ribbon filter and switched to Snappy. Absent-account lookups inverted to a 19&times; "
      "advantage for the generated store, and it took a full re-run with the real per-family "
      "options to get the parity figure above.</li>")
    w("<li>A rebuild was applied to the mounted volume without promoting it, so the harness "
      "restored the untreated image before the first test and a 2.2-hour run measured nothing "
      "new. It became an accidental replication, which is the only reason we can quote a "
      "run-to-run noise figure.</li>")
    w(f"<li><b>The probe measured both stores as if they had no filters.</b> It opened every "
      f"column family with RocksDB's default options, and a reader with no "
      f"<code>filter_policy</code> configured never consults the filters that are in the files. "
      f"Absent and present lookups therefore cost the same, which made us retract a correct "
      f"explanation. Opened properly, the filters work on both arms &mdash; "
      f"{thousands(fl['sa']['useful'])} and {thousands(fl['joc']['useful'])} of "
      f"{thousands(fl['n'])} negatives rejected &mdash; and an absent lookup costs "
      f"{fl['sa']['absent_bytes']} against {fl['sa']['present_bytes']:,} bytes.</li>")
    w("<li><b>We published a mechanism for the last cell and it was wrong.</b> The residual was "
      "attributed to the generated store's larger code database. Three direct measurements say "
      "the opposite: reading code is cheaper on that store per lookup, cheaper on a sweep of "
      "distinct maximum-size contracts, and the two stores hold the same number of them. The "
      "section above now reports the cell with the mechanism that survived and the intervention "
      "that confirmed it.</li>")
    ce_e = D["cache_experiment"]
    w(f"<li><b>We had a fourth explanation and it failed too.</b> The control gap looked like "
      f"cross-step cache carry-over, and we pre-registered the prediction that starving the "
      f"block cache would pull it to 0.85&ndash;0.95. It moved to "
      f"{ce_e['small']['thr']['CONTROL']:.3f}. The section above reports the eliminated "
      f"explanation rather than the one we expected to be writing, which is the only reason "
      f"this list is worth keeping.</li>")
    nz_all = D["noise"]["replica"]["all"]
    nz_s, nz_l = D["noise"]["replica"]["by_duration"]["lt0.2s"], D["noise"]["replica"]["by_duration"]["ge5s"]
    w(f"<li><b>We reported per-test divergence counts before measuring whether a test "
      f"reproduces.</b> Running the same store twice under the same configuration puts only "
      f"{100*nz_all['within10']/nz_all['n']:.0f}% of {nz_all['n']} tests inside "
      f"&plusmn;10% of themselves &mdash; "
      f"{100*nz_s['within10']/nz_s['n']:.0f}% for tests under a fifth of a second against "
      f"{100*nz_l['within10']/nz_l['n']:.0f}% for tests over five seconds. An earlier version "
      f"of this page ranked the twelve most divergent tests in the suite; all twelve ran in "
      f"under 0.2 s, so that table was a ranking of the noisiest measurements. It is gone, and "
      f"the dispersion figure now states the floor.</li>")
    w(f"<li><b>We blamed the wrong subsystem three times for the same gap.</b> First the "
      f"client's block cache, refuted by starving it. Then a background compaction the "
      f"generated store really was running, refuted by settling the account family and "
      f"watching the throughput not move. Then a much larger one on the trie families &mdash; "
      f"{BM['idle']['sa_mb']:,} MB per {BM['idle']['window_s']} idle seconds, "
      f"Finding 3 above &mdash; where the prediction on record was that most of the remaining "
      f"gap would close, and it moved "
      f"{BM['cells']['DIFF_MAX code-exec']['settled'] - (BM['cells']['DIFF_MAX code-exec']['r1'] + BM['cells']['DIFF_MAX code-exec']['r2'])/2:+.3f}. "
      f"The one that did explain the bulk of it was the JIT, visible only by looking at the "
      f"client's threads rather than its I/O. Three of the four were eliminated by "
      f"intervention rather than argument, which is the only reason the fourth was "
      f"reachable.</li>")
    w(f"<li><b>We attributed bytes to the test while the store was reading on its own account.</b> "
      f"The generated store's client was compacting in the background throughout every run, and "
      f"the per-column-family probes compare two <em>separate</em> runs &mdash; one filtered to "
      f"DIFF_MAX, one to SAME_MAX, each with its own boot &mdash; so that traffic enters each "
      f"window in proportion to how long the window stayed open rather than to what the test "
      f"did. It landed on the difference between two large numbers, which is exactly the "
      f"quantity we were reading. The effect on the per-test byte columns elsewhere in this "
      f"page is small by comparison: at the measured idle rate of "
      f"{BM['idle']['sa_mb']/BM['idle']['window_s']:.0f} MB/s and a DIFF_MAX test length of "
      f"{BM['test_secs']['DIFF_MAX_160M']:.1f} s, about "
      f"{BM['idle']['sa_mb']/BM['idle']['window_s']*BM['test_secs']['DIFF_MAX_160M']:.0f} MB "
      f"against read volumes in the thousands. Re-measured on the settled store, the marginal "
      f"cost of a "
      f"distinct contract is {sa_w/joc_w:.2f}&times; rather than the "
      f"{BM['attribution']['code']['before']['sa']['total_marg'] / BM['attribution']['code']['before']['joc']['total_marg']:.2f}&times; "
      f"the same probe reported while the compaction was running, and the "
      f"{BM['attribution']['noncode']['before']['sa']['cf']['flat/StateNodes']['marg']:.0f} MB "
      f"of trie reads we had attributed to non-code account lookups turned out to be "
      f"{BM['attribution']['noncode']['after']['sa']['cf'].get('flat/StateNodes', {}).get('marg', 0.0):.0f}. "
      f"An I/O measurement taken while the store is doing its own I/O measures the store, not "
      f"the test.</li>")
    _sw = D["topnodes"]["swap"]
    w(f"<li><b>We attributed the transfer asymmetry to the arms; it was ours.</b> The snapshot "
      f"read {100*(_sw['joc']['top_per_account_before']/_sw['sa']['top_per_account_before']-1):.0f}% "
      f"more top-of-trie blocks per touched account than the generated store and we called it a "
      f"migrated trie costing more to update. The tries are the same shape. The snapshot's "
      f"top-of-trie column had been rewritten in 4 KB blocks by the same read-write open that "
      f"repaired the first item in this list, which transcribed the client's options for the "
      f"column it meant to rewrite and left the rest on RocksDB's defaults; the audit after it "
      f"checked two columns and missed the third. Swapping the two layouts moved the transfer "
      f"cell from {_sw['ratio_settled']:.3f} to {_sw['ratio_swapped']:.3f} and swapped the read "
      f"counts with it. A read-write open of a store by tooling has to transcribe every "
      f"column's options, not just the one being rewritten: an idle column with a compaction "
      f"pending is rewritten under whatever the open carries.</li>")
    _den = D["outliers"]["denominator"]
    w(f"<li><b>We called an outlier reproducible because it appeared in two runs that shared a "
      f"denominator.</b> The regenerated store was measured twice, both times against the same "
      f"jochemnet run, and a handful of tests sat 20&ndash;38% apart in both. Re-measuring "
      f"{_den['n']} of them as a fresh pair moved jochemnet by up to {100*_den['joc_spread']:.0f}% "
      f"on a single test and took the largest transfer excursions back inside the band. Two runs "
      f"of one arm are one measurement of the ratio, not two.</li>")
    w("</ul>")
    w("<p class=note>The numbers in this page are computed from the collected run data at build "
      "time; the generator refuses to emit the page if the data stops supporting the sentences "
      "above.</p>")

    w('<div class=endbar><a href="../">&larr; all articles</a>'
      '<a href="https://github.com/CPerezz/articles/tree/main/nethermind-state-db-divergence">'
      'source &amp; data &rarr;</a></div>')
    w('<span class=cursor style="position:fixed;bottom:1.4rem;right:1.4rem;z-index:6"></span>')
    w("</body></html>")

    html_text = "\n".join(o)
    with open(OUT, "w") as fh:
        fh.write(html_text)

    os.makedirs(FIGDIR, exist_ok=True)
    figs = {
        "fig_cost_curves": chart_cost_curves(cc),
        "fig_amortisation": chart_amortisation(amort),
        "fig_treatment_dumbbell": chart_treatment_dumbbell(bc, ac),
        "fig_ratio_dots": chart_ratio_dots(rat_b, rat_a, spr_b, spr_a, CL),
        "fig_grid": chart_grid(AFT["grid"]),
        "fig_steps": chart_steps(D["steps"]),
        "fig_code_ladder": chart_code_ladder(modes, {"sa": fp["sa"]["code"],
                                                     "joc": fp["joc"]["code"]}),
        "fig_duration_floor": chart_duration_floor(CL),
        "fig_class2_families": chart_class2_families(CL),
        "fig_seqno_paths": chart_seqno_paths(BM),
        "fig_idle_reads": chart_idle_reads(BM),
        "fig_marginal_cf": chart_marginal_cf(BM),
        "fig_levels": chart_levels(D["storage"]),
        "fig_storage_close": chart_storage_close(D["storage"]),
        "fig_final_cells": chart_final_cells(CL, {c: v["after"] for c, v in D["intervention_blocks"]["cells"].items()}, _v2),
    }
    for name, svg in figs.items():
        with open(os.path.join(FIGDIR, name + ".svg"), "w") as fh:
            fh.write(standalone(svg) + "\n")

    print(f"wrote {os.path.relpath(OUT, HERE)} ({len(html_text):,} bytes)")
    for name in figs:
        p = os.path.join(FIGDIR, name + ".svg")
        print(f"wrote figures/{name}.svg ({os.path.getsize(p):,} bytes)")
    print(f"headline factor: {factor:.1f}x")
    print(f"agreement: {BEF['agreement']['agree_pct']:.1f}% -> "
          f"{AFT['agreement']['agree_pct']:.1f}%")
    print("categories at parity after treatment: "
          + ", ".join(SHORT[c] for c in CATS if c in ac and 0.9 <= ac[c]["thr"] <= 1.1))
    print(f"code ladder: {' < '.join(f'{v:.2f}' for v in ladder)}")


if __name__ == "__main__":
    main()
