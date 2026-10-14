#!/usr/bin/env python3
"""Build the reth state-DB divergence report from the collected run data.

Every measured number in the page is read from data/report_data.json (collect_reth.py's output);
none is typed into the prose. The diagrams are schematic, and any measured value printed on them
comes from the same data. Generation refuses to run without cycle 2 (claims.C19, the storage-shape
finding) and cycle 3 (claims.C20, the final store): the page must not ship without either.

Usage: python3 gen_reth_state_db_report.py [--data PATH] [--out DIR]
"""
import argparse
import html
import json
import os
import re
import sys
from statistics import median

import report_svg as S
from crt_theme import CSS

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "https://github.com/CPerezz/articles/tree/main/reth-state-db-divergence"

# Ratios throughout are state-actor / jochemnet throughput (MGas/s): 1.00 is parity, < 1 means the
# generated store is slower. The band is +-10% taken symmetrically in log space, as collect_reth.py
# scores it.
LO, HI = 1 / 1.1, 1.1

STORES = ("orig", "fixed", "g", "h", "k")
STORE_LABEL = {"J": "jochemnet (v2)", "orig": "original store", "fixed": "PR1+2", "g": "PR1-4",
               "h": "PR1-5", "k": "PR1-8"}
# The latest store always takes the accent colour.
STORE_VAR = {"J": "--fg", "orig": "--bad-fg", "fixed": "--db-u", "g": "--db-c", "h": "--db-sa",
             "k": "--accent"}

FAMILY_ORDER = ["account reads", "account reads +value", "code-heavy reads",
                "code-heavy reads +value", "ether transfers", "sload_bloated", "sstore no-write",
                "sstore write", "ext_account_query_warm", "sload_same_key_benchmark",
                "overhead control"]
FAMILY_LABEL = {
    "account reads": "account reads",
    "account reads +value": "CALL / CALLCODE with value",
    "code-heavy reads": "code-heavy reads (24 KB code)",
    "code-heavy reads +value": "code-heavy CALL with value",
    "ether transfers": "ether transfers",
    "sload_bloated": "sload, bloated contract",
    "sstore no-write": "sstore, no-op write",
    "sstore write": "sstore, new value",
    "ext_account_query_warm": "warm account query",
    "sload_same_key_benchmark": "sload, same key",
    "overhead control": "overhead control",
}
CLASSES = (">=1s", "0.5-1s", "<0.5s")

# The C19 contract (cycle 2): the page reads every one of these, so a partial collection fails here
# rather than half-way through a figure.
C19_KEYS = ("families", "acceptance_by_family", "tests_ge_0.5s", "share_in_band", "accepted",
            "families_not_robust", "below_0.5s_flagged", "out_of_band", "tree_stats_h", "manifest_h",
            "storage_shape", "t3_pages", "tree_fill", "accounts", "rootcheck_inconsistencies")
# The C20 contract (cycle 3, the final store PR1-8): headline, "where it stands" and the accounts
# section read these.
C20_KEYS = ("families", "acceptance_by_family", "tests_ge_0.5s", "share_in_band", "accepted",
            "families_not_robust", "out_of_band", "tree_stats_k", "manifest_k", "storage_shape",
            "account_shape", "t3_pages", "tree_fill", "accounts", "rootcheck_inconsistencies")


def esc(s):
    return html.escape(str(s))


def thousands(n):
    return f"{n:,}"


def compact(n):
    """Count formatter that stays readable at every magnitude: plain below 1,000, 'k'/'M'/'B'
    above it, with trailing .0 dropped (16373 -> '16.4k', 276 -> '276', 2600857 -> '2.6M')."""
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n < 1000:
        return f"{sign}{n:.0f}"
    unit, div = ("k", 1e3) if n < 1e6 else ("M", 1e6) if n < 1e9 else ("B", 1e9)
    s = f"{n / div:.1f}".rstrip("0").rstrip(".")
    return f"{sign}{s}{unit}"


def span(lo, hi, fmt=compact):
    """Format a range, collapsing to one value when both ends format the same ('13.7k', not
    '13.7k-13.7k')."""
    a, b = fmt(lo), fmt(hi)
    return a if a == b else f"{a}\u2013{b}"


def pct(x, d=0):
    return f"{100 * x:.{d}f}%"


def inband(x):
    return LO <= x <= HI


def fam_label(f):
    return FAMILY_LABEL.get(f, f)


def ygrid(scale, ticks, x0, x1, fmt=str):
    """Horizontal gridlines with left-hand labels (report_svg.hgrid is the x-axis variant)."""
    out = []
    for t in ticks:
        y = scale.to(t)
        out.append(S.line(x0, y, x1, y, "--line", 1))
        out.append(S.label(x0 - 8, y + 4, fmt(t), "end", "tick"))
    return "".join(out)


def box(x, y, w, h, var, opacity=0.25, stroke="--green-muted", dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="var({var})" '
            f'fill-opacity="{opacity}" stroke="var({stroke})" stroke-width="1"{d}/>')


def ring(x, y, r, var, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="none" stroke="var({var})" '
            f'stroke-width="2"{d}/>')


def thick_poly(points, var, width=7, opacity=0.4):
    """A pale, wide underlay line: draws a series behind a thinner one so two curves that
    coincide (by design, not noise) both stay visible. report_svg.polyline has no opacity knob."""
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return (f'<polyline points="{pts}" fill="none" stroke="var({var})" '
            f'stroke-width="{width}" stroke-linejoin="round" stroke-opacity="{opacity}"/>')


def dash_poly(points, var, width=2.5, dash="7 4"):
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return (f'<polyline points="{pts}" fill="none" stroke="var({var})" '
            f'stroke-width="{width}" stroke-linejoin="round" stroke-dasharray="{dash}"/>')


def legend(items, x, y, W=760):
    """One row of dot + text items, wrapping at the figure edge."""
    o, x0 = [], x
    for text, var in items:
        span = 22 + 6.6 * len(text)
        if x + span > W and x > x0:
            x, y = x0, y + 16
        o.append(S.dot(x + 4, y - 4, 4, var))
        o.append(S.label(x + 12, y, text, "start", "tick"))
        x += span
    return "".join(o), y


def axis_ticks(sx, ticks, y, lo, hi):
    # The ticks on the axis ends are anchored inward so half the label doesn't hang outside.
    o = []
    for t in ticks:
        anchor = "start" if t == lo else "end" if t == hi else "middle"
        o.append(S.label(sx.to(t), y, ("%.2f" % t).rstrip("0").rstrip("."), anchor, "tick"))
    return "".join(o)


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


def chart_rows(title, sections, lo, hi, ticks, legend_items, path=False):
    """Rows of dots on one log ratio axis with the +-10% band, grouped into titled sections.

    rows: (label, [(value, var, hover)], right-hand text). With path=True the dots of a row are
    successive stages of one quantity, drawn slightly staggered and joined in order."""
    W, L, R, T, rh, gap = 760, 236, 140, 30, 19, 26
    nrows = sum(len(r) for _, r in sections)
    H = T + 14 * len(sections) + rh * nrows + gap * (len(sections) - 1) + 62
    sx = S.LogScale(lo, hi, L, W - R)
    clamp = lambda v: max(lo, min(hi, v))
    o = [S.label(0, 14, title, "start", "big")]
    y0 = T
    for stitle, rows in sections:
        o.append(S.label(0, y0 + 4, stitle, "start", "ax"))
        top = y0 + 12
        bot = top + rh * len(rows)
        o.append(S.band(sx.to(LO), sx.to(HI), top, bot, "--accent", 0.10))
        o.append(S.line(sx.to(1.0), top, sx.to(1.0), bot, "--green-muted", 1))
        for i, (lab, pts, right) in enumerate(rows):
            y = top + rh * i + 10
            o.append(S.label(L - 10, y + 4, lab, "end", "tick"))
            offs = [(j - (len(pts) - 1) / 2) * 3 if path else 0 for j in range(len(pts))]
            if path:
                for j in range(len(pts) - 1):
                    o.append(S.line(sx.to(clamp(pts[j][0])), y + offs[j], sx.to(clamp(pts[j + 1][0])),
                                    y + offs[j + 1], "--green-muted", 1, dash="2 3"))
            for (v, var, hover), off in zip(pts, offs):
                o.append(S.dot(sx.to(clamp(v)), y + off, 3.2, var, hover))
            o.append(S.label(W - R + 8, y + 4, right, "start", "tick"))
        y0 = bot + gap
    o.append(axis_ticks(sx, ticks, y0 - gap + 16, lo, hi))
    leg, _ = legend(legend_items, L, H - 10)
    o.append(leg)
    return S.svg(W, H, "".join(o))


# --------------------------------------------------------------------------- the problem
MODE_ORDER = ["EXISTING_EOA", "NON_EXISTING_ACCOUNT", "EXISTING_CONTRACT_MINIMAL",
              "EXISTING_CONTRACT_SAME_MAX", "EXISTING_CONTRACT_DIFF_MAX", "EXISTING_CONTRACT_JUMPDEST",
              "ether_transfers_onchain_receivers", "sload_bloated", "sstore_bloated",
              "ext_account_query_warm", "sload_same_key_benchmark"]
MODE_LABEL = {
    "EXISTING_EOA": "existing EOAs", "NON_EXISTING_ACCOUNT": "absent accounts",
    "EXISTING_CONTRACT_MINIMAL": "minimal contracts", "EXISTING_CONTRACT_SAME_MAX": "one reused contract",
    "EXISTING_CONTRACT_DIFF_MAX": "distinct 24 KB contracts", "EXISTING_CONTRACT_JUMPDEST": "jumpdest contracts",
    "ether_transfers_onchain_receivers": "ether transfers", "sload_bloated": "sload, bloated contract",
    "sstore_bloated": "sstore, bloated contract", "ext_account_query_warm": "warm account query",
    "sload_same_key_benchmark": "sload, same key",
}


def baseline_rows(cats):
    """C13 categories ('ge1s | CALL EXISTING_EOA') pooled by account mode or family, per class;
    one value per category: the geomean of its two pairs."""
    by = {}
    for k, v in cats.items():
        cls, cat = k.split(" | ")
        parts = cat.split(" ")
        mode = parts[1] if len(parts) == 2 else parts[0]
        by.setdefault(cls, {}).setdefault(mode, []).append((v["pair_a"] * v["pair_b"]) ** 0.5)
    return by


def chart_baseline(cats):
    by = baseline_rows(cats)
    sections = []
    for cls, title in (("ge1s", "tests over a second (by the first jochemnet run)"),
                       ("lt1s", "tests under a second")):
        rows = []
        for m in MODE_ORDER:
            vs = by.get(cls, {}).get(m)
            if vs:
                rows.append((MODE_LABEL[m], [(v, "--bad-fg", f"{v:.3f}") for v in vs],
                             f"median {median(vs):.3f}"))
        sections.append((title, rows))
    return chart_rows("buffered loops, jochemnet as published: throughput ratio per test category",
                      sections, 0.01, 2.0, [0.01, 0.03, 0.1, 0.3, 1.0, 2.0],
                      [("one opcode or receiver category (geomean of two pairs)", "--bad-fg")])


# The six causes as one table-shaped diagram: where each sat, what it was, and whether the fix was in
# the test setup or in state-actor. Its only measured value is the account excess.
def chart_map(extra_accounts):
    rows = (("1", "disk setup", "reads reach the disk one at a time", "direct I/O", "setup"),
            ("2", "storage layout", "jochemnet is v1, state-actor writes v2", "convert jochemnet to v2", "setup"),
            ("3", "table rows", "rows out of key order; extra trie rows", "PR1, PR2", "gen"),
            ("4", "table pages", "every page packed full; mainnet's aren't", "PR3, PR4", "gen"),
            ("5", "stored state", "every contract holds a few hundred slots", "PR5: mainnet storage shape", "gen"),
            ("5", "stored state", f"{extra_accounts:.0%} more accounts than mainnet", "generate at mainnet's count", "gen"))
    var = {"setup": "--db-u", "gen": "--accent"}
    W, T, rh = 760, 46, 36
    H = T + rh * len(rows) + 34
    o = [S.label(0, 14, "six causes: where each sat, and what fixed it", "start", "big"),
         S.label(28, T - 8, "where", "start", "ax"), S.label(152, T - 8, "cause", "start", "ax"),
         S.label(524, T - 8, "fix", "start", "ax")]
    for i, (n, layer, cause, fix, who) in enumerate(rows):
        y = T + i * rh
        o.append(S.line(0, y, W, y, "--line", 1))
        o.append(S.label(10, y + 23, n, "middle", "big"))
        o.append(box(28, y + 7, 114, 22, "--line", 0.25))
        o.append(S.label(85, y + 22, layer, "middle", "tick"))
        o.append(S.label(152, y + 22, cause))
        o.append(box(524, y + 7, 236, 22, var[who], 0.18, var[who]))
        o.append(S.label(532, y + 22, fix))
    o.append(S.line(0, T + rh * len(rows), W, T + rh * len(rows), "--line", 1))
    leg, _ = legend([("fixed in the test setup", "--db-u"), ("fixed in state-actor", "--accent")], 0, H - 6)
    o.append(leg)
    return S.svg(W, H, "".join(o))


# --------------------------------------------------------------------------- finding 1
def chart_fio(fio):
    W, H, L, R, T, B = 760, 300, 64, 200, 30, 250
    jobs = [1, 4, 16, 64]
    sx = S.LogScale(1, 64, L, W - R)
    sy = S.LogScale(5e3, 1e6, B, T)
    o = [S.label(0, 14, "random 4 KiB reads per second, fio psync, by parallel jobs", "start", "big"),
         ygrid(sy, [1e4, 1e5, 1e6], L, W - R, fmt=lambda v: {1e4: "10k", 1e5: "100k", 1e6: "1M"}[v])]
    for name, k, var in (("loop, buffered", "buffered", "--bad-fg"), ("loop, direct-io", "dio", "--accent"),
                         ("raw file, O_DIRECT", "raw", "--dim")):
        pts = [(sx.to(j), sy.to(fio[k][f"psync:{j}"]["iops"])) for j in jobs]
        o.append(S.polyline(pts, var, 2.5))
        o += [S.dot(x, y, 3.5, var, f"{name}, {j} jobs: {fio[k][f'psync:{j}']['iops']:,} IOPS")
              for (x, y), j in zip(pts, jobs)]
        o.append(S.label(W - R + 10, pts[-1][1] + 4, f"{name} {compact(fio[k]['psync:64']['iops'])}", "start", "tick"))
    for i, j in enumerate(jobs):
        anchor = "start" if i == 0 else "end" if i == len(jobs) - 1 else "middle"
        o.append(S.label(sx.to(j), B + 18, str(j), anchor, "tick"))
    o.append(S.label((L + W - R) / 2, H - 8, "parallel psync jobs", "middle", "ax"))
    return S.svg(W, H, "".join(o))


# --------------------------------------------------------------------------- finding 2
def chart_v1v2(pages_v1, pages_v2):
    """Schematic: sequential addresses are neighbours in a table keyed by address and scatter in one
    keyed by their hash. Only the two page counts are measured."""
    W, H = 760, 270
    o = [S.label(0, 14, "the same six sequential accounts, looked up in two layouts", "start", "big")]
    addrs = ["0x1000", "0x1001", "0x1002", "0x1003", "0x1004", "0x1005"]
    scatter = [7, 1, 9, 3, 5, 0]  # illustrative positions of the hashed keys
    for p, (x0, title, targets, pages, sub) in enumerate((
            (10, "v1: PlainAccountState, keyed by address", [4] * 6, pages_v1, "jochemnet as published"),
            (395, "v2: HashedAccounts, keyed by keccak(address)", scatter, pages_v2, "after reth db migrate-v2"))):
        o.append(S.label(x0, 40, title, "start", "big"))
        o.append(S.label(x0, 56, sub, "start", "tick"))
        for i, a in enumerate(addrs):
            ax = x0 + 6 + i * 58
            o.append(box(ax, 70, 50, 20, "--db-c", 0.18))
            o.append(S.label(ax + 25, 84, a if p == 0 else "k(" + a[-2:] + ")", "middle", "tick"))
        hit = set(targets)
        for k in range(10):
            px = x0 + 6 + k * 35
            o.append(box(px, 160, 30, 42, "--accent" if k in hit else "--line", 0.35 if k in hit else 0.25))
        for i, t in enumerate(targets):
            o.append(S.line(x0 + 31 + i * 58, 90, x0 + 21 + t * 35, 160, "--green-dim", 1))
        o.append(S.label(x0 + 6, 220, "leaf pages (each square one 4 KiB page)", "start", "tick"))
        o.append(S.label(x0 + 6, 248, f"measured, BALANCE on 52k existing EOAs: {pages:,} pages", "start", "tick"))
    return S.svg(W, H, "".join(o))


# --------------------------------------------------------------------------- finding 3
def chart_btree(toy, before, after):
    """Schematic of where libmdbx splits a full leaf: in the middle for a key inside the page's range,
    at the edge for a key past its end. Measured values in the footer only."""
    W, H = 760, 330
    o = [S.label(0, 14, "what a full leaf does with one more key", "start", "big")]

    def page(x, y, keys, fill, var="--accent", new=None):
        out = [box(x, y, 92, 30, "--line", 0.2), S.band(x + 1, x + 1 + 90 * fill, y + 22, y + 29, var, 0.55)]
        for i, k in enumerate(keys):
            out.append(S.label(x + 10 + i * 20, y + 15, k, "middle", "big" if k == new else "tick"))
        return "".join(out)

    rows = (
        (40, "random order (how state-actor wrote HashedAccounts)", "key d lands inside the range: split in the middle",
         [("a c e g", 1.0, None)], [("a c d", 0.5, "d"), ("e g", 0.5, None)], 0.5,
         "every leaf ends about half full"),
        (175, "key order (PR1)", "key h lands past the end: split at the edge",
         [("a c e g", 1.0, None)], [("a c e g", 1.0, None), ("h", 0.25, "h")], 1.0,
         "every leaf but the last stays full"),
    )
    for y, title, how, full, split, settle, outcome in rows:
        o.append(S.label(0, y, title, "start", "big"))
        o.append(S.label(0, y + 16, how, "start", "tick"))
        o.append(page(10, y + 30, full[0][0].split(), 1.0))
        o.append(S.line(110, y + 45, 150, y + 45, "--green-dim", 1.5))
        o.append(S.label(130, y + 40, "+1", "middle", "tick"))
        for i, (ks, f, new) in enumerate(split):
            o.append(page(160 + i * 100, y + 30, ks.split(), f, new=new))
        o.append(S.line(360, y + 45, 400, y + 45, "--green-dim", 1.5))
        o.append(S.label(380, y + 40, "x N", "middle", "tick"))
        for i in range(3):
            o.append(page(410 + i * 100, y + 30, [], settle))
        o.append(S.label(410, y + 82, outcome, "start", "tick"))
    o.append(S.label(0, 290, f"measured, 2M keys in the same libmdbx: random order {thousands(toy['random-put'])} "
                             f"leaf pages, key order {thousands(toy['sorted-put'])}", "start", "tick"))
    o.append(S.label(0, 310, f"state-actor's HashedAccounts: h{before['height']}, leaf fill {before['leaf_fill']:.2f}; "
                             f"the same rows in key order: h{after['height']}, leaf fill {after['leaf_fill']:.2f}",
                     "start", "tick"))
    return S.svg(W, H, "".join(o))


# id: (x, y, parent, nibble path); leaves are generated under their branch.
TRIE = {"R": (380, 40, None, ""), "A": (110, 112, "R", "0"), "B": (380, 112, "R", "7"),
        "C": (650, 112, "R", "c"), "D": (300, 196, "B", "72"), "E": (580, 196, "C", "c0"),
        "F": (720, 196, "C", "c5")}
TRIE_LEAVES = {"A": 2, "B": 1, "D": 3, "E": 2, "F": 2}


def trie_stored():
    # alloy_trie stores a branch iff tree_mask | hash_mask != 0; in this shape that is exactly the
    # branches with a branch child. The bottom branches, whose children are all leaves, get no row.
    return {n for n in TRIE if any(v[2] == n for v in TRIE.values())}


def chart_trie(orig_leaf, fixed_leaf, branch_ratio):
    W, H = 760, 350
    stored = trie_stored()
    o = [S.label(0, 14, "which branch nodes of an account trie get a stored row", "start", "big")]
    for n, (x, y, parent, _) in TRIE.items():
        if parent:
            px, py = TRIE[parent][:2]
            o.append(S.line(px, py, x, y, "--green-muted", 1))
        nl = TRIE_LEAVES.get(n, 0)
        if n == "B":
            # B's one direct leaf hangs beside it, not below, so it never shares a row with D.
            lx, ly = x + 76, y
            o.append(S.line(x, y, lx, ly, "--green-muted", 1))
            o.append(box(lx - 6, ly - 6, 12, 12, "--db-c", 0.6, "--db-c"))
            continue
        for i in range(nl):
            lx = x - 18 * (nl - 1) + 36 * i
            ly = y + 58
            o.append(S.line(x, y, lx, ly, "--green-muted", 1))
            o.append(box(lx - 6, ly - 6, 12, 12, "--db-c", 0.6, "--db-c"))
    for n, (x, y, _, path) in TRIE.items():
        # Right-half nodes anchor their label leftward, so nothing clips past the canvas edge.
        right = x > W / 2
        anchor = "end" if right else "start"
        lx = x - 14 if right else x + 14
        if n in stored:
            o.append(S.dot(x, y, 9, "--accent"))
        else:
            o.append(S.dot(x, y, 9, "--bg"))
            o.append(ring(x, y, 9, "--bad-fg", "3 2"))
        o.append(S.label(lx, y - 12, "root" if not path else f"'{path}'", anchor, "tick"))
    leg, y = legend([("row reth stores (has a branch below it)", "--accent"),
                     ("row only state-actor stored (only leaves below)", "--bad-fg"),
                     ("leaf", "--db-c")], 10, 290)
    o.append(leg)
    o.append(S.label(10, y + 22, f"measured, AccountsTrie leaf pages: {compact(orig_leaf)} as state-actor wrote "
                                 f"them, {compact(fixed_leaf)} after PR1, PR2", "start", "tick"))
    o.append(S.label(10, y + 40, f"before the fix, CALL with value to 52k EOAs read {branch_ratio:.2f}x "
                                 f"jochemnet's AccountsTrie branch pages", "start", "tick"))
    return S.svg(W, H, "".join(o))


# --------------------------------------------------------------------------- finding 4
def chart_fill_dial(marks):
    """How full a page stays after an edge split, against the room left free on it (libmdbx's split
    reserve, as a share of the page), and the measured HashedAccounts leaf fill of each store."""
    W, H, L, R, T, B = 760, 300, 60, 250, 34, 250
    sx = S.Scale(0, 32768, L, W - R)
    sy = S.Scale(0.4, 1.0, B, T)
    o = [S.label(0, 14, "how full a page stays, against the room left free when it splits", "start", "big"),
         ygrid(sy, [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], L, W - R, fmt=lambda v: f"{v:.1f}")]
    o.append(S.polyline([(sx.to(0), sy.to(1.0)), (sx.to(32768), sy.to(0.5))], "--accent", 2.5))
    o.append(S.label(sx.to(16000), sy.to(1 - 16000 / 65536) - 10, "fill left behind", "start", "tick"))
    for r in (0, 8192, 16384, 24576, 32768):
        o.append(S.label(sx.to(r), B + 18, f"{r / 65536:.1%}".replace(".0%", "%"),
                         "start" if r == 0 else "end" if r == 32768 else "middle", "tick"))
    o.append(S.label((L + W - R) / 2, H - 8, "room left free on a page when it splits", "middle", "ax"))
    o.append(S.line(W - R + 14, T, W - R + 14, B, "--line", 1))
    o.append(S.label(W - R + 14, T - 8, "measured HashedAccounts leaf fill", "start", "tick"))
    placed = []
    for text, v, var in sorted(marks, key=lambda m: -m[1]):
        y = sy.to(v)
        ty = max([y + 4] + [p + 13 for p in placed])
        placed.append(ty)
        o.append(S.dot(W - R + 14, y, 4, var, f"{text}: {v:.3f}"))
        o.append(S.line(W - R + 18, y, W - R + 30, ty - 4, "--line", 1))
        o.append(S.label(W - R + 34, ty, f"{v:.2f} {text}", "start", "tick"))
    return S.svg(W, H, "".join(o))


TABLES = ("HashedAccounts", "AccountsTrie", "HashedStorages", "StoragesTrie", "Bytecodes")


def chart_tree_stats(stats):
    """Leaf fill per table per store, with height and leaf pages. DupSort tables (HashedStorages,
    StoragesTrie) count their nested trees in the same totals."""
    W, L, T, bh = 760, 150, 30, 14
    stores = [s for s in ("J", "orig", "fixed", "g", "h", "k") if s in stats]
    H = T + len(TABLES) * (len(stores) * bh + 18) + 40
    sx = S.Scale(0, 1, L, L + 300)
    o = [S.label(0, 14, "leaf fill per table (bar), height and leaf pages (text)", "start", "big")]
    y = T
    for t in TABLES:
        o.append(S.label(L - 10, y + 10, t, "end", "big"))
        for s in stores:
            st = stats[s][t]
            o.append(S.band(sx.to(0), sx.to(1), y, y + bh - 3, "--line", 0.5))
            o.append(S.band(sx.to(0), sx.to(st["leaf_fill"]), y, y + bh - 3, STORE_VAR[s], 0.75))
            o.append(S.label(L + 308, y + 9, f"{st['leaf_fill']:.2f}  h{st['height']}  {compact(st['leaf'])} leaves"
                                             f"  {STORE_LABEL[s]}", "start", "tick"))
            y += bh
        y += 18
    leg, _ = legend([(STORE_LABEL[s], STORE_VAR[s]) for s in stores], L, H - 10)
    o.append(leg)
    return S.svg(W, H, "".join(o))


# --------------------------------------------------------------------------- finding 5
def quantile_cdf(qs, xs):
    n = len(qs)
    return [(x, sum(1 for q in qs if q <= x) / n) for x in xs]


def chart_storage_cdf(J, g, k):
    """jochemnet and PR1-8 coincide by design (that's the finding), so jochemnet draws as a
    pale, wide underlay and PR1-8 as a dashed line on top: both stay visible where they overlap.
    PR1-5 is left out: it sits on the same curve and a third coinciding line adds nothing."""
    W, H, L, R, T, B = 760, 330, 60, 170, 30, 270
    xmax = max(J["max"], k["max"], max(g["quantiles_1000"]))
    sx = S.LogScale(1, xmax, L, W - R)
    sy = S.Scale(0, 1, B, T)
    xs = sorted({x for x, _ in J["cdf"]} | {x for x, _ in k["cdf"]})
    o = [S.label(0, 14, "share of storage-holding accounts with at most x slots", "start", "big"),
         ygrid(sy, [0, 0.25, 0.5, 0.75, 1.0], L, W - R, fmt=lambda v: f"{v:.2f}")]
    o.append(S.line(sx.to(28), T, sx.to(28), B, "--dim", 1, dash="4 3"))
    # Left of the gridline at mid height no series runs: the mainnet-shaped curves start above 0.5
    # and the PR1-4 sample stays near 0 until well past 28.
    o.append(S.label(sx.to(28) - 6, sy.to(0.4), "28 slots: inline limit", "end", "tick"))
    j_pts = [(sx.to(max(1, min(xmax, x))), sy.to(f)) for x, f in J["cdf"]]
    k_pts = [(sx.to(max(1, min(xmax, x))), sy.to(f)) for x, f in k["cdf"]]
    g_pts = [(sx.to(max(1, min(xmax, x))), sy.to(f)) for x, f in quantile_cdf(g["quantiles_1000"], xs)]
    o.append(thick_poly(j_pts, STORE_VAR["J"]))
    o += [S.dot(x, y, 4, STORE_VAR["J"], f"jochemnet: F({xx:,}) = {f:.3f}")
          for (x, y), (xx, f) in zip(j_pts, J["cdf"])]
    o.append(S.polyline(g_pts, STORE_VAR["g"], 2))
    o += [S.dot(x, y, 2, STORE_VAR["g"]) for x, y in g_pts]
    o.append(dash_poly(k_pts, STORE_VAR["k"]))
    o += [S.dot(x, y, 2.2, STORE_VAR["k"], f"PR1-8: F({xx:,}) = {f:.3f}")
          for (x, y), (xx, f) in zip(k_pts, k["cdf"])]
    ly = T + 20
    for name, var in (("jochemnet", STORE_VAR["J"]), ("PR1-4 (sample)", STORE_VAR["g"]),
                      ("PR1-8", STORE_VAR["k"])):
        o.append(S.dot(W - R + 20, ly - 4, 4, var))
        o.append(S.label(W - R + 30, ly, name, "start", "tick"))
        ly += 18
    names = {1: "1", 10: "10", 100: "100", 1000: "1k", 10 ** 4: "10k", 10 ** 5: "100k",
             10 ** 6: "1M", 10 ** 7: "10M", 10 ** 8: "100M"}
    for t in (t for t in names if t <= xmax):
        o.append(S.label(sx.to(t), B + 18, names[t], "start" if t == 1 else "middle", "tick"))
    o.append(S.label((L + W - R) / 2, H - 8, "slots per storage account (log)", "middle", "ax"))
    return S.svg(W, H, "".join(o))


def chart_sibling():
    """Schematic of the sibling storage-root walk. A changed account re-hashes its path in the
    account trie; the lowest branch needs every sibling leaf's hash, and a contract leaf's hash
    includes its storage root, which reth does not store, so it walks that contract's storage."""
    W, H = 760, 360
    o = [S.label(0, 14, "one modified account, its siblings, and what reth reads to re-hash them", "start", "big")]
    for x0, title, kinds in ((0, "jochemnet-shaped siblings", ["eoa", "one", "few", "eoa"]),
                             (390, "autofill siblings (before PR5)", ["eoa", "nested", "nested", "eoa"])):
        o.append(S.label(x0 + 10, 44, title, "start", "big"))
        bx, by = x0 + 185, 80
        o.append(S.dot(bx, by, 9, "--accent"))
        o.append(S.label(bx, by - 16, "branch on the changed path", "middle", "tick"))
        slots = [(x0 + 40 + i * 72, kind) for i, kind in enumerate(kinds[:2] + ["mod"] + kinds[2:])]
        for sx_, kind in slots:
            o.append(S.line(bx, by, sx_, 130, "--green-muted", 1))
            if kind == "mod":
                o.append(box(sx_ - 9, 130, 18, 18, "--accent", 0.8, "--accent"))
                o.append(S.label(sx_, 168, "changed", "middle", "tick"))
                continue
            o.append(box(sx_ - 9, 130, 18, 18, "--db-c", 0.5, "--db-c"))
            if kind == "eoa":
                o.append(S.label(sx_, 168, "EOA", "middle", "tick"))
                o.append(S.label(sx_, 184, "no storage", "middle", "tick"))
            elif kind in ("one", "few"):
                o.append(S.line(sx_, 148, sx_, 190, "--db-u", 1))
                o.append(box(sx_ - 14, 190, 28, 16, "--db-u", 0.5, "--db-u"))
                o.append(S.label(sx_, 222, "1 slot" if kind == "one" else "<= 28 slots", "middle", "tick"))
                o.append(S.label(sx_, 238, "inline in the", "middle", "tick"))
                o.append(S.label(sx_, 252, "main-tree leaf", "middle", "tick"))
            else:
                o.append(S.line(sx_, 148, sx_, 190, "--bad-fg", 1))
                o.append(box(sx_ - 8, 190, 16, 12, "--bad-fg", 0.5, "--bad-fg"))
                for k in (-1, 0, 1):
                    o.append(S.line(sx_, 202, sx_ + 18 * k, 226, "--bad-fg", 1))
                    o.append(box(sx_ + 18 * k - 7, 226, 14, 12, "--bad-fg", 0.5, "--bad-fg"))
                o.append(S.label(sx_, 254, "~250 slots:", "middle", "tick"))
                o.append(S.label(sx_, 268, "nested sub-tree", "middle", "tick"))
    o.append(S.label(10, 304, "the walk happens for every modified account's siblings, at every level that "
                              "has no stored trie row", "start", "tick"))
    o.append(S.label(10, 322, "blue: account leaves; amber: storage read in place; pink: pages of a nested "
                              "storage tree (traced as 'other')", "start", "tick"))
    return S.svg(W, H, "".join(o))


T3_GROUPS = (("HashedAccounts", ("HashedAccounts:leaf", "HashedAccounts:branch"), "--db-c"),
             ("AccountsTrie", ("AccountsTrie:leaf", "AccountsTrie:branch"), "--db-sa"),
             ("HashedStorages main", ("HashedStorages:main",), "--db-u"),
             ("HashedStorages bloated", ("HashedStorages:nested(bloated)",), "--good-fg"),
             ("StoragesTrie", ("StoragesTrie:main", "StoragesTrie:nested(bloated)"), "--green-dim"),
             ("Bytecodes", ("Bytecodes:leaf", "Bytecodes:branch", "Bytecodes:large"), "--muted"),
             ("other (nested storage walks)", ("other",), "--bad-fg"))
# t3jg and t3sh are in both C19 and C20 (same store, same binary); t3sg is cycle 1, t3sk cycle 3.
T3_STORES = (("t3jg", "jochemnet"), ("t3sg", "PR1-4"), ("t3sh", "PR1-5"), ("t3sk", "PR1-8"))


def t3_family(name):
    """collect_reth.family() on a traced test's window name."""
    if "ether_transfers" in name:
        return "ether transfers"
    if "sstore_bloated" in name:
        return "sstore write" if "write_new_value_True" in name else "sstore no-write"
    if "sload_bloated" in name:
        return "sload_bloated"
    if "account_access" in name:
        if "overhead_baseline_True" in name:
            return "overhead control"
        base = "code-heavy reads" if re.search(r"DIFF_MAX|JUMPDEST", name) else "account reads"
        return base + (" +value" if "value_sent_1" in name else "")
    return name


def t3_by_family(t3):
    """Mean pages per table group per traced store, for each family, over the tests traced on all
    three stores. The residual of each test's total against its listed tables is kept as 'rest'."""
    tests = sorted(set.intersection(*(set(t3[r]) for r, _ in T3_STORES)))
    out = {}
    for name in tests:
        f = t3_family(name)
        for r, _ in T3_STORES:
            row = t3[r][name]
            parts = [sum(row.get(k, 0) for k in keys) for _, keys, _ in T3_GROUPS]
            parts.append(max(0, row["total"] - sum(parts)))
            acc = out.setdefault(f, {}).setdefault(r, [])
            acc.append(parts + [row["total"]])
    fams = {}
    for f, by in out.items():
        fams[f] = {r: [sum(col) / len(col) for col in zip(*rows)] for r, rows in by.items()}
        fams[f]["n"] = len(by["t3jg"])
    return fams


def chart_t3(fams):
    W, L, R, T, bh = 760, 180, 70, 30, 14
    order = [f for f in FAMILY_ORDER if f in fams] + sorted(f for f in fams if f not in FAMILY_ORDER)
    H = T + 40 + len(order) * (len(T3_STORES) * bh + 26) + 20
    o = [S.label(0, 14, "distinct mdbx pages per traced test, by table (mean over the family's traced tests)",
                 "start", "big")]
    leg, ly = legend([(g, v) for g, _, v in T3_GROUPS] + [("unlisted", "--dim")], 0, T + 4)
    o.append(leg)
    y = ly + 22
    for f in order:
        by = fams[f]
        hi = max(by[r][-1] for r, _ in T3_STORES) or 1
        o.append(S.label(0, y + 4, f"{fam_label(f)} ({by['n']} traced)", "start", "ax"))
        y += 10
        for r, name in T3_STORES:
            parts, total = by[r][:-1], by[r][-1]
            o.append(S.label(L - 8, y + 10, name, "end", "tick"))
            x = L
            for (g, _, var), v in zip(T3_GROUPS + (("unlisted", (), "--dim"),), parts):
                w_ = (W - R - L) * v / hi
                if w_ > 0:
                    o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w_:.1f}" height="{bh - 3}" '
                             f'fill="var({var})" opacity="0.8"><title>{esc(g)}: {v:,.0f}</title></rect>')
                x += w_
            o.append(S.label(x + 6, y + 10, f"{compact(total)}", "start", "tick"))
            y += bh
        y += 16
    return S.svg(W, H, "".join(o))


# --------------------------------------------------------------------------- where it stands
def chart_progression(fams):
    sections = []
    for cls, title in ((">=1s", "jochemnet step time >= 1 s (gated)"),
                       ("0.5-1s", "0.5 - 1 s (gated)"),
                       ("<0.5s", "under 0.5 s: shown, not counted")):
        rows = []
        for f in FAMILY_ORDER:
            v = fams.get(f"{cls} | {f}")
            if v:
                rows.append((f"{fam_label(f)} ({v['n']})",
                             [(v[s], STORE_VAR[s], f"{STORE_LABEL[s]}: {v[s]:.3f}") for s in STORES],
                             f"{v['orig']:.2f} \u2192 {v['k']:.2f}  {v['in band k']}/{v['n']}"))
        sections.append((title, rows))
    return chart_rows("per-family median of each test's pair geomean, store by store", sections,
                      0.6, 1.5, [0.6, 0.8, 0.909, 1.0, 1.1, 1.25, 1.5],
                      [(STORE_LABEL[s], STORE_VAR[s]) for s in STORES], path=True)


# Share of the gated tests in band, one bar per store: the result in one picture. Each row's label
# sits above its bar, so a long list of fixes never squeezes the bar.
SHARE_ROWS = (("original store", "orig"), ("+ PR1, PR2: key order, reth's trie rows", "fixed"),
              ("+ PR3, PR4: key order everywhere, mainnet's page fill", "g"),
              ("+ PR5: mainnet's storage shape and account count", "h"),
              ("+ PR6-8: mainnet's account shape, contract trie order, storage tail", "k"))


def chart_share(share, n):
    W, R, T, rh = 760, 130, 34, 40
    H = T + rh * len(SHARE_ROWS) + 22
    sx = S.Scale(0, 1, 0, W - R)
    bottom = T + rh * len(SHARE_ROWS)
    o = [S.label(0, 14, f"tests of 0.5 s or more within \u00b110% of jochemnet, out of {n}", "start", "big")]
    for t in (0, 0.5, 1):
        o.append(S.line(sx.to(t), T, sx.to(t), bottom - 4, "--line", 1))
        o.append(S.label(sx.to(t), bottom + 12, f"{t:.0%}", "start" if t == 0 else "middle", "tick"))
    for i, (lab, s) in enumerate(SHARE_ROWS):
        y = T + i * rh
        o.append(S.label(0, y + 10, lab, "start", "tick"))
        o.append(box(0, y + 16, sx.to(share[s]), 16, STORE_VAR[s], 0.7, STORE_VAR[s]))
        o.append(S.label(W - R + 10, y + 29, f"{pct(share[s], 1)}  {round(share[s] * n)}/{n}", "start", "tick"))
    return S.svg(W, H, "".join(o))


# --------------------------------------------------------------------------- accounts
CODED_KINDS = (("contract", "code only", "--db-c"), ("contract +storage", "code + storage", "--db-u"),
               ("delegation", "delegation", "--db-sa"), ("delegation +storage", "delegation + storage", "--muted"))
ACCOUNT_STORES = ("J", "h", "k")


def chart_accounts(ashape, pages):
    """Three panels, one row per store: mean account-row value size, the share of accounts that
    carry code split by kind, and the pages a traced account-read test touches (index vs row).
    pages: {store: (index pages, row pages)}."""
    W, L, R, rh = 760, 130, 150, 20
    o = [S.label(0, 14, "what an account row holds, and what reading one costs", "start", "big")]
    y = 40

    def rows(title, draw, legend_items=()):
        nonlocal y
        o.append(S.label(0, y, title, "start", "ax"))
        y += 10
        for s in ACCOUNT_STORES:
            o.append(S.label(L - 10, y + 12, STORE_LABEL[s], "end", "tick"))
            draw(s, y)
            y += rh
        if legend_items:
            leg, ly = legend(legend_items, L, y + 14)
            o.append(leg)
            y = ly
        y += 30

    vmax = max(ashape[s]["value_len_mean"] for s in ACCOUNT_STORES) * 1.05
    sv = S.Scale(0, vmax, L, W - R)

    def value(s, y):
        v = ashape[s]["value_len_mean"]
        o.append(box(L, y + 3, sv.to(v) - L, 13, STORE_VAR[s], 0.7, STORE_VAR[s]))
        o.append(S.label(sv.to(v) + 8, y + 13, f"{v:.1f} bytes", "start", "tick"))
    rows("account row value, mean size", value)

    cmax = max(ashape[s]["code_hash_share"] for s in ACCOUNT_STORES) * 1.05
    sc = S.Scale(0, cmax, L, W - R)

    def coded(s, y):
        share, kinds, x = ashape[s]["code_hash_share"], ashape[s]["coded_kinds"], L
        for key, name, var in CODED_KINDS:
            wd = (sc.to(share) - L) * kinds.get(key, 0)
            if wd > 0:
                o.append(f'<rect x="{x:.1f}" y="{y + 3:.1f}" width="{wd:.1f}" height="13" fill="var({var})" '
                         f'opacity="0.8"><title>{esc(name)}: {kinds[key]:.1%} of rows with code</title></rect>')
            x += wd
        o.append(S.label(x + 8, y + 13, f"{share:.1%} of accounts", "start", "tick"))
    rows("accounts with code, by kind", coded, [(name, var) for _, name, var in CODED_KINDS])

    pmax = max(sum(pages[s]) for s in ACCOUNT_STORES) * 1.05
    sp = S.Scale(0, pmax, L, W - R)

    def traced(s, y):
        idx, row = pages[s]
        xi = sp.to(idx)
        o.append(box(L, y + 3, xi - L, 13, "--db-u", 0.7, "--db-u"))
        o.append(box(xi, y + 3, sp.to(idx + row) - xi, 13, "--db-c", 0.7, "--db-c"))
        o.append(S.label(sp.to(idx + row) + 8, y + 13, f"{idx / 1000:.1f}k + {row / 1000:.1f}k", "start", "tick"))
    rows("pages per traced account-read test", traced, [("index pages", "--db-u"), ("row pages", "--db-c")])
    return S.svg(W, y - 12, "".join(o))


# --------------------------------------------------------------------------- data
def require_c19(D):
    cl = D["claims"]
    C19 = cl.get("C19")
    if not C19:
        sys.exit("C19 missing: data/report_data.json has no claims.C19 (cycle 2, the store with "
                 "PR1-PR5). Re-run collect_reth.py on the bench host once hj1 hs1 hj2 hs2 and t3sh "
                 "are in; the page does not ship without its last finding.")
    missing = [k for k in C19_KEYS if C19.get(k) in (None, {}, [])
               and k not in ("families_not_robust", "below_0.5s_flagged", "out_of_band")]
    missing += [f"storage_shape.{k}" for k in ("J", "h", "g_sample") if not (C19.get("storage_shape") or {}).get(k)]
    missing += [f"t3_pages.{r}" for r in ("t3jg", "t3sg", "t3sh") if not (C19.get("t3_pages") or {}).get(r)]
    missing += [f"tree_fill.{s}" for s in ("J", "fixed", "g", "h") if not (C19.get("tree_fill") or {}).get(s)]
    missing += [f"accounts.{s}" for s in ("J", "h") if not (C19.get("accounts") or {}).get(s)]
    if "pr5" not in cl.get("C13", {}):
        missing.append("C13.pr5 (the cycle-2 baseline and its replica floors)")
    if missing:
        sys.exit("C19 incomplete: missing " + ", ".join(missing))
    return C19


def require_c20(D):
    cl = D["claims"]
    C20 = cl.get("C20")
    if not C20:
        sys.exit("C20 missing: data/report_data.json has no claims.C20 (cycle 3, the final store with "
                 "PR1-PR8). Re-run collect_reth.py on the bench host once kj1 ks1 kj2 ks2 and t3sk "
                 "are in.")
    missing = [k for k in C20_KEYS if C20.get(k) in (None, {}, [])
               and k not in ("families_not_robust", "out_of_band", "rootcheck_inconsistencies")]
    missing += [f"share_in_band.{s}" for s in STORES if s not in (C20.get("share_in_band") or {})]
    missing += [f"storage_shape.{s}" for s in ("J", "k") if not (C20.get("storage_shape") or {}).get(s)]
    missing += [f"account_shape.{s}" for s in ACCOUNT_STORES if not (C20.get("account_shape") or {}).get(s)]
    missing += [f"t3_pages.{r}" for r in ("t3jg", "t3sh", "t3sk") if not (C20.get("t3_pages") or {}).get(r)]
    missing += [f"tree_fill.{s}" for s in ("J", "h", "k") if not (C20.get("tree_fill") or {}).get(s)]
    if C20.get("rootcheck_inconsistencies") is None:
        missing.append("rootcheck_inconsistencies")
    if "final" not in cl.get("C13", {}):
        missing.append("C13.final (the cycle-3 baseline and its replica floors)")
    if missing:
        sys.exit("C20 incomplete: missing " + ", ".join(missing))
    return C20


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=os.path.join(HERE, "data", "report_data.json"))
    ap.add_argument("--out", default=HERE, help="directory for the html and figures/")
    args = ap.parse_args()
    D = json.load(open(args.data))
    C19 = require_c19(D)
    C20 = require_c20(D)
    cl = D["claims"]
    out_html = os.path.join(args.out, "reth-state-db-report.html")
    figdir = os.path.join(args.out, "figures")

    C13, V = cl["C13"], cl["verdicts"]
    # The page states C1-C14 as facts; each is an oracle in the collector.
    bad = {c: v["verdict"] for c, v in V.items() if v["verdict"] != "supported"}
    assert not bad, f"claims the page states as fact are not supported by the data: {bad}"
    ev = lambda c: V[c]["evidence"]
    cls13 = lambda tag, c="ge1s": C13[tag]["by_class"][c]

    # ----- the problem
    buf_cats = C13["buffered"]["categories"]
    by_mode = baseline_rows(buf_cats)
    seq_fast = [v for m in ("EXISTING_EOA", "NON_EXISTING_ACCOUNT") for v in by_mode["lt1s"].get(m, [])]
    assert seq_fast, "no EXISTING_EOA / NON_EXISTING_ACCOUNT categories under the buffered loop"
    # The headline is the worst of the sequential-account family finding 2 explains (buffered
    # loop + v1/v2 read path), not a global min: an unrelated category sliding past it would
    # silently change what the title claims to explain.
    factor = 1 / min(seq_fast)
    assert 45 <= factor <= 90, f"headline factor moved out of the sequential-account band: {factor:.1f}"
    seq = seq_fast + by_mode["lt1s"].get("sload_bloated", []) + by_mode["lt1s"].get("sstore_bloated", [])
    big_code = by_mode["ge1s"]["EXISTING_CONTRACT_DIFF_MAX"] + by_mode["ge1s"]["EXISTING_CONTRACT_JUMPDEST"]
    bfl = cls13("buffered")
    assert bfl["floor_joc"]["within10"] == bfl["floor_sa"]["within10"] == bfl["floor_sa"]["n"], \
        "a store no longer reproduces against itself under the buffered loop; the first caption says it does"

    # ----- finding 1
    fio = cl["C2"]["fio"]
    e2 = ev("C2")
    assert e2["buffered psync 64 / psync 4"] <= 1.1 < e2["dio / buffered at psync 16"], "the buffered loop no longer looks serialized"
    loop_q, nvme_q = e2["iob loop1 aqu-sz, nvme aqu-sz sum"]
    sp = cl["C1"]["speedup_buffered_to_dio"]
    state_fams = [f for f in sp if f not in ("ext_account_query_warm", "sload_same_key_benchmark",
                                             "EXISTING_EOA", "NON_EXISTING_ACCOUNT", "sload_bloated")]
    sp_lo = min(min(sp[f]["joc"], sp[f]["sa"]) for f in state_fams)
    sp_hi = max(max(sp[f]["joc"], sp[f]["sa"]) for f in state_fams)

    # ----- finding 2
    A2 = cl["T2_pages_and_A2"]
    eoa = next(v for k, v in A2.items() if "BALANCE-value_sent_0" in k and "EXISTING_EOA" in k)
    assert eoa["t2jc"]["pages"] * 10 < eoa["t2jv"]["pages"], "v1 no longer reads sequential accounts from a few pages"
    hashed_cost = 1 / max(ev("C5")["jh/jc A, B"])

    # ----- finding 3
    rp = cl["C6-C7"]
    toy = dict(re.findall(r"STAT mktest-(\S+) T \{.*LeafPages:(\d+)", "\n".join(rp["repack-toy.log"])))
    toy = {k: int(v) for k, v in toy.items()}
    hb, ha = rp["repack_before"]["HashedAccounts"], rp["repack_after"]["HashedAccounts"]
    C17 = cl["C17"]
    ts_orig, ts_fixed, ts_J = C17["tree_stats_original"], C17["tree_stats_fixed"], C17["tree_stats_v2_jochemnet"]
    ha_entries = int(re.search(r"entries=(\d+)", C17["logs"]["fix-virgin-hash.txt"][0]).group(1))
    assert toy["sorted-put"] == toy["sorted-append"] < toy["random-put"], "the toy no longer shows order, not Append, setting fill"
    assert ts_fixed["HashedAccounts"]["leaf_fill"] > ts_J["HashedAccounts"]["leaf_fill"] + 0.2, "PR1's tree is no longer denser than jochemnet's"
    assert C13["fix"]["by_class"]["ge1s"]["pair_a"]["median"] > 1, "PR1+2 no longer overshoots; finding 3 says it does"

    # ----- finding 4
    C18 = cl["C18"]
    ts_g = C18["tree_stats_g"]

    # ----- finding 5 (cycle 2's storage shape; the CDF shows the final store)
    sh = C19["storage_shape"]
    J, Sg = sh["J"], sh["g_sample"]
    Sk = C20["storage_shape"]["k"]
    jb = J["buckets"]
    assert C19["t3_pages"]["t3jg"] == C20["t3_pages"]["t3jg"], "cycles 2 and 3 no longer share jochemnet's trace"
    tp = {**C19["t3_pages"], **C20["t3_pages"]}
    t3 = t3_by_family(tp)
    assert "ether transfers" in t3, "no traced transfer tests; finding 5's caption quotes them"
    walks = {r: t3["ether transfers"][r][len(T3_GROUPS) - 1] for r, _ in T3_STORES}
    extra_accounts = ha_entries / C19["accounts"]["J"] - 1
    assert C19["rootcheck_inconsistencies"] == 0 == C20["rootcheck_inconsistencies"], \
        "reth's trie check found inconsistencies; finding 5 says none"
    # PR6: the storage tail is drawn too. Both stores count the bloated test contract (identical
    # rows in each) among their accounts above 2^24 slots; the final store has others besides it.
    big = 1 << 24
    bloated = max(J["over_2_24"])
    assert any(abs(x - bloated) <= 1000 for x in Sk["over_2_24"]), "the test contract is not among PR1-8's largest accounts"
    assert len(Sk["over_2_24"]) > 1, "PR1-8 no longer has accounts above 2^24 besides the test contract"

    # ----- accounts (cycle 3)
    ashape, ts_k = C20["account_shape"], C20["tree_stats_k"]
    acc19, acc20 = C19["acceptance_by_family"], C20["acceptance_by_family"]
    acct_tests = [n for n in tp["t3jg"] if t3_family(n) == "account reads"
                  and all(n in tp[r] for r in ("t3sh", "t3sk"))]
    assert acct_tests, "no traced account-read tests; the accounts figure quotes them"
    acct_pages = {s: tuple(sum(tp[r][n][f"HashedAccounts:{part}"] for n in acct_tests) / len(acct_tests)
                           for part in ("branch", "leaf"))
                  for s, r in (("J", "t3jg"), ("h", "t3sh"), ("k", "t3sk"))}
    vb = {s: ashape[s]["value_len_mean"] for s in ACCOUNT_STORES}
    assert vb["h"] > vb["J"] and abs(vb["k"] - vb["J"]) < abs(vb["h"] - vb["J"]), "PR8 no longer brings account rows to mainnet's size"
    assert ashape["h"]["coded_kinds"].get("contract", 0) < 0.05 < ashape["J"]["coded_kinds"]["contract"], \
        "the accounts section says PR1-5 had almost no code-only contracts"
    rows_ = [acct_pages[s][1] for s in ACCOUNT_STORES]
    assert max(rows_) / min(rows_) < 1.01, "row pages per account-read test differ; the accounts section says they don't"
    assert acct_pages["J"][0] < acct_pages["k"][0] <= acct_pages["h"][0], "index pages no longer explain the account-read gap"
    ar_move = acc20["account reads"]["median"] - acc19["account reads"]["median"]
    assert abs(ar_move) < 0.02, f"account reads moved {ar_move:+.3f} with PR8; the section says barely"
    index_extra = ts_k["HashedAccounts"]["branch"] / ts_J["HashedAccounts"]["branch"] - 1
    assert ts_k["HashedAccounts"]["branch_fill"] < ts_J["HashedAccounts"]["branch_fill"], "jochemnet's index pages are no longer fuller"
    # PR7: contract trie rows in order fill StoragesTrie's top-level tree like reth's rebuild
    st_main = {s: C20["tree_fill"][s]["main StoragesTrie"]["leaf_fill"] for s in ("J", "h", "k")}
    assert st_main["h"] < st_main["k"] and abs(st_main["k"] - st_main["J"]) < 0.05, "PR7 no longer brings StoragesTrie to jochemnet's fill"
    vt = [n for n in tp["t3sk"] if t3_family(n) in ("ether transfers", "account reads +value") and n in tp["t3sh"]]
    st_saved = sum(tp["t3sh"][n].get("StoragesTrie:main", 0) - tp["t3sk"][n].get("StoragesTrie:main", 0)
                   for n in vt) / len(vt)
    assert st_saved > 0, "PR7 no longer saves StoragesTrie pages on value-transfer tests"

    # ----- where it stands (the final store)
    fam20 = C20["families"]
    share, n_gated, oob = C20["share_in_band"], C20["tests_ge_0.5s"], C20["out_of_band"]
    assert C20["accepted"] and not C20["families_not_robust"], "the final store no longer passes acceptance"
    ph = C13["final"]["by_class"]
    g1 = ph["ge1s"]
    all_ge1s = g1["pair_a"]["within10"] == g1["pair_b"]["within10"] == g1["pair_a"]["n"]
    floors_full = g1["floor_joc"]["within10"] == g1["floor_sa"]["within10"] == g1["floor_sa"]["n"]
    lean = (g1["pair_a"]["median"] * g1["pair_b"]["median"]) ** 0.5 - 1

    # ----- page ------------------------------------------------------------------------------
    o = []
    w = o.append
    figs = {}

    def fig(name, svg, caption):
        figs[name] = svg
        return figure(svg, f"<b>Figure {len(figs)}.</b> {caption}")

    fignum = lambda name: list(figs).index(name) + 1
    kp = lambda n: f"{n / 1000:.1f}k"

    # the series' title form (Nethermind: "How can two Nethermind databases ... differ 17×, and then agree?")
    title = f"How can two reth databases differ {factor:.0f}&times; on the same benchmarks, and then agree?"
    w("<!doctype html><html lang=en><head><meta charset=utf-8>")
    w('<meta name=viewport content="width=device-width,initial-scale=1">')
    w(f'<meta name="description" content="The same EEST bloatnet benchmarks ran up to {factor:.0f}x '
      'slower on a generated reth database than on a mainnet snapshot. None of the six causes were in '
      'reth. Here is each one, and why its fix works.">')
    w('<link rel="preconnect" href="https://fonts.googleapis.com">'
      '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
      '<link href="https://fonts.googleapis.com/css2?family=VT323&'
      'family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&display=swap" '
      'rel="stylesheet">')
    w("<title>reth state-DB divergence, benchmarkoor bloatnet runs</title>")
    w(f"<style>{CSS}</style></head><body>")
    w('<div class=topbar><a href="../">&larr; all articles</a>'
      '<span>EXECUTION &middot; STATE DB</span></div>')
    w('<div class=eyebrow>// REPORT</div>')
    w(f"<h1>{title}</h1>")
    w('<div class=meta><span class=tag>Ethereum &middot; reth &middot; MDBX &middot; '
      f'benchmarking</span> &middot; 2026 &middot; <a href="{REPO}">reproducible pipeline &amp; '
      'data &rarr;</a></div>')
    w(f"<p class=sub>The same EEST benchmarks ran up to {factor:.0f}&times; slower on a generated reth "
      f"database than on a mainnet snapshot. None of the causes were in reth. With all six fixed and "
      f"three refinements on top, {round(share['k'] * n_gated)} of the {n_gated} tests that run half "
      f"a second or more agree within &plusmn;10%.</p>")
    w(f"<p><b>jochemnet</b> is a mainnet shadowfork snapshot. <b>state-actor</b> writes synthetic "
      f"state straight into reth's tables. benchmarkoor runs the same {C13['buffered']['common']} "
      f"EEST bloatnet tests against both, restoring the store before each one. Every ratio below is "
      f"state-actor's throughput over jochemnet's, so 1.00 is parity, and a test is in band within "
      f"&plusmn;10% on two independent pairs of runs. Tests under half a second are shown but not "
      f"scored: they barely reproduce against themselves.</p>")

    # ---- the problem
    w(f"<h2>The problem: up to {factor:.0f}&times; apart</h2>")
    w(fig("fig_baseline", chart_baseline(buf_cats),
          f"The first measurement, before any fix, one dot per test category. Sequential-account "
          f"lookups ran {1 / max(seq):.0f}&ndash;{factor:.0f}&times; slower, and calls into distinct "
          f"24&nbsp;KB contracts at {min(big_code):.2f}&ndash;{max(big_code):.2f}. Each store measured "
          f"against itself agreed, so the gap was real."))
    w(fig("fig_map", chart_map(extra_accounts),
          "The six causes, from the disk up. The numbers are this article's sections."))

    # ---- finding 1
    w("<h2>1. The test rig read the disk one request at a time</h2>")
    w(fig("fig_loop_fio", chart_fio(fio),
          f"Reads per second through a test copy of the same disk setup. In its default mode it stays "
          f"at {span(fio['buffered']['psync:4']['iops'], fio['buffered']['psync:64']['iops'])} however "
          f"many readers there are; with direct I/O it reaches "
          f"{compact(fio['dio']['psync:64']['iops'])}."))
    w("<p>Both databases lived inside a disk image, attached through Linux's loop device. In its "
      "default mode the loop device passes reads to the disk one at a time, so reth's many parallel "
      "reads waited in line. It also read ahead, fetching data nobody asked for, which hurt "
      "state-actor's layout of contract code most.</p>")
    w(f"<p>Switching it to direct I/O fixed both: every test that reads state got "
      f"{sp_lo:.0f}&ndash;{sp_hi:.0f}&times; faster. Everything below is measured that way. Our "
      f"earlier geth and Besu runs on this host used the same default.</p>")

    # ---- finding 2
    w("<h2>2. The two stores used different storage layouts</h2>")
    w(fig("fig_v1v2", chart_v1v2(eoa["t2jc"]["pages"], eoa["t2jv"]["pages"]),
          f"The same six neighbouring accounts in each layout. By address (v1) they share a page; by "
          f"hash (v2) each lands on a different one. Switching jochemnet to the hashed lookups alone "
          f"made its sequential tests {hashed_cost:.0f}&times; slower."))
    w("<p><b>jochemnet was a v1 store; state-actor writes v2.</b> reth has two storage layouts: the "
      "older v1 looks accounts up by address, the current v2 by hash. EEST's sequential tests read "
      "neighbouring addresses, which v1 finds together and v2 scatters. So the two stores weren't "
      "doing the same work, and that was most of the gap.</p>")
    w("<p>New reth nodes use v2, so we converted jochemnet. From here on, every gap is "
      "state-actor's.</p>")

    # ---- finding 3
    w("<h2>3. Rows out of order, and trie rows reth never stores</h2>")
    w(fig("fig_btree_split", chart_btree(toy, hb, ha),
          "A full page splits where the new key lands: in the middle for a key inside its range, at "
          "the edge for a key past its end."))
    w("<p>state-actor wrote accounts in the order it generated them, which is random against the "
      "table's hash order, so nearly every insert split a page in half. <b>PR1</b> writes them in "
      "key order.</p>")
    w(fig("fig_trie_rows", chart_trie(ts_orig["AccountsTrie"]["leaf"], ts_fixed["AccountsTrie"]["leaf"],
                                      ev("C10")["AccountsTrie branch t2s / t2jh (CALL EOA value 1)"]),
          "reth only stores a trie node that has another branch below it; the bottom ones it "
          "rebuilds from the leaves it reads anyway."))
    w("<p>state-actor stored every node, so state-root updates read rows reth would never have "
      "written. <b>PR2</b> stores only what reth would. Neither PR changes the state root.</p>")

    # ---- finding 4
    w("<h2>4. Page fill is a dial, and mainnet's pages aren't full</h2>")
    marks = [("jochemnet", ts_J["HashedAccounts"]["leaf_fill"], STORE_VAR["J"]),
             ("original (random order)", ts_orig["HashedAccounts"]["leaf_fill"], STORE_VAR["orig"]),
             ("PR1+2 (key order)", ts_fixed["HashedAccounts"]["leaf_fill"], STORE_VAR["fixed"]),
             ("PR1-4 migrated", ts_g["HashedAccounts"]["leaf_fill"], STORE_VAR["g"]),
             ("PR1-5", C19["tree_stats_h"]["HashedAccounts"]["leaf_fill"], STORE_VAR["h"])]
    w(fig("fig_fill_dial", chart_fill_dial(marks),
          "libmdbx can leave room free on a page when it splits: none packs it full, the most leaves "
          "it half full. The dots are each store's measured account table."))
    w("<p>Once writes arrive in key order, how full each page ends up is a choice, and it decides "
      "how many pages a lookup touches. jochemnet's account and storage tables carry years of "
      "random inserts, so their pages are well short of full.</p>")
    w("<p><b>PR3</b> puts the rest of state-actor's writes in key order. <b>PR4</b> lets it choose "
      "how full each table's pages end up, with a <code>migrated</code> setting that matches a node "
      "converted to v2.</p>")
    stats = {"J": ts_J, "orig": ts_orig, "fixed": ts_fixed, "g": ts_g, "h": C19["tree_stats_h"], "k": ts_k}
    w(fig("fig_tree_stats", chart_tree_stats(stats),
          f"Every store's five state tables. For the two storage tables the fill bar samples the "
          f"top-level tree only, while the page count includes each contract's own sub-tree. PR7 "
          f"brings StoragesTrie's bar up to jochemnet's, and value-transfer tests read about "
          f"{kp(st_saved)} fewer of its pages."))

    # ---- finding 5
    w("<h2>5. The wrong storage shape, and too many accounts</h2>")
    w(fig("fig_storage_cdf", chart_storage_cdf(J, Sg, Sk),
          f"Slots per storage-holding account. jochemnet: median {J['p50']}, {pct(jb['1'])} with "
          f"exactly one, {pct(jb['1'] + jb['2-28'])} with at most 28. The PR1-4 store (a "
          f"{thousands(Sg['n'])}-account sample): median {Sg['slots_per_account']['p50']}. The final "
          f"store traces jochemnet's curve, tail included: {len(Sk['over_2_24'])} accounts above "
          f"{compact(big)} slots, jochemnet {len(J['over_2_24'])}, each counting the big test contract."))
    w("<p>state-actor gave every contract a few hundred slots. Mainnet storage is heavy-tailed: most "
      "contracts hold one slot, a few hold millions.</p>")
    w("<p>The shape matters because reth stores no storage roots:</p><ul class=tight>"
      "<li>A contract with up to about 28 slots keeps them in its own row. A bigger one gets a "
      "separate sub-tree.</li>"
      "<li>When a block changes an account, reth re-hashes its path in the account trie, which "
      "needs the storage root of every sibling on that path.</li>"
      "<li>For a mainnet-shaped sibling that's one row reth often reads anyway. For one of "
      "state-actor's contracts it was a walk through a sub-tree.</li></ul>")
    w(fig("fig_sibling", chart_sibling(),
          "One modified account, its siblings, and what reth reads to re-hash them. The sub-tree "
          "walks are the pages the tracer labels 'other'."))
    w(fig("fig_t3_pages", chart_t3(t3),
          f"The same traced tests on jochemnet, the PR1-4, PR1-5 and PR1-8 stores, by table. The pink "
          f"'other' segment is the sub-tree walk: on the transfer tests, {kp(walks['t3jg'])} pages on "
          f"jochemnet, {kp(walks['t3sg'])} on PR1-4, {kp(walks['t3sh'])} after PR5, "
          f"{kp(walks['t3sk'])} on PR1-8."))
    w(f"<p><b>PR5</b> draws each contract's size from the distribution measured on jochemnet. We also "
      f"generated the store at jochemnet's account count (the original had {extra_accounts:.0%} "
      f"more) and matched the fill of the one big test contract. The new state needed new fixtures, "
      f"which reth itself filled, and reth checked every trie node of the new store: nothing to "
      f"repair. <b>PR6</b> draws the largest contracts too, with no cap, so they grow with the "
      f"store.</p>")

    # ---- accounts (cycle 3: a refinement, not one of the six causes)
    w("<h2>Then: accounts that look like mainnet's</h2>")
    w(fig("fig_accounts", chart_accounts(ashape, acct_pages),
          f"jochemnet, PR1-5 and PR1-8. {pct(ashape['h']['balance_len_share']['9'])} of PR1-5's "
          f"balances took 9 bytes, where {pct(ashape['J']['balance_len_share']['0'])} of jochemnet's "
          f"are zero, and its median nonce was {ashape['h']['nonce_quantiles']['0.5']}, two bytes on "
          f"{pct(ashape['h']['nonce_len_share']['2'])} of accounts. Pages are the mean over the "
          f"{len(acct_tests)} traced account-read tests. Account reads ran at "
          f"{acc19['account reads']['median']:.3f} on PR1-5 and {acc20['account reads']['median']:.3f} "
          f"on PR1-8."))
    w("<p>state-actor's accounts didn't look like mainnet's: big balances and nonces, and almost no "
      "contracts with code but no storage. <b>PR8</b> fixes that, but account reads barely get "
      "faster.</p>")
    w(f"<p>A block that reads accounts touches one row page per account it reads, however small "
      f"the row, so smaller rows don't help. What still differs is the index above the rows: "
      f"jochemnet's index pages are fuller, so state-actor's index has about {index_extra:.0%} more "
      f"pages.</p>")
    w(f"<p><b>PR7</b> writes each contract's trie rows in address order, so the top level of the "
      f"contract-trie table now fills like jochemnet's (Figure {fignum('fig_tree_stats')}, "
      f"StoragesTrie).</p>")

    # ---- where it stands
    w("<h2>Where it stands</h2>")
    w(fig("fig_share", chart_share(share, n_gated),
          f"Share of the {n_gated} tests that run half a second or more landing within &plusmn;10% "
          f"of jochemnet, store by store, all against v2 jochemnet under direct-io. PR6-8 refine the "
          f"store: they fix no cause of the {factor:.0f}&times;, and the share holds."))
    w(fig("fig_progression", chart_progression(fam20),
          "Every family, store by store. The right column shows original &rarr; PR1-8 and how many "
          "of the family's tests PR1-8 leaves in band."))
    ge1s = (f"Every test over a second is now in band on both pairs" if all_ge1s else
            f"Over a second, {g1['pair_a']['within10']} and {g1['pair_b']['within10']} of "
            f"{g1['pair_a']['n']} tests are in band on the two pairs")
    floors = ("" if not floors_full else ", as good as each store does against itself" if all_ge1s else
              f"; each store against itself manages all {g1['floor_sa']['n']}")
    w(f"<p>{ge1s}{floors}. state-actor leans {abs(lean):.1%} {'fast' if lean > 0 else 'slow'} "
      f"there, under the 3% we set out not to chase.</p>")

    # ---- what's left
    # tree_fill's "main HashedStorages" leaf_pages is fillgate.py's dedicated main-tree count;
    # storage_shape's main_tree_leaves comes from a different tool (the exact HashedStorages walk)
    # and is not guaranteed to scope the same way, so this residual uses the former.
    tf = C20["tree_fill"]
    lpa = lambda s, accounts: tf[s]["main HashedStorages"]["leaf_pages"] / accounts
    j_lpa, k_lpa = lpa("J", J["storage_accounts"]), lpa("k", Sk["storage_accounts"])
    lt = ph["lt1s"]["floor_joc"]
    w("<h2>What's left</h2><ul class=tight>")
    # PR1-5's out-of-band tests that PR1-8 brought back: same contract, a different test outside
    prev = [g_ for g_ in C19["out_of_band"] if g_ not in oob]
    for g_, v in sorted(oob.items(), key=lambda kv: kv[1]["k"]):
        # the explanation below holds for a bloated-contract test just outside the band only
        assert v["family"] in ("sload_bloated", "sstore no-write", "sstore write"), f"new out-of-band family: {v['family']}"
        assert abs(v["k"] - 1) < 0.15, f"{g_} is no longer just outside the band: {v['k']:.3f}"
        size = g_.rsplit("-", 1)[-1]
        moved = "".join(f" In PR1-5 it was {esc(fam_label(C19['out_of_band'][p]['family']))}, "
                        f"{p.rsplit('-', 1)[-1]} instead, now back in band." for p in prev)
        w(f"<li><b>{esc(fam_label(v['family']))}, {size}.</b> One test stays just outside the band, "
          f"on the {'fast' if v['k'] > 1 else 'slow'} side. It reads only the big test contract, "
          f"whose rows are identical in every store.{moved}"
          + (" Which test sits just outside changes between regenerations." if prev else "")
          + "</li>")
    ch = acc20["code-heavy reads"]["median"]
    w(f"<li><b>Distinct code.</b> Mainnet holds far more of it (Figure {fignum('fig_tree_stats')}, "
      f"Bytecodes), so code-heavy reads still run {abs(ch - 1):.0%} {'fast' if ch > 1 else 'slow'}. "
      f"That's the generator's code pool, not the layout.</li>")
    ar = acc20["account reads"]["median"]
    w(f"<li><b>The account index.</b> Account reads still run {abs(ar - 1):.0%} "
      f"{'fast' if ar > 1 else 'slow'}, and the gap is index pages (Figure {fignum('fig_accounts')}). "
      f"The generator's fill control fills index pages like row pages; jochemnet's index pages are "
      f"fuller.</li>")
    w(f"<li><b>HashedStorages' top-level tree</b> takes {k_lpa / j_lpa - 1:.0%} more pages per "
      f"contract than jochemnet's at any fill setting. That density is the snapshot's years of "
      f"history.</li>")
    w(f"<li><b>Short tests.</b> Under a second, jochemnet run twice agrees with itself on only "
      f"{pct(lt['within10'] / lt['n'])} of tests, so below half a second we don't score.</li></ul>")
    w("<p>Four of the six causes change nothing a state root can see, and none was in reth. A "
      "comparison between a generated store and a real one should state how each was laid out, not "
      "just what it holds.</p>")
    w(f'<div class=endbar><a href="../">&larr; all articles</a><a href="{REPO}">source &amp; data &rarr;</a></div>')
    w('<span class=cursor style="position:fixed;bottom:1.4rem;right:1.4rem;z-index:6"></span>')
    w("</body></html>")

    html_text = "\n".join(o)
    os.makedirs(figdir, exist_ok=True)
    with open(out_html, "w") as fh:
        fh.write(html_text)
    for old in os.listdir(figdir):
        if old.endswith(".svg"):
            os.remove(os.path.join(figdir, old))
    for name, svg in figs.items():
        with open(os.path.join(figdir, name + ".svg"), "w") as fh:
            fh.write(standalone(svg) + "\n")
    print(f"wrote {out_html} ({len(html_text):,} bytes), {len(figs)} standalone figures")
    print(f"headline factor: {factor:.1f}x")
    print(f">= 0.5 s in band: " + ", ".join(f"{s} {pct(share[s], 1)}" for s in STORES)
          + f"; accepted {C20['accepted']}; out of band {len(oob)}")


if __name__ == "__main__":
    main()
