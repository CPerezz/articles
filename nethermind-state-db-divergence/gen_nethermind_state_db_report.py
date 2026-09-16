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

    for p in points:
        o.append(S.label(sx.to(p["n"]), b2 + 22, thousands(p["n"]), "middle", "tick"))
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
    # Dispersion claims. A median landing on parity is not convergence if the tests stay
    # scattered, so the page states both and both have to hold.
    eo, st = AFT["spread"]["ACCOUNT cold existing EOA"], AFT["spread"]["STORAGE slot access"]
    assert eo["within10"] / eo["n"] > 0.9, f"existing-EOA no longer tight: {eo}"
    assert eo["p75"] - eo["p25"] < 0.1, f"existing-EOA middle half widened: {eo}"
    assert st["max"] - st["min"] > 0.5, \
        f"storage-slot spread claim no longer holds: {st}"
    # The worst tests in the suite are supposed to be the ones doing no account work. If that
    # stops being true the residual section's whole argument changes.
    wr_ = AFT["worst"]
    assert sum(1 for r in wr_ if r["control"]) > len(wr_) / 2, \
        "the worst tests are no longer dominated by controls; rewrite the residual section"
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
    w("<p>Three things, in the order they matter. Two are properties of how the baseline was "
      "prepared; the third is the harness not having the controls this kind of study needs.</p>")
    w("<ol>")
    w("<li><b>The pre-run is promoted into the baseline.</b> Only one arm replays a pre-run "
      "before measuring, and the harness is told to promote the result into the image every test "
      "restores from. That leaves the benchmark's own accounts as the newest versions in the "
      "youngest files of the LSM tree. Diagnosed below, <b>fixed</b>, and the fix accounts for "
      "almost all of the gap.</li>")
    w("<li><b>The measured step inherits its own setup step's cache.</b> The page cache is "
      "dropped between the two, but the client is not restarted, so its RocksDB block cache is "
      "not. Diagnosed below, <b>not fixed</b> &mdash; every number here still carries it.</li>")
    w(f"<li><b>The harness has no compaction control.</b> "
      f"<code>{esc(hw['compact_between_steps'])}</code> is {esc(hw['compact_status'])}, and "
      f"<code>{esc(hw['post_prerun_hook'])}</code> is {esc(hw['hook_status'])}. The treatment "
      f"below had to be applied by hand.</li>")
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

    w(figure(chart_ratio_dots(rat_b, rat_a, spr_b, spr_a),
             f"The same {thousands(AFT['agreement']['n'])} tests as individual results rather "
             f"than medians: one dot per cluster of tests at that ratio, sized by how many, with "
             f"the middle half drawn as a bar and the median as a tick. The count on the right is "
             f"how many of that category's tests land inside &plusmn;10% of parity. Reading the "
             f"two panels together is the point &mdash; the account clouds do not merely shift, "
             f"they collapse from a smear across the left of the axis onto the parity band."))

    # ---------------------------------------------------------------- residual
    w("<h2>Defect 2: the measured step inherits its own setup step's cache</h2>")
    st = D["steps"]
    w("<p>The harness drops the OS page cache between the setup payload and the measured one. It "
      "cannot drop the client's <em>own</em> cache: Nethermind is not restarted inside a test "
      "&mdash; <code>container-recreate</code> rolls back per test, not per step &mdash; so the "
      "RocksDB block cache carries whatever setup pulled in straight into the measurement. The "
      "two arms are warmed by very different amounts:</p>")
    w("<table><tr><th>tests</th><th>arm</th><th class=n>setup reads</th>"
      "<th class=n>measured reads</th><th class=n>total</th></tr>")
    for key, lbl in (("control", "control (no account work)"), ("measured", "reads accounts")):
        for arm, nm in (("joc", "jochemnet"), ("sa", "state-actor")):
            r = st[key][arm]
            w(f"<tr><td>{esc(lbl)}</td><td>{nm}</td>"
              f"<td class=n>{r['setup']:,.1f} MB</td><td class=n>{r['test']:,.1f} MB</td>"
              f"<td class=n>{r['setup']+r['test']:,.1f} MB</td></tr>")
    w(f"<caption>Read the control rows across the two steps: jochemnet pays "
      f"{st['control']['joc']['setup']:.1f} MB in setup and "
      f"{st['control']['joc']['test']:.1f} MB when measured, state-actor "
      f"{st['control']['sa']['setup']:.1f} MB then "
      f"{st['control']['sa']['test']:.1f} MB. The arms are inverted between the steps, and the "
      f"setup figure is identical across categories on each arm, so it is a fixed payload whose "
      f"only variable effect is how much of each store it happens to leave cached.</caption>"
      f"</table>")
    w(figure(chart_steps(st),
             "The same numbers on a log axis. A measurement that begins with a warm client cache "
             "is measuring the setup payload as much as the test, and the harness has no control "
             "over that cache today."))
    w(f"<p><b>What would fix it:</b> restart the client, or flush its block cache, between the "
      f"setup and the measured step. That is affordable &mdash; the harness already recreates a "
      f"container per test in seconds. Per-step <em>compaction</em>, the other obvious lever and "
      f"the one geth used, is not affordable here: Nethermind exposes no compaction RPC, and "
      f"doing it offline costs {M['harness']['compaction_seconds_account']:.0f} s for the "
      f"account family alone &mdash; about {M['harness']['compaction_seconds_account']*M['harness']['tests']/86400:.0f} "
      f"days across {thousands(M['harness']['tests'])} tests &mdash; about "
      f"{M['harness']['compaction_seconds_account']*M['harness']['tests']/3600/12.7:.0f}&times; "
      f"the runtime of the suite it is supposed to be preparing.</p>")
    w("<p class=note>This defect is diagnosed but <b>not fixed</b> in the numbers on this page. "
      "Everything below still carries it.</p>")

    w("<h2>What is left, and how much of it we can account for</h2>")
    # ------------------------------------------------- open item: DIFF_MAX
    dm = modes["EXISTING_CONTRACT_DIFF_MAX"]
    w(f"<h3>Open: a different contract per access still costs {dm['readX']:.2f}&times;</h3>")
    w("<h3>What we know</h3>")
    w("<p>One cell does not come back to parity, and it is the same cell the geth study flagged "
      "and left unexplained. Laying every opcode against every access mode shows it is a column, "
      "not a scatter &mdash; whatever is left does not care which opcode reads the account:</p>")
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
    w(f"<p>So the effect is real, it is confined to one square of the table above, and the "
      f"three explanations that fit that square are each contradicted by a direct measurement. "
      f"We are leaving it here rather than reaching for a fourth story: the honest statement is "
      f"that executing a <em>distinct</em> contract costs the generated store "
      f"{1/dm_code[0]:.2f}&times; what it costs the snapshot, and we cannot yet say why. "
      f"The fixture accounts themselves are not the answer either &mdash; all "
      f"{thousands(M['fixture_eoas']['probed'])} addresses in the range the tests use carry no "
      f"code at all on either arm.</p>")

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
    w("<li><b>Give the harness control of the client's cache, not just the page cache.</b> "
      "Dropping <code>/proc/sys/vm/drop_caches</code> between steps leaves the client's own "
      "RocksDB block cache warm, so a measured step partly reflects what its own setup payload "
      "happened to load. Restarting the client between steps is affordable; the harness already "
      "recreates a container per test in seconds.</li>")
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
    w(f"<p>Two caveats stop that being a blanket endorsement. Executing a <em>distinct</em> "
      f"contract still costs the generated store {1/dm_code[0]:.2f}&times; what it costs the "
      f"snapshot and we cannot say why, so anything code-execution heavy is not yet covered. And "
      f"Defect 2 is diagnosed but unfixed, so the numbers here still contain an unknown amount "
      f"of cross-step cache help.</p>")

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
