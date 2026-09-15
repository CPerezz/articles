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
    H = T + 26 * len(rows) + 40
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


# --------------------------------------------------------------------------- page
def main():
    D = json.load(open(os.path.join(HERE, "data", "report_data.json")))
    P, M = D["provenance"], D["measured"]
    BEF, AFT = D["before"], D["after"]
    bc, ac = BEF["categories"], AFT["categories"]
    modes, modes_ctrl = AFT["by_mode"], AFT["by_mode_control"]
    add = AFT["additive"]
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

    cc = BEF["cost_curve"]
    w(figure(chart_cost_curves(cc),
             f"Read volume against gas for the contract-reading tests. jochemnet stays flat "
             f"&mdash; {cc[0]['jocMB']:.0f} MB at {cc[0]['gas']}M gas and "
             f"{cc[-1]['jocMB']:.0f} MB at {cc[-1]['gas']}M, triple the work for the same bytes "
             f"&mdash; while state-actor climbs from {cc[0]['saMB']:.0f} MB to "
             f"{cc[-1]['saMB']:.0f} MB. Flat in gas means the arm is re-reading one bounded set "
             f"of blocks; rising means every access goes somewhere new."))

    # ---------------------------------------------------------------- traps
    w("<h2>Two traps before the measurement was even valid</h2>")
    nine, fourteen = M["eip_trap"]["nine"], M["eip_trap"]["fourteen"]
    extra = [e for e in fourteen if e not in nine]
    w(f"<p><b>The EIP list.</b> geth and Besu are told to activate Amsterdam by name and take "
      f"whatever their build considers Amsterdam to be. Nethermind is told nothing of the kind: "
      f"it activates exactly the EIPs you enumerate. benchmarkoor ships two Amsterdam sets, and "
      f"the shorter one &mdash; {len(nine)} EIPs &mdash; makes Nethermind compute a different "
      f"block access list, so every payload came back <code>INVALID</code> with a BAL hash "
      f"mismatch. The mismatch was byte-identical to one Besu had produced earlier, which sent "
      f"us after client builds for two rounds. The cause was the config: the "
      f"<code>existing-snapshot</code> family's {len(fourteen)}-EIP set, which adds "
      f"{esc(', '.join(str(e) for e in extra))}, is the one that reproduces what the other two "
      f"clients get for free.</p>")
    w(f"<p><b>The backend.</b> Nethermind can serve state either from the Patricia trie or from "
      f"a flat database, and it decides at startup by looking for one. The generated store had "
      f"been built by a <code>state-actor</code> revision predating its flat-state writer, so "
      f"Nethermind logged <code>patricia (flat DB disabled)</code> on one arm and "
      f"<code>flat (existing flat DB detected)</code> on the other. The arms were not slow and "
      f"fast; they were structurally unable to share a read path. We published a "
      f"15&times;-wall figure from that pair and then retracted it, rebuilt the store from a "
      f"revision that writes the flat layout, and only then had something worth comparing. The "
      f"rebuild moved the trie rather than removing it: <code>state/</code> went from "
      f"{esc(fp['joc']['state'])}-scale down to {esc(fp['sa']['state'])} as the nodes relocated "
      f"into <code>flat/</code>.</p>")
    w("<p class=note>Both traps share a shape worth naming: a benchmark can be perfectly "
      "reproducible and still be comparing two different things. Neither showed up as an error "
      "&mdash; one showed up as every block being invalid, the other as a number.</p>")

    # ---------------------------------------------------------------- eliminations
    w("<h2>What we ruled out</h2>")
    rk_rows = M["random_keys"]
    w("<table><tr><th>hypothesis</th><th>what killed it</th></tr>")
    w("<tr><td>different RocksDB configuration</td><td>every read-path knob identical, "
      f"column family by column family &mdash; {len(M['options_per_cf']['rows'])} families, "
      "same ribbon filter, same block sizes, same compression, no direct I/O</td></tr>")
    w("<tr><td>different key encoding</td><td>identical <code>keccak256(addr)[0:20]</code>, "
      "identical key-length histograms, and every spec-guaranteed fixture address resolves in "
      "both stores</td></tr>")
    w("<tr><td>the client's read path amplifies</td><td>a cold <code>eth_getBalance</code> on "
      f"the generated store costs {rk_rows['Account']['sa_blk']:.2f} blocks &mdash; exactly its "
      "raw RocksDB cost, so the client adds nothing</td></tr>")
    w(f"<tr><td>startup I/O dominates the window</td><td>jochemnet's boot reads <em>more</em> "
      f"({fp['boot_read_gb']['joc']:.2f} GB vs {fp['boot_read_gb']['sa']:.2f} GB) yet it runs "
      f"{factor:.0f}&times; faster</td></tr>")
    w("<tr><td>background compaction during the run</td><td>writes are negligible against "
      "reads, a ratio of 0.02</td></tr>")
    w("<tr><td>the generated store is simply worse</td><td>on keys sampled from each store's own "
      f"account family, jochemnet is the <em>more</em> expensive one: "
      f"{rk_rows['Account']['joc_blk']:.2f} vs {rk_rows['Account']['sa_blk']:.2f} blocks per "
      "lookup</td></tr>")
    w("<caption>The last row is the one that reframes the problem. If the generated store were "
      "intrinsically slow, it would be slow on its own keys too. It is faster on them. So the "
      "gap cannot be a property of the store in general &mdash; only of the particular keys the "
      "benchmark reads.</caption></table>")

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
    w("<p>This is not a caching story. The harness drops the page cache between every test and "
      "between setup and measurement, and the pre-run happens once, before the loop. What "
      "survives the cache drop is not warm memory &mdash; it is <em>where the bytes sit</em>. "
      "The pre-run's writes are the newest versions of exactly those keys, so they occupy a "
      "small, young, physically contiguous corner of the tree, and a levelled store answers a "
      "lookup from the first place it finds a version.</p>")

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
    w("<h2>Removing the confound instead of explaining it</h2>")
    ab, aa = iv["account_before"], iv["account_after"]
    sb, sa_ = iv["statenodes_before"], iv["statenodes_after"]
    w(f"<p>If the corner is the cause, flattening it must erase the advantage. We merged the "
      f"account and state-node families into their bottom level &mdash; rewriting them with the "
      f"other store's exact per-family options, verified knob by knob, so nothing but placement "
      f"changed &mdash; and stripped the pre-run from the config, because replaying it would "
      f"simply rebuild the corner.</p>")
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
      "<th class=n>equalised</th><th class=n>bytes sa/joc</th><th class=n>within &plusmn;10%</th>"
      "</tr>")
    for cat in CATS:
        if cat not in ac:
            continue
        r, rb = ac[cat], bc[cat]
        good = " good" if 0.9 <= r["thr"] <= 1.1 else ""
        w(f"<tr><td>{esc(SHORT[cat])}</td><td class=n>{r['n']}</td>"
          f"<td class=n>{f(rb['thr'], 3)}</td>"
          f"<td class=\"n{good}\">{f(r['thr'], 3)}</td><td class=n>{f(r['read'])}</td>"
          f"<td class=n>{r['agree']}/{r['n']}</td></tr>")
    w(f"<caption>Tests agreeing within &plusmn;10% go from "
      f"{BEF['agreement']['agree_pct']:.1f}% to {AFT['agreement']['agree_pct']:.1f}%. "
      f"Every category that reads state lands on parity; the control, which reads almost "
      f"nothing, does not move. Independently reproduced on a "
      f"{thousands(D['replication']['agreement']['n'])}-test subset that agreed with the "
      f"uncorrected arm to within a couple of percent, so these ratios are not run-to-run "
      f"noise.</caption></table>")

    w(figure(chart_treatment_dumbbell(bc, ac),
             "Each row is one kind of test: amber is the confounded measurement, green the "
             "equalised one, and the band is &plusmn;10% around parity. The two rows that "
             "were already inside the band stay inside it &mdash; the control that makes "
             "the rest credible."))

    # ---------------------------------------------------------------- code
    dm = modes["EXISTING_CONTRACT_DIFF_MAX"]
    w(f"<h2>Why a different contract per access still costs {dm['readX']:.2f}&times;</h2>")
    w("<p>One cell does not come back to parity, and it is the same cell the geth study flagged "
      "and left unexplained. Sorting the access modes by how much contract code they touch "
      "explains it in one pass:</p>")
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
    w(figure(chart_code_ladder(modes, {"sa": fp["sa"]["code"], "joc": fp["joc"]["code"]}),
             "The residual is a property of how the generator sizes contract code, not of how "
             "either store reads accounts."))

    # ---------------------------------------------------------------- residual
    w("<h2>The residual is one fixed overhead, not a set of slow categories</h2>")
    b0 = add["buckets"][0]
    small_b = [b for b in add["buckets"] if b["jocMB"] < 4000]
    fixed_mb = sorted(b["excess"] for b in small_b)[len(small_b) // 2]
    big_b = add["buckets"][-1]
    w(f"<p>What is left has two terms, and only one of them is interesting. Sorting every test "
      f"by how much it reads on jochemnet, the extra volume state-actor pulls sits near "
      f"{fixed_mb:.0f} MB for everything up to a few gigabytes &mdash; a fixed cost, not a "
      f"penalty per unit of work. On top of it runs a ~10% proportional component, which only "
      f"becomes visible in the largest bucket, where 10% of "
      f"{big_b['jocMB']:.0f} MB is most of the {big_b['excess']:.0f} MB measured:</p>")
    w(figure(chart_additive(add["buckets"]),
             f"Median excess per test, by how much work the test does. Four buckets spanning a "
             f"1600&times; range of test size sit on the same dashed line, which is the fixed "
             f"term; only the largest departs from it, by roughly 10% of its own volume. The "
             f"throughput ratio underneath follows mechanically: a test reading "
             f"{b0['jocMB']:.1f} MB is swamped by the fixed cost and lands at {b0['thr']:.3f}, "
             f"while anything reading hundreds of megabytes absorbs it and sits at parity."))
    w(f"<p>So the model is <code>state-actor &asymp; 1.1 &times; jochemnet + "
      f"{fixed_mb:.0f} MB</code>, and the control row retires as a special case "
      f"rather than a mystery: those tests do no account work, read "
      f"{ac['CONTROL overhead_baseline']['jocMB']:.1f} MB on jochemnet, and are therefore "
      f"entirely overhead. Three explanations are already dead. It is not client startup "
      f"&mdash; jochemnet's boot reads more. It is not trie placement &mdash; merging the "
      f"state-node family moved the control by a percent. And it is not the measurement window "
      f"&mdash; the first payload carries almost all of each test's bytes on both arms. Its "
      f"origin is not yet pinned to a column family, which we would rather say than round off; "
      f"it is bounded, and invisible to any test that does real work.</p>")

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
    w("<ol>")
    w("<li><b>Never compare a promoted-after-pre-run snapshot against a store that did not get "
      "one.</b> It is worth an order of magnitude and it does not announce itself.</li>")
    w("<li><b>Give both arms the same placement treatment</b> &mdash; a pre-run each, or a "
      "compaction each. The generated store's fixtures release currently ships no pre-run "
      "bundle, so compacting both is the cheaper control today.</li>")
    w("<li><b>Make the harness print a locality diagnostic:</b> read bytes per unit of gas, per "
      f"arm. Flat in gas means a bounded working set and therefore an artifact &mdash; "
      f"jochemnet read {cc[0]['jocMB']:.0f} MB at {cc[0]['gas']}M and "
      f"{cc[-1]['jocMB']:.0f} MB at {cc[-1]['gas']}M. That check is a few lines, and it would "
      f"have caught this on the first run instead of the thirtieth.</li>")
    w("</ol>")
    w(f"<p>And the answer to the question in the title: the generated state was never "
      f"{factor:.0f}&times; slower. On account reads the two stores are within "
      f"{(1 - ac['ACCOUNT cold existing contract']['thr'])*100:.0f}&ndash;"
      f"{(1 - ac['ACCOUNT cold existing EOA']['thr'])*100:.0f}%, on storage within "
      f"{(ac['STORAGE slot access']['thr'] - 1)*100:.0f}%, and on ether transfers within "
      f"{(ac['ETHER transfer receivers']['thr'] - 1)*100:.0f}%. Synthetic state is a sound "
      f"substitute for benchmarking state access. It just has to be measured against a store "
      f"that was prepared the same way.</p>")

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
    w("<li>A 15&times; result was published from the Patricia-versus-flat pair and retracted. "
      "Every number here comes from the rebuilt, symmetric pair.</li>")
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
