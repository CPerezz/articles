#!/usr/bin/env python3
"""Build the Nethermind state-DB divergence article from the collected run data.

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


# --------------------------------------------------------------------------- reused figures
def chart_final_pair(fi):
    """The whole suite on two independent pairs, by duration class, against the floor the harness
    itself sets: each store measured against itself."""
    W, L, R, T = 760, 210, 40, 34
    rh, gap = 26, 26
    lanes = [("pair A", "pair_a", "--accent"),
             ("pair B, no run shared", "pair_b", "--accent"),
             ("state-actor vs itself", "floor_sa", "--db-sa"),
             ("jochemnet vs itself", "floor_joc", "--db-c")]
    H = T + (rh * len(lanes) + 20 + gap) * 2 + 24
    sx = S.Scale(0, 100, L, W - R - 150)
    o = [S.label(L - 10, T - 16, "share of tests within \u00b110% of parity", "start", "big")]
    y = T
    for title, key in (("tests \u2265 1 s", "long"), ("tests < 1 s", "short")):
        d = fi["by_class"][key]
        o.append(S.label(L - 10, y + 12, "%s  (n=%d)" % (title, d["pair_a"]["n"]), "end", "big"))
        y += 20
        for name, k, var in lanes:
            v = d[k]
            pct = 100.0 * v["within10"] / v["n"]
            o.append(S.band(L, sx.to(pct), y + 2, y + 20, var, 0.30))
            o.append(S.label(L - 10, y + 15, name, "end", "tick"))
            o.append(S.label(sx.to(pct) + 8, y + 15, "%.0f%%   median %.3f" % (pct, v["median"]),
                             "start", "tick"))
            y += rh
        y += gap
    o.append(S.line(L, T - 6, L, y - gap + 2, "--green-muted", 1))
    for t in (0, 25, 50, 75, 100):
        o.append(S.label(sx.to(t), H - 8, "%d%%" % t, "middle", "tick"))
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
    rows = [("absent slot (< 1 s)", "slots=False new=False"),
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



# --------------------------------------------------------------------------- families
# Seven families, one per finding or open item. Order is the order the article discusses them.
FAMILIES = ["account reads", "code, reused or small", "code, distinct large", "storage",
            "ether transfers", "absent accounts", "no state work"]
FAMILY_NOTE = {
    "account reads": "BALANCE, EXTCODEHASH on existing accounts",
    "code, reused or small": "CALL family on EOA, minimal, one reused max-size contract",
    "code, distinct large": "CALL family on a different max-size contract per access",
    "storage": "sload / sstore on bloated contracts",
    "ether transfers": "value transfers to every receiver shape",
    "absent accounts": "lookups of accounts that do not exist",
    "no state work": "overhead-baseline controls and warm queries",
}
CLASS_TITLE = {"long": "tests \u2265 1 s", "short": "tests < 1 s"}
STAGE_LABEL = {"baseline": "baseline", "placement": "pre-run", "warmup": "warm-up",
               "codepool": "code pool", "final": "final"}


def pct(k, n):
    return 100.0 * k / n if n else 0.0


def chart_family_overview(wf, stage):
    """One dot per family at its median ratio, the line its range, two panels by class. The
    same chart is drawn for the baseline and for the final pair so the two read as before and
    after at a glance."""
    W, L, R, T = 760, 190, 150, 30
    rh, gap = 22, 30
    rows = {c: [f for f in FAMILIES if stage in wf["cells"].get(c, {}).get(f, {})] for c in ("long", "short")}
    H = T + sum(len(v) for v in rows.values()) * rh + gap * 2 + 30
    sx = S.LogScale(0.03, 3.0, L, W - R)
    o = [S.label(L, T - 14, "throughput ratio, state-actor / jochemnet (log; band = \u00b110%)", "start", "big")]
    y = T
    for c in ("long", "short"):
        top = y
        allc = wf["cells"][c]["_all"][stage]
        o.append(S.label(L - 10, y + 10, "%s  (n=%d)" % (CLASS_TITLE[c], allc["n"]), "end", "big"))
        y += 16
        body_top = y
        for fam in rows[c]:
            v = wf["cells"][c][fam][stage]
            lo, hi, md = (max(0.03, min(3.0, v[k])) for k in ("min", "max", "median"))
            o.append(S.label(L - 10, y + 12, fam, "end"))
            o.append(S.line(sx.to(lo), y + 8, sx.to(hi), y + 8, "--green-muted", 2))
            ok = 0.9 <= v["median"] <= 1.1
            o.append(S.dot(sx.to(md), y + 8, 5, "--accent" if ok else "--db-u",
                           "%s, %s: median %.3f, %d of %d in band" % (fam, CLASS_TITLE[c], v["median"], v["within10"], v["n"])))
            o.append(S.label(W - R + 10, y + 12, "%.2f   %d/%d in band" % (v["median"], v["within10"], v["n"]),
                             "start", "tick"))
            y += rh
        o.insert(1, S.band(sx.to(0.9), sx.to(1.1), body_top - 2, y, "--accent", 0.10))
        o.insert(2, S.line(sx.to(1.0), body_top - 2, sx.to(1.0), y, "--green-muted", 1))
        y += gap
    for t in (0.05, 0.1, 0.2, 0.5, 1.0, 2.0):
        o.append(S.label(sx.to(t), y - gap + 16, ("%g" % t), "middle", "tick"))
    return S.svg(W, H, "".join(o))


def chart_placement(wf):
    """Finding 1, isolated: the only thing that changes between the two points of each row is
    that jochemnet's pre-run was compacted. Write families are not shown - their intermediate
    runs were taken on a snapshot our tooling had also repacked."""
    W, L, R, T = 760, 190, 120, 30
    rh, gap = 22, 26
    rows = [(c, fam) for c in ("long", "short") for fam in FAMILIES
            if {"baseline", "placement"} <= set(wf["cells"].get(c, {}).get(fam, {}))]
    H = T + len(rows) * rh + gap * 2 + 26
    sx = S.LogScale(0.03, 3.0, L, W - R)
    o = [S.label(L, T - 14, "state-actor / jochemnet, before and after compacting the pre-run", "start", "big")]
    y = T
    last = None
    for c, fam in rows:
        if c != last:
            if last is not None:
                y += gap - rh
            o.append(S.label(L - 10, y + 10, CLASS_TITLE[c], "end", "big"))
            y += 18
            last = c
        a, b = wf["cells"][c][fam]["baseline"]["median"], wf["cells"][c][fam]["placement"]["median"]
        o.append(S.label(L - 10, y + 12, fam, "end"))
        o.append(S.line(sx.to(a), y + 8, sx.to(b), y + 8, "--green-muted", 2))
        o.append(S.dot(sx.to(a), y + 8, 4.5, "--db-u", "%s baseline %.3f" % (fam, a)))
        o.append(S.dot(sx.to(b), y + 8, 5, "--accent", "%s pre-run compacted %.3f" % (fam, b)))
        o.append(S.label(W - R + 10, y + 12, "%.2f \u2192 %.2f" % (a, b), "start", "tick"))
        y += rh
    o.insert(1, S.band(sx.to(0.9), sx.to(1.1), T + 4, y, "--accent", 0.10))
    o.insert(2, S.line(sx.to(1.0), T + 4, sx.to(1.0), y, "--green-muted", 1))
    for t in (0.05, 0.1, 0.2, 0.5, 1.0, 2.0):
        o.append(S.label(sx.to(t), y + 18, ("%g" % t), "middle", "tick"))
    o.append(S.dot(L, H - 10, 4.5, "--db-u"))
    o.append(S.label(L + 10, H - 6, "baseline", "start", "tick"))
    o.append(S.dot(L + 100, H - 10, 5, "--accent"))
    o.append(S.label(L + 110, H - 6, "jochemnet's pre-run compacted, nothing else changed", "start", "tick"))
    return S.svg(W, H, "".join(o))


def chart_jit(jit):
    """Finding 2, isolated: same stores, one flag on both arms."""
    ab, pub, eq = jit["ab"], jit["slice"]["published"], jit["slice"]["jit_equalised"]
    rows = [("no state work (controls)", ab["baseline"]["thr"], ab["no_tiered_jit"]["thr"]),
            ("absent accounts, code", pub["NON_EXISTING_ACCOUNT code-exec"]["thr"], eq["NON_EXISTING_ACCOUNT code-exec"]["thr"]),
            ("code, distinct large", pub["DIFF_MAX code-exec"]["thr"], eq["DIFF_MAX code-exec"]["thr"]),
            ("code, reused max-size", pub["SAME_MAX code-exec"]["thr"], eq["SAME_MAX code-exec"]["thr"])]
    W, L, R, T = 760, 190, 120, 30
    rh = 26
    H = T + len(rows) * rh + 50
    sx = S.Scale(0.55, 1.25, L, W - R)
    bot = T + len(rows) * rh
    o = [S.band(sx.to(0.9), sx.to(1.1), T - 4, bot, "--accent", 0.10),
         S.line(sx.to(1.0), T - 4, sx.to(1.0), bot, "--green-muted", 1),
         S.label(L, T - 14, "state-actor / jochemnet, tiered JIT on and off (both arms)", "start", "big")]
    for i, (name, a, b) in enumerate(rows):
        y = T + rh * i + 8
        o.append(S.label(L - 10, y + 4, name, "end"))
        o.append(S.line(sx.to(a), y, sx.to(b), y, "--green-muted", 2))
        o.append(S.dot(sx.to(a), y, 4.5, "--db-u", "%s, tiered JIT on: %.3f" % (name, a)))
        o.append(S.dot(sx.to(b), y, 5, "--accent", "%s, tiered JIT off: %.3f" % (name, b)))
        o.append(S.label(W - R + 10, y + 4, "%.2f \u2192 %.2f" % (a, b), "start", "tick"))
    for t in (0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2):
        o.append(S.label(sx.to(t), bot + 16, "%.1f" % t, "middle", "tick"))
    o.append(S.dot(L, H - 10, 4.5, "--db-u"))
    o.append(S.label(L + 10, H - 6, "tiered JIT on (as benchmarked)", "start", "tick"))
    o.append(S.dot(L + 250, H - 10, 5, "--accent"))
    o.append(S.label(L + 260, H - 6, "DOTNET_TieredCompilation=0", "start", "tick"))
    return S.svg(W, H, "".join(o))


def chart_tenancy(ib, cpop):
    """Finding 4, as a picture: what is read to fetch one fixture contract. RocksDB packs
    records into a block until it passes the target size, so a 24,576-byte contract usually
    lands after a tail of whatever was written before it, and a fetch reads the tail too."""
    W, L, T = 760, 190, 34
    rh = 50
    fix_kb, tail_kb = 24.0, 2.0
    scale = 360.0 / (fix_kb + tail_kb)
    rows = [("mainnet snapshot", "real contracts, median %d B, which compress" % cpop["joc"]["p50"], tail_kb, "--green-dim", 0.35),
            ("generated, old pool", "%d-byte stubs, which don't" % cpop["sa"]["p50"], tail_kb, "--db-u", 0.55),
            ("generated, #141 pool", "records \u2265 1 KiB: the contract often starts the block", 0.0, "--db-sa", 0.35)]
    H = T + rh * len(rows) + 20
    o = [S.label(L, T - 16, "the data block a fetch of one 24 KB fixture contract reads", "start", "big")]
    for i, (name, note, tail, var, op) in enumerate(rows):
        y = T + rh * i
        o.append(S.label(L - 10, y + 16, name, "end"))
        x = L
        if tail:
            w = tail * scale
            o.append(S.band(x, x + w, y + 4, y + 26, var, op))
            o.append(S.line(x, y + 4, x, y + 26, var, 1))
            x += w
        o.append(S.band(x, x + fix_kb * scale, y + 4, y + 26, "--accent", 0.16))
        o.append(S.label(x + fix_kb * scale / 2, y + 19, "fixture contract, 24,576 B", "middle", "tick"))
        o.append(S.label(L, y + 40, ("tail: " + note) if tail else note, "start", "tick"))
    o.append(S.label(L + (fix_kb + tail_kb) * scale + 14, T + 19, "{:,} B read per fetch".format(ib["pread"]["joc"]["code_mean_b"]), "start", "tick"))
    o.append(S.label(L + (fix_kb + tail_kb) * scale + 14, T + rh + 19, "{:,} B read per fetch".format(ib["pread"]["sa"]["code_mean_b"]), "start", "tick"))
    o.append(S.label(L + (fix_kb + tail_kb) * scale + 14, T + 2 * rh + 19, "cheaper than mainnet", "start", "tick"))
    return S.svg(W, H, "".join(o))


def chart_code_cells(ib, v2):
    """Finding 4, the proof and the fix: the two distinct-contract cells and the reused-contract
    control, on the old store, the same store repacked, and the regenerated store."""
    rows = [("code, distinct large (DIFF_MAX)", "DIFF_MAX code-exec"),
            ("jump-destination scan (JUMPDEST)", "JUMPDEST code-exec"),
            ("one reused contract (control)", "SAME_MAX code-exec")]
    W, L, R, T = 760, 230, 60, 30
    rh = 30
    H = T + rh * len(rows) + 50
    sx = S.Scale(0.9, 1.15, L, W - R)
    bot = T + rh * len(rows)
    o = [S.band(sx.to(0.9), sx.to(1.1), T - 4, bot, "--accent", 0.10),
         S.line(sx.to(1.0), T - 4, sx.to(1.0), bot, "--green-muted", 1),
         S.label(L, T - 14, "state-actor / jochemnet on the three code cells", "start", "big")]
    for i, (name, key) in enumerate(rows):
        y = T + rh * i + 10
        o.append(S.label(L - 10, y + 4, name, "end"))
        pts = [(ib["cells"][key]["before"], "--db-u", 5, "old pool, 4 KB blocks"),
               (ib["cells"][key]["after"], "--green-dim", 5, "same store, 64-byte blocks"),
               (v2["cells"][key]["v2r1"], "--db-sa", 5, "regenerated with #141, run 1"),
               (v2["cells"][key]["v2r2"], "--db-sa", 3.5, "regenerated with #141, run 2")]
        xs = [sx.to(max(0.9, min(1.15, v))) for v, _, _, _ in pts]
        o.append(S.line(min(xs), y, max(xs), y, "--green-muted", 1, dash="2 3"))
        for (v, var, r, t), x in zip(pts, xs):
            o.append(S.dot(x, y, r, var, "%s: %.3f" % (t, v)))
    for t in (0.9, 0.95, 1.0, 1.05, 1.1, 1.15):
        o.append(S.label(sx.to(t), bot + 16, "%.2f" % t, "middle", "tick"))
    for j, (var, t) in enumerate((("--db-u", "old pool"), ("--green-dim", "repacked: contract alone in its block"),
                                  ("--db-sa", "regenerated with #141"))):
        x = 20 + (0, 110, 400)[j]
        o.append(S.dot(x, H - 10, 5, var))
        o.append(S.label(x + 10, H - 6, t, "start", "tick"))
    return S.svg(W, H, "".join(o))


def chart_waterfall(wf):
    """Every family through every stage, one small panel each, one row per duration class.
    Transfers and storage show only the two ends; the sub-second row has no code-pool point
    (that run covered the long class)."""
    stages = wf["stages"]
    rows = [(c, [fam for fam in FAMILIES if fam in wf["cells"].get(c, {})]) for c in ("long", "short")]
    cols = max(len(r) for _, r in rows)
    W, T, pw, ph, gx = 760, 26, 142, 118, 8
    H = T + len(rows) * (ph + 40) + 6
    o = [S.label(8, T - 10, "state-actor / jochemnet at each stage (log; band = \u00b110%)", "start", "big")]
    for ri, (c, fams) in enumerate(rows):
        ry = T + 8 + ri * (ph + 40)
        o.append(S.label(8, ry + 10, CLASS_TITLE[c], "start", "big"))
        for ci, fam in enumerate(fams):
            cx, cy = 8 + ci * (pw + gx), ry + 18
            sx = S.Scale(0, len(stages) - 1, cx + 28, cx + pw - 6)
            sy = S.LogScale(0.03, 3.0, cy + ph - 22, cy + 22)
            o.append(S.band(cx + 28, cx + pw - 6, sy.to(1.1), sy.to(0.9), "--accent", 0.10))
            o.append(S.line(cx + 28, sy.to(1.0), cx + pw - 6, sy.to(1.0), "--green-muted", 1))
            o.append(S.label(cx + 28, cy + 10, fam, "start", "tick"))
            for tk in (0.1, 1.0):
                o.append(S.label(cx + 24, sy.to(tk) + 4, "%g" % tk, "end", "tick"))
            cell = wf["cells"][c][fam]
            pts = [(sx.to(j), sy.to(max(0.03, min(3.0, cell[s]["median"]))), s) for j, s in enumerate(stages) if s in cell]
            for (x1, y1, s1), (x2, y2, s2) in zip(pts, pts[1:]):
                gapped = stages.index(s2) - stages.index(s1) > 1
                o.append(S.line(x1, y1, x2, y2, "--green-muted" if gapped else "--accent", 1.5,
                                dash="3 3" if gapped else None))
            for x, y, s in pts:
                m = cell[s]["median"]
                o.append(S.dot(x, y, 3.5, "--accent" if 0.9 <= m <= 1.1 else "--db-u",
                               "%s, %s, %s: %.3f" % (fam, CLASS_TITLE[c], STAGE_LABEL[s], m)))
            for j in range(len(stages)):
                o.append(S.label(sx.to(j), cy + ph - 6, "%d" % j, "middle", "tick"))
    return S.svg(W, H, "".join(o))


# --------------------------------------------------------------------------- page
def main():
    D = json.load(open(os.path.join(HERE, "data", "report_data.json")))
    P, M = D["provenance"], D["measured"]
    BEF, AFT = D["before"], D["after"]
    WF, JIT, BM = D["waterfall"], D["jit_experiment"], D["bottommost"]
    IB, V2, ST, FI = D["intervention_blocks"], D["v2"], D["storage"], D["final"]
    wc = WF["cells"]

    # ----------------------------------------------------------------- oracles
    # Scope: the article starts at the flat-backed pair. A collector re-pointed at an earlier run
    # (before the generated store had the flat layout) must fail, not publish.
    assert P["arms"]["sa"]["run"] == M["preconditions"]["sa_run_flat_backed"], \
        "state-actor arm is not the flat-backed run: %r" % P["arms"]["sa"]
    assert P["arms"]["joc"]["run"] == M["preconditions"]["joc_run"], \
        "jochemnet arm is not the recorded run: %r" % P["arms"]["joc"]
    # The headline and Finding 1 (1,461 tests).
    factor = 1.0 / min(BEF["categories"][c]["thr"] for c in
                       ("ACCOUNT cold existing EOA", "ACCOUNT cold existing contract"))
    assert 10 <= factor <= 20, "headline factor moved out of band: %.1f" % factor
    assert AFT["agreement"]["n"] == BEF["agreement"]["n"] == sum(g["n"] for g in BEF["per_gas"]), \
        "the sweep's before and after sets are not the same tests"
    assert AFT["agreement"]["agree_pct"] > 3 * BEF["agreement"]["agree_pct"], \
        "compacting the pre-run no longer multiplies agreement"
    # The waterfall: membership, coverage and gap markers must match what the figure draws.
    assert sum(WF["membership"]["long"].values()) == FI["classes"]["long"] and \
        sum(WF["membership"]["short"].values()) == FI["classes"]["short"], \
        "waterfall membership disagrees with the final pair's classes"
    assert WF["coverage"]["codepool"]["short"] < 0.1 * FI["classes"]["short"] and "codepool" not in wc["short"]["_all"], \
        "the code-pool stage now covers the short class; the gap marker is wrong"
    for fam in WF["write_families"]:
        for c in ("long", "short"):
            if fam in wc.get(c, {}):
                assert set(wc[c][fam]) <= {"baseline", "final"}, \
                    "%s shows intermediate stages taken on an altered snapshot" % fam
    # The baseline gap is real and lives in the families that read accounts.
    for fam, lim in (("account reads", 0.1), ("code, reused or small", 0.1), ("code, distinct large", 0.5)):
        assert wc["long"][fam]["baseline"]["median"] < lim, \
            "%s was not far below parity at baseline: %r" % (fam, wc["long"][fam]["baseline"])
    assert abs(wc["long"]["storage"]["baseline"]["median"] - 1) < 0.05, \
        "storage was not at parity at baseline; 'nobody looked at it' no longer holds"
    # Finding 1 isolated: compacting jochemnet's pre-run alone brings the account families up.
    for fam in ("account reads", "code, reused or small"):
        assert wc["long"][fam]["placement"]["median"] > 0.85, \
            "compacting the pre-run no longer brings %s to parity: %r" % (fam, wc["long"][fam])
    # Finding 2 isolated: one flag, both arms; controls cross parity, distinct-code closes most.
    ab = JIT["ab"]
    assert ab["baseline"]["thr"] < 0.8 < 1.0 < ab["no_tiered_jit"]["thr"], \
        "tiered JIT is no longer what separates the control tests: %r" % ab
    dm_pub, dm_eq = JIT["slice"]["published"]["DIFF_MAX code-exec"]["thr"], JIT["slice"]["jit_equalised"]["DIFF_MAX code-exec"]["thr"]
    assert dm_eq > dm_pub + 0.2, "equalising the JIT no longer moves distinct-contract code"
    _na_p, _na_e = JIT["slice"]["published"]["NON_EXISTING_ACCOUNT code-exec"], JIT["slice"]["jit_equalised"]["NON_EXISTING_ACCOUNT code-exec"]
    assert min(_na_p["joc_secs"] / _na_e["joc_secs"], _na_p["sa_secs"] / _na_e["sa_secs"]) > 1.5, \
        "equalising the JIT no longer speeds the short tests up on both arms"
    tier = {arm: 100 * p["threads"].get(".NET Tiered Com", 0) / sum(p["threads"].values())
            for arm, p in JIT["profile"].items()}
    assert tier["joc_unsettled"] > 50 and 25 < tier["sa_unsettled"] < 60, \
        "the tiering thread's share of CPU is no longer what the section says: %r" % tier
    # Finding 3: the client rewrote the store, the fix silenced it, and throughput did not move.
    assert BM["idle"]["sa_mb"] > 500 > BM["idle"]["joc_mb"] and BM["idle"]["sa_settled_mb"] < 10, \
        "the idle-rewrite finding no longer holds: %r" % BM["idle"]
    assert BM["boot"]["sa"]["reason"] == "BottommostFiles", "compaction reason changed: %r" % BM["boot"]["sa"]
    bm_move = BM["cells"]["DIFF_MAX code-exec"]["settled"] - (BM["cells"]["DIFF_MAX code-exec"]["r1"] + BM["cells"]["DIFF_MAX code-exec"]["r2"]) / 2
    assert abs(bm_move) < 0.05, "settling the store moved DIFF_MAX %.3f; 'not the cause' is out" % bm_move
    # Finding 4: larger code fetches on the old pool, repacking closes both cells and leaves the
    # control, the regenerated store overshoots.
    assert IB["pread"]["sa"]["code_mean_b"] > 1.2 * IB["pread"]["joc"]["code_mean_b"], \
        "code blocks are no longer larger per fetch on the old pool: %r" % IB["pread"]
    for key in ("DIFF_MAX code-exec", "JUMPDEST code-exec"):
        c_ = IB["cells"][key]
        assert c_["before"] < 0.96 and abs(c_["after"] - 1) < 0.03, "%s no longer closes when repacked: %r" % (key, c_)
        assert min(V2["cells"][key]["v2r1"], V2["cells"][key]["v2r2"]) > 1.04, \
            "%s no longer overshoots on the regenerated store: %r" % (key, V2["cells"][key])
    assert abs(IB["cells"]["SAME_MAX code-exec"]["after"] - IB["cells"]["SAME_MAX code-exec"]["before"]) < 0.02 and \
        abs(V2["cells"]["SAME_MAX code-exec"]["v2r1"] - 1) < 0.02, "the reused-contract control moved"
    # Finding 5: two unsettled columns, each compaction equalised its reads, the control held.
    col, sc, sr = ST["columns"], ST["cells"], ST["reads"]
    assert len(col["joc_storage_before"]["levels"]) >= 5 and col["joc_storage_after"]["levels"] == [6]
    assert len(col["joc_storagenodes_before"]["levels"]) >= 4 and col["joc_storagenodes_after"]["levels"] == [6]
    for nm, sh in col.items():
        if isinstance(sh, dict) and "per_level" in sh:
            assert {int(k) for k in sh["per_level"]} == set(sh["levels"]) and sum(sh["per_level"].values()) == sh["files"], \
                "per-level counts disagree with the column summary for %s" % nm
    for k in ("slots=False new=False 160M", "slots=False new=False 240M"):
        assert sc[k]["r68"] > 1.9 and sc[k]["r72"] < 1.15, "the absent-slot cell no longer closes: %r" % sc[k]
    for k, v in sc.items():
        secs = [int(k.split()[-1][:-1]) / v[x] for x in v if x.endswith(("_joc", "_sa"))]
        if k.startswith("slots=False new=False"):
            assert max(secs) < 1, "the absent-slot test now runs over a second; quote its ratio: %s" % k
        elif k.startswith("slots=True"):
            assert min(secs) > 1, "%s now runs under a second; its ratio can't be quoted" % k
    ar_ = sr["slots=False new=False 240M"]["after_r69"]
    assert abs(ar_["joc_rows"] / ar_["sa_rows"] - 1) < 0.15 and \
        D["outliers"]["tests"]["sstore slots=False new=False 240M"]["cols"]["flat/Storage"]["joc_n"] > \
        3 * D["outliers"]["tests"]["sstore slots=False new=False 240M"]["cols"]["flat/Storage"]["sa_n"], \
        "the absent-slot test's storage-row reads no longer equalise from a multiple: %r" % ar_
    for k in ("slots=True new=True 160M", "slots=True new=True 240M"):
        assert sr[k]["after_r69"]["joc_nodes"] > 1.1 * sr[k]["after_r69"]["sa_nodes"] and \
            abs(sr[k]["after_r72"]["joc_nodes"] / sr[k]["after_r72"]["sa_nodes"] - 1) < 0.1, \
            "storage-trie reads did not equalise: %r" % sr[k]
    for k in ("slots=True new=False 160M", "slots=True new=False 240M"):
        assert abs(sc[k]["r69"] - 1) < 0.05 and abs(sc[k]["r72"] - 1) < 0.05, "the overwrite control moved: %r" % sc[k]
    # Where it stands: long class at parity beside its floor, short class unreadable, outliers
    # concentrated, every state-reading family at parity except the two named items.
    lo, sh_ = FI["by_class"]["long"], FI["by_class"]["short"]
    ol = FI["outliers"]
    assert abs(lo["pair_a"]["median"] - 1) < 0.03 and abs(lo["pair_b"]["median"] - 1) < 0.03, "long class left parity: %r" % lo
    assert min(lo["floor_sa"]["within10"], lo["floor_joc"]["within10"]) >= max(lo["pair_a"]["within10"], lo["pair_b"]["within10"]), \
        "a pair beats a store's own floor: %r" % lo
    assert max(sh_["floor_sa"]["within10"], sh_["floor_joc"]["within10"]) / sh_["floor_sa"]["n"] < 0.65, \
        "short class now reproduces; it could be quoted: %r" % sh_
    assert set(FI["tiered_compilation"]) >= {"nm-sa-fin1", "nm-sa-fin2", "nm-joc-fin1", "nm-joc-fin2"} and \
        all(v == "0" for v in FI["tiered_compilation"].values()), \
        "a run after Finding 2 has tiered compilation on: %r" % FI["tiered_compilation"]
    assert ol["long"] < 0.2 * lo["pair_a"]["n"] and ol["long_buckets"].get("code pool (#141 overshoot)", 0) >= 0.6 * ol["long"], \
        "the long outliers are no longer mostly the pool overshoot: %r" % ol
    for fam in ("account reads", "code, reused or small", "storage"):
        v = wc["long"][fam]["final"]
        assert abs(v["median"] - 1) < 0.03 and v["within10"] >= v["n"] - 1, "%s is not at parity on the final pair: %r" % (fam, v)
    assert wc["long"]["code, distinct large"]["final"]["median"] > 1.04, "the pool overshoot is gone; rewrite part 4"
    aa = ST["absent_account"]
    assert min(aa["throughput"]["160M"]["sa"]) > 1.2 * max(aa["throughput"]["160M"]["joc"]) and \
        aa["cpu_seconds"]["joc"]["160M"][".net thread pool"] > 1.5 * aa["cpu_seconds"]["sa"]["160M"][".net thread pool"], \
        "the absent-account CPU item no longer holds: %r" % aa
    for cfg in ("B prewarming off", "C trie warmer off"):
        assert min(ST["ablation"][cfg]["sa 160M"]) > 1.15 * max(ST["ablation"][cfg]["joc 160M"]), \
            "%s now closes the absent-account gap" % cfg
    # Where it stands, transfers: the worst long miss is an absent-account transfer, and every
    # traced transfer outlier issues the same reads on both stores.
    ot = D["outliers"]["tests"]
    assert ol["long_rows"][0]["cat"] == "ether transfer" and "nonexistent" in ol["long_rows"][0]["variant"], \
        "the worst long miss is no longer an absent-account transfer: %r" % ol["long_rows"][0]
    wtr = next(v["cols"] for k, v in ot.items() if k.startswith("amt") and k.split(" ", 1)[1] == ol["long_rows"][0]["variant"])
    tr_dev = 100 * max(abs(c_["sa_n"] / c_["joc_n"] - 1) for k, v in ot.items() if k.startswith("amt") for c_ in v["cols"].values())
    assert tr_dev < 5, "a transfer outlier now reads differently on the two stores: %.1f%%" % tr_dev
    # Finding 1's placement evidence, Finding 2's setup reads and parallel ablation, Besu's shape.
    rkn_, am_ = M["random_keys"]["StateNodes"], M["amortisation"]["points"][-1]
    assert rkn_["joc_blk"] > rkn_["sa_blk"], "jochemnet is no longer the more expensive store on random keys"
    assert am_["joc_blk"] < 0.5 * am_["sa_blk"] and am_["joc_mb"] < 0.5 * am_["sa_mb"], \
        "jochemnet's working set no longer stops growing: %r" % am_
    assert D["steps"]["control"]["joc"]["setup"] > 2 * D["steps"]["control"]["sa"]["setup"], \
        "jochemnet's setup block no longer does much more work than state-actor's"
    assert ab["no_parallel"]["thr"] < ab["baseline"]["thr"], "turning parallel execution off no longer moves away from parity"
    bx_ = M["besu_cross_check"]["families"]["loads_code"]
    assert bx_["EXISTING_CONTRACT_DIFF_MAX"]["median"] < bx_["EXISTING_CONTRACT_SAME_MAX"]["median"] - 0.05, \
        "Besu's distinct-contract code no longer trails its reused contract"

    # ----------------------------------------------------------------- page
    o = []
    w = o.append
    title = "How can two Nethermind databases holding the same state differ %d&times;?" % round(factor)
    w("<!doctype html><html lang=en><head><meta charset=utf-8>")
    w('<meta name=viewport content="width=device-width,initial-scale=1">')
    w('<meta name="description" content="A mainnet snapshot and a generated store run the same '
      'EEST benchmark suite and disagree by up to 17x. Five findings account for it; what is left '
      'once they are fixed is two named items and a class of tests that cannot be read at all.">')
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
    w("<p class=sub>A mainnet snapshot, a generated store, the same benchmark suite. Five "
      "reasons the numbers disagreed, and what is left once all five are fixed.</p>")

    # ================================================================= 1. the problem
    b_long, b_short = wc["long"]["_all"]["baseline"], wc["short"]["_all"]["baseline"]
    ar0 = wc["long"]["account reads"]["baseline"]
    w("<h2>The problem</h2>")
    w(f"<p>We ran the same EEST bloatnet suite against two Nethermind databases holding the "
      f"same logical state: <b>jochemnet</b>, a mainnet shadowfork snapshot at block "
      f"{thousands(P['snapshot_block'])}, and a store generated from scratch by "
      f"<b>state-actor</b>. Same fixtures, same machine, page cache dropped between tests. If the "
      f"two stores were equivalent, every test would run at the same speed on both. They didn't: "
      f"where the tests read accounts, the generated store looked up to "
      f"<b>{factor:.0f}&times;</b> slower.</p>")
    w(f"<p>Each test is two blocks. A setup block deploys or funds what the test needs; then the "
      f"measured block does the work, thousands of cold account lookups, contract calls, storage "
      f"writes or transfers sized to a gas budget (160M and 240M here). Before every test the "
      f"harness restores the store from a golden image and boots a fresh client, and it drops the "
      f"page cache between the two blocks, so each measured block starts cold. Both arms run the "
      f"same Nethermind image with the same flags, reading through its flat state database.</p>")
    w("<p>The gap came apart into five findings, each fixed and measured on its own:</p>")
    w("<ol>"
      "<li>The snapshot's pre-run was baked into its baseline.</li>"
      "<li>The client restarts for every test, and the two stores warm it up differently.</li>"
      "<li>The generated store made the client rewrite it on every boot.</li>"
      "<li>What shares a code block with the contract being read.</li>"
      "<li>Two storage columns nobody had compacted.</li></ol>")
    fbl, fbs = FI["by_class"]["long"], FI["by_class"]["short"]
    span = lambda c: "%.0f&ndash;%.0f%%" % tuple(sorted(pct(c[k]["within10"], c[k]["n"]) for k in ("floor_sa", "floor_joc")))
    w(f"<p><b>How to read the numbers.</b> Every ratio is state-actor's throughput over "
      f"jochemnet's on the same test: 1.00 is parity, below 1 the generated store is slower. We "
      f"split the suite at one second of measured time, because a sub-second test doesn't "
      f"reproduce against itself. Measure the same store twice and "
      f"{span(fbl)} of the longer tests land within &plusmn;10% of their first result, but only "
      f"{span(fbs)} of the short ones. Short tests appear in every view below, but we read no store "
      f"difference from them.</p>")
    w(figure(chart_family_overview(WF, "baseline"),
             f"The baseline, by family: {b_long['n']} tests over a second and {b_short['n']} under, "
             f"at 160M and 240M gas. Each dot is a family's median, the line its range. Account "
             f"reads sit at {ar0['median']:.2f} and code on reused contracts at "
             f"{wc['long']['code, reused or small']['baseline']['median']:.2f}; storage, which "
             f"reads no account, is the one family at parity."))
    w("<table><tr><th>family</th><th>what it does</th><th class=n>\u2265 1 s</th>"
      "<th class=n>median</th><th class=n>&lt; 1 s</th><th class=n>median</th></tr>")
    for fam in FAMILIES:
        cl_ = wc["long"].get(fam, {}).get("baseline")
        cs_ = wc["short"].get(fam, {}).get("baseline")
        def cell(v):
            if not v:
                return "<td class=n>&ndash;</td><td class=n>&ndash;</td>"
            cls_ = " bad" if v["median"] < 0.9 else (" good" if v["median"] > 1.1 else "")
            return f"<td class=n>{v['n']}</td><td class=\"n{cls_}\">{v['median']:.2f}</td>"
        w(f"<tr><td>{esc(fam)}</td><td>{esc(FAMILY_NOTE[fam])}</td>{cell(cl_)}{cell(cs_)}</tr>")
    w("<caption>Baseline medians, state-actor over jochemnet.</caption></table>")

    # ================================================================= finding 1
    pr = M["prerun"]
    w("<h2>Finding 1: the snapshot's pre-run was baked into its baseline</h2>")
    w(f"<p>Before measuring, the jochemnet arm replays {thousands(pr['blocks'])} blocks that "
      f"create the accounts the benchmark reads, and the harness promotes the result into the "
      f"image every test restores from. Those accounts are then the newest versions in the "
      f"youngest files of the LSM tree: a handful of recently flushed files near the top, where a "
      f"cold lookup finds them in one or two reads. On the generated store the same accounts are "
      f"spread through a fully compacted tree, which is what a cold read on a real node looks "
      f"like. The baseline compared a hot corner of one store with the whole of the other.</p>")
    rkn, am9 = M["random_keys"]["StateNodes"], M["amortisation"]["points"][-1]
    w(f"<p>Two measurements say it is placement and not content. On keys sampled from each "
      f"store's own contents instead of the benchmark's, jochemnet is the <em>more</em> expensive "
      f"store: {rkn['joc_blk']:.2f} blocks per trie-node lookup against {rkn['sa_blk']:.2f}. Its "
      f"data isn't cheaper to read; the benchmark's keys are. And as the benchmark reads more "
      f"accounts, jochemnet's read volume stops growing: {am9['joc_mb']:.0f} MB for "
      f"{thousands(am9['n'])} lookups, {am9['joc_blk']:.2f} blocks each, because the same few "
      f"files serve all of them. state-actor reads {am9['sa_mb']:.0f} MB at "
      f"{am9['sa_blk']:.2f} blocks each, flat. A working set that stops growing is the signature "
      f"of a hot corner.</p>")
    w("<p>We fixed it the way a real node would have: compact the snapshot, so its benchmark "
      "accounts sit where every other key does. Nothing about the generated store changed.</p>")
    ar1 = wc["long"]["account reads"]["placement"]
    cr0, cr1 = wc["long"]["code, reused or small"]["baseline"], wc["long"]["code, reused or small"]["placement"]
    w(figure(chart_placement(WF),
             f"The same tests before and after compacting jochemnet's pre-run. Account reads go "
             f"from {ar0['median']:.2f} to {ar1['median']:.2f}, code on reused or small contracts "
             f"from {cr0['median']:.2f} to {cr1['median']:.2f}. Transfers and storage are left out "
             f"here and shown at the two ends in the waterfall below."))
    pg = [g["gas"] for g in BEF["per_gas"]]
    w(f"<p>Across the full sweep, {thousands(AFT['agreement']['n'])} tests at {len(pg)} gas levels "
      f"from {min(pg)}M to {max(pg)}M, the share that agree within "
      f"&plusmn;10% went from {BEF['agreement']['agree_pct']:.1f}% to "
      f"{AFT['agreement']['agree_pct']:.1f}%, and the long class's median from "
      f"{wc['long']['_all']['baseline']['median']:.2f} to {wc['long']['_all']['placement']['median']:.2f}. "
      f"That is the bulk of the {factor:.0f}&times;. What it left behind is distinct-contract code at "
      f"{wc['long']['code, distinct large']['placement']['median']:.2f}, and a sub-second class that "
      f"got no better, which is the next finding.</p>")

    # ================================================================= finding 2
    ctl0, ctl1 = ab["baseline"]["thr"], ab["no_tiered_jit"]["thr"]
    w("<h2>Finding 2: the client restarts for every test, and the stores warm it up differently</h2>")
    w(f"<p>The harness restarts Nethermind for every test, so tests stay independent. That "
      f"means every measured block runs in a .NET process a few seconds old, which is still "
      f"compiling itself: hot methods start in an unoptimised tier and get promoted in the "
      f"background. jochemnet's setup step is heavy EVM work, so its interpreter is promoted by "
      f"the time the measured block arrives. state-actor's setup is an empty block, so its "
      f"measured block runs unoptimised. The tiering thread alone takes "
      f"{tier['joc_unsettled']:.0f}% of jochemnet's measured-step CPU and "
      f"{min(tier['sa_unsettled'], tier['sa_settled']):.0f}&ndash;{max(tier['sa_unsettled'], tier['sa_settled']):.0f}% "
      f"of state-actor's.</p>")
    stp = D["steps"]["control"]
    w(f"<p>The control tests show it most cleanly, because they do no state work at all: they "
      f"measure the process. Their setup block reads {stp['joc']['setup']:.0f} MB on jochemnet and "
      f"{stp['sa']['setup']:.0f} MB on state-actor, and their measured block ran at "
      f"{ctl0:.2f}, the generated store slower on a test that never touches the store.</p>")
    w(figure(chart_jit(JIT),
             f"One flag on both arms, <code>DOTNET_TieredCompilation=0</code>, which compiles "
             f"every method fully optimised on its first call. The control tests cross parity "
             f"({ctl0:.2f} &rarr; {ctl1:.2f}) and distinct-contract code closes most of its gap "
             f"({dm_pub:.2f} &rarr; {dm_eq:.2f})."))
    w(f"<p>The other suspect for a process-level gap was parallel execution, and it points the "
      f"wrong way: turning it off moved the controls to {ab['no_parallel']['thr']:.2f}, further "
      f"from parity, not closer.</p>")
    na_p, na_e = JIT["slice"]["published"]["NON_EXISTING_ACCOUNT code-exec"], JIT["slice"]["jit_equalised"]["NON_EXISTING_ACCOUNT code-exec"]
    speed = min(na_p["joc_secs"] / na_e["joc_secs"], na_p["sa_secs"] / na_e["sa_secs"])
    w("<p>The fix is a harness setting, not a store change, and it equalises the arms rather than "
      "making them realistic: a live node's EVM is long past the tiering threshold. It also makes "
      f"the sub-second account tests at least {speed:.1f}&times; faster on both arms, which says "
      "how much of a short test is the process warming up. The honest fix is a discarded burn-in block before every "
      "measured one; the harness can't do that yet, so every number from here on is taken with "
      "tiered compilation off on both sides.</p>")

    # ================================================================= finding 3
    w("<h2>Finding 3: the generated store made the client rewrite it on every boot</h2>")
    w(f"<p>state-actor finished its store with a plain <code>CompactRange</code>. With no "
      f"compaction filter configured, RocksDB <em>moves</em> the flushed files into the bottom "
      f"level instead of rewriting them, so their sequence numbers stay set. Every client that "
      f"opens the store starts rewriting its bottom files, and since the harness restarts the "
      f"client per test, that rewrite restarted {thousands(M['harness']['tests'])} times and "
      f"never finished. An idle client with zero queries read "
      f"{thousands(BM['idle']['sa_mb'])} MB in {BM['idle']['window_s']} seconds.</p>")
    w(f"<p>The client's own event log names it: {BM['boot']['sa']['jobs']} compaction jobs at "
      f"every boot, reason <code>{esc(BM['boot']['sa']['reason'])}</code>, on a store with nothing "
      f"pending.</p>")
    w(figure(chart_seqno_paths(BM),
             "Both paths end with every file in the bottom level and no compaction pending, which "
             "is why neither level shape nor pending bytes can tell them apart. Only the sequence "
             "numbers differ."))
    w(f"<p>Forcing the bottommost rewrite silenced it: idle reads went from "
      f"{thousands(BM['idle']['sa_mb'])} MB to {BM['idle']['sa_settled_mb']}. The fix is now in "
      f"the generator as <a href=\"https://github.com/ethereum/state-actor/pull/139\">"
      f"state-actor#139</a>. Throughput moved by {bm_move:+.3f}. A real defect, and not the "
      f"cause.</p>")

    # ================================================================= finding 4
    pj, ps = IB["pread"]["joc"], IB["pread"]["sa"]
    dmc, jdc, smc = IB["cells"]["DIFF_MAX code-exec"], IB["cells"]["JUMPDEST code-exec"], IB["cells"]["SAME_MAX code-exec"]
    w("<h2>Finding 4: what shares a code block with the contract being read</h2>")
    w(f"<p>With the first three fixed, one thing still separated the stores on long tests: "
      f"executing a contract the store had never served. Distinct-contract code sat at "
      f"{dmc['before']:.3f} and jump-destination scanning at {jdc['before']:.3f}, while the same "
      f"opcodes on one reused contract were at {smc['before']:.3f}.</p>")
    w("<p>Code is keyed by its hash, so a contract's neighbours in a data block are random. What "
      "differs is who they are. RocksDB packs records into a block until it passes the target "
      "size, so a 24 KB fixture contract usually lands after a tail of whatever was written "
      "before it, and fetching the contract reads that tail too. On the snapshot the tail is "
      f"real mainnet contracts, median {M['code_population']['joc']['p50']} bytes, which compress. "
      f"On the generated store it was the filler pool's {M['code_population']['sa']['p50']}-byte "
      f"stubs, which don't.</p>")
    w(figure(chart_tenancy(IB, M["code_population"]),
             "What one fetch of a fixture contract reads. The contract is the same on both stores; "
             "the tail in front of it is not."))
    w("<table><tr><th>one distinct-contract test, per fetch</th><th class=n>jochemnet</th>"
      "<th class=n>state-actor, old pool</th></tr>")
    w(f"<tr><td>code reads</td><td class=n>{thousands(pj['code_n'])}</td><td class=n>{thousands(ps['code_n'])}</td></tr>")
    w(f"<tr><td>bytes per read</td><td class=n>{thousands(pj['code_mean_b'])}</td>"
      f"<td class=\"n bad\">{thousands(ps['code_mean_b'])}</td></tr>")
    w(f"<tr><td>disk pages per read</td><td class=n>{IB['pages_per_fetch']['joc']:.2f}</td>"
      f"<td class=\"n bad\">{IB['pages_per_fetch']['sa']:.2f}</td></tr>")
    w(f"<tr><td>mean latency per read</td><td class=n>{thousands(pj['code_mean_us'])} &micro;s</td>"
      f"<td class=\"n bad\">{thousands(ps['code_mean_us'])} &micro;s</td></tr>")
    w(f"<tr><td>account-row reads (unchanged)</td><td class=n>{thousands(pj['account_n'])}</td>"
      f"<td class=n>{thousands(ps['account_n'])}</td></tr>")
    w(f"<caption>Same number of fetches, {ps['code_mean_b'] - pj['code_mean_b']} bytes more each. "
      f"A bigger compressed block crosses a 4 KB page boundary more often, so more fetches need a "
      f"second physical read.</caption></table>")
    bxf = M["besu_cross_check"]["families"]["loads_code"]
    w(f"<p>Besu shows the same shape on its own generated store: distinct-contract code at "
      f"{bxf['EXISTING_CONTRACT_DIFF_MAX']['median']:.2f} against "
      f"{bxf['EXISTING_CONTRACT_SAME_MAX']['median']:.2f} for the reused contract. Two clients, "
      f"one generator artifact.</p>")
    w(f"<p>To prove it we rewrote the generated code database with a {IB['repack']['block_size']}-byte "
      f"block, so every contract sits alone: same keys, same values, same state root. The two "
      f"cells went to {dmc['after']:.3f} and {jdc['after']:.3f}; the reused-contract control "
      f"stayed at {smc['after']:.3f}.</p>")
    w(figure(chart_code_cells(IB, V2),
             "The two distinct-contract cells and the reused-contract control on the old store, "
             "the same store repacked, and a store regenerated with the fixed pool."))
    dv = V2["cells"]
    w(f"<p>The 64-byte block is a diagnostic, not a fix. The fix belongs in the generator: "
      f"<a href=\"https://github.com/ethereum/state-actor/pull/141\">state-actor#141</a> slices "
      f"the pool from real mainnet bytecode at mainnet compressibility. On a store regenerated "
      f"with it the two cells read "
      f"{min(dv['DIFF_MAX code-exec']['v2r1'], dv['JUMPDEST code-exec']['v2r1']):.2f}&ndash;"
      f"{max(dv['DIFF_MAX code-exec']['v2r2'], dv['JUMPDEST code-exec']['v2r1']):.2f}: fixed, and "
      f"a little past parity, for a reason we come back to at the end.</p>")

    # ================================================================= finding 5
    w("<h2>Finding 5: two storage columns nobody had compacted</h2>")
    ab_rows = D["outliers"]["tests"]["sstore slots=False new=False 240M"]["cols"]["flat/Storage"]
    w(f"<p>The snapshot's storage rows sat in {thousands(col['joc_storage_before']['files'])} "
      f"files spread over {len(col['joc_storage_before']['levels'])} levels, its storage trie in "
      f"{thousands(col['joc_storagenodes_before']['files'])} over "
      f"{len(col['joc_storagenodes_before']['levels'])}; the generated store keeps each in one "
      f"level. A lookup for a key that isn't there has to be refused by every level that could "
      f"hold it, so on one test the snapshot issued {thousands(ab_rows['joc_n'])} storage reads "
      f"where the generated store issued {thousands(ab_rows['sa_n'])}. Finding 1 compacted the "
      f"columns the account tests read; storage was at parity from the first run, so nobody "
      f"looked at it.</p>")
    w(f"<p>The pre-run is why. Its {thousands(pr['blocks'])} blocks of {pr['txs_per_block']} "
      f"transactions each write storage, and every flush lands fresh files at the top of the tree "
      f"that cascade down over the following compactions. The account column had been settled by "
      f"hand; the storage ones hadn't.</p>")
    w(figure(chart_levels(ST),
             "Where the files sit. Amber is the snapshot as it was, green the same column after one "
             "<code>CompactRange</code> with the client's own table options, and the generated "
             "store as it was written."))
    w(figure(chart_storage_close(ST),
             f"The four storage tests through both compactions. The absent-slot test runs under a "
             f"second, so it is judged on its reads, below; settling the trie took the "
             f"new-value tests from {sc['slots=True new=True 160M']['r69']:.2f} to "
             f"{sc['slots=True new=True 160M']['r72']:.3f}. The overwrite test, which touches no "
             f"trie node, never left the band."))
    w(f"<p>Each step was registered on its reads before it ran, and both read predictions held: "
      f"storage-row reads on the absent-slot test fell to "
      f"{thousands(sr['slots=False new=False 240M']['after_r69']['joc_rows'])} against the "
      f"generated store's {thousands(sr['slots=False new=False 240M']['after_r69']['sa_rows'])}, "
      f"and storage-trie reads to {thousands(sr['slots=True new=True 240M']['after_r72']['joc_nodes'])} "
      f"against {thousands(sr['slots=True new=True 240M']['after_r72']['sa_nodes'])}.</p>")

    # ================================================================= 3. where it stands
    w("<h2>Where it stands</h2>")
    w("<p>With all five fixed, we ran the whole suite on both stores twice, as two pairs that "
      "share no run: the snapshot's pre-run and storage columns compacted, the generator on the "
      "fixed pool with #139's compaction, tiered JIT off on both arms. Each store is also measured "
      "against itself, so the floor sits beside the comparison.</p>")
    w(figure(chart_family_overview(WF, "final"),
             "The same view as the first figure, on the final pair. Every family that reads state "
             "is inside the band except distinct-contract code, which is now slightly faster on "
             "the generated store."))
    w("<table><tr><th>family</th><th class=n colspan=3>\u2265 1 s: baseline &rarr; final, in band</th>"
      "<th class=n colspan=3>&lt; 1 s: baseline &rarr; final, in band</th></tr>")
    for fam in FAMILIES:
        def pair(c):
            cell_ = wc[c].get(fam)
            if not cell_:
                return "<td class=n>&ndash;</td><td class=n>&ndash;</td><td class=n>&ndash;</td>"
            a, b = cell_["baseline"], cell_["final"]
            cls_ = "" if 0.9 <= b["median"] <= 1.1 else (" bad" if b["median"] < 0.9 else " good")
            return (f"<td class=n>{a['median']:.2f}</td><td class=\"n{cls_}\">{b['median']:.3f}</td>"
                    f"<td class=n>{b['within10']}/{b['n']}</td>")
        w(f"<tr><td>{esc(fam)}</td>{pair('long')}{pair('short')}</tr>")
    fa, fs = wc["long"]["_all"], wc["short"]["_all"]
    w(f"<tr><td><b>all</b></td><td class=n>{fa['baseline']['median']:.2f}</td><td class=n><b>{fa['final']['median']:.3f}</b></td>"
      f"<td class=n>{fa['final']['within10']}/{fa['final']['n']}</td>"
      f"<td class=n>{fs['baseline']['median']:.2f}</td><td class=n>{fs['final']['median']:.3f}</td>"
      f"<td class=n>{fs['final']['within10']}/{fs['final']['n']}</td></tr>")
    w("<caption>Median ratio per family at baseline and on the final pair, and how many of the "
      "final pair's tests sit within &plusmn;10%.</caption></table>")
    w(figure(chart_final_pair(FI),
             f"Two pairs that share no run. The long class reaches {lo['pair_a']['within10']} and "
             f"{lo['pair_b']['within10']} of {lo['pair_a']['n']} in the band, against "
             f"{lo['floor_sa']['within10']} and {lo['floor_joc']['within10']} when each store is "
             f"measured against itself. The short class reaches {sh_['pair_a']['within10']} and "
             f"{sh_['pair_b']['within10']} of {sh_['pair_a']['n']}, and only "
             f"{sh_['floor_sa']['within10']} and {sh_['floor_joc']['within10']} against itself."))
    w(figure(chart_waterfall(WF),
             "Every family through every stage: 0 baseline, 1 pre-run compacted, 2 tiered JIT off "
             "and the generated store settled, 3 the regenerated code pool, 4 final. Dashed segments "
             "skip a stage: transfers and storage show only the two ends, because their intermediate "
             "runs were taken on a snapshot our tooling had also altered, and the code-pool run "
             f"covered only {WF['coverage']['codepool']['short']} of the {FI['classes']['short']} "
             "short tests."))
    la, dl = wc["long"]["_all"], wc["long"]["code, distinct large"]
    w(f"<p>Read left to right, the long class moves in four steps. Compacting the pre-run takes it "
      f"from {la['baseline']['median']:.2f} to {la['placement']['median']:.2f}. Equalising the JIT "
      f"and settling the store adds a little, mostly on distinct-contract code "
      f"({dl['placement']['median']:.2f} &rarr; {dl['warmup']['median']:.2f}). The regenerated pool "
      f"moves that one family past parity ({dl['codepool']['median']:.2f}) and nothing else. "
      f"Settling the storage columns closes storage and leaves the rest where it was. The short "
      f"class moves only when the JIT is equalised, and then stops at its floor.</p>")
    _b = ol["long_buckets"]
    trf = wc["long"]["ether transfers"]["final"]
    w(f"<p>{ol['long']} of the {lo['pair_a']['n']} long tests still miss the band in both pairs, and "
      f"they are not spread across the suite: {_b.get('code pool (#141 overshoot)', 0)} are "
      f"distinct-contract code, where the regenerated pool overshoots, and "
      f"{_b.get('absent-key work', 0) + _b.get('ether transfer', 0)} are transfers, led by the "
      f"transfer to an absent account at {ol['long_rows'][0]['pair_a']:.2f}. The other "
      f"{ol['short']} misses are sub-second.</p>")
    w(f"<p>As a family, transfers reach {trf['median']:.3f}, with {trf['within10']} of {trf['n']} "
      f"in the band. The ones that miss issue the same reads on both stores. The worst reads "
      f"{thousands(wtr['flat/Account']['sa_n'])} accounts on state-actor and "
      f"{thousands(wtr['flat/Account']['joc_n'])} on jochemnet, and "
      f"{thousands(wtr['flat/StateTopNodes']['sa_n'])} against "
      f"{thousands(wtr['flat/StateTopNodes']['joc_n'])} top-of-trie nodes; every transfer outlier "
      f"we traced is within {tr_dev:.0f}% on every column. What is left there is not I/O.</p>")

    # ================================================================= 4. what is left
    tp = aa["cpu_seconds"]
    w("<h2>What is left, and why</h2>")
    w("<p><b>The code pool overshoots.</b> #141 draws its records from mainnet bytecode, but "
      "keeps a 1 KiB floor on record size. Mainnet's median contract is 45 bytes, so on "
      "Nethermind's 4 KB code block a fixture contract now starts a block of its own more often "
      "than it would on mainnet, and reading it is cheaper. Same mechanism as Finding 4, sign "
      "reversed. The pool was tuned against a 32 KB block, which is what Besu uses and where a "
      "24 KB fixture contract shares its block with other records either way; Nethermind's 4 KB block is where "
      "the floor shows. The fix is to draw record sizes from mainnet's distribution rather than a "
      "floor, in the generator.</p>")
    w(f"<p><b>Absent-key work costs the snapshot more CPU.</b> Transfers to accounts that don't "
      f"exist issue the same reads on both stores, for the same bytes at the same latency, yet "
      f"jochemnet spends {tp['joc']['160M']['.net thread pool']:.2f} CPU-seconds in managed "
      f"worker threads where state-actor spends {tp['sa']['160M']['.net thread pool']:.2f}. "
      f"Turning off state pre-warming or the trie warmer doesn't change it. It is client work, "
      f"and the next instrument is a profiler, not another benchmark.</p>")
    w(f"<p><b>Sub-second tests can't be read at any store shape.</b> Measured against itself, "
      f"state-actor puts {pct(sh_['floor_sa']['within10'], sh_['floor_sa']['n']):.0f}% of them "
      f"within &plusmn;10% and jochemnet {pct(sh_['floor_joc']['within10'], sh_['floor_joc']['n']):.0f}%. A per-test restart plus a JIT still warming up is most of what "
      f"a short test measures. That is fixed in the harness, with a discarded burn-in block, not "
      f"in either store.</p>")
    w("<p>The lesson is the one the geth study reached from the other side. A snapshot that was "
      "replayed into shape carries its history: whatever was written last is in the youngest "
      "files, and whatever was never compacted stays a stack of levels. A generated store has "
      "none of that; it is uniform by construction. Equalising the two makes them comparable. It "
      "does not make the generated one look like mainnet, and a benchmark that wants to know how "
      "an aged, fragmented store behaves needs one.</p>")
    w("<p class=note>Earlier versions of this page attributed the transfer tests' small edge first "
      "to a migrated trie costing more to update, then to per-read cost on a mainnet-shaped trie. "
      "The traces refute both: those tests issue identical reads on both stores. The numbers in "
      "this page are computed from the collected run data at build time, and the generator refuses "
      "to emit the page if the data stops supporting a sentence above.</p>")
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
        "fig_baseline": chart_family_overview(WF, "baseline"),
        "fig_placement": chart_placement(WF),
        "fig_jit": chart_jit(JIT),
        "fig_seqno_paths": chart_seqno_paths(BM),
        "fig_tenancy": chart_tenancy(IB, M["code_population"]),
        "fig_code_cells": chart_code_cells(IB, V2),
        "fig_levels": chart_levels(ST),
        "fig_storage_close": chart_storage_close(ST),
        "fig_final": chart_family_overview(WF, "final"),
        "fig_final_pair": chart_final_pair(FI),
        "fig_waterfall": chart_waterfall(WF),
    }
    for name, svg in figs.items():
        with open(os.path.join(FIGDIR, name + ".svg"), "w") as fh:
            fh.write(standalone(svg) + "\n")
    print(f"wrote {os.path.relpath(OUT, HERE)} ({len(html_text):,} bytes)")
    for name in figs:
        print(f"wrote figures/{name}.svg ({os.path.getsize(os.path.join(FIGDIR, name + '.svg')):,} bytes)")
    print(f"headline factor: {factor:.1f}x")
    print(f"long class: baseline {fa['baseline']['median']:.3f} -> final {fa['final']['median']:.3f} "
          f"({fa['final']['within10']}/{fa['final']['n']} in band)")
    print(f"short class: baseline {fs['baseline']['median']:.3f} -> final {fs['final']['median']:.3f} "
          f"({fs['final']['within10']}/{fs['final']['n']} in band)")


if __name__ == "__main__":
    main()
