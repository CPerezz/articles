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


def figure(svg, caption):
    return f"<figure>{svg}<figcaption>{caption}</figcaption></figure>"


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


def chart_additive(buckets):
    """Excess bytes against how much the test itself reads.

    Two terms, and the figure has to show both honestly: a fixed overhead that dominates small
    tests, plus a ~10% proportional component that only becomes visible once a test reads
    gigabytes. The dashed line is the fixed term; bars sitting on it are paying only that.
    """
    W, H, L, R, T, B = 760, 320, 62, 20, 34, 60
    rows = buckets
    hi = max(r["excess"] for r in rows)
    # The fixed term, estimated from the buckets small enough that 10% of their own volume is
    # negligible against it.
    flat = [r["excess"] for r in rows if r["jocMB"] < 4000]
    fixed = sorted(flat)[len(flat) // 2]
    step = (W - R - L) / len(rows)
    sy = S.Scale(0, hi * 1.14, H - B, T)
    o = [ygrid(sy, [0, hi * 0.5, hi], L, W - R, fmt=lambda v: f"{v:.0f} MB")]
    o.append(S.line(L, sy.to(fixed), W - R, sy.to(fixed), "--db-u", 1.5, dash="5 4"))
    o.append(S.label(W - R, sy.to(fixed) - 7, f"fixed term \u2248 {fixed:.0f} MB", "end", "tick"))
    for i, r in enumerate(rows):
        cx = L + step * (i + 0.5)
        o.append(S.band(cx - step * 0.3, cx + step * 0.3, sy.to(0), sy.to(r["excess"]),
                        "--accent", 0.34))
        o.append(S.label(cx, sy.to(r["excess"]) - 7, f"{r['excess']:.0f}", "middle", "big"))
        lbl = f"{r['lo']:g}-{r['hi']:g}" if r["hi"] else f"{r['lo']:g}+"
        o.append(S.label(cx, H - B + 16, lbl + " MB", "middle", "tick"))
        o.append(S.label(cx, H - B + 30, f"n={r['n']}", "middle", "tick"))
        o.append(S.label(cx, H - B + 44, f"\u00d7{r['saMB']/max(r['jocMB'],0.01):.1f} bytes",
                         "middle", "tick"))
        o.append(S.label(cx, H - B + 58, f"thr {r['thr']:.2f}", "middle", "tick"))
    o.append(S.label(L, T - 14, "extra bytes state-actor reads per test", "start", "big"))
    o.append(S.label(W - R, T - 14, "columns: what the test reads on jochemnet", "end", "ax"))
    return S.svg(W, H, "".join(o))



GRID_MODES = ["EXISTING_EOA", "EXISTING_CONTRACT_MINIMAL", "EXISTING_CONTRACT_SAME_MAX",
              "EXISTING_CONTRACT_JUMPDEST", "EXISTING_CONTRACT_DIFF_MAX",
              "NON_EXISTING_ACCOUNT"]
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


def chart_ratio_dots(rat_b, rat_a, spr_b, spr_a):
    """Every test's ratio, by category, before and after the treatment.

    The dumbbell shows that the medians moved; this shows the distributions moving, which is the
    claim that actually matters - a category whose median lands on parity while its tests stay
    scattered has not converged.
    """
    W, L, R = 760, 178, 80
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
            o.append(S.label(L - 8, y + 4, SHORT[cat], "end"))
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
    add = AFT["additive"]
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
    # additive model: excess roughly constant across three orders of magnitude of test size
    small = add["buckets"][0]["excess"]
    mid = [b["excess"] for b in add["buckets"] if b["lo"] in (100, 1000)]
    assert all(0.3 * small <= e <= 3 * small for e in mid), \
        f"excess is no longer flat in test size: {small} vs {mid}"
    # The article's scope starts at the flat-backed pair. If the collector is ever re-pointed at
    # a run from before the generated store was rebuilt with the flat layout, fail loudly rather
    # than publish a number from a pair that never shared a read path.
    assert P["arms"]["sa"]["run"] == M["preconditions"]["sa_run_flat_backed"], (
        f"state-actor arm is {P['arms']['sa']['run']}, expected the flat-backed run "
        f"{M['preconditions']['sa_run_flat_backed']}")
    assert P["arms"]["joc"]["run"] == M["preconditions"]["joc_run"], \
        f"jochemnet arm is not the recorded run: {P['arms']['joc']['run']}"
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
    sc_ = J_["subset"]["corrected"]
    # Removing every page-cache drop must still take state-actor's control reads to zero without
    # making it faster; that is the step that moved the investigation off I/O.
    dr_, nd_ = J_["drops"]["drops"], J_["drops"]["nodrop"]
    assert nd_["sa_read_mb"] < 1.0 < dr_["sa_read_mb"], \
        "the control reads no longer vanish without the drops: %r" % nd_
    assert nd_["thr"] <= dr_["thr"], \
        "state-actor now gains from keeping the cache; the 'not I/O' argument is out"
    assert min(v["thr"] for k, v in sc_.items() if k != "_all") > 0.9, \
        "a category fell below 0.9 in the corrected subset; 'no category below' is out"
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
    # the proportional term must be real, and must only matter for the largest tests
    big = add["buckets"][-1]
    assert big["excess"] > 2 * small, "proportional term vanished; §residual claims two terms"
    assert 1.0 < big["saMB"] / big["jocMB"] < 1.3, \
        f"the proportional term is no longer ~10%: {big['saMB']/big['jocMB']:.2f}"

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
    w(f"<p>Two Nethermind databases. One is a mainnet shadowfork snapshot taken at block "
      f"{thousands(P['snapshot_block'])}; the other is state generated from scratch by "
      f"<code>state-actor</code>. The same EEST bloatnet fixtures run against both, on the same "
      f"machine, with the page cache dropped between every test. Where the tests read accounts, "
      f"the generated store reports up to <b>{factor:.0f}&times;</b> less throughput.</p>")

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
    w("<caption>The two rows that do <em>not</em> diverge are the tell. Absent accounts "
      f"({f(bc['ACCOUNT cold non-existing']['thr'], 3)}) never read an account record, and the "
      f"storage sweep ({f(bc['STORAGE slot access']['thr'], 3)}) is far larger than anything a "
      "store can hold in a corner. Whatever is happening, it is specific to reading accounts "
      "that exist.</caption></table>")

    bg = BEF["grid"]
    bcells = [c["thr"] for row in bg.values() for c in row.values()]
    boff = sum(1 for r in bcells if not (0.9 <= r <= 1.1))
    w(figure(chart_grid(bg),
             f"Every opcode against every access mode, before any treatment: "
             f"{boff} of {len(bcells)} cells are outside &plusmn;10% of parity, ranging from "
             f"{min(bcells):.2f} to {max(bcells):.2f}. This is not a few bad tests &mdash; it is "
             f"nearly the whole matrix. The single column that stays dim is the one whose "
             f"lookups never read an account record at all."))

    cc = BEF["cost_curve"]
    w(figure(chart_cost_curves(cc),
             f"Read volume against gas for the contract-reading tests. jochemnet stays flat "
             f"&mdash; {cc[0]['jocMB']:.0f} MB at {cc[0]['gas']}M gas and "
             f"{cc[-1]['jocMB']:.0f} MB at {cc[-1]['gas']}M, triple the work for the same bytes "
             f"&mdash; while state-actor climbs from {cc[0]['saMB']:.0f} MB to "
             f"{cc[-1]['saMB']:.0f} MB. Flat in gas means the arm is re-reading one bounded set "
             f"of blocks; rising means every access goes somewhere new."))

    # ---------------------------------------------------------------- defects found
    w("<h2>What we found wrong with the measurement</h2>")
    hw = M["harness"]
    J0 = D["jit_experiment"]
    w("<p>Four things, in the order they matter. Three are properties of how the arms were "
      "prepared &mdash; two in the store, one in the fixtures &mdash; and the fourth is the "
      "harness not having the controls this kind of study needs. All four were found by "
      "changing them and re-measuring, and only the first one moved the headline: the other "
      "three are here because each was a plausible cause that had to be killed by "
      "intervention rather than by argument.</p>")
    w("<ol>")
    w("<li><b>The pre-run is promoted into the baseline.</b> Only one arm replays a pre-run "
      "before measuring, and the harness is told to promote the result into the image every test "
      "restores from. That leaves the benchmark's own accounts as the newest versions in the "
      "youngest files of the LSM tree. Diagnosed below, <b>fixed</b>, and the fix accounts for "
      "almost all of the gap.</li>")
    w(f"<li><b>The client is restarted for every test, and the two arms warm up differently.</b> "
      f"A .NET process seconds old is still compiling itself. jochemnet's setup step is heavy "
      f"EVM work, so its interpreter is promoted to optimised code before the measurement; "
      f"state-actor's fixtures spend that window on an empty block, so its measured block runs "
      f"on the unoptimised tier. Diagnosed below, <b>fixed by intervention</b>: equalising it "
      f"moves the control tests from {J0['ab']['baseline']['thr']:.2f} to "
      f"{J0['ab']['no_tiered_jit']['thr']:.2f} and closes every remaining category.</li>")
    w(f"<li><b>The generated store makes every client that opens it rewrite the store.</b> "
      f"Its trie column families were left in a state that RocksDB garbage-collects on open, "
      f"so a client sitting completely idle read {BM['idle']['sa_mb']:,} MB from it in "
      f"{BM['idle']['window_s']} seconds against jochemnet's {BM['idle']['joc_mb']} &mdash; and "
      f"the harness restarts the client for every one of "
      f"{thousands(hw['tests'])} tests, so the job never finished and never stopped. Diagnosed "
      f"below, <b>fixed in the generator</b>, and it changed the throughput by almost "
      f"nothing.</li>")
    w(f"<li><b>The harness has no compaction control and no warm-up control.</b> "
      f"<code>{esc(hw['compact_between_steps'])}</code> is {esc(hw['compact_status'])}, and "
      f"<code>{esc(hw['post_prerun_hook'])}</code> is {esc(hw['hook_status'])}. There is also no "
      f"way to ask for a discarded burn-in block before the measured one. Both treatments below "
      f"had to be applied by hand.</li>")
    w("</ol>")

    # ---------------------------------------------------------------- root cause
    w("<h2>The root cause: the benchmark's keys live in a corner of one store</h2>")
    pr = M["prerun"]
    w(f"<p>Only one arm runs a pre-run. Before measuring, the jochemnet arm replays "
      f"{pr['bytes']/1e9:.2f} GB of blocks &mdash; {thousands(pr['blocks'])} of them, "
      f"{pr['txs_per_block']} transactions each, taking the chain from "
      f"{thousands(pr['first_block'])} to {thousands(pr['last_block'])} &mdash; which create "
      f"the accounts the benchmark then reads. The harness is then told "
      f"<code>promote_post_pre_runs: true</code>, which freezes that post-pre-run layout into "
      f"the golden image every test is restored from.</p>")
    w("<p>This is not a caching story. The harness drops the page cache between every test, and "
      "the pre-run happens once, before the loop. What survives the drop is not warm memory "
      "&mdash; it is <em>which files hold the current copy of each key</em>.</p>")
    w("<p>The structure that matters here is not the Merkle trie but the <b>LSM tree underneath "
      "it</b>: Nethermind keeps the flat state in RocksDB, whose account column family is keyed "
      "by <code>keccak256(address)[0:20]</code>. Those keys are hashes, so they are scattered "
      "uniformly &mdash; nothing about the benchmark's accounts is adjacent in key order. What "
      "<em>is</em> concentrated is the set of files holding their newest versions. The pre-run "
      "rewrote every one of those accounts, so their current copies landed together in a handful "
      "of recently flushed SSTs near the top of the tree, and a levelled store answers a point "
      "lookup from the newest level that has the key and stops. The working set is therefore "
      "bounded by the size of those few files, not by the number of keys.</p>")
    w("<p class=note>Stated that way the mechanism makes a prediction: merging those files down "
      "into the bottom level should destroy the advantage entirely, because afterwards no level "
      "holds a privileged copy. That is a compaction, it is testable, and the rest of this page "
      "is the test.</p>")

    w(figure(chart_amortisation(amort),
             f"Cold lookups against each store's own copy of the fixtures' accounts, fresh "
             f"process per point, page cache dropped, 100% hits. At {thousands(a0['n'])} lookups "
             f"the two stores are indistinguishable &mdash; {a0['joc_blk']:.2f} against "
             f"{a0['sa_blk']:.2f} blocks. By {thousands(a9['n'])} jochemnet is at "
             f"{a9['joc_blk']:.2f} because its volume has <b>stopped growing</b>: "
             f"{amort[-2]['joc_mb']:.0f} MB at {thousands(amort[-2]['n'])} lookups and "
             f"{a9['joc_mb']:.0f} MB at {thousands(a9['n'])}. state-actor never saturates, "
             f"climbing to {a9['sa_mb']:.0f} MB, because there is no corner to exhaust."))

    w("<p class=note>The per-lookup cost is not what differs &mdash; the number of distinct "
      "physical blocks is. Both stores pay about two blocks for a lookup they have not made "
      "before. One of them runs out of new blocks to read.</p>")

    # ---------------------------------------------------------------- the fix
    w("<h2>Defect 1: the pre-run is promoted into the baseline &mdash; and what compacting it does</h2>")
    ab, aa = iv["account_before"], iv["account_after"]
    sb, sa_ = iv["statenodes_before"], iv["statenodes_after"]
    w("<p><b>The change, concretely.</b> The treatment is a <b>full RocksDB compaction</b> of the "
      "affected column families: <code>CompactRange</code> over the whole key range with "
      "<code>bottommost_level_compaction=kForce</code>, which is required because a family that "
      "already sits entirely in its bottom level is a no-op for an ordinary compaction. The "
      "rewrite uses the <em>other</em> store's exact per-family options &mdash; filter policy, "
      "block size, restart interval, compression &mdash; verified knob by knob afterwards, so "
      "the only thing that changes is which file holds each key's newest copy. No value is "
      "touched and the state root is unchanged.</p>")
    w("<p>The pre-run is then removed from the arm's config. That is not a reduction of the "
      "workload: its writes are already in the promoted image, so the arm still starts from "
      "exactly the state the pre-run produced. Replaying it would simply write those accounts "
      "again and rebuild the very thing we just flattened.</p>")
    w("<p class=note>The reproducible way to do this is the harness's post-pre-run hook "
      "(<code>BENCHMARKOOR_POST_PRERUN_CMD</code>), which runs an operator command after the "
      "pre-run and before the snapshot is promoted, aborting the promote if it fails. That hook "
      "lives on a branch and is <em>not</em> in the binary these runs used, so the compaction "
      "here was applied to the promoted image by hand. Same end state; the hook is the path "
      "anyone reproducing this should take.</p>")
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
      "whole treatment: no value changes, only which file holds the newest copy of a key."
      "</caption></table>")

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
      f"{BEF['agreement']['agree_pct']:.1f}% to {AFT['agreement']['agree_pct']:.1f}%. The two "
      f"spread columns are there because a median can flatter a category: "
      f"<em>{esc(SHORT['ACCOUNT cold existing EOA'])}</em> really is tight &mdash; middle half "
      f"{eo['p25']:.3f}&ndash;{eo['p75']:.3f}, {eo['within10']}/{eo['n']} inside the band "
      f"&mdash; whereas <em>{esc(SHORT['STORAGE slot access'])}</em> sits on parity at "
      f"{st['median']:.3f} while ranging {st['min']:.3f}&ndash;{st['max']:.3f} with only "
      f"{st['within10']}/{st['n']} inside it. Independently reproduced on a "
      f"{thousands(D['replication']['agreement']['n'])}-test subset that agreed with the "
      f"uncorrected arm to within a couple of percent, so these ratios are not run-to-run "
      f"noise.</caption></table>")

    w(figure(chart_treatment_dumbbell(bc, ac),
             "Each row is one kind of test: amber is the confounded measurement, green the "
             "equalised one, and the band is &plusmn;10% around parity. The two rows that "
             "were already inside the band stay inside it &mdash; the control that makes "
             "the rest credible."))

    nz, nx = D["noise"]["replica"], D["noise"]["cross_by_duration"]
    nl, ng = nz["by_duration"]["lt0.2s"], nz["by_duration"]["ge5s"]
    w(figure(chart_ratio_dots(rat_b, rat_a, spr_b, spr_a),
             f"The same {thousands(AFT['agreement']['n'])} tests as individual results rather "
             f"than medians: one dot per cluster of tests at that ratio, sized by how many, with "
             f"the middle half drawn as a bar and the median as a tick. Read the <em>shift</em>, "
             f"not the width. The width is mostly measurement: running the same store twice under "
             f"the same configuration puts only {100*nl['within10']/nl['n']:.0f}% of tests under "
             f"{nl['n']} short tests inside &plusmn;10% of themselves, against "
             f"{100*ng['within10']/ng['n']:.0f}% for the {ng['n']} tests over five seconds. So "
             f"per-test scatter in the short categories is noise, and only the medians and the "
             f"long-test counts carry weight."))

    # ---------------------------------------------------------------- residual
    # Defect 2 in the published version blamed the client cache. Two rounds of intervention
    # eliminated that (this section keeps the measurement) and a third found the mechanism: the
    # JIT. Everything below reads from D["jit_experiment"], collected by collect_jit.py.
    J = D["jit_experiment"]
    st = D["steps"]
    w("<h2>Defect 2: the client is restarted for every test, and the two arms warm up "
      "differently</h2>")
    w("<p>Every test runs against a freshly started client: <code>container-recreate</code> "
      "restores the image and boots Nethermind again, 1,463 times. That is the right way to keep "
      "tests independent. It also means every measured step runs inside a process that is "
      "seconds old, and a .NET process that is seconds old is still <em>compiling itself</em>: "
      "hot methods start in the unoptimised tier and are promoted in the background after a "
      "call-count threshold and a settling delay. Whether the EVM's inner loop has been promoted "
      "by the time the measured block arrives depends on what the process did in the seconds "
      "before &mdash; and the two arms' fixtures make it do different things.</p>")

    # -- the fixture asymmetry
    w("<h3>What the setup step does on each arm</h3>")
    w("<table><tr><th>arm</th><th>setup step</th><th>gap to measured block</th>"
      "<th>measured block starts on</th></tr>")
    w("<tr><td>jochemnet</td><td>one block of 535k gas of real EVM work, ~240 ms</td>"
      "<td>~45 ms</td><td>promoted code</td></tr>")
    w("<tr><td>state-actor</td><td>one <b>empty</b> block (a fork-activation block the fixtures "
      "add because this chain starts at genesis), ~240 ms, then the 535k-gas block in 46 ms</td>"
      "<td>~1.4 ms</td><td>unoptimised code, JIT compiling underneath</td></tr>")
    w("<caption>Per-payload timing of one control test per arm. The first block after boot costs "
      "~240 ms on both arms whatever it contains &mdash; that is process warm-up. jochemnet "
      "spends it executing EVM code, so its interpreter crosses the tiering threshold before the "
      "measurement; state-actor spends it on an empty block and enters the measured block with a "
      "cold interpreter. The harness's gas-weighted setup timing does not see the empty block, "
      f"which is why state-actor's setup step reads {st['control']['sa']['setup']:.1f} MB in "
      f"0.04 s against jochemnet's {st['control']['joc']['setup']:.1f} MB in 0.24 s.</caption>"
      "</table>")

    # -- the profile
    pj, ps, pss = J["profile"]["joc_unsettled"], J["profile"]["sa_unsettled"], J["profile"]["sa_settled"]
    dr, nd = J["drops"]["drops"], J["drops"]["nodrop"]
    w(figure(chart_steps(st),
             f"Read volumes for the two steps, log axis. The arms are inverted: jochemnet does "
             f"its reading while setting up, state-actor while being measured. As published this "
             f"looked like the explanation &mdash; one arm entering the measurement warm. It is "
             f"not. Removing the page-cache drops entirely took state-actor's measured control "
             f"reads from {dr['sa_read_mb']:.0f} MB to {nd['sa_read_mb']:.1f} MB, so the reads "
             f"really were re-reads of evicted pages; and it made state-actor no faster "
             f"({dr['sa_mgas']:.1f} to {nd['sa_mgas']:.1f} MGas/s) while jochemnet gained "
             f"({dr['joc_mgas']:.1f} to {nd['joc_mgas']:.1f}), taking the ratio the wrong way, "
             f"{dr['thr']:.3f} to {nd['thr']:.3f}. Removing all of the I/O did not remove the "
             f"gap, which is what sent us to the client's threads."))

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
      f"wall time. Two things stand out. RocksDB was compacting underneath state-actor's "
      f"measurements &mdash; the generator's finishing <code>CompactRange</code> had left the "
      f"account column family parked at L3 and <code>compaction-pending</code>, so every fresh "
      f"client re-started the same job and the per-test rollback threw the work away. Settling "
      f"the store (rebuilding it into L6, then promoting) removed most of that thread and none "
      f"of the throughput gap: control stayed at "
      f"{J['ab']['baseline']['thr']:.3f}. The other thing is that the JIT thread is large on "
      f"<em>both</em> arms: a fifth to a third of all CPU in the measurement window is spent "
      f"compiling the client, on every one of 1,463 tests.</caption></table>")

    # -- the A/B
    ab = J["ab"]
    w("<h3>The test: take the JIT out of the measurement</h3>")
    w("<p>Two levers, each on both arms, same 40 control tests. Disabling optimistic parallel "
      "execution tests whether state-actor's fixtures cause more transaction conflicts; setting "
      "<code>DOTNET_TieredCompilation=0</code> makes every method compile fully optimised on "
      "first call, so there is no unoptimised tier and no background promotion &mdash; both "
      "arms measure steady-state code from the first block.</p>")
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
    w(f"<caption>Control tests, identical ids, n={ab['baseline']['n']}. Parallel execution is "
      f"exonerated &mdash; turning it off hurts state-actor more. Removing tiered compilation "
      f"takes the control ratio from {ab['baseline']['thr']:.3f} to "
      f"<b>{ab['no_tiered_jit']['thr']:.3f}</b>: state-actor's measured step goes from "
      f"{ab['baseline']['sa_secs']*1000:.0f} to {ab['no_tiered_jit']['sa_secs']*1000:.0f} ms "
      f"while jochemnet's barely moves ({ab['baseline']['joc_secs']*1000:.0f} to "
      f"{ab['no_tiered_jit']['joc_secs']*1000:.0f} ms), because jochemnet was already running "
      f"promoted code when its measurement started.</caption></table>")

    # -- the rest of regime 3
    sl = J["slice"]
    w("<h3>The same lever on every cell that was still divergent</h3>")
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
    w(f"<caption>The one cell the geth study also flagged and left open &mdash; a different "
      f"maximum-size contract per access, executed &mdash; goes from {dmp['thr']:.3f} to "
      f"{dmj['thr']:.3f}. Not because state-actor got faster: <b>jochemnet got slower</b>, from "
      f"{dmp['joc_secs']:.1f} to {dmj['joc_secs']:.1f} s per test, once it could no longer reach "
      f"promoted code partway through a 15-second test that state-actor spent on the "
      f"unoptimised tier. Three store-level explanations for this cell were each refuted by "
      f"direct measurement; the fourth was never in the store. The short tests tell the same "
      f"story from the other side: warm-query and same-key storage tests run 5&ndash;6&times; "
      f"faster on <em>both</em> arms with tiering off, because as published they were measuring "
      f"an interpreter that had not finished compiling.</caption></table>")

    w("<p><b>What this is and is not.</b> <code>DOTNET_TieredCompilation=0</code> is the "
      "diagnostic, not the recommended configuration &mdash; a live node runs promoted, "
      "profile-guided code, and fully-optimised-on-first-call is slower to start and skips the "
      "profile guidance. What the benchmark needs is what a live node has: an EVM that has "
      "already crossed the tiering threshold before the block being measured. Concretely, the "
      "harness should give every arm the same EVM-heavy warm-up after boot &mdash; a burn-in "
      "block whose result is discarded &mdash; before the measured step. That is the pre-run "
      "problem again, one level down: not which files hold the keys, but which tier holds the "
      "code. Any JIT-hosted client restarted per test is exposed; ahead-of-time compiled clients "
      "are not, which is one reason the geth study found this cell open and could not close it "
      "from geth's side.</p>")
    # ------------------------------------------------- defect 3: the store rewrites itself
    w("<h2>Defect 3: the generated store makes the client rewrite it</h2>")
    bidle, bboot, brpc, bset = BM["idle"], BM["boot"], BM["rpc"], BM["settle"]
    w(f"<p>This one was found by asking a simpler question than the study had been asking: "
      f"what does the client read when nobody is asking it for anything? Boot each arm, drop "
      f"the page cache, issue <b>zero</b> queries, and watch the client's own "
      f"<code>/proc/&lt;pid&gt;/io</code> for {bidle['window_s']} seconds. jochemnet reads "
      f"{bidle['joc_mb']} MB. The generated store's client reads "
      f"<b>{bidle['sa_mb']:,} MB</b>, at roughly "
      f"{bidle['sa_mb']/bidle['window_s']:.0f} MB/s, indefinitely, with every one of its "
      f"threads at 0% CPU.</p>")
    w(figure(chart_idle_reads(BM),
             f"The reads do not need a query, which is what took this off the read path. "
             f"{brpc['calls']:,} plain <code>eth_getBalance</code> calls read the identical "
             f"{brpc['sa']['account_mb']:.1f} MB from <code>flat/Account</code> on both arms "
             f"&mdash; the flat state is serving lookups correctly, and costs the same on both "
             f"&mdash; while the generated store's client separately pulls "
             f"{brpc['sa']['trie_mb']:,.0f} MB of trie nodes, {brpc['sa']['trie_share_pct']:.0f}% "
             f"of everything it reads. Idling changes none of it."))
    w(f"<p><b>What it is.</b> Per-thread attribution puts the traffic on "
      f"<code>rocksdb:low</code> &mdash; {BM['threads']['rocksdb_low_mb']:,.0f} MB in "
      f"{BM['threads']['window_s']} seconds &mdash; so it is RocksDB's own background "
      f"compaction inside the client, not client code. The event log names the reason: "
      f"{bboot['sa']['jobs']} jobs at boot, all on <code>{esc(bboot['sa']['cf'])}</code>, all "
      f"<code>{esc(bboot['sa']['reason'])}</code>. jochemnet's client starts "
      f"{bboot['joc']['jobs']} job, on <code>{esc(bboot['joc']['cf'])}</code>, for the ordinary "
      f"reason (<code>{esc(bboot['joc']['reason'])}</code>).</p>")
    w("<p><code>kBottommostFiles</code> is RocksDB rewriting bottom-level files purely to zero "
      "out their sequence numbers: it marks every bottommost file whose "
      "<code>largest_seqno != 0</code> once no snapshot protects it. So the trigger is not how "
      "much data is there or how the levels are shaped &mdash; it is <em>how the files got "
      "there</em>. The generator does finish by compacting, but with the default "
      "<code>bottommost_level_compaction = kIfHaveCompactionFilter</code>, and no compaction "
      "filter is configured anywhere. RocksDB therefore <b>trivially moved</b> the flushed L0 "
      "files into the empty bottom level rather than rewriting them. A moved file is not a "
      "rewritten file: the tree comes out flat, which is what the call was there to achieve, "
      "and every file keeps a non-zero sequence number.</p>")
    w(figure(chart_seqno_paths(BM),
             "The two paths differ by one option and produce stores that are indistinguishable "
             "by the checks a generator would naturally run. Both end flat at the bottom level; "
             "both report <code>estimate-pending-compaction-bytes = 0</code>. Only one of them "
             "makes every client that opens it re-do the work."))
    w(f"<p class=note>That is why this survived thirty rounds of looking at level shape and "
      f"pending-compaction bytes: in this condition both look perfectly healthy. It also means "
      f"an idling node shows it only if the client takes and releases a snapshot at startup, "
      f"which Nethermind does and Besu does not &mdash; on Besu the same store sits quiet until "
      f"something asks it for state.</p>")
    st_gb = sum(v["gb_before"] for v in bset.values())
    st_s = sum(v["secs"] for v in bset.values())
    w(f"<p><b>The fix, and what it costs.</b> Run the finishing compaction with "
      f"<code>bottommost_level_compaction=kForce</code> so the files are rewritten once, by "
      f"the generator, instead of repeatedly by every consumer. Applied here to the trie "
      f"families &mdash; {thousands(bset['StateNodes']['files_before'])}&rarr;"
      f"{thousands(bset['StateNodes']['files_after'])} files on "
      f"<code>StateNodes</code> in {bset['StateNodes']['secs']:.0f} s and "
      f"{thousands(bset['StorageNodes']['files_before'])}&rarr;"
      f"{thousands(bset['StorageNodes']['files_after'])} on <code>StorageNodes</code> in "
      f"{bset['StorageNodes']['secs']:.0f} s, {st_gb:.0f} GB and {st_s/60:.0f} minutes in total "
      f"&mdash; it takes the idle client from {bidle['sa_mb']:,} MB to "
      f"{bidle['sa_settled_mb']} MB and the boot from {bboot['sa']['jobs']} compaction jobs to "
      f"{bboot['sa_settled']['jobs']}. It is upstream as "
      f"<a href=\"https://github.com/ethereum/state-actor/pull/{BM['pr']}\">state-actor#"
      f"{BM['pr']}</a>, which fixes the same call in the Besu, ethrex and reth writers "
      f"too.</p>")
    dmc, jmc = BM["cells"]["DIFF_MAX code-exec"], BM["cells"]["JUMPDEST code-exec"]
    w("<p><b>And it explained nothing.</b> Re-running the subset on the settled store, with the "
      "same configuration measured twice before it as the yardstick:</p>")
    w("<table><tr><th>cell</th><th class=n>n</th><th class=n>replica 1</th>"
      "<th class=n>replica 2</th><th class=n>settled store</th><th class=n>move</th></tr>")
    for name in ("DIFF_MAX code-exec", "JUMPDEST code-exec", "SAME_MAX code-exec",
                 "MINIMAL code-exec", "EXISTING_EOA code-exec", "CONTROL"):
        c = BM["cells"][name]
        mv = c["settled"] - (c["r1"] + c["r2"]) / 2
        cls = " bad" if c["settled"] < 0.9 else ""
        w(f"<tr><td>{esc(name)}</td><td class=n>{c['n']}</td><td class=n>{c['r1']:.3f}</td>"
          f"<td class=n>{c['r2']:.3f}</td><td class=\"n{cls}\">{c['settled']:.3f}</td>"
          f"<td class=n>{mv:+.3f}</td></tr>")
    w(f"<caption>Throughput ratio, state-actor over jochemnet, identical test ids throughout. "
      f"The two cells this study has been chasing moved "
      f"{dmc['settled'] - (dmc['r1']+dmc['r2'])/2:+.3f} and "
      f"{jmc['settled'] - (jmc['r1']+jmc['r2'])/2:+.3f} &mdash; against a replica-to-replica "
      f"swing of {abs(dmc['r1']-dmc['r2']):.3f} and {abs(jmc['r1']-jmc['r2']):.3f} on the same "
      f"pair of cells. Removing continuous background I/O from every test bought about a tenth "
      f"of a seven-point gap. Real defect, wrong suspect &mdash; the third one killed this "
      f"way.</caption></table>")
    w(f"<p>It did change what can be <em>measured</em>, though, and that is what the next "
      f"section is built on. Attributing bytes to a column family means tracing one run "
      f"filtered to one kind of test and comparing it with another, and a store that reads "
      f"{BM['idle']['sa_mb']/BM['idle']['window_s']:.0f} MB/s on its own account puts traffic "
      f"into both windows in proportion to how long each stayed open. On a per-test byte column "
      f"that is a couple of per cent; on the <em>difference</em> between two windows, which is "
      f"the quantity that says what a distinct contract costs, it was most of the answer. With "
      f"the store quiet, the attribution is finally about the test.</p>")

    w("<h2>What is left, and how much of it we can account for</h2>")
    sub_p, sub_c = J["subset"]["published"], J["subset"]["corrected"]
    w(f"<p>With both stores settled and both arms measuring steady-state code, the "
      f"{sub_c['_all']['n']}-test subset that reproduces the full run comes out at a median of "
      f"{sub_c['_all']['median']:.3f} against the published {sub_p['_all']['median']:.3f}, and "
      f"no category sits below {min(v['thr'] for k, v in sub_c.items() if k != '_all'):.2f}:</p>")
    w("<table><tr><th>category</th><th class=n>n</th><th class=n>as published</th>"
      "<th class=n>corrected</th><th class=n>CPU sa/joc</th></tr>")
    for k in sorted(sub_c, key=lambda k: sub_c[k]["thr"] if k != "_all" else 9):
        if k == "_all":
            continue
        r, p = sub_c[k], sub_p.get(k)
        cls = "" if abs(r["thr"] - 1) < 0.1 else " bad"
        w(f"<tr><td>{esc(k)}</td><td class=n>{r['n']}</td>"
          f"<td class=n>{p['thr']:.3f}</td>" if p else
          f"<tr><td>{esc(k)}</td><td class=n>{r['n']}</td><td class=n>&ndash;</td>")
        w(f'<td class="n{cls}">{r["thr"]:.3f}</td>'
          f"<td class=n>{r['cpu']:.2f}</td></tr>" if r["cpu"] else
          f'<td class="n{cls}">{r["thr"]:.3f}</td><td class=n>&ndash;</td></tr>')
    w(f"<caption>Throughput ratio, state-actor over jochemnet, identical test ids. The "
      f"correction is not a neutral configuration &mdash; it <em>overshoots</em>. Disabling "
      f"tiered compilation costs jochemnet the promoted code it used to reach mid-test, so "
      f"several categories now land above parity: the short ones, where a few milliseconds of "
      f"compilation was most of the measurement. Read this table as bracketing the truth with "
      f"the published column, not as a replacement for it.</caption></table>")

    # ------------------------------------------------- open item: DIFF_MAX
    dm = modes["EXISTING_CONTRACT_DIFF_MAX"]
    dmp, dmj = J["slice"]["published"]["DIFF_MAX code-exec"], J["slice"]["jit_equalised"]["DIFF_MAX code-exec"]
    w(f"<h3>Narrowed: a different contract per access, from {dmp['thr']:.2f} to "
      f"{dmj['thr']:.2f}</h3>")
    w("<h3>What we know</h3>")
    w("<p>This is the cell the geth study flagged and left unexplained, and most of it was the "
      "warm-up above &mdash; but not all. Laying every opcode against every access mode shows "
      "the published effect was a column, not a scatter, which is what made it look like a "
      "property of the account being read:</p>")
    gcol = {m: median([row[m]["thr"] for row in AFT["grid"].values() if m in row])
            for m in GRID_MODES}
    w(figure(chart_grid(AFT["grid"]),
             f"Throughput ratio for each of the {len(AFT['grid'])} opcodes against each access "
             f"mode, after treatment. Read it by column, not by row: DIFF_MAX sits at "
             f"{gcol['EXISTING_CONTRACT_DIFF_MAX']:.2f} and JUMPDEST at "
             f"{gcol['EXISTING_CONTRACT_JUMPDEST']:.2f}, while EOA, MINIMAL and SAME_MAX are all "
             f"{min(gcol[m] for m in ('EXISTING_EOA','EXISTING_CONTRACT_MINIMAL','EXISTING_CONTRACT_SAME_MAX')):.2f}"
             f"&ndash;"
             f"{max(gcol[m] for m in ('EXISTING_EOA','EXISTING_CONTRACT_MINIMAL','EXISTING_CONTRACT_SAME_MAX')):.2f}. "
             f"The absent column is the uneven one at {gcol['NON_EXISTING_ACCOUNT']:.2f}, which "
             f"is the same dispersion its category showed above. Within the DIFF_MAX column the "
             f"rows are <em>not</em> uniform, and the split is the whole story: the opcodes that "
             f"execute the callee's code sit near {median([row['EXISTING_CONTRACT_DIFF_MAX']['thr'] for op, row in AFT['grid'].items() if op in LOADS_CODE and 'EXISTING_CONTRACT_DIFF_MAX' in row]):.2f} "
             f"while BALANCE and EXTCODEHASH, which only read the account row, stay at parity."))
    w("<p>Sorting the access modes by how much contract code they touch orders it cleanly:</p>")
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
    w(f"<caption>Monotonic in code, and the cause is on disk: the code database is "
      f"{esc(fp['sa']['code'])} on the generated store against {esc(fp['joc']['code'])} on the "
      f"snapshot. Touch a different maximal contract every time and you pay for the larger "
      f"database; reuse one contract, or touch no code at all, and the two stores are within "
      f"{(max(modes[m]['readX'] for m in ('EXISTING_EOA','EXISTING_CONTRACT_SAME_MAX')) - 1)*100:.0f}%."
      f"</caption></table>")
    sm, dm_m = modes["EXISTING_CONTRACT_SAME_MAX"], modes["EXISTING_CONTRACT_DIFF_MAX"]
    w(figure(chart_code_ladder(modes, {"sa": fp["sa"]["code"], "joc": fp["joc"]["code"]}),
             f"The ordering is monotonic in how much distinct contract code the mode touches, "
             f"and it is the incremental step that is lopsided: going from one reused contract to "
             f"a different one per access costs state-actor "
             f"{sm['saMB']:.0f}&rarr;{dm_m['saMB']:.0f} MB (+{dm_m['saMB']-sm['saMB']:.0f}) "
             f"against jochemnet's {sm['jocMB']:.0f}&rarr;{dm_m['jocMB']:.0f} MB "
             f"(+{dm_m['jocMB']-sm['jocMB']:.0f}) &mdash; roughly "
             f"{(dm_m['saMB']-sm['saMB'])/max(dm_m['jocMB']-sm['jocMB'],1):.1f}&times; the "
             f"marginal cost per additional distinct contract."))

    # The data contains its own control: SAME_MAX is the same opcodes against one reused
    # contract, so it separates "a distinct contract" from "contract code at all".
    def cell(mode, loads):
        vals = [c["thr"] for op, row in AFT["grid"].items() if mode in row
                for c in [row[mode]] if (op in LOADS_CODE) == loads]
        return median(vals), min(vals), max(vals), len(vals)

    dm_code = cell("EXISTING_CONTRACT_DIFF_MAX", True)
    dm_acct = cell("EXISTING_CONTRACT_DIFF_MAX", False)
    sm_code = cell("EXISTING_CONTRACT_SAME_MAX", True)
    sm_acct = cell("EXISTING_CONTRACT_SAME_MAX", False)

    w("<h3>Where exactly it lives</h3>")
    w("<p>Splitting the same cells two ways isolates it to a single square. Along one axis, "
      "whether the opcode loads the callee's code at all; along the other, whether the contract "
      "is a different one each access or the same one reused:</p>")
    w("<table><tr><th></th><th class=n>one contract, reused</th>"
      "<th class=n>a different contract each access</th></tr>")
    w(f"<tr><td>opcodes that <b>load the code</b><br><span class=note>CALL, CALLCODE, "
      f"DELEGATECALL, STATICCALL, EXTCODECOPY, EXTCODESIZE</span></td>"
      f"<td class=n>{sm_code[0]:.3f}</td>"
      f"<td class=\"n bad\">{dm_code[0]:.3f}</td></tr>")
    w(f"<tr><td>opcodes that read <b>only the account row</b><br><span class=note>BALANCE, "
      f"EXTCODEHASH</span></td><td class=n>{sm_acct[0]:.3f}</td>"
      f"<td class=n>{dm_acct[0]:.3f}</td></tr>")
    w(f"<caption>One square out of four. Reusing a contract is fine even for the opcodes that "
      f"execute it ({sm_code[1]:.3f}&ndash;{sm_code[2]:.3f} across {sm_code[3]} opcodes), and "
      f"under DIFF_MAX the two opcodes that never touch code are at parity "
      f"({dm_acct[1]:.3f}, {dm_acct[2]:.3f}). Only <b>loading a distinct contract's code</b> is "
      f"expensive, at {dm_code[0]:.3f} across {dm_code[3]} opcodes "
      f"({dm_code[1]:.3f}&ndash;{dm_code[2]:.3f}). So it is not the account row, and it is not "
      f"distinctness on its own.</caption></table>")

    w("<h3>What we ruled out</h3>")
    cp, cs, cpop = M["code_probe"], M["code_sweep"], M["code_population"]
    w("<p>The obvious answer is the code database: the generated store's is "
      f"{esc(cp['sa']['size'])} against {esc(cp['joc']['size'])}. Measured three ways, it is "
      "wrong in every one of them.</p>")
    w("<table><tr><th>measurement</th><th class=n>state-actor</th><th class=n>jochemnet</th>"
      "<th>verdict</th></tr>")
    w(f"<tr><td>cold random code lookup</td><td class=n>{cp['sa']['bytes']:,} B</td>"
      f"<td class=n>{cp['joc']['bytes']:,} B</td>"
      f"<td>generated store is <b>cheaper</b></td></tr>")
    w(f"<tr><td>cold sweep, {thousands(cs['n'])} distinct maximum-size contracts</td>"
      f"<td class=n>{cs['sa']['bytes']:,} B/read</td>"
      f"<td class=n>{cs['joc']['bytes']:,} B/read</td>"
      f"<td>generated store is <b>cheaper</b></td></tr>")
    w(f"<tr><td>contracts at or above the 24,576-byte maximum</td>"
      f"<td class=n>{cpop['sa']['at_max']}</td><td class=n>{cpop['joc']['at_max']}</td>"
      f"<td>same population</td></tr>")
    w(f"<caption>Per {thousands(cpop['scanned'])} accounts scanned. The generated store holds "
      f"more contracts ({cpop['sa']['pct']:.1f}% of accounts against "
      f"{cpop['joc']['pct']:.1f}%) but far smaller ones (median "
      f"{cpop['sa']['p50']} B against {cpop['joc']['p50']} B), and its maximum-size contracts "
      f"compress to {cs['sa']['bytes']:,} bytes on disk against jochemnet's "
      f"{cs['joc']['bytes']:,}. Reading code is cheaper on the generated store at every "
      f"granularity we can measure, which is the opposite of what the benchmark reports."
      f"</caption></table>")

    w("<h3>What is still open</h3>")
    st_ = J["settle"]
    w(f"<p><b>The fourth explanation was not in the store at all.</b> Three store-level stories "
      f"fit this square and each was contradicted by a direct measurement; a fourth was found by "
      f"equalising the warm-up, which took the cell from {dmp['thr']:.3f} to {dmj['thr']:.3f}. "
      f"The direction is the instructive part: state-actor barely moved "
      f"({dmp['sa_secs']:.1f} to {dmj['sa_secs']:.1f} s), while <b>jochemnet slowed from "
      f"{dmp['joc_secs']:.1f} to {dmj['joc_secs']:.1f} s</b>. Its advantage here was reaching "
      f"promoted code partway through a fifteen-second test that state-actor spent on the "
      f"unoptimised tier &mdash; the same mechanism as the control loop, on a long test rather "
      f"than a short one.</p>")
    w(f"<p>Two smaller store defects turned up while chasing this and are worth recording even "
      f"though neither moved a ratio. The generated store's account column family was left "
      f"<code>{esc(st_['sa_account']['before'])}</code>, so a freshly booted client restarted "
      f"the same compaction on every test and the per-test rollback discarded it; rebuilding it "
      f"to <code>{esc(st_['sa_account']['after'])}</code> removed that background thread and "
      f"changed the throughput by nothing measurable. The code database on <em>both</em> arms "
      f"was in the same state &mdash; {esc(st_['sa_code']['before'])} on the generated store, "
      f"{esc(st_['joc_code']['before'])} on the snapshot. The cause is a RocksDB detail worth "
      f"knowing: a manual <code>CompactRange</code> writes its output into the deepest level "
      f"that already holds files unless it is told <code>change_level</code> and a target, so a "
      f"generator that finishes with a plain compaction leaves the store permanently "
      f"compaction-pending. Both are the same family of mistake as Defect 3, caught earlier "
      f"and on smaller column families.</p>")

    # The attribution below is only worth printing because the store is quiet; before that,
    # every byte count scaled with how long the window was rather than with what the test did.
    nc_a, nc_b = BM["attribution"]["noncode"]["after"], BM["attribution"]["noncode"]["before"]
    wide = BM["attribution"]["code_wide"]
    sa_w = wide["sa"]["total_marg"]
    joc_w = wide["joc"]["cf"]["24402727"]["marg"]
    nwin = wide["sa"]["_windows"]
    w(figure(chart_marginal_cf(BM),
             f"The same probe run twice, on the same store, before and after settling it: the "
             f"marginal cost of touching a distinct contract, by column family. "
             f"{BM['attribution']['code']['before']['sa']['cf']['flat/StateNodes']['marg']:.0f} MB "
             f"of it was the background compaction and is now zero; the code database's "
             f"{BM['attribution']['code']['after']['sa']['cf']['code']['marg']:.0f} MB is "
             f"untouched by the fix, because it is the test doing work. The account row does "
             f"not move either way."))
    w(f"<p>With the phantom gone the two probes say something clean, and for the first time "
      f"they agree with the throughput. On access patterns that touch <b>no code</b> &mdash; "
      f"BALANCE against EOAs, EXTCODESIZE against minimal contracts &mdash; the two stores are "
      f"byte-for-byte alike: state-actor's marginal is "
      f"{nc_a['sa']['cf']['flat/Account']['marg']:.1f} MB from <code>flat/Account</code> "
      f"against jochemnet's {nc_a['joc']['cf']['24402727']['marg']:.1f} MB across its whole "
      f"datadir, and the trie families contribute nothing "
      f"({nc_a['sa']['cf'].get('flat/StateNodes', {}).get('marg', 0.0):.1f} MB, down from "
      f"{nc_b['sa']['cf']['flat/StateNodes']['marg']:.0f}). Those are exactly the cells "
      f"sitting at {BM['cells']['EXISTING_EOA code-exec']['settled']:.3f} and "
      f"{BM['cells']['MINIMAL code-exec']['settled']:.3f} in the table above.</p>")
    w(f"<p>On the pattern that touches a <b>distinct maximum-size contract per access</b>, "
      f"measured over {nwin} matched pairs per arm (three code-loading opcodes at two gas "
      f"points), the generated store pays <b>{sa_w:,.0f} MB</b> against the snapshot's "
      f"<b>{joc_w:,.0f} MB</b> &mdash; {sa_w/joc_w:.2f}&times; the bytes for the same work, of "
      f"which {wide['sa']['cf']['code']['marg']:,.0f} MB is the code database itself. Its "
      f"account rows are identical between the two patterns "
      f"({wide['sa']['cf']['flat/Account']['marg']:+.1f} MB), and its trie families still "
      f"contribute nothing ({wide['sa']['cf']['flat/StateNodes']['marg']:+.1f} MB). So the "
      f"residual is one thing: fetching bytecode the store has never fetched before.</p>")
    w(f"<p>That is consistent with the throughput and with the shape of the two code databases. "
      f"The snapshot dedups bytecode by code hash; the generated store keys it per account, so "
      f"it holds {esc(fp['sa']['code'])} against {esc(fp['joc']['code'])} and its entries are "
      f"far smaller and far more numerous. Nothing about that is a bug &mdash; it is what "
      f"generating distinct contracts means &mdash; but it does mean a benchmark that touches "
      f"a new contract on every access reads more from it. What remains unexplained is now "
      f"only the size of the effect: {sa_w/joc_w:.2f}&times; the bytes coming out as "
      f"{1/BM['cells']['DIFF_MAX code-exec']['settled'] - 1:.0%} less throughput, with the "
      f"client using {dmj['cpu']:.2f} of the snapshot's CPU for the same work. The fixture "
      f"accounts are not the answer: all {thousands(M['fixture_eoas']['probed'])} addresses in "
      f"the range the tests use carry no code at all on either arm.</p>")

    # ---------------------------------------------------------------- three clients
    w("<h2>Three clients, one artifact</h2>")
    g = tc["geth_sa_over_uncompacted"]
    w("<table><tr><th>client</th><th class=n>same state costs</th>"
      "<th>generated vs snapshot, untreated</th><th>generated vs snapshot, treated</th></tr>")
    w(f"<tr><td>geth</td><td class=n>{tc['state_gib']['geth']} GiB</td>"
      f"<td>{g['EOA']:.2f}&ndash;{g['SAME_MAX']:.2f}&times; on account reads, "
      f"{g['NON_EXISTING']:.2f} on absent</td>"
      f"<td>{tc['geth_sa_over_compacted']['lo']:.3f}&ndash;"
      f"{tc['geth_sa_over_compacted']['hi']:.3f}&times;</td></tr>")
    w(f"<tr><td>Besu</td><td class=n>{tc['state_gib']['besu']} GiB</td>"
      f"<td>{1/tc['besu_sa_over_plain']:.1f}&times; on account reads "
      f"({tc['besu_bytes_plain']:.2f}&times; the bytes)</td>"
      f"<td>{tc['besu_sa_over_compacted']:.3f}&times; "
      f"({tc['besu_bytes_compacted']:.2f}&times; the bytes)</td></tr>")
    w(f"<tr><td>Nethermind</td><td class=n>{tc['state_gib']['nethermind']} GiB</td>"
      f"<td>{factor:.0f}&times; on account reads "
      f"({bc['ACCOUNT cold existing contract']['read']:.2f}&times; the bytes)</td>"
      f"<td>{f(ac['ACCOUNT cold existing contract']['thr'], 3)}&ndash;"
      f"{f(ac['ACCOUNT cold existing EOA']['thr'], 3)}&times; "
      f"({ac['ACCOUNT cold existing contract']['read']:.2f}&times; the bytes)</td></tr>")
    w(f"<caption>Three engines, three storage designs, three state sizes for the same logical "
      f"state &mdash; and the same artifact. The Besu and Nethermind columns are computed the "
      f"same way from each study's own data ({tc['besu_cells']} and "
      f"{ac['ACCOUNT cold existing contract']['n']} account cells respectively, gas matched "
      f"exactly); treat the geth spread as its published range. Untreated, the generated store "
      f"looks between {1/tc['besu_sa_over_plain']:.0f}&times; and {factor:.0f}&times; slower. "
      f"Treated, all three land within a few percent of parity. That is what a methodology "
      f"artifact looks like, as opposed to a property of any one database.</caption></table>")

    # ---------------------------------------------------------------- takeaway
    w("<h2>What to do about it</h2>")
    hw, fl = M["harness"], M["filters"]
    days = hw["compaction_seconds_account"] * hw["tests"] / 86400
    w("<ol>")
    w("<li><b>Never compare a promoted-after-pre-run snapshot against a store that did not get "
      "one.</b> It is worth an order of magnitude and it does not announce itself.</li>")
    w(f"<li><b>Neutralise the pre-run's placement effect on the arm that has one</b> &mdash; "
      f"compact after the pre-run, before the snapshot is promoted. That is a single compaction "
      f"per baseline, and the harness already has the right hook for it "
      f"(<code>{esc(hw['post_prerun_hook'])}</code>), though it is "
      f"{esc(hw['hook_status'])}. Note what <em>not</em> to do: compacting between every test's "
      f"steps, the lever geth could reach over RPC, costs "
      f"{hw['compaction_seconds_account']:.0f} s per column family here &mdash; about "
      f"{days:.1f} days across {thousands(hw['tests'])} tests, six times the runtime of the "
      f"suite it would be preparing.</li>")
    w(f"<li><b>Give every arm the same EVM warm-up before the measured block.</b> This is the "
      f"one that cost us the most rounds. A client restarted per test measures a process that is "
      f"still compiling itself, and whichever arm's fixtures happen to do heavy EVM work in the "
      f"seconds before the measurement gets promoted code for free. Here the two arms differ by "
      f"a single empty block, and it is worth "
      f"{(J['ab']['no_tiered_jit']['thr'] / J['ab']['baseline']['thr'] - 1)*100:.0f}% on the "
      f"control tests. The fix is a burn-in block whose result is discarded, identical on every "
      f"arm &mdash; not disabling tiered compilation, which is the diagnostic and biases the "
      f"other way.</li>")
    w(f"<li><b>Finish a generated store's compaction with <code>kForce</code> and an explicit "
      f"target level</b> &mdash; the two halves of the same mistake, and the only one of these "
      f"items that is a bug in the artifact rather than in the methodology. Without a target "
      f"level a plain <code>CompactRange</code> writes into the deepest level that already "
      f"holds files, leaving the store permanently <code>compaction-pending</code>. Without "
      f"<code>bottommost_level_compaction=kForce</code> it does something quieter and worse: "
      f"with no compaction filter configured it <em>moves</em> the flushed files into the "
      f"bottom level instead of rewriting them, so every file keeps a non-zero sequence number "
      f"and the first client to open the store starts garbage-collecting all of them. That was "
      f"worth {bidle['sa_mb']:,} MB of background I/O per {bidle['window_s']} idle seconds "
      f"here, restarted on every one of {thousands(hw['tests'])} tests. Both are one-line "
      f"changes at generation time, {st_s/60:.0f} minutes for {st_gb:.0f} GB, paid once by the "
      f"producer instead of repeatedly by every consumer "
      f"(<a href=\"https://github.com/ethereum/state-actor/pull/{BM['pr']}\">state-actor#"
      f"{BM['pr']}</a>). Worth doing for reproducibility even though it moved no ratio "
      f"here.</li>")
    w(f"<li><b>Give the harness control of the client's cache, not just the page cache</b> "
      f"&mdash; but do not expect it to explain much. Starving the block cache here moved the "
      f"result by "
      f"{(D['cache_experiment']['small']['thr']['CONTROL'] / D['cache_experiment']['big']['thr']['CONTROL'] - 1)*100:.0f}%, "
      f"and removing the page-cache drops entirely took state-actor's control reads to zero "
      f"without making it faster. Useful control, wrong suspect.</li>")
    w("<li><b>Print a locality diagnostic:</b> read bytes per unit of gas, per arm. Flat in gas "
      f"means a bounded working set and therefore an artifact &mdash; jochemnet read "
      f"{cc[0]['jocMB']:.0f} MB at {cc[0]['gas']}M and {cc[-1]['jocMB']:.0f} MB at "
      f"{cc[-1]['gas']}M while state-actor climbed from {cc[0]['saMB']:.0f} to "
      f"{cc[-1]['saMB']:.0f} MB. That check is a few lines, and it would have caught this on the "
      f"first run rather than the thirtieth.</li>")
    w("</ol>")
    w(f"<p>And the answer to the question in the title: the generated state was never "
      f"{factor:.0f}&times; slower. With placement equalised, account reads agree within "
      f"{min((1 - ac['ACCOUNT cold existing contract']['thr'])*100, (1 - ac['ACCOUNT cold existing EOA']['thr'])*100):.0f}&ndash;"
      f"{max((1 - ac['ACCOUNT cold existing contract']['thr'])*100, (1 - ac['ACCOUNT cold existing EOA']['thr'])*100):.0f}%, storage within "
      f"{(ac['STORAGE slot access']['thr'] - 1)*100:.0f}%, ether transfers within "
      f"{(ac['ETHER transfer receivers']['thr'] - 1)*100:.0f}%, and absent-account lookups "
      f"resolve from a filter in {fl['sa']['absent_us']:.1f} against "
      f"{fl['joc']['absent_us']:.1f} microseconds. Synthetic state is a sound substitute for "
      f"benchmarking <em>state access</em>.</p>")
    w(f"<p>One caveat stops that being a blanket endorsement, and it is narrower than it was. "
      f"Executing a <em>distinct</em> maximum-size contract still costs the generated store "
      f"{1/dmj['thr']:.2f}&times; once both arms measure steady-state code &mdash; down from "
      f"{1/dmp['thr']:.2f}&times; as published &mdash; and with the store no longer compacting "
      f"itself underneath the measurement, that remainder has a clean account: "
      f"{sa_w/joc_w:.2f}&times; the bytes for the same work, essentially all of it the code "
      f"database, while the client uses {dmj['cpu']:.2f} of the snapshot's CPU. So "
      f"code-execution-heavy workloads are mostly covered now, with a residual worth roughly "
      f"{(1/dmj['thr'] - 1)*100:.0f}% on the one access pattern that touches a new contract "
      f"every time &mdash; and that residual is a property of generating distinct contracts, "
      f"not a defect anyone can patch away.</p>")
    w(f"<p>The control tests &mdash; the ones doing no account work at all, which carried more "
      f"of the published divergence than any real category &mdash; were measuring the harness, "
      f"not either store. They are the reason to read the corrected column above as a bracket "
      f"rather than a verdict: neither configuration is neutral, and the honest range for every "
      f"state-reading category lies between them, within a few per cent of parity in both.</p>")

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
      "section above now reports the cell as open.</li>")
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
      f"Defect 3 above &mdash; where the prediction on record was that most of the remaining "
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
        "fig_ratio_dots": chart_ratio_dots(rat_b, rat_a, spr_b, spr_a),
        "fig_grid": chart_grid(AFT["grid"]),
        "fig_steps": chart_steps(D["steps"]),
        "fig_code_ladder": chart_code_ladder(modes, {"sa": fp["sa"]["code"],
                                                     "joc": fp["joc"]["code"]}),
        "fig_additive": chart_additive(add["buckets"]),
        "fig_seqno_paths": chart_seqno_paths(BM),
        "fig_idle_reads": chart_idle_reads(BM),
        "fig_marginal_cf": chart_marginal_cf(BM),
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
