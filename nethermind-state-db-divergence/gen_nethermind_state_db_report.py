#!/usr/bin/env python3
"""Build the Nethermind state-DB divergence report from the collected run data.

Every number in the page is derived here from data/report_data.json; none is typed into the
prose. The oracles in main() fail generation if the data stops supporting a sentence the article
states as fact.

Usage: python3 gen_nethermind_state_db_report.py
"""
import html
import json
import os
import re
from statistics import median

import report_svg as S
from crt_theme import CSS

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "nethermind-state-db-report.html")
FIGDIR = os.path.join(HERE, "figures")

# Ratios throughout are state-actor / jochemnet, so 1.00 is parity and < 1 means the generated
# store is slower.


def esc(s):
    return html.escape(str(s))


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


BUCKETS = ("lt0.2s", "0.2to1s", "1to5s", "ge5s")
BUCKET_LABEL = {"lt0.2s": "< 0.2 s", "0.2to1s": "0.2 - 1 s", "1to5s": "1 - 5 s", "ge5s": "> 5 s"}


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
    # The v2 runs shared one jochemnet denominator (README, errata), so the before is the fresh pair.
    stages = [("before", "r68"), ("rows settled", "r69"), ("+ trie settled", "r72")]
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
        o.append(S.label(W - R + 6, y + 4, "%.2f \u2192 %.2f" % (sc["%s 160M" % key]["r68"], sc["%s 160M" % key]["r72"]),
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



# --------------------------------------------------------------------------- the rewrite
GE_ORDER = ["account row EXISTING_EOA", "account row MINIMAL", "account row SAME_MAX",
            "account row JUMPDEST", "account row DIFF_MAX",
            "code-exec EXISTING_EOA", "code-exec MINIMAL", "code-exec SAME_MAX",
            "code-exec JUMPDEST", "code-exec DIFF_MAX", "ether transfer", "storage slot"]
LT_ORDER = ["control (no state work)", "absent account", "warm query", "sload same key",
            "storage slot"]
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
    "control (no state work)": "control, no state work",
    "absent account": "absent account",
    "warm query": "warm query",
    "sload same key": "same slot, reloaded",
}


def final_rows(fn, cls):
    rows = {r["cat"]: r for r in fn["rows"] if r["cls"] == cls}
    order = GE_ORDER if cls == "ge1s" else LT_ORDER
    return [(c, rows[c]) for c in order if c in rows]


def chart_overview(fn, stage):
    """Every test of the page's population as a dot on one log axis, split by duration class.

    Drawn twice with the same axis and the same rows: once for the untreated pair, once for the
    two settled pairs. Reading one against the other is the article."""
    W, L, R, T = 760, 250, 112, 34
    rh, gap = 17, 30
    ge, lt = final_rows(fn, "ge1s"), final_rows(fn, "lt1s")
    H = T + 2 * 12 + rh * (len(ge) + len(lt)) + gap + 48
    sx = S.LogScale(0.03, 3.2, L, W - R)
    o = [S.label(0, 14, "throughput, state-actor / jochemnet, one dot per test (band = \u00b110%)",
                 "start", "big")]
    tests = fn["tests"]
    keys = ("base",) if stage == "base" else ("a", "b")
    y0 = T
    for title, rows, cls in (("tests over a second", ge, "ge1s"),
                             ("tests under a second: shown, not counted", lt, "lt1s")):
        o.append(S.label(0, y0 + 4, title, "start", "ax"))
        if cls == "ge1s":
            o.append(S.label(W - R + 8, y0 + 4, "median  band", "start", "tick"))
        top = y0 + 12
        bot = top + rh * len(rows)
        o.append(S.band(sx.to(0.9), sx.to(1.1), top, bot, "--accent", 0.10))
        o.append(S.line(sx.to(1.0), top, sx.to(1.0), bot, "--green-muted", 1))
        for i, (cat, row) in enumerate(rows):
            y = top + rh * i + 9
            o.append(S.label(L - 10, y + 4, ROW_LABEL.get(cat, cat), "end", "tick"))
            for k in keys:
                var = "--db-u" if k == "base" else ("--accent" if k == "a" else "--db-c")
                off = {"base": 0, "a": -2, "b": 2}[k]
                for t in tests.values():
                    if t["cls"] == cls and t["cat"] == cat and t[k] is not None:
                        o.append(S.dot(sx.to(max(0.03, min(3.2, t[k]))), y + off, 2.2, var))
            s = row["base"] if stage == "base" else row["a"]
            x = sx.to(max(0.03, min(3.2, s["median"])))
            o.append(S.line(x, y - 7, x, y + 7, "--fg", 2))
            o.append(S.label(W - R + 8, y + 4, "%.2f  %d/%d" % (s["median"], s["within10"], s["n"]),
                             "start", "tick"))
        y0 = bot + gap
    ty = y0 - gap + 18
    for t in (0.05, 0.1, 0.25, 0.5, 1, 2):
        o.append(S.label(sx.to(t), ty, ("%g" % t), "middle", "tick"))
    ly = H - 8
    if stage == "base":
        o.append(S.dot(L, ly - 4, 3, "--db-u"))
        o.append(S.label(L + 8, ly, "untreated pair", "start", "tick"))
    else:
        o.append(S.dot(L, ly - 4, 3, "--accent"))
        o.append(S.label(L + 8, ly, "pair A", "start", "tick"))
        o.append(S.dot(L + 80, ly - 4, 3, "--db-c"))
        o.append(S.label(L + 88, ly, "pair B", "start", "tick"))
    o.append(S.line(L + 180, ly - 10, L + 180, ly + 2, "--fg", 2))
    o.append(S.label(L + 188, ly, "category median", "start", "tick"))
    return S.svg(W, H, "".join(o))


def floor_buckets(fn):
    out = {}
    for b in BUCKETS:
        lo, hi = {"lt0.2s": (0, 0.2), "0.2to1s": (0.2, 1), "1to5s": (1, 5), "ge5s": (5, 1e9)}[b]
        ts = [t for t in fn["tests"].values() if lo <= t["joc_secs"] < hi]
        def pct(k):
            v = [t[k] for t in ts if t[k] is not None]
            return (100.0 * sum(1 for r in v if 0.9 <= r <= 1.1) / len(v), len(v)) if v else (None, 0)
        out[b] = {"floor": pct("floor_sa"), "pair": pct("a")}
    return out


def chart_floor(fn):
    """How often a test lands within 10% of the number it is compared to, by how long it runs.

    The floor is one store measured twice, so a comparison can't do better than it. Where the
    two dots meet, the comparison is measuring the harness."""
    W, L, R, T = 760, 96, 170, 52
    fb = floor_buckets(fn)
    H = T + 34 * len(BUCKETS) + 52
    sx = S.Scale(0, 100, L, W - R)
    o = [S.label(L, T - 34, "tests inside \u00b110%, by how long the test runs", "start", "big")]
    for v in (0, 25, 50, 75, 100):
        o.append(S.label(sx.to(v), T - 16, f"{v}%", "middle", "tick"))
    for i, b in enumerate(BUCKETS):
        y = T + 34 * i + 10
        (fp, _), (cp, cn) = fb[b]["floor"], fb[b]["pair"]
        o.append(S.label(L - 8, y + 4, BUCKET_LABEL[b], "end"))
        if fp is None or cp is None:
            continue
        o.append(S.line(sx.to(min(fp, cp)), y, sx.to(max(fp, cp)), y, "--green-muted", 2))
        o.append(S.dot(sx.to(fp), y, 4, "--db-u", f"same store twice: {fp:.0f}%"))
        o.append(S.dot(sx.to(cp), y, 4.5, "--accent", f"the two stores: {cp:.0f}%"))
        o.append(S.label(W - R + 10, y + 4, f"{cp:.0f}% of {cn}, floor {fp:.0f}%", "start", "tick"))
    o.append(S.dot(L + 6, H - 28, 4, "--db-u"))
    o.append(S.label(L + 16, H - 24, "state-actor, measured twice", "start", "tick"))
    o.append(S.dot(L + 236, H - 28, 4.5, "--accent"))
    o.append(S.label(L + 246, H - 24, "the two stores, all fixes applied", "start", "tick"))
    return S.svg(W, H, "".join(o))


JIT_ROWS = [("control, no state work", ("ab", "baseline"), ("ab", "no_tiered_jit"), "lt"),
            ("absent account, call", ("published", "NON_EXISTING_ACCOUNT code-exec"),
             ("jit_equalised", "NON_EXISTING_ACCOUNT code-exec"), "lt"),
            ("warm query", ("published", "warm query"), ("jit_equalised", "warm query"), "lt"),
            ("call, reused contract", ("published", "SAME_MAX code-exec"),
             ("jit_equalised", "SAME_MAX code-exec"), "ge"),
            ("call, distinct contract", ("published", "DIFF_MAX code-exec"),
             ("jit_equalised", "DIFF_MAX code-exec"), "ge")]


def jit_value(J, key):
    kind, name = key
    return J["ab"][name]["thr"] if kind == "ab" else J["slice"][kind][name]["thr"]


def chart_jit(J):
    """The JIT lever: the same tests with tiered compilation on (as published) and off (both arms
    running optimised code from the first block)."""
    W, L, R, T = 760, 236, 112, 34
    rh = 30
    H = T + rh * len(JIT_ROWS) + 50
    sx = S.LogScale(0.5, 1.8, L, W - R)
    bot = T + rh * len(JIT_ROWS) - 8
    o = [S.band(sx.to(0.9), sx.to(1.1), T - 8, bot, "--accent", 0.10),
         S.line(sx.to(1.0), T - 8, sx.to(1.0), bot, "--green-muted", 1),
         S.label(L, T - 18, "throughput, state-actor / jochemnet, before and after taking the JIT out",
                 "start", "big")]
    for i, (label, a, b, cls) in enumerate(JIT_ROWS):
        y = T + rh * i + 6
        va, vb = jit_value(J, a), jit_value(J, b)
        o.append(S.label(L - 10, y + 4, label + ("  (<1 s)" if cls == "lt" else ""), "end",
                         "tick" if cls == "lt" else ""))
        o.append(S.line(sx.to(va), y, sx.to(vb), y, "--green-muted", 2))
        o.append(S.dot(sx.to(va), y, 4.5, "--db-u", f"{label}, JIT on: {va:.3f}"))
        o.append(S.dot(sx.to(vb), y, 4.5, "--accent", f"{label}, JIT off: {vb:.3f}"))
        o.append(S.label(W - R + 8, y + 4, f"{va:.2f} \u2192 {vb:.2f}", "start", "tick"))
    for t in (0.5, 0.75, 1.0, 1.25, 1.5):
        o.append(S.label(sx.to(t), bot + 20, f"{t:g}", "middle", "tick"))
    o.append(S.dot(L, H - 12, 4.5, "--db-u"))
    o.append(S.label(L + 10, H - 8, "as published", "start", "tick"))
    o.append(S.dot(L + 130, H - 12, 4.5, "--accent"))
    o.append(S.label(L + 140, H - 8, "tiered compilation off, both arms", "start", "tick"))
    return S.svg(W, H, "".join(o))


def chart_fetch(ib):
    """What one code fetch costs on each store, measured: bytes read per fetch against the 4 KB
    page, pages touched, and latency. The fixture contract is the same; its neighbours aren't."""
    W, L, R, T = 760, 200, 70, 40
    pr, pages = ib["pread"], ib["pages_per_fetch"]
    rows = [("jochemnet (mainnet code)", "joc", "--accent"), ("state-actor, old pool", "sa", "--db-sa")]
    rh = 44
    H = T + rh * len(rows) + 56
    sx = S.Scale(0, 4096 * 1.08, L, W - R)
    o = [S.label(L, T - 22, "bytes read per code fetch, one test traced on both stores", "start", "big")]
    for i, (label, k, var) in enumerate(rows):
        y = T + rh * i
        b = pr[k]["code_mean_b"]
        o.append(S.label(L - 10, y + 16, label, "end"))
        o.append(S.band(L, sx.to(b), y + 4, y + 26, var, 0.45))
        o.append(S.label(sx.to(b) + 8, y + 19,
                         f"{b:,} B, {pages[k]:.2f} pages, {pr[k]['code_mean_us']:,} \u00b5s",
                         "start", "tick"))
    x4 = sx.to(4096)
    o.append(S.line(x4, T - 6, x4, T + rh * len(rows), "--muted", 1, dash="3 3"))
    o.append(S.label(x4, T + rh * len(rows) + 14, "4 KB page", "middle", "tick"))
    o.append(S.label(L, H - 10,
                     f"same number of fetches ({pr['joc']['code_n']:,} and {pr['sa']['code_n']:,}); "
                     "the account row reads are identical", "start", "tick"))
    return S.svg(W, H, "".join(o))


def chart_topnodes(tn):
    """A node and its sixteen children, laid out the way each packing stores them."""
    pk, sw = tn["packing"], tn["swap"]
    lanes = [("4 KB blocks, as we left it", int(round(pk["joc_before"]["entries_per_block"])),
              "--db-u", sw["joc"]["top_per_account_before"]),
             ("16 KB blocks, the client's", int(round(pk["sa_before"]["entries_per_block"])),
              "--accent", sw["sa"]["top_per_account_before"])]
    W, L, T = 760, 250, 36
    cw, ch, gapb = 18, 18, 10
    rh = 58
    H = T + rh * len(lanes) + 44
    o = [S.label(L, T - 18, "a level-4 node and its 16 children, in key order", "start", "big")]
    for i, (label, per, var, reads) in enumerate(lanes):
        y = T + rh * i + 6
        o.append(S.label(L - 12, y + 14, label, "end"))
        x = L
        for n in range(17):
            if n and n % per == 0:
                x += gapb
            fill = 0.55 if n == 0 else 0.28
            o.append(S.band(x, x + cw - 2, y, y + ch, var, fill))
            x += cw
        blocks = -(-17 // per)
        o.append(S.label(L, y + ch + 16,
                         f"{blocks} block{'s' if blocks > 1 else ''}; {reads:.2f} top-node reads per touched account",
                         "start", "tick"))
    o.append(S.label(L, H - 10, "first square: the parent; one gap marks a block boundary", "start", "tick"))
    return S.svg(W, H, "".join(o))


def chart_stages(title, rows, stages):
    """Tests walked through a sequence of treatments against the \u00b110% band.

    rows: (label, [series]) where each series maps stage key -> ratio.
    stages: (label, key, colour var, dot radius, final); the right-hand label reads the first
    stage against every final one."""
    W, L, R, T = 760, 200, 150, 34
    rh = 46
    H = T + rh * len(rows) + 54
    lo = min(v for _, ss in rows for s in ss for v in s.values())
    hi = max(v for _, ss in rows for s in ss for v in s.values())
    sx = S.LogScale(min(0.83, lo * 0.97), max(1.2, hi * 1.05), L, W - R)
    bot = T + rh * len(rows) - 12
    o = [S.band(sx.to(0.9), sx.to(1.1), T - 10, bot + 6, "--accent", 0.10),
         S.line(sx.to(1.0), T - 10, sx.to(1.0), bot + 6, "--green-muted", 1),
         S.label(L, T - 18, title, "start", "big")]
    for i, (label, series) in enumerate(rows):
        y = T + rh * i + 8
        o.append(S.label(L - 10, y + 4, label, "end"))
        for si, s in enumerate(series):
            yy = y - 6 + 12 * si if len(series) > 1 else y
            prev = None
            for lab, key, var, r, _ in stages:
                if key not in s:
                    continue
                x = sx.to(s[key])
                if prev is not None:
                    o.append(S.line(prev, yy, x, yy, "--green-muted", 1, dash="2 3"))
                o.append(S.dot(x, yy, r, var, "%s: %.3f" % (lab, s[key])))
                prev = x
        s0 = series[0]
        finals = " / ".join("%.2f" % s0[k] for _, k, _, _, fin in stages if fin and k in s0)
        o.append(S.label(W - R + 6, y + 4, "%.2f \u2192 %s" % (s0[stages[0][1]], finals), "start", "tick"))
    ticks = [t for t in (0.85, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0, 2.5) if sx.lo <= t <= sx.hi]
    for t in ticks:
        o.append(S.label(sx.to(t), bot + 26, f"{t:g}", "middle", "tick"))
    lx = L
    for lab, _, var, r, _ in stages:
        o.append(S.dot(lx, H - 12, r, var))
        o.append(S.label(lx + 9, H - 8, lab, "start", "tick"))
        lx += 20 + 7 * len(lab)
    return S.svg(W, H, "".join(o))


# --------------------------------------------------------------------------- page
def main():
    D = json.load(open(os.path.join(HERE, "data", "report_data.json")))
    P, M = D["provenance"], D["measured"]
    BEF, AFT = D["before"], D["after"]
    bc, ac = BEF["categories"], AFT["categories"]
    amort = M["amortisation"]["points"]
    BM, J, IB, TN, ST = D["bottommost"], D["jit_experiment"], D["intervention_blocks"], D["topnodes"], D["storage"]
    FN = D["final"]

    # ----- oracles: every sentence below that states a fact has one ---------------------------
    # Scope: the baseline pair is the flat-backed pair, pinned by run id, in both the old
    # provenance block and the new population block.
    assert P["arms"]["sa"]["run"] == M["preconditions"]["sa_run_flat_backed"] == FN["runs"]["baseline"]["sa"], \
        "the baseline state-actor run is not the flat-backed one"
    assert P["arms"]["joc"]["run"] == M["preconditions"]["joc_run"] == FN["runs"]["baseline"]["joc"], \
        "the baseline jochemnet run is not the recorded one"
    # The headline, on the full suite.
    worst = min(bc[c]["thr"] for c in ("ACCOUNT cold existing EOA", "ACCOUNT cold existing contract"))
    factor = 1.0 / worst
    assert 10 <= factor <= 20, f"headline factor moved out of band: {factor:.1f}"
    # The population: both views use the same tests and the same class membership. They are
    # built from one list, so what has to hold is that every row has every column it shows.
    assert FN["n"] == 266, "the page population is no longer the 266 tests at 160M/240M"
    assert FN["complete"], "the second final pair is missing"
    for t in FN["tests"].values():
        assert t["base"] is not None and t["a"] is not None, "a test lacks a before or after ratio"
        assert t["b"] is not None, "a test lacks its pair-B ratio"
    assert len(set(FN["runs"]["final"].values())) == len(FN["runs"]["final"]), "a final run is shared between pairs"
    ALL = {r["cls"]: r for r in FN["rows"] if r["cat"] == "__all__"}
    ge_all, lt_all = ALL["ge1s"], ALL["lt1s"]
    # The rule the page states: under a second one store can't agree with itself, over a
    # second it nearly always does.
    arms_ = ("floor_sa", "floor_joc")
    f_ge = [ge_all[k]["within10"] / ge_all[k]["n"] for k in arms_]
    f_lt = [lt_all[k]["within10"] / lt_all[k]["n"] for k in arms_]
    assert min(f_ge) > 0.9 and max(f_lt) < 0.65, \
        "the duration floors no longer separate: %r / %r" % (f_ge, f_lt)
    # Part 1: account reads are the slow thing; the controls aren't.
    ge_rows = dict(final_rows(FN, "ge1s"))
    lt_rows = dict(final_rows(FN, "lt1s"))
    acct = [ge_rows[c]["base"]["median"] for c in ge_rows if c.startswith("account row")]
    assert max(acct) < 0.1, "account-row reads are no longer an order of magnitude apart: %r" % acct
    assert lt_rows["control (no state work)"]["base"]["median"] > 5 * max(acct), \
        "the controls are dragged down as far as the account reads; the first clue is gone"
    assert abs(ge_rows["storage slot"]["base"]["median"] - 1) < 0.05 and \
        max(acct) < ge_rows["ether transfer"]["base"]["median"] < 0.9, \
        "the storage/transfer clues moved: %r %r" % (ge_rows["storage slot"]["base"], ge_rows["ether transfer"]["base"])
    # Finding 1: the corner, and the compaction that removes it.
    a0, a9 = amort[0], amort[-1]
    assert abs(a0["joc_blk"] - a0["sa_blk"]) < 0.2, "arms no longer start at parity"
    assert a9["joc_blk"] < 0.4 and a9["sa_blk"] > 1.8, "saturation broke"
    assert a9["joc_mb"] < 2 * amort[-2]["joc_mb"], "jochemnet volume no longer saturates"
    for cat in ("ACCOUNT cold existing EOA", "ACCOUNT cold existing contract"):
        assert bc[cat]["thr"] < 0.1 and ac[cat]["thr"] > 0.94, f"{cat} before/after moved: {bc[cat]} {ac[cat]}"
    assert AFT["agreement"]["agree_pct"] > 3 * BEF["agreement"]["agree_pct"], "agreement no longer triples"
    rk = M["random_keys"]["Account"]
    ivb, iva = M["intervention"]["account_before"], M["intervention"]["account_after"]
    assert len(ivb["levels"]) >= 3 and list(iva["levels"]) == ["6"], "the account compaction shape changed: %r %r" % (ivb, iva)
    assert rk["joc_blk"] > rk["sa_blk"], "random-key inversion gone; 'it isn't a worse store' depends on it"
    # Finding 2: the JIT lever moves the controls past parity and the distinct-contract cell up,
    # and jochemnet is the arm that slows down (it had been measuring warm code).
    dmp, dmj = J["slice"]["published"]["DIFF_MAX code-exec"], J["slice"]["jit_equalised"]["DIFF_MAX code-exec"]
    assert J["ab"]["baseline"]["thr"] < 0.8 < 1.0 < J["ab"]["no_tiered_jit"]["thr"], "the control lever moved"
    assert dmj["thr"] > dmp["thr"] + 0.2 and dmj["joc_secs"] > 1.2 * dmp["joc_secs"], \
        "the distinct-contract cell no longer moves with jochemnet slowing"
    swing_lt = max(abs(jit_value(J, b) / jit_value(J, a) - 1) for _, a, b, c in JIT_ROWS if c == "lt")
    swing_ge = max(abs(jit_value(J, b) / jit_value(J, a) - 1) for _, a, b, c in JIT_ROWS
                   if c == "ge" and "distinct" not in _)
    assert swing_lt > 3 * swing_ge, "sub-second rows no longer swing hardest under the JIT lever"
    assert abs(dmj["sa_secs"] / dmp["sa_secs"] - 1) < 0.1, "state-actor moved under the JIT lever"
    # Every run after finding 2 carries the lever; the baseline pair doesn't. The page says both.
    TC = FN["tiered_compilation"]
    assert TC["sa"] == TC["joc"] == "default" and \
        all(TC[k] == "0" for k in FN["runs"]["final"]), "the JIT setting of a pair is not what the page says: %r" % TC
    assert lt_rows["control (no state work)"]["a"]["median"] > 1.05 and lt_rows["warm query"]["a"]["median"] > 1.05, \
        "the short tests no longer land above parity with tiering off"
    pj, ps = J["profile"]["joc_unsettled"], J["profile"]["sa_unsettled"]
    assert pj["windows"] == ps["windows"] and all(
        x["threads"][".NET Tiered Com"] > x["threads"][".NET TP Worker"] for x in (pj, ps)), \
        "the JIT thread no longer out-burns block execution in the control windows"
    dr, nd = J["drops"]["drops"], J["drops"]["nodrop"]
    assert nd["sa_read_mb"] < 1.0 < dr["sa_read_mb"] and nd["sa_mgas"] <= dr["sa_mgas"], \
        "removing the page-cache drops now helps state-actor; 'taking the I/O away' is out"
    assert J["ab"]["no_parallel"]["thr"] < J["ab"]["baseline"]["thr"], "parallel execution is no longer exonerated"
    # Finding 3: two columns spread over levels, each compaction equalised the reads it aimed at,
    # and the control never moved.
    col, sc, sr = ST["columns"], ST["cells"], ST["reads"]
    assert len(col["joc_storage_before"]["levels"]) >= 5 and col["joc_storage_after"]["levels"] == [6], \
        "the snapshot's storage rows are no longer many levels settled to one"
    assert len(col["joc_storagenodes_before"]["levels"]) >= 4 and col["joc_storagenodes_after"]["levels"] == [6], \
        "the snapshot's storage trie is no longer many levels settled to one"
    assert len(col["sa_storage"]["levels"]) == 1 and len(col["sa_storagenodes"]["levels"]) == 1, \
        "the generated store's storage columns are no longer single-level"
    for nm_, sh in col.items():
        if isinstance(sh, dict) and "per_level" in sh:
            assert {int(k) for k in sh["per_level"]} == set(sh["levels"]) and \
                sum(sh["per_level"].values()) == sh["files"], "level figure input disagrees: %s" % nm_
    for g in ("160M", "240M"):
        assert sc["slots=False new=False " + g]["r68"] > 1.9 and sc["slots=False new=False " + g]["r72"] < 1.15, \
        "the absent-slot cell no longer closes from about 2x"
        assert sc["slots=True new=True " + g]["r68"] > 1.05 and abs(sc["slots=True new=True " + g]["r72"] - 1) < 0.15, \
        "the new-value cell no longer closes"
        assert abs(sc["slots=True new=False " + g]["r69"] - 1) < 0.05 and abs(sc["slots=True new=False " + g]["r72"] - 1) < 0.05, \
        "the overwrite control moved"
        r = sr["slots=True new=True " + g]
        assert r["after_r69"]["joc_nodes"] > 1.1 * r["after_r69"]["sa_nodes"] and \
            abs(r["after_r72"]["joc_nodes"] / r["after_r72"]["sa_nodes"] - 1) < 0.1, \
        "the storage-trie reads did not equalise after the second compaction"
    absent_reads = D["outliers"]["tests"]["sstore slots=False new=False 240M"]["cols"]["flat/Storage"]
    assert absent_reads["joc_n"] > 3 * absent_reads["sa_n"], "the absent-slot read asymmetry is gone"
    # Finding 3's cells run on sstore tests; the ones under a second get their timing shown and
    # their reads counted, same rule as everywhere else.
    absent_slot = [t for k, t in FN["tests"].items()
                   if "test_sstore" in k and "existing_slots_False" in k and "write_new_value_False" in k]
    assert len(absent_slot) == 2, "expected the absent-slot sstore test at 160M and 240M: %d" % len(absent_slot)
    assert all(t["cls"] == "lt1s" for t in absent_slot), \
        "an absent-slot test now runs over a second; finding 3 says both run under one"
    # Finding 4: bigger code blocks per fetch, the repack closes both cells without moving the
    # control, and the regenerated store overshoots in both final pairs.
    assert IB["pread"]["sa"]["code_mean_b"] > 1.2 * IB["pread"]["joc"]["code_mean_b"], \
        "code blocks are no longer bigger per fetch on the generated store"
    assert IB["pread"]["sa"]["code_n"] / IB["pread"]["joc"]["code_n"] - 1 < 0.01, "fetch counts diverged"
    for c in ("DIFF_MAX code-exec", "JUMPDEST code-exec"):
        assert IB["cells"][c]["before"] < 0.96 and abs(IB["cells"][c]["after"] - 1) < 0.03, \
        "a code cell no longer closes under the repack"
    assert abs(IB["cells"]["SAME_MAX code-exec"]["after"] - IB["cells"]["SAME_MAX code-exec"]["before"]) < 0.02, \
        "the reused-contract control moved under the repack"
    for c in ("code-exec DIFF_MAX", "code-exec JUMPDEST"):
        assert ge_rows[c]["a"]["median"] > 1.04 and ge_rows[c]["b"]["median"] > 1.04, \
            "%s no longer overshoots on the regenerated store" % c
    assert abs(ge_rows["code-exec SAME_MAX"]["a"]["median"] - 1) < 0.02, "the reused-contract control moved"
    cpop, cprobe, csweep = M["code_population"], M["code_probe"], M["code_sweep"]
    assert cprobe["sa"]["bytes"] < cprobe["joc"]["bytes"] and cprobe["sa"]["us"] < cprobe["joc"]["us"] and \
        csweep["sa"]["bytes"] < csweep["joc"]["bytes"], "code lookups are no longer cheaper on the generated store"
    assert abs(cpop["sa"]["at_max"] / cpop["joc"]["at_max"] - 1) < 0.05, "max-size contract counts diverged"
    bx_lc = M["besu_cross_check"]["families"]["loads_code"]
    assert bx_lc["EXISTING_CONTRACT_DIFF_MAX"]["median"] < 0.9 < bx_lc["EXISTING_CONTRACT_SAME_MAX"]["median"], \
        "the Besu store no longer shows the distinct-vs-reused split: %r" % bx_lc
    sec = IB["secs"]
    assert min(sec["sa_4k"]) > max(sec["joc"]) and max(sec["sa_64b"]) < min(sec["sa_4k"]) and \
        median(sec["sa_64b"]) <= median(sec["joc"]), "the traced test no longer moves to jochemnet's side: %r" % sec
    assert cpop["sa"]["pct"] > cpop["joc"]["pct"] and cpop["sa"]["p50"] == cpop["sa"]["p90"] < cpop["joc"]["p50"], \
        "the generated store's code is no longer a uniform stub smaller than mainnet's median: %r" % cpop
    # Finding 5: same trie shape, the packing differed and the swap swapped it, the cell closed,
    # the read counts swapped, and the file numbers date the 4 KB files to our tooling.
    assert TN["shape"]["joc"]["top_nodes"] == TN["shape"]["sa_v1"]["top_nodes"] == 1118481, \
        "the two tops are no longer the same complete tree"
    assert TN["shape"]["sa_v1"]["walk_nodes"] >= TN["shape"]["joc"]["walk_nodes"] - 0.05, \
        "the generated trie is now shallower than the snapshot's"
    pk, sw = TN["packing"], TN["swap"]
    assert pk["joc_before"]["bytes_per_block"] < 5000 < 12000 < pk["sa_before"]["bytes_per_block"], \
        "the top-of-trie packing no longer differed the way the page says"
    assert pk["joc_after"]["bytes_per_block"] > 12000 > 5000 > pk["sa_after"]["bytes_per_block"], \
        "the swap no longer swapped the packing"
    assert sw["ratio_settled"] > 1.05 and abs(sw["ratio_swapped"] - 1) < 0.03, \
        "the swap no longer closed the transfer cell"
    gap = sw["ratio_settled"] - 1
    assert sw["joc_change"] - 1 > 0.25 * gap and 1 - sw["sa_change"] > 0.25 * gap, \
        "the swap no longer moves both arms toward each other: %r" % sw
    assert TN["shape"]["sa_v1"]["accounts_est_M"] > TN["shape"]["joc"]["accounts_est_M"], "the generated trie is no longer the bigger one"
    assert sw["joc"]["top_per_account_before"] > sw["sa"]["top_per_account_before"] and \
        sw["joc"]["top_per_account_after_240M"] < sw["sa"]["top_per_account_after_240M"], \
        "the top-node reads per account did not swap with the layout"
    pv = TN["provenance"]
    assert pv["Storage"]["min"] < 1000 < pv["StateTopNodes"]["min"] <= pv["StateTopNodes"]["max"] \
        < pv["Account"]["min"], "the 4 KB top-node files no longer predate our account rebuild: %r" % pv
    # The one-line mention: #139 was real and moved nothing.
    assert BM["idle"]["sa_mb"] > 500 > BM["idle"]["joc_mb"] and BM["idle"]["sa_settled_mb"] < 10, \
        "the #139 idle rewrite or its settle changed"
    for c in ("DIFF_MAX code-exec", "JUMPDEST code-exec"):
        cl = BM["cells"][c]
        assert abs(cl["settled"] - (cl["r1"] + cl["r2"]) / 2) < 0.05, "#139's settle moved %s" % c
    # Part 3: the long class is at parity in both pairs, close to its own floor.
    for k in ("a", "b"):
        s = ge_all[k]
        assert abs(s["median"] - 1) < 0.03 and s["within10"] >= 0.8 * s["n"], "long class left parity: %r" % s
    assert abs(ge_all["a"]["median"] - ge_all["b"]["median"]) < 0.02, "the two final pairs disagree"
    # "Three rows are still further from parity than the floor explains", and every other long row
    # is close to it. The three are named in part 4, so the set itself is the claim.
    off = {c for c, r in ge_rows.items() if abs(r["a"]["median"] - 1) >= 0.03}
    assert off == {"ether transfer", "code-exec DIFF_MAX", "code-exec JUMPDEST"}, \
        "the long rows off parity are no longer the three part 4 names: %r" % sorted(off)
    for c in off:
        assert abs(ge_rows[c]["floor_sa"]["median"] - 1) < abs(ge_rows[c]["a"]["median"] - 1) / 2, \
            "%s is inside what one store measured twice explains" % c
    # Part 4: the absent-account transfer is CPU and survives both warming ablations.
    aa, ab_ = ST["absent_account"], ST["ablation"]
    assert min(aa["throughput"]["160M"]["sa"]) > 1.2 * max(aa["throughput"]["160M"]["joc"]), \
        "the absent-account transfer is no longer faster on the generated store"
    assert aa["cpu_seconds"]["joc"]["160M"][".net thread pool"] > 1.5 * aa["cpu_seconds"]["sa"]["160M"][".net thread pool"], \
        "the absent-account CPU asymmetry is gone"
    tr_ = D["outliers"]["tests"]["amt1 diff_to_nonexistent 160M"]["cols"]
    for cf in ("flat/Account", "flat/StateTopNodes", "flat/StateNodes"):
        assert abs(tr_[cf]["sa_n"] / tr_[cf]["joc_n"] - 1) < 0.05 and abs(tr_[cf]["sa_us"] / tr_[cf]["joc_us"] - 1) < 0.1, \
            "the absent-account transfer no longer reads the same on %s: %r" % (cf, tr_[cf])
    traced = {k: v["cols"] for k, v in D["outliers"]["tests"].items() if k.startswith("amt")}
    assert len(traced) >= 10 and all(abs(c["sa_n"] / c["joc_n"] - 1) < 0.05 for cols in traced.values()
                                     for c in cols.values()), "a traced transfer test reads differently now"
    nonexist = [t["a"] for k, t in FN["tests"].items()
                if t["cat"] == "ether transfer" and "transfer_amount_1-case_id_diff_to_nonexistent" in k]
    nonexist_max = max(nonexist)
    assert len(nonexist) == 2 and nonexist_max == max(t["a"] for t in FN["tests"].values()
                                                     if t["cat"] == "ether transfer" and t["cls"] == "ge1s"), \
        "value transfers to absent accounts are no longer the extreme of the ether row"
    for cfg in ("B prewarming off", "C trie warmer off"):
        assert min(ab_[cfg]["sa 160M"]) > 1.15 * max(ab_[cfg]["joc 160M"]), "%s closed the gap" % cfg

    # ----- page ------------------------------------------------------------------------------
    o = []
    w = o.append
    figs = {}

    def fig(name, svg, caption):
        figs[name] = svg
        return figure(svg, caption)

    title = (f"How can two Nethermind databases holding the same state differ "
             f"{factor:.0f}&times;, and then agree?")
    w("<!doctype html><html lang=en><head><meta charset=utf-8>")
    w('<meta name=viewport content="width=device-width,initial-scale=1">')
    w(f'<meta name="description" content="Identical EEST bloatnet runs reported a {factor:.0f}x '
      'throughput gap between two Nethermind state databases. Five things about how the stores '
      'were built and measured made it. Fix them and the tests that run over a second come back '
      'to parity.">')
    w('<link rel="preconnect" href="https://fonts.googleapis.com">'
      '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
      '<link href="https://fonts.googleapis.com/css2?family=VT323&'
      'family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&display=swap" '
      'rel="stylesheet">')
    w("<title>Nethermind state-DB divergence, benchmarkoor bloatnet runs</title>")
    w(f"<style>{CSS}</style></head><body>")
    w('<div class=topbar><a href="../">&larr; all articles</a>'
      '<span>EXECUTION &middot; STATE DB</span></div>')
    w('<div class=eyebrow>// REPORT</div>')
    w(f"<h1>{title}</h1>")
    w('<div class=meta><span class=tag>Ethereum &middot; nethermind &middot; flat DB &middot; '
      'benchmarking</span> &middot; 2026 &middot; '
      '<a href="https://github.com/CPerezz/articles/tree/main/nethermind-state-db-divergence">'
      'reproducible pipeline &amp; data &rarr;</a></div>')
    w(f"<p class=sub>We ran the same EEST bloatnet benchmarks against two Nethermind databases "
      f"that hold the same state. The one generated from scratch came out up to "
      f"{factor:.0f}&times; slower. It wasn't. Five things about how the two stores were built "
      f"and measured made the gap. Fix them one at a time and the tests that run over a second "
      f"land at a median of {ge_all['a']['median']:.2f}, {ge_all['a']['within10']} of "
      f"{ge_all['a']['n']} inside &plusmn;10%. Here's each one, what it did to the numbers, and "
      f"what's left.</p>")

    # ---- part 1: the problem
    gb = ge_all["base"]
    w("<h2>The problem: the same state, up to %d&times; apart</h2>" % round(factor))
    w(f"<p>Two databases with the same accounts: a mainnet shadowfork snapshot at block "
      f"{thousands(P['snapshot_block'])} (we call it jochemnet), and the same state written from "
      f"scratch by <code>state-actor</code>. Same fixtures, same machine, page cache dropped "
      f"between tests. Every number here is state-actor's throughput divided by jochemnet's: "
      f"1.00 is parity, 0.10 means the generated store is ten times slower.</p>")
    w(fig("fig_overview_before", chart_overview(FN, "base"),
             f"The untreated pair, the {FN['n']} tests at 160M and 240M gas. Over a second, "
             f"{gb['within10']} of {gb['n']} tests sit inside the band; the account reads sit "
             f"at {min(acct):.2f} to {max(acct):.2f}."))
    w("<table><tr><th>tests</th><th class=n>n</th><th class=n>median</th>"
      "<th class=n>inside &plusmn;10%</th></tr>")
    for cls, label in (("ge1s", "over a second"), ("lt1s", "under a second")):
        w(f"<tr><td colspan=4><b>{label}</b></td></tr>")
        for cat, row in final_rows(FN, cls):
            s = row["base"]
            bad = " bad" if s["median"] < 0.5 else ""
            w(f"<tr><td>{esc(ROW_LABEL.get(cat, cat))}</td><td class=n>{s['n']}</td>"
              f"<td class=\"n{bad}\">{s['median']:.3f}</td><td class=n>{s['within10']}/{s['n']}</td></tr>")
    w(f"<caption>Median ratio per category, untreated pair. The full suite of "
      f"{thousands(BEF['agreement']['n'])} tests says the same thing, and gives the "
      f"{factor:.0f}&times; in the title.</caption></table>")
    w("<p>Each dot in the figure is one test. The white tick is the category's median, and the "
      "numbers on the right are that median and how many of the category's tests land inside "
      "&plusmn;10%. The same rows and the same axis come back at the end, after the fixes.</p>")
    w(f"<p>The tests that read accounts are {1/max(acct):.0f} to {1/min(acct):.0f} times slower on "
      f"the generated store. The controls run the same loop and touch no state, and they sit at "
      f"{lt_rows['control (no state work)']['base']['median']:.2f}. That's the first clue. "
      f"Whatever makes account reads that slow isn't the whole client being slow.</p>")
    w(f"<p><b>The second clue is storage.</b> The storage tests that run over a second read far "
      f"more data than any corner of a store could hold, and they sit at "
      f"{ge_rows['storage slot']['base']['median']:.2f}. Ether transfers, which touch accounts "
      f"too, sit at {ge_rows['ether transfer']['base']['median']:.2f}. Whatever this is, it's "
      f"about reading accounts that already exist.</p>")
    w(f"<p><b>Two kinds of test.</b> A test that runs for ten seconds and one that runs for a "
      f"tenth of a second aren't measuring the same thing. Every test boots a fresh client, and "
      f"for its first fraction of a second the client is still warming up. So every view here "
      f"is split at one second of measured time. Under a second, one store measured twice "
      f"lands only {100*min(f_lt):.0f}% to {100*max(f_lt):.0f}% of its tests within "
      f"&plusmn;10% of itself; over a second, {100*min(f_ge):.0f}% to {100*max(f_ge):.0f}% do. "
      f"Sub-second tests are always shown and never counted as "
      f"evidence.</p>")
    w(fig("fig_floor", chart_floor(FN),
             "Amber is state-actor measured twice, the best any comparison can do. Green is the "
             "two stores with every fix applied. Above a second the two nearly meet; below it, "
             "neither gets far."))
    w("<p>Five things caused the gap:</p><ol>"
      "<li>the benchmark's accounts were the newest files in the snapshot;</li>"
      "<li>every test boots a fresh client, and the two stores warm it up differently;</li>"
      "<li>two storage columns nobody had compacted;</li>"
      "<li>a contract's code block is shared with whatever the generator packed next to it;</li>"
      "<li>we had repacked the top of the snapshot's trie into blocks a quarter of the "
      "client's size.</li></ol>")

    # ---- finding 1
    pr = M["prerun"]
    eo_b, eo_a = bc["ACCOUNT cold existing EOA"]["thr"], ac["ACCOUNT cold existing EOA"]["thr"]
    ec_b, ec_a = bc["ACCOUNT cold existing contract"]["thr"], ac["ACCOUNT cold existing contract"]["thr"]
    w("<h2>1. The benchmark's accounts were the newest files in the snapshot</h2>")
    w(fig("fig_amortisation", chart_amortisation(amort),
             f"Cold account lookups against each store's own copy of the fixtures' accounts. At "
             f"{thousands(a0['n'])} lookups the two cost the same, {a0['joc_blk']:.2f} against "
             f"{a0['sa_blk']:.2f} blocks each. By {thousands(a9['n'])}, jochemnet's read volume "
             f"has stopped growing: it has run out of new blocks to read."))
    w(f"<p>Only jochemnet runs a pre-run: {thousands(pr['blocks'])} blocks that create the "
      f"accounts the benchmark then reads. The harness promotes the result into the image every "
      f"test restores from. So each of those accounts has its newest copy in a handful of fresh "
      f"files at the top of the LSM tree, and a lookup stops at the newest file holding the key. "
      f"On jochemnet the benchmark reads a small, hot corner of the store; on state-actor it "
      f"reads all of it.</p>")
    w(f"<p><b>It isn't caching, and it isn't a worse store.</b> The page cache is dropped between "
      f"tests, so the advantage is on disk. And on keys sampled at random from each store's own "
      f"accounts, jochemnet is the more expensive one: {rk['joc_blk']:.2f} blocks per lookup "
      f"against {rk['sa_blk']:.2f}. What the figure shows is that the benchmark's keys are "
      f"special. The cost per lookup is the same on both stores; what runs out on jochemnet is "
      f"the supply of blocks it hasn't read yet.</p>")
    w(f"<p><b>The fix</b> is one compaction of the promoted image, into the bottom level, with the "
      f"client's own table options. No value changes and the state root doesn't move; only which "
      f"file holds each key's newest copy. Then the pre-run comes out of the arm's config: its "
      f"writes are already in the promoted image, and replaying it would rebuild the corner we "
      f"just flattened. The snapshot's account column went from "
      f"{sum(ivb['levels'].values())} files on {len(ivb['levels'])} levels to "
      f"{sum(iva['levels'].values())} files on the bottom one, rewritten in {iva['seconds']:.0f} s. "
      f"<b>What it did,</b> across the full suite of {thousands(AFT['agreement']['n'])} tests: "
      f"existing EOAs went from "
      f"{eo_b:.3f} to {eo_a:.3f}, existing contracts from {ec_b:.3f} to {ec_a:.3f}, and the share "
      f"of tests inside the band from {BEF['agreement']['agree_pct']:.0f}% to "
      f"{AFT['agreement']['agree_pct']:.0f}%. That's almost all of the {factor:.0f}&times;.</p>")

    # ---- finding 2
    w("<h2>2. Every test boots a fresh client, and the two stores warm it up differently</h2>")
    w(fig("fig_jit", chart_jit(J),
             "The same tests with .NET tiered compilation on, as published, and off on both arms. "
             "The sub-second rows swing hardest, which is the reason they aren't counted."))
    w("<p>The harness restarts Nethermind for every test so tests can't leak into each other. "
      "That means every measured block runs in a process a few seconds old, and a young .NET "
      "process is still compiling itself: hot methods start on an unoptimised tier and get "
      "promoted in the background once they've been called enough.</p>")
    w("<p><b>Why the arms differ.</b> The first block after boot is slow on both arms, whatever "
      "it holds. jochemnet's fixtures spend it on a block of real EVM work, so the interpreter "
      "is promoted before the measurement starts. state-actor's fixtures spend it on an empty "
      "block, a fork-activation block they need because that chain starts at genesis. So "
      "state-actor enters the measured block with an interpreter that's still being compiled "
      "underneath it. One arm measures warm code, the other measures the JIT catching up.</p>")
    w(f"<p>The compiler isn't a rounding error. Inside the measured steps of "
      f"{pj['windows']} control tests, the JIT thread burned {pj['threads']['.NET Tiered Com']:.1f} "
      f"CPU-seconds on jochemnet and {ps['threads']['.NET Tiered Com']:.1f} on state-actor, more "
      f"than the threads executing the blocks ({pj['threads']['.NET TP Worker']:.1f} and "
      f"{ps['threads']['.NET TP Worker']:.1f}).</p>")
    w(f"<p><b>What it isn't.</b> Turning off the page-cache drops took state-actor's control "
      f"reads from {dr['sa_read_mb']:.0f} MB to {nd['sa_read_mb']:.1f} MB and made it no faster "
      f"({dr['sa_mgas']:.1f} to {nd['sa_mgas']:.1f} MGas/s). Turning off parallel execution "
      f"made the gap wider ({J['ab']['no_parallel']['thr']:.2f}). Taking the I/O away didn't "
      f"remove the gap. Taking the JIT away did.</p>")
    w(f"<p><b>The test:</b> switch tiered compilation off on both arms, so both run optimised "
      f"code from the first block. It's a diagnostic, not a production setting. <b>What it "
      f"did:</b> the controls went from {J['ab']['baseline']['thr']:.2f} to "
      f"{J['ab']['no_tiered_jit']['thr']:.2f}, and distinct-contract calls from "
      f"{dmp['thr']:.2f} to {dmj['thr']:.2f}. That's the tell: state-actor barely moved, and "
      f"jochemnet got slower ({dmp['joc_secs']:.1f} to {dmj['joc_secs']:.1f} s). With tiering on "
      f"it had reached promoted code partway through the test.</p>")
    w("<p><b>The fix</b> that belongs in the harness is a discarded burn-in block before the "
      "measured one. The harness doesn't have one yet, so <b>every number after this section is "
      "measured with tiered compilation off on both arms</b>. That over-corrects the short tests, "
      "which now land above parity, and it's one more reason they aren't counted.</p>")

    # ---- finding 3
    w("<h2>3. Two storage columns nobody had compacted</h2>")
    w(fig("fig_levels", chart_levels(ST),
             "Where the files sit. Amber is the snapshot as we found it, green is the same column "
             "after one compaction, and the generated store as it was written."))
    w(f"<p>The snapshot's storage rows sat in {col['joc_storage_before']['files']:,} files over "
      f"{len(col['joc_storage_before']['levels'])} LSM levels, and its storage trie in "
      f"{col['joc_storagenodes_before']['files']:,} over "
      f"{len(col['joc_storagenodes_before']['levels'])}. The generated store keeps each in one. "
      f"A lookup for a slot that doesn't exist has to be turned away by every level, so on one "
      f"test the snapshot read {absent_reads['joc_n']:,} blocks where the generated store read "
      f"{absent_reads['sa_n']:,}. This one cut the other way: the generated store was the fast "
      f"one. It hid in the first comparison because the storage tests over a second sat at "
      f"parity, and the absent-slot test runs under one. Finding 1 compacted the columns the "
      f"slow tests read, and storage wasn't one of them.</p>")
    w(fig("fig_storage_close", chart_storage_close(ST),
             "Each storage test through both compactions, 160M and 240M. The overwrite test "
             "touches no trie node and never left the band: each step moved what it was aimed "
             "at."))
    w(f"<p><b>The fix</b> is the same compaction as in finding 1, one column at a time. <b>What it "
      f"did:</b> the absent-slot test went from {sc['slots=False new=False 160M']['r68']:.2f}&times; "
      f"to {sc['slots=False new=False 160M']['r72']:.2f}, and new-value writes from "
      f"{sc['slots=True new=True 160M']['r68']:.2f} to {sc['slots=True new=True 160M']['r72']:.2f}. "
      f"Both absent-slot tests run under a second, so their timings are shown, not counted. The reads are what closed: storage-row reads on the absent-slot "
      f"test are {sr['slots=False new=False 240M']['after_r72']['joc_rows']:,} against "
      f"{sr['slots=False new=False 240M']['after_r72']['sa_rows']:,}, and storage-trie reads on "
      f"the new-value test {sr['slots=True new=True 240M']['after_r72']['joc_nodes']:,} against "
      f"{sr['slots=True new=True 240M']['after_r72']['sa_nodes']:,}.</p>")
    w(f"<p>The lesson isn't about storage. A generated store is written once and compacted once. "
      f"A real one is a stack of levels, and on operations that ask for keys that aren't there "
      f"that difference was worth up to {max(v['r68'] for v in sc.values()):.1f}&times;. "
      f"Compacting the snapshot makes the two stores comparable. It doesn't make the generated "
      f"one more like mainnet.</p>")

    # ---- finding 4
    dm_a, jd_a = ge_rows["code-exec DIFF_MAX"]["a"]["median"], ge_rows["code-exec JUMPDEST"]["a"]["median"]
    dm_b = ge_rows["code-exec DIFF_MAX"]["b"]["median"]
    jd_b = ge_rows["code-exec JUMPDEST"]["b"]["median"]
    extra = IB["pread"]["sa"]["code_mean_b"] - IB["pread"]["joc"]["code_mean_b"]
    w("<h2>4. A contract's code block is shared with whatever the generator packed next to it</h2>")
    w(fig("fig_fetch", chart_fetch(IB),
             "One distinct-contract test, traced on both stores. Same fetches, same account reads; "
             "each code fetch is bigger on the generated store, and more of them cross a page."))
    w(f"<p>After the first three fixes, one kind of test was still slow: calls into a different "
      f"maximum-size contract every time. Both stores key code by its hash, so a contract's "
      f"neighbours in a data block are random. What differs is who they are. On the snapshot, "
      f"{cpop['joc']['pct']:.0f}% of accounts have code, median {cpop['joc']['p50']} bytes and "
      f"a wide spread. On the generated store, {cpop['sa']['pct']:.0f}% do, almost all of it a "
      f"distinct {cpop['sa']['p50']}-byte stub that doesn't compress. Every code fetch is one "
      f"block, and each one is {extra} bytes bigger on the generated store, so more of them cross "
      f"a 4 KB page and pay a second physical read.</p>")
    w(f"<p><b>Why the obvious answer is wrong.</b> The generated store's code database is "
      f"{esc(cprobe['sa']['size'])} against {esc(cprobe['joc']['size'])}, so the natural guess "
      f"is that code lookups cost more there. Measured alone, they cost less. One random cold "
      f"lookup reads {cprobe['sa']['bytes']:,} bytes in {cprobe['sa']['us']:.0f} &micro;s "
      f"against {cprobe['joc']['bytes']:,} bytes in {cprobe['joc']['us']:.0f} &micro;s, and a "
      f"sweep of {thousands(csweep['n'])} distinct maximum-size contracts reads "
      f"{csweep['sa']['bytes']:,} bytes per contract against {csweep['joc']['bytes']:,}. The two "
      f"stores even hold about the same number of maximum-size contracts, "
      f"{cpop['sa']['at_max']} and {cpop['joc']['at_max']} per {thousands(cpop['scanned'])} "
      f"accounts. The cost isn't in the lookup. It's in what the lookup drags in with it.</p>")
    w(f"<p>Each code read takes "
      f"{IB['pread']['sa']['code_mean_us'] - IB['pread']['joc']['code_mean_us']} &micro;s longer "
      f"on average, and {IB['hist_code_ms']['sa']['1-2']}% of them land in the 1&ndash;2 ms "
      f"bucket against {IB['hist_code_ms']['joc']['1-2']}%. The traced test runs about a second "
      f"slower: "
      f"{min(IB['secs']['sa_4k']):.2f}&ndash;{max(IB['secs']['sa_4k']):.2f} s against "
      f"{min(IB['secs']['joc']):.2f}&ndash;{max(IB['secs']['joc']):.2f} s, five runs each.</p>")
    w(fig("fig_code_cells", chart_stages(
        "throughput ratio, state-actor / jochemnet  (band = \u00b110%)",
        [("call, distinct contract", [{"v1": IB["cells"]["DIFF_MAX code-exec"]["before"], "rp": IB["cells"]["DIFF_MAX code-exec"]["after"], "a": dm_a, "b": dm_b}]),
         ("call, jumpdest scan", [{"v1": IB["cells"]["JUMPDEST code-exec"]["before"], "rp": IB["cells"]["JUMPDEST code-exec"]["after"], "a": jd_a, "b": jd_b}]),
         ("call, reused contract", [{"v1": IB["cells"]["SAME_MAX code-exec"]["before"], "rp": IB["cells"]["SAME_MAX code-exec"]["after"],
                                     "a": ge_rows["code-exec SAME_MAX"]["a"]["median"],
                                     "b": ge_rows["code-exec SAME_MAX"]["b"]["median"]}])],
        [("old pool", "v1", "--db-u", 4.5, False), ("one contract per block", "rp", "--green-dim", 3, False),
         ("#141, pair A", "a", "--accent", 4.5, True), ("#141, pair B", "b", "--db-c", 4.5, True)]),
        "The two code cells through the diagnostic repack and the generator fix. The reused "
        "contract never paid for its neighbours and doesn't move."))
    w(f"<p><b>The test:</b> rewrite the generated store's code with one contract per block. Every "
      f"key and value stays the same, and the traced test then ran in "
      f"{', '.join(f'{s:.2f}' for s in IB['secs']['sa_64b'])} s, on jochemnet's side of the gap. Both "
      f"cells closed "
      f"({IB['cells']['DIFF_MAX code-exec']['before']:.3f} to "
      f"{IB['cells']['DIFF_MAX code-exec']['after']:.3f}, "
      f"{IB['cells']['JUMPDEST code-exec']['before']:.3f} to "
      f"{IB['cells']['JUMPDEST code-exec']['after']:.3f}) and the reused-contract control stayed "
      f"put. <b>The fix</b> belongs in the generator's code pool, not in a block size: "
      f"<a href=\"https://github.com/ethereum/state-actor/pull/{IB['pr']}\">state-actor#{IB['pr']}</a> "
      f"slices it from real mainnet bytecode. On a store regenerated with it the two cells read "
      f"{dm_a:.2f} and {jd_a:.2f}. That's the gap closed and a little past it.</p>")
    w(f"<p>Besu sees the same split on the store its own study generated: calls into a distinct "
      f"contract at {bx_lc['EXISTING_CONTRACT_DIFF_MAX']['median']:.2f} against "
      f"{bx_lc['EXISTING_CONTRACT_SAME_MAX']['median']:.2f} for a reused one. Different client, "
      f"different block size, same neighbours.</p>")

    # ---- finding 5
    w("<h2>5. We had repacked the top of the snapshot's trie into 4 KB blocks</h2>")
    w(fig("fig_topnodes", chart_topnodes(TN),
             "Nodes are keyed by path, so a parent and its children are neighbours. The walk to a "
             "touched account reads the parent and one child: one block when they share it, two "
             "when they don't."))
    w(f"<p>A transfer writes two accounts, so every transfer re-hashes both paths up to the state "
      f"root. Nethermind keeps the top of that trie, every node on a path of up to five nibbles, in "
      f"one column, where a node and its "
      f"sixteen children sit side by side. The client packs them into 16 KB blocks, "
      f"{pk['sa_before']['entries_per_block']:.0f} nodes each, so a family usually shares one "
      f"read. The snapshot's column held {pk['joc_before']['entries_per_block']:.0f} nodes per "
      f"4 KB block: {sw['joc']['top_per_account_before']:.2f} top-node reads per touched account "
      f"against {sw['sa']['top_per_account_before']:.2f}.</p>")
    w(f"<p><b>The tries are the same shape.</b> Both tops are the complete sixteen-way tree five "
      f"nibbles deep, "
      f"{thousands(TN['shape']['joc']['top_nodes'])} nodes. The generated trie holds "
      f"{100*(TN['shape']['sa_v1']['accounts_est_M']/TN['shape']['joc']['accounts_est_M']-1):.0f}% "
      f"more accounts and is marginally deeper, {TN['shape']['sa_v1']['walk_nodes']:.2f} nodes on "
      f"a cold root-to-leaf walk against {TN['shape']['joc']['walk_nodes']:.2f}. Shape can't make "
      f"it read fewer nodes. The packing can.</p>")
    w(f"<p>That layout wasn't the snapshot's. We wrote it. RocksDB numbers files in order, and "
      f"the 4 KB files ({pv['StateTopNodes']['min']:06d}&ndash;{pv['StateTopNodes']['max']:06d}) "
      f"came just before our rebuild of the account column ({pv['Account']['min']:06d}+). The "
      f"tool that did it opened the store with the client's options for that one column and "
      f"RocksDB's defaults for the rest, and a pending compaction rewrote the top-of-trie column "
      f"under those defaults. <b>The test:</b> give each store the other's packing. Across "
      f"{sw['n_pairs']} transfer test pairs the cell went from {sw['ratio_settled']:.3f} to "
      f"{sw['ratio_swapped']:.3f}, the read counts swapped, and each arm moved about half the gap "
      f"(jochemnet &times;{sw['joc_change']:.3f}, state-actor &times;{sw['sa_change']:.3f}). The "
      f"snapshot now carries the client's packing.</p>")
    w(f"<p class=note>Also found and fixed, and moving nothing: the generator's closing "
      f"compaction left files the client rewrote on every boot, {thousands(BM['idle']['sa_mb'])} "
      f"MB in {BM['idle']['window_s']} idle seconds "
      f"(<a href=\"https://github.com/ethereum/state-actor/pull/139\">state-actor#139</a>). The "
      f"dead ends and our own measurement mistakes are in the "
      f"<a href=\"https://github.com/CPerezz/articles/tree/main/nethermind-state-db-divergence#method-and-errata\">"
      f"README</a>.</p>")

    # ---- part 3
    ga = ge_all["a"]
    gbb = ge_all["b"]
    la = lt_all["a"]
    w("<h2>Where it stands</h2>")
    w(fig("fig_overview_after", chart_overview(FN, "after"),
             "The same tests after all five fixes, measured as two independent pairs. Compare it "
             "with the first figure: same rows, same axis."))
    w("<table><tr><th>tests</th><th class=n>n</th><th class=n>before</th>"
      "<th class=n>pair A</th><th class=n>pair B</th><th class=n>inside &plusmn;10%</th>"
      "<th class=n>same store twice</th></tr>")
    for cls, label in (("ge1s", "over a second"), ("lt1s", "under a second")):
        w(f"<tr><td colspan=7><b>{label}</b></td></tr>")
        for cat, row in final_rows(FN, cls):
            b_, a_, bb_, fl = row["base"], row["a"], row["b"], row["floor_sa"]
            good = " good" if 0.9 <= a_["median"] <= 1.1 else ""
            w(f"<tr><td>{esc(ROW_LABEL.get(cat, cat))}</td><td class=n>{a_['n']}</td>"
              f"<td class=n>{b_['median']:.3f}</td><td class=\"n{good}\">{a_['median']:.3f}</td>"
              f"<td class=n>{bb_['median']:.3f}</td>")
            w(f"<td class=n>{a_['within10']}/{a_['n']}</td><td class=n>{fl['within10']}/{fl['n']}</td></tr>")
    w("<caption>Median ratio per category. Pair A and pair B are separate runs of both stores; "
      "the last column is state-actor measured twice, the best any row can do.</caption></table>")
    acct_a = [ge_rows[c]["a"]["median"] for c in ge_rows if c.startswith("account row")]
    plain_a = [ge_rows["code-exec " + m]["a"]["median"] for m in ("EXISTING_EOA", "MINIMAL", "SAME_MAX")]
    w(f"<p>Over a second, {ga['within10']} of {ga['n']} tests now sit inside the band (median "
      f"{ga['median']:.3f}, and {gbb['median']:.3f} in the second pair), against "
      f"{ge_all['floor_sa']['within10']} of {ge_all['floor_sa']['n']} when state-actor is "
      f"measured twice. The account reads that started at {min(acct):.2f} are at "
      f"{min(acct_a):.3f} to {max(acct_a):.3f}. Calls into an EOA, a minimal contract or a reused "
      f"one sit at {min(plain_a):.3f} to {max(plain_a):.3f}, and storage at "
      f"{ge_rows['storage slot']['a']['median']:.2f}. Three rows are still further from parity "
      f"than the floor explains: ether transfers at {ge_rows['ether transfer']['a']['median']:.2f}, "
      f"and the distinct-contract and jumpdest calls at {dm_a:.2f} and {jd_a:.2f}. They're the "
      f"first two items below.</p>")
    w(f"<p><b>Pair B</b> repeats the whole comparison with fresh runs of both stores, so neither "
      f"arm's number is shared between the two pairs. Over a second it lands at "
      f"{gbb['median']:.3f} against pair A's {ga['median']:.3f}. That's how we know the table isn't "
      f"one lucky run of either store.</p>")
    w(f"<p><b>Under a second</b>, {la['within10']} of {la['n']} tests land in the band, and the "
      f"same store measured twice manages only {lt_all['floor_sa']['within10']} "
      f"({lt_all['floor_joc']['within10']} for jochemnet). The controls "
      f"read {lt_rows['control (no state work)']['a']['median']:.2f} and the warm queries "
      f"{lt_rows['warm query']['a']['median']:.2f}, above parity because tiering is off. Those "
      f"rows measure the harness, not the stores.</p>")

    # ---- part 4
    cpu_j = aa["cpu_seconds"]["joc"]["160M"][".net thread pool"]
    cpu_s = aa["cpu_seconds"]["sa"]["160M"][".net thread pool"]
    w("<h2>What's left, and why</h2>")
    w(f"<p>The generated state was never {factor:.0f}&times; slower. Three things are left, and "
      f"each has a name:</p><ul>")
    w(f"<li><b>Distinct-contract code runs {100*(min(dm_a, dm_b, jd_a, jd_b)-1):.0f} to "
      f"{100*(max(dm_a, dm_b, jd_a, jd_b)-1):.0f}% faster on the generated store.</b> "
      f"#{IB['pr']} samples real mainnet code but keeps a 1 KiB floor on each record, so a "
      f"fixture contract starts a block of its own more often than on mainnet, where the median "
      f"contract is {cpop['joc']['p50']} bytes. Cheaper than mainnet is as wrong as dearer. The "
      f"next generator fix is record sizes drawn from mainnet's distribution.</li>")
    w(f"<li><b>Ether transfers run about {100*(ge_rows['ether transfer']['a']['median']-1):.0f}% "
      f"faster on the generated store, and up to {nonexist_max:.1f}&times; when the value goes to "
      f"accounts that don't exist yet.</b> We traced {len(traced)} transfer tests on both stores, "
      f"and the read counts match within 5% on every column. So it's client work, not I/O. The "
      f"clearest case creates thousands of accounts in every block, and there the snapshot spends "
      f"{cpu_j:.2f} CPU-seconds in managed thread-pool threads against {cpu_s:.2f}. Turning off "
      f"either warming path doesn't change that. It's open, and the next instrument is a "
      f"profiler.</li>")
    w("<li><b>Sub-second tests can't be compared on this harness yet.</b> That's not a store "
      "property. Every test boots a fresh client, and under a second the measurement is mostly "
      "that client warming up. A discarded burn-in block before the measured one would fix it. "
      "Until the harness has one, those numbers are shown and not counted.</li></ul>")
    w("<p>None of the three is a reason to distrust the generated store on tests over a second. "
      "The first is a generator fix, the second is a question for the client, and the third is a "
      "harness fix.</p>")
    w("<p class=note>Every number on this page is computed from the collected run data when the "
      "page is built, and the build fails if the data stops supporting a sentence.</p>")
    w('<div class=endbar><a href="../">&larr; all articles</a>'
      '<a href="https://github.com/CPerezz/articles/tree/main/nethermind-state-db-divergence">'
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
    print(f"headline factor: {factor:.1f}x")
    print(f"over 1 s: before {gb['median']:.3f} ({gb['within10']}/{gb['n']}), after "
          f"{ga['median']:.3f} ({ga['within10']}/{ga['n']}), floor {ge_all['floor_sa']['within10']}/{ge_all['floor_sa']['n']}")
    print(f"under 1 s: after {la['median']:.3f} ({la['within10']}/{la['n']}), floor "
          f"{lt_all['floor_sa']['within10']}/{lt_all['floor_sa']['n']}")


if __name__ == "__main__":
    main()
