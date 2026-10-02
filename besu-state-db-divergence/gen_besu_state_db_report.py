#!/usr/bin/env python3
"""Build the Besu state-DB divergence report from the collected run data.

Every number in the page is derived here from data/report_data.json; none is typed into the
prose. The oracles in main() fail generation if the data stops supporting a sentence the
article states as fact.

Usage: python3 gen_besu_state_db_report.py
"""
import collections
import datetime
import html
import json
import os
import re

import report_svg as S

SHORT_MODE = {
    "NON_EXISTING_ACCOUNT": "absent",
    "EXISTING_EOA": "EOA",
    "EXISTING_CONTRACT_MINIMAL": "MINIMAL",
    "EXISTING_CONTRACT_SAME_MAX": "SAME_MAX",
    "EXISTING_CONTRACT_DIFF_MAX": "DIFF_MAX",
    "EXISTING_CONTRACT_JUMPDEST": "JUMPDEST",
}

def esc(s):
    return html.escape(str(s))


def fnum(v, nd=2):
    return "—" if v is None else f"{v:.{nd}f}"


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def thousands(n):
    return f"{n:,}"

# The verdict run: the same cells measured on the original jochemnet baseline,
# on the drained + compacted one, and on state-actor. Collected by
# collect_verdict.py; the bands below fail loudly if that file is ever
# regenerated wrong.
CSS = """
/* Site theme, mirroring build_site.py CRT_VARS and the ARTICLE stylesheet so the
   report reads as one of the site's pages. Dark-only, like the site. */
:root {
  --bg:#000000; --fg:#e2e6e2; --muted:#aab0aa; --dim:#5c645c; --line:#182818;
  --panel:#0a120a; --accent:#33ff33; --green-dim:#28d128; --green-muted:#1a5a1a;
  --bad-bg:#2a1214; --bad-fg:#ff9a9f; --good-bg:#0f2a12; --good-fg:#7fd98f;
  --barbg:#182818; --chip:#0f1f0f;
  --db-c:#6fb2e8; --db-u:#e8a83a; --db-sa:#b491f0;
  --glow:rgba(51,255,51,.30);
  --crt:'VT323',monospace; --mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--fg); max-width: 960px; margin: auto;
  padding: 28px 20px 80px; font: 15px/1.65 var(--mono);
  -webkit-font-smoothing: antialiased;
}
body::before { content:''; position:fixed; inset:0; z-index:100; pointer-events:none;
  background:repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(0,255,0,.006) 3px,rgba(0,255,0,.006) 6px); }
body::after { content:''; position:fixed; inset:0; z-index:101; pointer-events:none;
  background:radial-gradient(ellipse at center,transparent 62%,rgba(0,0,0,.45) 100%); }
::selection { background: rgba(51,255,51,.22); color:#fff; }
a { color: var(--green-dim); text-decoration: none; border-bottom: 1px solid rgba(51,255,51,.25); }
a:hover { color: var(--accent); border-bottom-color: var(--accent); text-shadow: 0 0 6px var(--glow); }
@media (prefers-reduced-motion: reduce){ *,*::before,*::after{animation-duration:.01ms!important} }
.topbar { display:flex; justify-content:space-between; font-family:var(--crt);
  font-size:1.05rem; color:var(--green-muted); margin-bottom:1.6rem; }
.topbar a { border:none; color:var(--green-muted); }
.topbar a:hover { color:var(--accent); }
.eyebrow { font-family:var(--crt); letter-spacing:.22em; color:var(--accent); opacity:.55;
  font-size:1rem; text-shadow:0 0 8px rgba(51,255,51,.2); margin-bottom:.5rem; }
h1 { font-family:var(--crt); font-weight:400; color:var(--accent); line-height:1.06;
  font-size:clamp(2rem,4.6vw,3rem); margin:0 0 6px;
  text-shadow:0 0 7px var(--glow),0 0 24px rgba(51,255,51,.08); }
.sub { color:var(--muted); font-size:13.5px; margin:0 0 4px; }
.meta { font-size:.72rem; letter-spacing:.05em; color:var(--dim); border-top:1px solid var(--line);
  border-bottom:1px solid var(--line); padding:.6rem 0; margin:14px 0 26px; }
.meta .tag { color:var(--muted); }
h2 { font-family:var(--mono); font-weight:700; color:var(--accent); font-size:19px;
  margin:40px 0 10px; text-shadow:0 0 5px rgba(51,255,51,.18); }
h2::after { content:''; display:block; height:1px; margin-top:.55rem; opacity:.3;
  background:linear-gradient(90deg,var(--green-muted),transparent 65%); }
h3 { font-weight:600; color:#d9ffd9; font-size:15.5px; margin:22px 0 8px; }
h3::before { content:':: '; color:var(--green-muted); }
/* The quoted client log lines are single unbreakable tokens; without this they widen the page. */
code { font-family:var(--mono); font-size:.9em; background:rgba(51,255,51,.07);
  border:1px solid var(--line); border-radius:3px; padding:.05em .35em; color:#bfeecf;
  overflow-wrap:anywhere; }
table { border-collapse:collapse; width:100%; margin:10px 0 6px; font-size:13.5px; line-height:1.55; }
th, td { border:1px solid var(--line); padding:6px 9px; text-align:left; vertical-align:middle; }
th { font-family:var(--crt); font-size:1.02rem; font-weight:400; letter-spacing:.05em;
  color:var(--accent); background:rgba(51,255,51,.05); text-shadow:0 0 5px rgba(51,255,51,.15); }
tr:nth-child(even) td { background:rgba(51,255,51,.02); }
tr:hover td { background:rgba(51,255,51,.045); }
td.n, th.n { text-align:right; font-variant-numeric:tabular-nums; }
td.bad { background:var(--bad-bg); color:var(--bad-fg); font-weight:600; }
td.good { background:var(--good-bg); color:var(--good-fg); font-weight:600; }
caption { caption-side:bottom; color:var(--muted); font-size:12.5px; text-align:left;
  padding:8px 0 0; line-height:1.55; }
.bar { background:var(--barbg); border-radius:2px; height:8px; width:110px;
  overflow:hidden; display:inline-block; }
.bar > i { display:block; height:100%; }
.legend { display:flex; gap:18px; flex-wrap:wrap; margin:14px 0 10px; font-size:13px; }
.legend b { font-weight:600; }
.sw { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; }
th.db { border-bottom-width:2px; }
details { border:1px solid var(--line); border-radius:2px; padding:4px 14px;
  margin:12px 0; background:var(--panel); }
details[open] { padding-bottom:12px; }
summary { cursor:pointer; font-weight:600; color:#d9ffd9; padding:9px 2px; }
summary::marker { color:var(--accent); }
.card { border:1px solid var(--line); border-left:3px solid var(--green-muted);
  border-radius:2px; padding:4px 18px 14px; margin:16px 0; background:var(--panel); }
.card details { background:var(--bg); }
.chip { display:inline-block; background:var(--chip); border:1px solid var(--green-muted);
  border-radius:3px; padding:2px 10px; font-size:12px; color:var(--muted);
  vertical-align:middle; margin-left:8px; }
.note { color:var(--muted); font-size:13px; }
ul.tight { list-style:none; padding-left:0; }
ul.tight li { position:relative; padding-left:1.3rem; margin:5px 0; }
ul.tight li::before { content:'▸'; position:absolute; left:0; color:var(--green-dim); }
ol.tight li { margin:5px 0; }
ol.tight li::marker { color:var(--green-dim); }
.tip { position:relative; border-bottom:1px dotted var(--muted); cursor:help; }
.tip > .bub { display:none; }
.tip:hover > .bub, .tip:focus > .bub, .tip:focus-within > .bub { display:block; }
.bub { position:absolute; left:0; top:1.7em; z-index:9; width:360px; max-width:70vw;
  background:#050805; color:var(--fg); border:1px solid var(--green-muted); border-radius:3px;
  padding:10px 12px; font-size:12.5px; line-height:1.5; font-weight:400; text-align:left;
  white-space:normal; box-shadow:0 0 18px rgba(51,255,51,.10); }
.bub b { display:block; margin-bottom:4px; font-family:var(--mono); }
.bub .src { display:block; margin-top:6px; color:var(--dim); font-size:11.5px; }
svg.chart { width:100%; height:auto; margin:6px 0 2px; overflow:visible; font:11px var(--mono); }
svg.chart text { fill:var(--fg); }
svg.chart text.tick, svg.chart text.ax { fill:var(--muted); }
svg.chart text.big { font-size:12px; font-weight:600; }
figure { margin:16px 0 8px; border:1px solid var(--line); background:#050805; padding:10px 12px; }
figure:hover { border-color:var(--green-muted); box-shadow:0 0 22px rgba(51,255,51,.06); }
figcaption { color:var(--muted); font-size:12.5px; margin-top:6px; line-height:1.55; }
/* Quoted client log lines, shown as the client prints them. */
pre.log { background:#050805; border:1px solid var(--line); border-radius:3px;
  padding:9px 11px; margin:12px 0; overflow-x:auto; font-size:12px; line-height:1.55;
  color:#bfeecf; white-space:pre-wrap; overflow-wrap:anywhere; }
.endbar { margin-top:48px; padding-top:1.2rem; border-top:1px solid var(--line);
  font-family:var(--crt); font-size:1rem; color:var(--green-muted);
  display:flex; justify-content:space-between; flex-wrap:wrap; gap:.6rem; }
.endbar a { border:none; }
.cursor { display:inline-block; width:.5em; height:.9em; background:var(--accent);
  vertical-align:-2px; margin-left:2px; animation:blink 1s step-end infinite; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
.deck { color:var(--muted); font-size:15.5px; line-height:1.6; margin:2px 0 14px; }
nav.toc { border:1px solid var(--line); background:var(--panel); padding:12px 16px;
  margin:18px 0 26px; font-size:13.5px; }
nav.toc .toch { color:var(--accent); letter-spacing:.08em; text-transform:uppercase;
  font-size:11.5px; margin-bottom:8px; }
nav.toc ul { list-style:none; margin:0; padding:0; }
nav.toc li { margin:3px 0; }
nav.toc li.sub { padding-left:20px; font-size:12.5px; }
nav.toc li.sub a { color:var(--muted); }
nav.toc a { text-decoration:none; }
nav.toc a:hover { text-decoration:underline; }
/* The data tables are wider than a phone. Without this the whole page scrolls sideways;
   with it only the table does. */
@media (max-width: 760px) {
  table { display:block; overflow-x:auto; }
  figure { padding:8px 6px; }
}
"""


# The standalone .svg files carry no page around them, so the chart variables and
# text rules have to travel inside each file. The palette is derived from CSS
# above rather than restated, so a colour change here cannot drift from the report.
def _css_vars(block):
    return dict(re.findall(r"(--[a-z-]+):\s*(#[0-9a-fA-F]{3,8})", block))


SVG_VARS = _css_vars(re.search(r":root \{(.*?)\}", CSS, re.S).group(1))
assert "--db-c" in SVG_VARS and "--accent" in SVG_VARS, \
    "chart palette no longer derivable from CSS"

SVG_TEXT_CSS = (
    "svg{font:11px 'IBM Plex Mono',ui-monospace,Menlo,monospace}"
    'text{fill:var(--fg)}text.tick,text.ax{fill:var(--muted)}'
    'text.big{font-size:12px;font-weight:600}'
)


def figure(svg, caption):
    return f"<figure>{svg}<figcaption>{caption}</figcaption></figure>"


def add_toc(doc):
    """Give every navigable heading an id and build the contents list.

    Headings inside a <details> are supporting material rather than
    navigation targets, so they are left alone.
    """
    entries = []

    def tag(m):
        level, inner = m.group(1), m.group(2)
        before = doc[:m.start()]
        if before.count("<details") > before.count("</details>"):
            return m.group(0)
        slug = re.sub(r"[^a-z0-9]+", "-",
                      html.unescape(re.sub(r"<[^>]+>", "", inner)).lower()).strip("-")
        entries.append((level, slug, inner))
        return f'<h{level} id="{slug}">{inner}</h{level}>'

    doc = re.sub(r"<h([23])>(.*?)</h\1>", tag, doc, flags=re.S)
    assert entries, "table of contents: no headings found"
    items = "".join(
        f'<li{" class=sub" if lvl == "3" else ""}><a href="#{slug}">{text}</a></li>'
        for lvl, slug, text in entries)
    nav = f'<nav class=toc><div class=toch>Contents</div><ul>{items}</ul></nav>'
    assert doc.count("<!--TOC-->") == 1, "table of contents: marker missing"
    return doc.replace("<!--TOC-->", nav)


def standalone_svg(svg):
    """Same chart markup, wrapped so the file renders on its own in any viewer.

    In the report the page supplies the background; a bare .svg does not, so the
    file carries its own background rect plus the site palette (dark, like the
    site — the report is dark-only).
    """
    vars_css = "".join(f"{k}:{v};" for k, v in SVG_VARS.items())
    style = f"<style>svg{{{vars_css}}}{SVG_TEXT_CSS}</style>"
    head, rest = svg.split(">", 1)
    return (f'{head} xmlns="http://www.w3.org/2000/svg">{style}'
            f'<rect width="100%" height="100%" fill="var(--bg)"/>{rest}')



# ---------------------------------------------------------------- data + derivations

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figures")
OUT = os.path.join(HERE, "besu-state-db-report.html")

BUCKETS = ["absent", "leaf-only", "code-reading"]
ARM_DOC = {
    "plain": "the published snapshot, pre-runs replayed, promoted, exactly as a benchmark uses it",
    "compacted": "the same store, flushed and then fully compacted",
    "state_actor": "the synthetically generated companion store",
}


def key(r):
    return (r["opcode"], r["mode"], r["gas"], r["value_sent"], r["baseline"])


def index(rows):
    return {key(r): r for r in rows}


def load():
    return json.load(open(os.path.join(DATA, "report_data.json")))


def shared(*armsets):
    return sorted(set.intersection(*(set(a) for a in armsets)))


def ratios(a, b, common, field="mgas_s"):
    """Per-workload b/a, grouped by bucket."""
    out = collections.defaultdict(list)
    for c in common:
        out[a[c]["bucket"]].append(b[c][field] / a[c][field])
    return out


def bucket_median(a, b, common, field="mgas_s"):
    return {k: median(v) for k, v in ratios(a, b, common, field).items()}


def bucket_bytes(a, b, common):
    """Aggregate byte ratio per bucket — a sum, not a median, so a few huge reads cannot hide."""
    num = collections.defaultdict(int)
    den = collections.defaultdict(int)
    for c in common:
        num[a[c]["bucket"]] += b[c]["disk_read_bytes"]
        den[a[c]["bucket"]] += a[c]["disk_read_bytes"]
    return {k: num[k] / den[k] for k in den if den[k]}


def gas_of(a, common):
    return sum(a[c]["gas_used"] for c in common)


# ---------------------------------------------------------------- figures

W = 760


def legend(x, y, items, trailer=""):
    """Legend with real coloured dots — a "●" in a text run carries the text colour, not the
    series colour, which makes a multi-series figure unreadable."""
    out, cx = [], x
    for name, var in items:
        out.append(S.dot(cx + 4, y - 4, 3.6, var))
        out.append(S.label(cx + 12, y, name, cls="ax"))
        cx += 12 + 7.1 * len(name) + 16
    if trailer:
        out.append(S.label(cx, y, trailer, cls="ax"))
    return "".join(out)


def thin(scale, ticks, gap=32):
    """Drop ticks whose labels would collide once the scale has placed them."""
    out, last = [], -1e9
    for t in ticks:
        if scale.to(t) - last >= gap:
            out.append(t)
            last = scale.to(t)
    return out


def chart_overview(rows, F):
    """Every test of each class against the snapshot as published, log scale, one dot per test.

    Split into the population the rest of the article counts (over a second) and the one it
    only shows (under a second); the tick is the class median the tables quote.
    """
    LEFT, RIGHT, TOP, ROW, GAP = 250, 112, 34, 24, 24
    H = TOP + ROW * len(rows) + GAP + 40
    vals = [F["state_actor"][c]["mgas_s"] / F["plain"][c]["mgas_s"] for r in rows for c in r["tests"]]
    lo, hi = min(vals) / 1.2, max(max(vals) * 1.2, 1.3)
    sc = S.LogScale(lo, hi, LEFT, W - RIGHT)
    y1 = TOP + ROW * len(rows) + GAP - 10
    body = [S.hgrid(sc, thin(sc, [t for t in (0.05, 0.1, 0.2, 0.5, 1.0) if lo <= t <= hi]),
                    TOP - 10, y1, fmt=lambda v: f"{v:g}\u00d7"),
            S.band(sc.to(0.9), sc.to(1.1), TOP - 10, y1, "--accent", 0.10),
            S.line(sc.to(1.0), TOP - 10, sc.to(1.0), y1, "--accent", width=1, dash="4 3")]
    var = {"absent": "--db-sa", "light": "--db-c", "dark": "--db-u", "control": "--muted"}
    body.append(S.label(0, TOP - 16, "over a second", cls="ax"))
    body.append(S.label(W - RIGHT + 10, TOP - 16, "median", cls="tick"))
    y, prev = TOP, None
    for r in rows:
        if prev is not None and r["dur"] != prev:
            y += GAP
            body.append(S.label(0, y - 10, "under a second: shown, not counted", cls="ax"))
        body.append(S.label(LEFT - 10, y + 4, f"{r['label']} (n={r['n']})", anchor="end",
                            cls="tick"))
        for c in r["tests"]:
            body.append(S.dot(sc.to(F["state_actor"][c]["mgas_s"] / F["plain"][c]["mgas_s"]),
                              y, 2.2, var[r["cls"]]))
        x = sc.to(r["sap"])
        body.append(S.line(x, y - 8, x, y + 8, "--fg", width=2))
        body.append(S.label(W - RIGHT + 10, y + 4, f"{r['sap']:.3f}\u00d7", cls="tick"))
        prev = r["dur"]
        y += ROW
    body.append(S.label(LEFT, H - 10, "state-actor \u00f7 snapshot as published, one dot per test",
                        cls="ax"))
    return S.svg(W, H, "".join(body))


def chart_lsm_levels(levels):
    """Where the pre-run's rows sit, before and after compaction.

    One bar per LSM level, width proportional to file count. This is the figure the mechanism
    argument rests on: four files at the top of the tree against hundreds at the bottom.
    """
    cfs = [("06", "ACCOUNT_INFO_STATE"), ("07", "CODE_STORAGE")]
    LEFT, TOP, ROW, GAP = 176, 30, 15, 34

    def files(st, cf, l):
        return levels[st].get(cf, {}).get(str(l), {}).get("files", 0)

    # a level that is empty in both states says nothing; drawing it as "0 → 0" is noise
    lvls = {cf: [l for l in range(7) if files("before", cf, l) or files("after", cf, l)]
            for cf, _ in cfs}
    H = TOP + sum(len(lvls[cf]) * ROW + GAP for cf, _ in cfs) + 48
    mx = max(files(st, cf, l) for st in ("before", "after") for cf, _ in cfs for l in lvls[cf])
    sc = S.Scale(0, mx, LEFT, W - 150)
    body = []
    y = TOP
    for cf, name in cfs:
        body.append(S.label(0, y - 8, f"cf {cf} {name}", cls="big"))
        for i, l in enumerate(lvls[cf]):
            b4, af = files("before", cf, l), files("after", cf, l)
            yy = y + ROW * i
            body.append(S.label(LEFT - 8, yy + 8, f"L{l}", anchor="end", cls="tick"))
            if b4:
                body.append(S.band(sc.to(0), sc.to(b4), yy + 1, yy + 5, "--db-c", opacity=0.85))
            if af:
                body.append(S.band(sc.to(0), sc.to(af), yy + 7, yy + 11, "--db-sa", opacity=0.85))
            body.append(S.label(max(sc.to(b4), sc.to(af)) + 8, yy + 9, f"{b4} → {af}", cls="tick"))
        y += len(lvls[cf]) * ROW + GAP
    body.append(S.label(LEFT, H - 14, "SST files per level", cls="ax"))
    body.append(legend(LEFT + 140, H - 14, [("after pre-run", "--db-c"),
                                            ("after compaction", "--db-sa")]))
    return S.svg(W, H, "".join(body))


def chart_bloom(props, byte_ratio):
    """Filter bytes per state column family, and what their absence costs.

    Left: the snapshot carries a bloom filter on every state column family; the generated store
    carries none. Right: the byte penalty that follows, split by whether the lookup finds a key.
    """
    cfs = [("06", "ACCOUNT_INFO_STATE"), ("07", "CODE_STORAGE"),
           ("08", "ACCOUNT_STORAGE"), ("09", "TRIE_BRANCH")]
    TOP, ROW = 34, 26
    H = TOP + ROW * len(cfs) + 96
    mid = 392
    mx = max(props["jochemnet"][cf]["filter_bytes"] for cf, _ in cfs)
    sc = S.Scale(0, mx, 200, mid - 26)
    body = [S.label(200, TOP - 14, "bloom filter bytes", cls="big"),
            S.label(mid + 26, TOP - 14, "bytes read, state-actor ÷ compacted", cls="big")]
    for i, (cf, name) in enumerate(cfs):
        y = TOP + ROW * i
        j = props["jochemnet"][cf]["filter_bytes"]
        s = props["state_actor"][cf]["filter_bytes"]
        body.append(S.label(194, y + 12, f"cf {cf} {name}", anchor="end", cls="tick"))
        body.append(S.band(sc.to(0), sc.to(j), y + 2, y + 9, "--db-c", opacity=0.85))
        body.append(S.label(sc.to(j) + 7, y + 9, thousands(j), cls="tick"))
        # a zero-length bar is invisible, and invisible is the wrong impression for "none"
        body.append(S.line(sc.to(0), y + 12, sc.to(0) + 5, y + 19, "--db-sa", width=2))
        body.append(S.label(sc.to(0) + 10, y + 20, f"{s} (none)", cls="tick"))
    order = ["absent", "leaf-only", "code-reading"]
    rlo = min(byte_ratio[b] for b in order) / 1.4
    rhi = max(byte_ratio[b] for b in order) * 1.4
    rsc = S.LogScale(rlo, rhi, mid + 150, W - 30)
    body.append(S.hgrid(rsc, thin(rsc, [t for t in (1, 2, 5, 10, 25, 50, 100)
                                       if rlo <= t <= rhi]),
                        TOP, TOP + ROW * len(order), fmt=lambda v: f"{v:g}×"))
    for i, b in enumerate(order):
        y = TOP + ROW * i + 10
        r = byte_ratio[b]
        body.append(S.label(mid + 144, y + 3, b, anchor="end", cls="tick"))
        body.append(S.dot(rsc.to(r), y, 4, "--db-sa", title=f"{b}: {r:.2f}×"))
        body.append(S.label(rsc.to(r) - 10, y - 8, f"{r:.1f}×", anchor="end", cls="tick"))
    body.append(S.label(150, H - 14,
                        "a filter rejects a missing key outright; without one the lookup reads "
                        "index and data blocks", cls="ax"))
    return S.svg(W, H, "".join(body))


def chart_geometry(props, gref):
    """Record size, compression and block size for the two stores, against geth's ratios.

    The residual argument is a chain: generated records are larger and less compressible, so a
    block holds fewer of them and a read moves more bytes. The figure shows both engines
    arriving at the same ratio.
    """
    rows = [
        ("mean record, cf06", "mean_record", "B", 1),
        ("physical ÷ logical, cf06", "phys_over_logical", "", 3),
        ("compressed bytes/block, cf06", "block_bytes", "B", 0),
    ]
    LEFT, TOP, ROW = 250, 44, 44
    H = TOP + ROW * len(rows) + 74
    body = [S.label(LEFT, TOP - 22, "compacted snapshot → state-actor", cls="big")]
    for i, (lbl, fld, unit, nd) in enumerate(rows):
        y = TOP + ROW * i
        a = props["jochemnet"]["06"][fld]
        b = props["state_actor"]["06"][fld]
        sc = S.Scale(0, max(a, b) * 1.18, LEFT, W - 120)
        body.append(S.label(LEFT - 10, y + 6, lbl, anchor="end", cls="tick"))
        body.append(S.band(sc.to(0), sc.to(a), y, y + 7, "--db-c", opacity=0.85))
        body.append(S.band(sc.to(0), sc.to(b), y + 9, y + 16, "--db-sa", opacity=0.85))
        body.append(S.label(sc.to(a) + 7, y + 6, f"{a:,.{nd}f}{unit}", cls="tick"))
        body.append(S.label(sc.to(b) + 7, y + 16, f"{b:,.{nd}f}{unit}", cls="tick"))
        body.append(S.label(W - 106, y + 11, f"{b/a:.3f}×", cls="big"))
    yb = TOP + ROW * len(rows) + 16
    body.append(S.label(LEFT - 10, yb + 4, "geth, same two ratios", anchor="end", cls="tick"))
    body.append(S.label(LEFT, yb + 4,
                        f"{gref['compression_ratio']:.3f}×  and  {gref['block_size_ratio']:.3f}×",
                        cls="big"))
    body.append(legend(LEFT, H - 14, [("compacted snapshot", "--db-c"),
                                      ("state-actor", "--db-sa")],
                       trailer="ratio at right"))
    return S.svg(W, H, "".join(body))


def chart_cost_curves(F, common):
    """Throughput against the gas budget, one line per arm.

    A fixed per-block overhead would make every line fall as the budget grows; lines that stay
    flat and separated are a per-read cost difference instead.
    """
    gases = sorted({c[2] for c in common})
    LEFT, RIGHT, TOP = 66, 122, 24
    H = 252
    arms = [("plain", "--db-c"), ("compacted", "--db-u"), ("state_actor", "--db-sa")]
    sel = [c for c in common if c[1] == "EXISTING_EOA" and not c[4]]
    assert sel, "cost curves: no EXISTING_EOA measurement rows"
    ys = [F[a][c]["mgas_s"] for a, _ in arms for c in sel]
    xsc = S.Scale(min(gases), max(gases), LEFT, W - RIGHT)
    ysc = S.Scale(0, max(ys) * 1.12, H - 46, TOP)
    body = []
    # y axis is horizontal rules; hgrid() draws vertical ones, so it is the wrong tool here
    step = 25 if max(ys) > 60 else 10
    for t in range(0, int(max(ys) * 1.12) + 1, step):
        body.append(S.line(LEFT, ysc.to(t), W - RIGHT, ysc.to(t), "--line", width=1))
        body.append(S.label(LEFT - 8, ysc.to(t) + 3, f"{t:g}", anchor="end", cls="tick"))
    for g in gases:
        body.append(S.label(xsc.to(g), H - 28, f"{g}", anchor="middle", cls="tick"))
    ends = []
    for a, var in arms:
        pts = [(xsc.to(g), ysc.to(median([F[a][c]["mgas_s"] for c in sel if c[2] == g])))
               for g in gases if any(c[2] == g for c in sel)]
        body.append(S.polyline(pts, var, width=2))
        ends.append((pts[-1][1], a.replace("_", "-")))
    # arms can finish within a line height of each other; push each label clear of the last
    prev = -1e9
    for y, name in sorted(ends):
        y = prev = max(y, prev + 13)
        body.append(S.label(W - RIGHT + 10, y + 3, name, cls="tick"))
    body.append(S.label(LEFT, H - 8, "MGas/s against gas budget (M), existing EOA, median over opcodes", cls="ax"))
    return S.svg(W, H, "".join(body))


def chart_verdict(rows, band):
    """Each category before and after the snapshot is treated, against the parity band.

    The mirror image of the first figure. There the question was how far apart the two stores
    look; here it is how much of that distance was the snapshot's placement artifact.
    """
    LEFT, RIGHT, TOP, ROW = 250, 40, 22, 13
    H = TOP + ROW * len(rows) + 58
    lo = min(min(r[3], r[4]) for r in rows) / 1.25
    hi = max(max(r[3], r[4]) for r in rows) * 1.25
    sc = S.LogScale(lo, hi, LEFT, W - RIGHT)
    y1 = TOP + ROW * len(rows) + 2
    body = [S.band(sc.to(1 - band), sc.to(1 + band), TOP - 6, y1, "--accent", 0.10),
            S.hgrid(sc, thin(sc, [t for t in (0.1, 0.2, 0.5, 1.0, 2.0) if lo <= t <= hi]),
                    TOP - 6, y1, fmt=lambda v: f"{v:g}×"),
            S.line(sc.to(1.0), TOP - 6, sc.to(1.0), y1, "--muted", width=1, dash="3 3")]
    for i, (_, op, m, before, after) in enumerate(rows):
        y = TOP + ROW * i + 7
        body.append(S.label(LEFT - 10, y + 3, f"{op} {SHORT_MODE.get(m, m)}", anchor="end",
                            cls="tick"))
        body.append(S.line(sc.to(before), y, sc.to(after), y, "--dim", width=1.5))
        body.append(S.dot(sc.to(before), y, 3.2, "--db-u", title=f"{op} {m} before {before:.3f}×"))
        body.append(S.dot(sc.to(after), y, 3.6, "--accent", title=f"{op} {m} after {after:.3f}×"))
    body.append(S.label(LEFT, H - 28, "state-actor ÷ snapshot, throughput", cls="ax"))
    body.append(legend(LEFT, H - 10, [("as published", "--db-u"), ("compacted", "--accent")],
                       trailer=f"shaded band = ±{band*100:.0f}% of parity"))
    return S.svg(W, H, "".join(body))


def chart_outcome(cats, band, v4=None):
    """Every category before the three fixes and after them, against the parity band.

    The closing bracket on the first figure. That one asked how far apart two stores holding the
    same state can look; this one answers it, and the answer is not one number. Two of the three
    mechanisms pull their categories into the band. The third pushed its sixteen straight through
    it under #138; `v4` carries where the corpus fix (#141) put them, as a third dot per row.
    """
    v4 = v4 or {}
    latest = lambda r: v4.get((r[1], r[2]), r[4])
    # Group by mechanism, then by outcome: three blocks read as three stories, where sorting
    # purely by value interleaves the absence and shared-code rows and hides both.
    order = {"light": 0, "absent": 1, "dark": 2}
    cats = sorted(cats, key=lambda r: (order[r[0]], latest(r)))
    LEFT, RIGHT, TOP, ROW = 250, 40, 22, 13
    H = TOP + ROW * len(cats) + 58
    lo = min(min(r[3], r[4], latest(r)) for r in cats) / 1.25
    hi = max(max(r[3], r[4], latest(r)) for r in cats) * 1.25
    sc = S.LogScale(lo, hi, LEFT, W - RIGHT)
    y1 = TOP + ROW * len(cats) + 2
    body = [S.band(sc.to(1 - band), sc.to(1 + band), TOP - 6, y1, "--accent", 0.10),
            S.hgrid(sc, thin(sc, [t for t in (0.1, 0.2, 0.5, 1.0, 1.5, 2.0) if lo <= t <= hi]),
                    TOP - 6, y1, fmt=lambda v: f"{v:g}×"),
            S.line(sc.to(1.0), TOP - 6, sc.to(1.0), y1, "--muted", width=1, dash="3 3")]
    # Colour by class rather than by arm: the story is which mechanism a category belonged to.
    hue = {"absent": "--db-c", "light": "--db-u", "dark": "--db-sa"}
    for i, (cl, op, m, before, after) in enumerate(cats):
        y = TOP + ROW * i + 7
        body.append(S.label(LEFT - 10, y + 3, f"{op} {SHORT_MODE.get(m, m)}", anchor="end",
                            cls="tick"))
        body.append(S.line(sc.to(before), y, sc.to(after), y, "--dim", width=1.5))
        body.append(S.dot(sc.to(before), y, 3.0, "--muted",
                          title=f"{op} {m} before {before:.3f}×"))
        if (op, m) in v4:
            body.append(S.line(sc.to(after), y, sc.to(v4[(op, m)]), y, hue[cl], width=1.5))
            body.append(S.dot(sc.to(after), y, 3.0, "--dim",
                              title=f"{op} {m} after #138 {after:.3f}×"))
            body.append(S.dot(sc.to(v4[(op, m)]), y, 3.8, hue[cl],
                              title=f"{op} {m} after #141 {v4[(op, m)]:.3f}×"))
        else:
            body.append(S.dot(sc.to(after), y, 3.8, hue[cl],
                              title=f"{op} {m} after {after:.3f}×"))
    body.append(S.label(LEFT, H - 28, f"state-actor ÷ snapshot, throughput (band = ±{band*100:.0f}%)",
                        cls="ax"))
    items = [("before", "--muted"), ("absence", "--db-c"), ("shared or no code", "--db-u"),
             ("distinct code", "--db-sa")]
    if v4:
        items.insert(1, ("after #138", "--dim"))
    body.append(legend(60, H - 10, items))
    return S.svg(W, H, "".join(body))


# ---------------------------------------------------------------- main

def main():
    D = load()
    P = D["provenance"]
    C = D["census"]
    GREF = D["geth_reference"]
    props = D["sst_props"]
    levels = D["levels"]

    F = {k: index(v) for k, v in D["full"].items()}
    FT = {k: index(v) for k, v in D["filtered"].items()}
    common = shared(F["plain"], F["compacted"], F["state_actor"])
    commonf = shared(FT["plain"], FT["drained"], FT["compacted"],
                     FT["compacted_rep"], FT["state_actor"])

    # Every workload exists twice: once doing the account-state work, and once as an
    # overhead_baseline control that runs the same loop and deliberately touches no state.
    DARK = ("EXISTING_CONTRACT_DIFF_MAX", "EXISTING_CONTRACT_JUMPDEST")
    meas = [c for c in common if not c[4]]
    ctrls = [c for c in common if c[4]]
    measf = [c for c in commonf if not c[4]]
    ctrlsf = [c for c in commonf if c[4]]
    assert meas and ctrls and measf and ctrlsf, "measurement/control split came out empty"

    # ---- class + duration, fixed once from the reference (compacted) arm of the final
    # comparison. wall_ns is Besu's own measured wall-clock time; collect_besu.py defines
    # mgas_s as gas_used / (wall_ns / 1e9) / 1e6, so gas_used / (mgas_s * 1e6) is the same
    # number by construction and wall_ns is used directly rather than re-derived.
    def cls(c):
        if c[1] == "NON_EXISTING_ACCOUNT":
            return "absent"
        return "dark" if c[1] in DARK else "light"

    def ge1s(c):
        return F["compacted"][c]["wall_ns"] >= 1e9

    absent_ge = [c for c in meas if cls(c) == "absent" and ge1s(c)]
    absent_lt = [c for c in meas if cls(c) == "absent" and not ge1s(c)]
    light_ge = [c for c in meas if cls(c) == "light" and ge1s(c)]
    # The #141 re-run covered three budgets only; the distinct-code row uses those tests in both
    # tables so its before and after share a population.
    V4_BUDGETS = D["status"]["v4"]["budgets"]
    dark_all = [c for c in meas if cls(c) == "dark"]
    dark_ge = [c for c in dark_all if ge1s(c) and c[2] in V4_BUDGETS]
    assert not [c for c in meas if cls(c) == "light" and not ge1s(c)], \
        "a shared-or-absent-code test is sub-second on the reference arm"
    assert not [c for c in meas if cls(c) == "dark" and not ge1s(c)], \
        "a distinct-code test is sub-second on the reference arm"
    assert all(not ge1s(c) for c in ctrls), "a control test is over a second on the reference arm"

    sub_per_arm = {arm: sum(1 for c in meas if F[arm][c]["wall_ns"] < 1e9)
                   for arm in ("plain", "compacted", "state_actor")}
    assert 29 <= sub_per_arm["compacted"] <= 37 and 29 <= sub_per_arm["plain"] <= 37, \
        f"snapshot-arm sub-second counts drifted: {sub_per_arm}"
    assert sub_per_arm["state_actor"] == 4, \
        f"generated-store sub-second count drifted: {sub_per_arm['state_actor']}"

    def sac(tests):
        return median([F["state_actor"][c]["mgas_s"] / F["compacted"][c]["mgas_s"] for c in tests])

    def sap(tests):
        return median([F["state_actor"][c]["mgas_s"] / F["plain"][c]["mgas_s"] for c in tests])

    ROWSPEC = [
        ("absent", "ge", absent_ge, "absent account"),
        ("light", "ge", light_ge, "shared or no code"),
        ("dark", "ge", dark_ge, "distinct code"),
        ("absent", "lt", absent_lt, "absent account"),
        ("control", "lt", ctrls, "control (no state work)"),
    ]
    base_rows = [dict(cls=c_, dur=d_, label=lbl, n=len(tests), tests=tests, sap=sap(tests), sac=sac(tests))
                 for c_, d_, tests, lbl in ROWSPEC]
    assert base_rows[0]["n"] + base_rows[3]["n"] == 110, \
        "the over/under-a-second absent split no longer covers the archived absence population"

    # The title carries the largest gap against the snapshot as published, the same rule as
    # the Nethermind page: distinct-contract code over all its tests. Absence, the gap with a
    # single cause, is quoted beside it.
    headline = 1 / base_rows[0]["sap"]
    dark_factor = 1 / sap(dark_all)
    assert headline > 1 and dark_factor > 1, "a headline factor is not actually a slowdown"
    assert dark_factor > max(headline, 1 / base_rows[1]["sap"]), \
        "distinct-contract code is no longer the largest gap; the title and lede order are wrong"
    factor = round(dark_factor)

    # The final table's rows and populations must match the baseline table's exactly. Both
    # are built from base_rows; FINAL supplies only the value column. Every class the final
    # arm split by duration reads a real per-duration number; the one it never split (absent
    # never got a separate sub-second re-run) is marked pooled, and this is the only cell
    # that is. A future per-test v3/v4 re-run only has to change this one dict entry.
    ST = D["status"]
    PR = {p["n"]: p for p in ST["prs"]}
    V3 = ST["v3"]
    V4 = ST.get("v4")
    V4CAT = {(r[1], r[2]): r[5] for r in V4["categories"]} if V4 else {}
    FINAL = {
        ("absent", "ge"): (V3["classes"]["absent"]["v3"], True),
        ("light", "ge"): (V3["classes"]["light"]["v3"], False),
        ("dark", "ge"): (V4["classes"]["dark"]["v4"] if V4 else V3["classes"]["dark"]["v3"], False),
        ("absent", "lt"): (None, False),
        ("control", "lt"): (V3["control_ratio"], False),
    }
    assert V4["classes"]["dark"]["rows"] == base_rows[2]["n"], \
        "the distinct-code final and baseline rows no longer cover the same tests"
    pooled_keys = [k for k, (_, p) in FINAL.items() if p]
    assert pooled_keys == [("absent", "ge")], \
        f"more than one final cell is pooled across durations: {pooled_keys}"
    assert set(FINAL) == {(r["cls"], r["dur"]) for r in base_rows}, \
        "the final table's rows do not match the baseline table's"

    DAYS_STALE = (datetime.date.fromisoformat(ST["measured_store_built"])
                  - datetime.date.fromisoformat(PR[133]["merged"])).days

    # ---- the WAL/compaction decomposition (finding 1's fix), still bucket-based: the
    # bloom-filter and code-pool findings are per column family, not per class, so the old
    # bucket split (absent / leaf-only / code-reading) stays for these internal checks.
    def ratios(a, b, tests, field="mgas_s"):
        out = collections.defaultdict(list)
        for c in tests:
            out[a[c]["bucket"]].append(b[c][field] / a[c][field])
        return out

    def bucket_median(a, b, tests, field="mgas_s"):
        return {k: median(v) for k, v in ratios(a, b, tests, field).items()}

    def bucket_bytes(a, b, tests):
        num = collections.defaultdict(int)
        den = collections.defaultdict(int)
        for c in tests:
            num[a[c]["bucket"]] += b[c]["disk_read_bytes"]
            den[a[c]["bucket"]] += a[c]["disk_read_bytes"]
        return {k: num[k] / den[k] for k in den if den[k]}

    sa_bytes = bucket_bytes(F["compacted"], F["state_actor"], meas)
    # What fraction of account lookups found nothing, per arm's own counters. The honest
    # aggregate is the ratio of per-test medians, not a sum, so one container's sample
    # cannot dominate another's.
    miss = {}
    for arm in ("compacted", "state_actor"):
        rows = [r for r in D["counters"][arm] if r["mode"] == "NON_EXISTING_ACCOUNT"]
        reads = median([r["reads"] for r in rows])
        missing = median([r["reads_missing"] for r in rows])
        miss[arm] = missing / reads if reads else None
    assert all(0 <= v <= 1.001 for v in miss.values() if v is not None), \
        f"miss ratio out of range: {miss}"

    drain_t = bucket_median(FT["plain"], FT["drained"], measf)
    drain_ctrl = median([FT["drained"][c]["mgas_s"] / FT["plain"][c]["mgas_s"] for c in ctrlsf])
    comp_ctrl = median([FT["compacted"][c]["mgas_s"] / FT["plain"][c]["mgas_s"] for c in ctrlsf])
    noise_t = bucket_median(FT["compacted"], FT["compacted_rep"], measf)
    noise = max(abs(v - 1) for v in noise_t.values())

    def floor(tests):
        r = [FT["compacted_rep"][c]["mgas_s"] / FT["compacted"][c]["mgas_s"] for c in tests]
        return sum(1 for x in r if abs(x - 1) <= 0.10), len(r)
    floor_ge = floor([c for c in commonf if FT["compacted"][c]["wall_ns"] >= 1e9])
    floor_lt = floor([c for c in commonf if FT["compacted"][c]["wall_ns"] < 1e9])
    eoa = [c for c in meas if c[1] == "EXISTING_EOA"]
    eoa_plain_over_comp = median([F["plain"][c]["mgas_s"] / F["compacted"][c]["mgas_s"] for c in eoa])
    eoa_sa_over_comp = median([F["state_actor"][c]["mgas_s"] / F["compacted"][c]["mgas_s"] for c in eoa])
    l0_06 = levels["before"]["06"]["0"]["files"]
    l6_06 = levels["before"]["06"]["6"]["files"]
    l0_06_after = levels["after"]["06"].get("0", {}).get("files", 0)
    e06 = D["entries_by_cf"]["06"]

    BAND = 0.10
    vcats = collections.defaultdict(lambda: ([], []))
    for c in meas:
        vcats[(c[0], c[1])][0].append(F["state_actor"][c]["mgas_s"] / F["plain"][c]["mgas_s"])
        vcats[(c[0], c[1])][1].append(F["state_actor"][c]["mgas_s"] / F["compacted"][c]["mgas_s"])
    verdict = sorted(((F["plain"][next(c for c in meas if (c[0], c[1]) == k)]["bucket"],
                       k[0], k[1], median(b), median(a)) for k, (b, a) in vcats.items()),
                     key=lambda r: r[4])
    inband = lambda v: abs(v - 1) <= BAND
    cat_before = sum(1 for r in verdict if inband(r[3]))
    cat_after = sum(1 for r in verdict if inband(r[4]))
    wl_before = sum(1 for c in meas
                    if inband(F["state_actor"][c]["mgas_s"] / F["plain"][c]["mgas_s"]))
    wl_after = sum(1 for c in meas
                   if inband(F["state_actor"][c]["mgas_s"] / F["compacted"][c]["mgas_s"]))
    dark_cats = [r for r in verdict if r[2] in DARK]
    light_cats = [r for r in verdict if r[0] != "absent" and r[2] not in DARK]
    best_cat = verdict[-1]
    max_row = max(F["state_actor"][c]["mgas_s"] / F["compacted"][c]["mgas_s"] for c in meas)
    n_absent = len({(c[0], c[1]) for c in common if c[1] == "NON_EXISTING_ACCOUNT"})

    def bpg(mode, arm):
        sel = [c for c in meas if c[1] == mode]
        return (sum(F[arm][c]["disk_read_bytes"] for c in sel)
                / sum(F[arm][c]["gas_used"] for c in sel))

    LIGHT_MODES = ("EXISTING_EOA", "EXISTING_CONTRACT_MINIMAL", "EXISTING_CONTRACT_SAME_MAX")
    code_bpg = {}
    for arm in ("compacted", "state_actor"):
        floor = median([bpg(m, arm) for m in LIGHT_MODES])
        code_bpg[arm] = median([bpg(m, arm) for m in DARK]) - floor
    code_bpg["ratio"] = code_bpg["state_actor"] / code_bpg["compacted"]
    CB = D["code_block_sim"]
    AM = D["account_mix"]
    reuse = {}
    for k, store in (("jochemnet", "jochemnet"), ("state_actor", "state_actor")):
        accts = props[store]["06"]["entries"]
        contracts = accts * (100 - AM[k]["eoa_pct"]) / 100
        reuse[k] = {"contracts": contracts, "codes": props[store]["07"]["entries"],
                    "per_code": contracts / props[store]["07"]["entries"]}
    g06j, g06s = props["jochemnet"]["06"], props["state_actor"]["06"]
    comp_ratio = g06s["phys_over_logical"] / g06j["phys_over_logical"]
    blk_ratio = g06s["block_bytes"] / g06j["block_bytes"]

    # ---- oracles ------------------------------------------------------------------------
    for arm in ("plain", "compacted", "state_actor"):
        assert abs(gas_of(F[arm], common) / gas_of(F["plain"], common) - 1) < 1e-6, \
            f"full arms disagree on gas: {arm}"
    for arm in FT:
        if arm == "compacted_alt":
            continue
        assert abs(gas_of(FT[arm], commonf) / gas_of(FT["plain"], commonf) - 1) < 1e-6, \
            f"filtered arms disagree on gas: {arm}"
    assert noise < 0.02, f"same-state repeat is not a noise floor: {noise:.3f}"
    for b in BUCKETS:
        assert abs(drain_t[b] - 1) <= 0.02, f"drain moved {b}: {drain_t[b]:.3f}"
    assert C["after_flush"]["ssts"] == C["after_prerun"]["ssts"], "flush changed the SST count"
    assert C["after_prerun"]["ssts"] - C["shipped"]["ssts"] == 4, "pre-run did not add four SSTs"
    for cf in ("06", "07", "08", "09"):
        assert props["state_actor"][cf]["filter_bytes"] == 0, f"state-actor cf{cf} has a filter"
        assert props["jochemnet"][cf]["filter_bytes"] > 0, f"jochemnet cf{cf} has no filter"
    assert l0_06_after == 0, f"compaction left {l0_06_after} files at the top of cf06"
    for cf, e in D["entries_by_cf"].items():
        assert e["compacted"] < e["plain"], f"cf{cf} lost no entries to the compaction"
    assert cat_before == 0, f"{cat_before} categories were already inside the band"
    assert cat_after == len(light_cats), \
        f"{cat_after} categories inside the band after treatment, expected {len(light_cats)}"
    assert all(inband(r[4]) for r in light_cats), "a code-reusing category missed the band"
    assert not any(inband(r[4]) for r in dark_cats), "a distinct-code category reached the band"
    assert not any(inband(r[4]) for r in verdict if r[0] == "absent"), \
        "an absence category reached the band"
    assert max_row < 1.0, f"a measurement workload is faster than the snapshot: {max_row:.3f}"
    assert best_cat[4] == max(r[4] for r in verdict), "verdict stopped being sorted by ratio"
    assert best_cat[4] < 1.0, \
        f"a category reached parity: {best_cat[1]}/{best_cat[2]} at {best_cat[4]:.3f}"
    assert abs(drain_ctrl - 1) <= 0.05 and abs(comp_ctrl - 1) <= 0.05, \
        f"the treatment moved the control: drain {drain_ctrl:.3f}, compact {comp_ctrl:.3f}"
    assert CB["jochemnet"]["fixture_deflate"] < 0.05 and CB["state_actor"]["fixture_deflate"] < 0.05, \
        "the fixture contracts are no longer near-free to store"
    assert reuse["jochemnet"]["per_code"] > 10 > reuse["state_actor"]["per_code"], \
        "the bytecode-reuse gap the residual rests on has closed"
    assert 1.4 < code_bpg["ratio"] < 2.6, f"code-read ratio moved: {code_bpg['ratio']:.2f}"
    assert g06s["mean_record"] > g06j["mean_record"] and comp_ratio > 1 and blk_ratio > 1, \
        "cf06 geometry chain no longer runs in the direction the prose states"
    assert V3["fail"] == 0 and V3["success"] > 0, f"the v3 arm had {V3['fail']} failing executions"
    assert V3["measurement"] == len(meas) and V3["control"] == len(ctrls), \
        "the v3 arm is not the same grid as the original"
    assert V3["classes"]["absent"]["v3"] > 0.95, "the absence class did not reach parity"
    assert V3["classes"]["dark"]["v3"] > 1.0, "the distinct-code class did not invert"
    assert V3["classes"]["light"]["v3"] > V3["classes"]["light"]["archived"], \
        "the shared-code class did not improve"
    if V4:
        assert V4["pr"] == 141 and V4["sha"] == "9b23eea", "v4 provenance drifted"
        assert V4["classes"]["dark"]["v3"] == V3["classes"]["dark"]["v3"], "v4 lost the v3 reference"
        PD = V4["paired"]
        assert PD["device_byte_factor"] > 2, \
            "the two media no longer disagree on bytes, so the caveat can go"
        assert (all(abs(c[4] - 1) <= PD["band"] for c in PD["categories"])
                and PD["inband"] == PD["measurement"]), \
            "a paired category left the band, so the parity sentence must change"
        assert PD["median"] < V4["classes"]["dark"]["v4"], \
            "the two media no longer disagree, so the unresolved framing must change"

    # The claims the rewrite's prose adds: Besu's short tests reproduce, the pre-run was the
    # whole EOA difference, the v3 store carries #133, and each class's final lands where part 3
    # puts it.
    assert floor_lt[0] >= 0.9 * floor_lt[1] and floor_ge[0] >= 0.95 * floor_ge[1], \
        f"the compacted snapshot no longer reproduces against itself: {floor_lt} {floor_ge}"
    assert eoa_plain_over_comp > 3 and abs(eoa_sa_over_comp - 1) < 0.1, \
        f"the pre-run is no longer the whole EOA difference: {eoa_plain_over_comp:.2f} {eoa_sa_over_comp:.3f}"
    assert PR[138]["sha"] in V3["store"] and PR[138]["merged"] > PR[133]["merged"], \
        "the v3 store no longer post-dates the filter fix"
    assert V3["classes"]["light"]["v3"] < 1 and abs(V3["classes"]["light"]["v3"] - 1) < BAND, \
        "the shared-code class left the band or crossed parity"
    assert V4["classes"]["dark"]["v4"] > 1 + BAND, "distinct code is no longer outside the band on the fast side"
    assert abs(V3["control_ratio"] - V3["control_archived"]) < 0.01, "the control drifted between stores"
    assert V4["categories_closer"] == V4["classes"]["dark"]["categories"], "a distinct-code category moved away from parity"

    existing_residual = 1 - median(
        [F["state_actor"][c]["mgas_s"] / F["compacted"][c]["mgas_s"]
         for c in meas if c[1] != "NON_EXISTING_ACCOUNT"])
    assert existing_residual * 100 < GREF["residual_median_pct"] and \
        min(sa_bytes["leaf-only"], sa_bytes["code-reading"]) > GREF["bytes_ratio"], \
        "Besu no longer pays less per extra byte than geth"

    pc = lambda r: f"{abs(1 - r) * 100:.1f}%"

    # ---- figures --------------------------------------------------------------------------
    figs = {
        "overview": (chart_overview(base_rows, F),
                     f"The benchmark as published: every test against the snapshot as it "
                     f"ships, one dot per test, the tick at the class median. Every class that "
                     f"reads state sits between {min(r['sap'] for r in base_rows[:3]):.2f} and "
                     f"{max(r['sap'] for r in base_rows[:3]):.2f}; the controls sit on "
                     f"parity."),
        "lsm_levels": (chart_lsm_levels(levels),
                       f"Where the pre-run's rows sit. After the pre-run, cf06 holds "
                       f"{l0_06} files at the top of the tree against {l6_06} at the bottom; "
                       "after compaction the top is empty."),
        "verdict": (chart_verdict(verdict, BAND),
                    f"The same {len(verdict)} categories, each measured against the snapshot "
                    f"as published and then against the same snapshot compacted. "
                    f"{cat_after} of {len(verdict)} land inside &plusmn;{BAND*100:.0f}% of "
                    f"parity; the {n_absent} absence categories and the {len(dark_cats)} "
                    f"distinct-code ones do not."),
        "bloom": (chart_bloom(props, sa_bytes),
                  "The snapshot carries a bloom filter on every state column family and the "
                  "generated store carries none. Without one, a lookup that will find nothing "
                  "can't be turned away early and has to read index and data blocks."),
        "cost_curves": (chart_cost_curves(F, meas),
                        f"Existing-EOA tests across the gas budget, median over opcodes. The "
                        f"snapshot as published runs {eoa_plain_over_comp:.1f}&times; ahead of "
                        f"the same snapshot compacted, and the compacted one lands within "
                        f"{pc(eoa_sa_over_comp)} of the generated store. On these tests the "
                        f"pre-run's placement was the whole difference."),
        "geometry": (chart_geometry(props, GREF),
                     "Record size, compression and block size, generated store against the "
                     "compacted snapshot. Geth's two ratios, measured on a different engine, "
                     "are printed for comparison."),
        "outcome": (chart_outcome(V3["categories"], BAND, V4CAT),
                    f"The same {len(V3['categories'])} categories before the three fixes and "
                    f"after them. Two mechanisms pull their categories into the band; the "
                    f"sixteen that read a distinct contract went straight through it under "
                    f"#{PR[138]['n']}, to {V3['classes']['dark']['v3']:.3f}&times;, and sit at "
                    + (f"{V4['classes']['dark']['v4']:.3f}&times; on the store built from "
                       f"#{V4['pr']}, the third dot on those rows." if V4 else
                       "that level; the corpus-pool rerun is not yet in this build.")),
    }
    for name, (s, _) in figs.items():
        assert "NaN" not in s and "inf" not in s, f"{name}: non-finite geometry"

    os.makedirs(FIGS, exist_ok=True)
    for old in os.listdir(FIGS):
        if old.endswith(".svg"):
            os.remove(os.path.join(FIGS, old))
    for name, (s, _) in figs.items():
        with open(os.path.join(FIGS, f"fig_{name}.svg"), "w") as fh:
            fh.write(standalone_svg(s) + "\n")

    def fig(name):
        s, cap = figs[name]
        return figure(s, cap)

    # ---- prose ------------------------------------------------------------
    o = []
    w = o.append

    title = f"How can two Besu databases holding the same state differ {factor}\u00d7?"
    meta = (f"A Besu mainnet snapshot and a generated store run the same EEST benchmarks and "
            f"disagree by up to {factor}x. Three findings, all about how the stores were built, "
            "account for it; distinct-contract code still overshoots, by an amount that depends "
            "on the disk.")
    assert f"{factor}\u00d7" in title, "the title's factor drifted from the computed headline"

    w("<!doctype html><html lang=en><head><meta charset=utf-8>")
    w('<meta name=viewport content="width=device-width,initial-scale=1">')
    w(f'<meta name="description" content="{esc(meta)}">')
    w('<link rel="preconnect" href="https://fonts.googleapis.com">'
      '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
      '<link href="https://fonts.googleapis.com/css2?family=VT323&'
      'family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&display=swap" '
      'rel="stylesheet">')
    w(f"<title>{title}</title>")
    w(f"<style>{CSS}</style></head><body>")

    w('<div class=topbar><a href="../">&larr; all articles</a>'
      '<span>EXECUTION &middot; STATE DB</span></div>')
    w('<div class=eyebrow>// REPORT</div>')
    w(f"<h1>How can two Besu databases holding the same state differ {factor}&times;?</h1>")
    w(f"<p class=deck>We ran the same EEST benchmarks against a Besu mainnet snapshot and a "
      f"store that state-actor generated from scratch. On calls into a different contract "
      f"every time, the generated store came out {dark_factor:.1f}&times; slower; on tests that "
      f"look up accounts that don't exist, {headline:.1f}&times;. Three things about how the "
      f"stores were built made the gap. Fixed, absence lands at parity and shared code within "
      f"{pc(V3['classes']['light']['v3'])}. Distinct-contract code overshoots, and how far "
      f"depends on the disk. Here's each finding, what it did, and what's left.</p>")
    w('<div class=meta><span class=tag>Ethereum &middot; Besu &middot; Bonsai &middot; RocksDB '
      '&middot; benchmarking</span> &middot; 2026 &middot; <a href="https://github.com/CPerezz/'
      'articles/tree/main/besu-state-db-divergence">reproducible pipeline &amp; data '
      '&rarr;</a></div>')
    w('<!--TOC-->')

    w("<div class=legend>")
    for lbl, var, txt in (("plain", "--db-c", ARM_DOC["plain"]),
                          ("compacted", "--db-u", ARM_DOC["compacted"]),
                          ("state-actor", "--db-sa", ARM_DOC["state_actor"])):
        w(f'<span><i class=sw style="background:var({var})"></i><b>{lbl}</b> {esc(txt)}</span>')
    w("</div>")
    w(f'<p class=note>{P["chain"]} block {thousands(P["block"])}, chain id {P["chain_id"]}. '
      f'Snapshot published by <code>{esc(P["snapshot_producer"])}</code> under '
      f'<code>--sync-mode={P["snapshot_sync_mode"]}</code>; benchmarked with '
      f'<code>{esc(P["benchmark_client"])}</code> under '
      f'<code>--sync-mode={P["benchmark_sync_mode"]}</code>, storage format '
      f'{P["storage_format"]}. Every arm ran on one host, from the same NVMe array.</p>')
    w(f"<p class=note>Both stores run byte-identical RocksDB settings on every state column "
      f"family: <code>compression={P['compression']}</code>, "
      f"<code>block_size={thousands(P['block_size'])}</code>. Account reads go through "
      f"Bonsai's flat keyspace on both, {P['flat_read_share']*100:.2f}% of lookups served "
      f"from it rather than a trie walk, so what a read costs is the cost of locating one "
      f"key in one column family, not the depth of a tree.</p>")
    w("<p class=note>Every ratio on this page is state-actor's throughput divided by a "
      "reference, taken as the median across whatever tests share a row. Above 1&times; "
      "means the generated store is faster; below means it's slower. We use medians rather "
      "than a pooled average everywhere, because a handful of huge reads shouldn't get to "
      "decide what a typical one costs.</p>")

    # ===================================================================== part 1
    w(f"<h2>The problem: the same state, {factor}&times; apart</h2>")
    w(fig("overview"))
    w(f"<p>Three databases hold the same state: the published mainnet snapshot as it ships, "
      f"the same snapshot compacted, and state-actor's generated companion. The same "
      f"{thousands(len(common))} EEST tests run against each of them, on the same host and "
      f"the same drive. Gas is identical to six figures, so all three were asked to do the "
      f"same work. Throughput isn't the same at all.</p>")
    w(f"<p>On the tests that call a different contract every time, the generated store is "
      f"<b>{dark_factor:.1f}&times; slower</b> than the snapshot as published. On the tests that "
      f"look up an account which isn't there it's {headline:.1f}&times;. Neither is a "
      f"client bug. Each is an artifact of how the stores were built, and each has a name "
      f"below.</p>")
    w("<p>Compacted just means flushed and fully merged, RocksDB's own maintenance "
      "operation, nothing client-specific. We measure the generated store against both the "
      "snapshot as published and the same snapshot compacted, because the two don't agree "
      "with each other either, and that disagreement is the first finding below.</p>")
    w("<table><tr><th>class</th><th>duration</th><th class=n>n</th>"
      "<th class=n>state-actor &divide; plain</th><th class=n>state-actor &divide; compacted</th>"
      "</tr>")
    prev_dur = None
    for r in base_rows:
        if prev_dur is not None and r["dur"] != prev_dur:
            label = "under a second" if r["dur"] == "lt" else "over a second"
            w(f"<tr><td colspan=5><b>{label}</b></td></tr>")
        elif prev_dur is None:
            w("<tr><td colspan=5><b>over a second</b></td></tr>")
        w(f"<tr><td>{esc(r['label'])}</td><td>{'&ge;1s' if r['dur']=='ge' else '&lt;1s'}</td>"
          f"<td class=n>{r['n']}</td><td class=n>{r['sap']:.3f}</td>"
          f"<td class=n>{r['sac']:.3f}</td></tr>")
        prev_dur = r["dur"]
    w(f"<caption>Median throughput ratio per class. Absent: the lookup must prove an account "
      f"isn't there. Shared or no code: the callee is an EOA, a minimal contract or one reused "
      f"contract. Distinct code: every access loads a different contract, here at the "
      f"{'/'.join(str(g) for g in V4_BUDGETS)}M budgets the final store was measured at. The "
      f"final table in &ldquo;Where it stands&rdquo; has the same rows and tests.</caption></table>")
    w(f"<p><b>Two kinds of test.</b> Every test boots a fresh client, so a test that runs for a "
      f"tenth of a second measures a young process. The companion <a href=\"../nethermind-state-db-divergence/nethermind-state-db-report.html\">Nethermind study</a> splits every "
      f"view at one second of measured time, and we do the same here, with each test's class "
      f"fixed once from the compacted arm. On Besu the split matters less. Of the "
      f"{thousands(len(meas))} measurement tests only {sub_per_arm['compacted']} run under a "
      f"second on the compacted snapshot, all of them absence tests, so the short class is "
      f"essentially the {thousands(len(ctrls))} controls. And Besu's short tests reproduce: "
      f"measured twice, the compacted snapshot lands {floor_lt[0]} of its {floor_lt[1]} "
      f"sub-second tests inside &plusmn;10% of itself, and {floor_ge[0]} of {floor_ge[1]} over a "
      f"second. We still show the short rows separately and keep the headline to tests over a "
      f"second, so the two pages read the same way.</p>")

    # ===================================================================== finding 1
    w("<h2>Finding 1: the pre-run's rows were the newest versions of their keys</h2>")
    w(fig("lsm_levels"))
    w("<p>The benchmark's fixtures touch specific accounts that have to exist first. "
      "State-actor bakes them straight into the state it generates, so it needs nothing "
      "extra. The snapshot is real historical mainnet state, and it doesn't contain the "
      "benchmark's own fixture accounts, so the harness has to create them by replaying a "
      "pre-run of setup blocks before the measured test ever runs.</p>")
    w(f"<p>That bundle is {D['prerun_bundle_bytes']/1e9:.2f} GB of blocks. It's not a big "
      f"change in file count, only {thousands(C['after_prerun']['ssts'])} SST files against "
      f"{thousands(C['shipped']['ssts'])} shipped. But it's the newest four files, and every "
      f"account the benchmark reads now has its newest version in one of them.</p>")
    w(f"<p>That's why the lookup is fast on the untreated snapshot. A point lookup checks the "
      f"youngest files first and stops at the first version it finds. After the pre-run, cf06 "
      f"holds just {l0_06} files at the top of its tree, against {l6_06} at the bottom. A "
      f"lookup for a recently written account never has to go further than the top.</p>")
    w(f"<p><b>The fix</b> is one full-range compaction of the promoted image, "
      f"{C['after_compact']['seconds']/60:.0f} minutes, with the client's own table options. "
      f"No value changes; only which file holds each key's newest copy does. Merging the "
      f"levels removes {thousands(e06['plain'] - e06['compacted'])} entries from cf06 alone, "
      f"{e06['plain']:,} down to {e06['compacted']:,}. Storage drops "
      f"{thousands(D['entries_by_cf']['08']['plain'] - D['entries_by_cf']['08']['compacted'])} "
      f"entries and trie-branch "
      f"{thousands(D['entries_by_cf']['09']['plain'] - D['entries_by_cf']['09']['compacted'])}, "
      f"the same pattern in every state column.</p>")
    w(f"<p>A store holding one version per key can't lose entries to a compaction, so these "
      f"were obsolete copies the pre-run had shadowed. Draining the write-ahead log first "
      f"changes nothing at all; every bucket ratio stays within "
      f"{max(abs(v-1) for v in drain_t.values())*100:.1f}% of 1. Compaction does all the "
      f"work.</p>")
    w(fig("cost_curves"))
    w(f"<p><b>What it did:</b> against the snapshot as published, "
      f"<b>{cat_before} of {len(verdict)}</b> categories were inside &plusmn;{BAND*100:.0f}% of "
      f"parity. Against the compacted one, <b>{cat_after} of {len(verdict)}</b> are, and the "
      f"share of individual tests inside the band goes from {100*wl_before/len(meas):.0f}% to "
      f"{100*wl_after/len(meas):.0f}%. Every category still reads below 1; the closest is "
      f"{best_cat[1]} {SHORT_MODE[best_cat[2]]} at {best_cat[4]:.3f}&times;. The control, which "
      f"the treatment must not move, sits at {drain_ctrl:.3f} drained and {comp_ctrl:.3f} "
      f"compacted. What clears the band is every category whose callee has no code or shares "
      f"it. The {n_absent} absence categories and the {len(dark_cats)} distinct-code ones "
      f"don't, and each has its own cause below.</p>")
    w(fig("verdict"))

    # ===================================================================== finding 2
    w("<h2>Finding 2: the generated store carries no bloom filters</h2>")
    w(fig("bloom"))
    w(f"<p>Every state column family in the compacted snapshot carries a bloom filter, "
      f"{ST['filters']['bits_per_key']:.0f} bits/key, "
      f"{sum(props['jochemnet'][cf]['filter_bytes'] for cf in ('06','07','08','09'))/1e9:.2f} "
      f"GB of them across the four state column families. The generated store's carry none "
      f"at all. A filter answers &ldquo;this file cannot contain that key&rdquo; without "
      f"reading it. Without one, a lookup that will find nothing still has to read index and "
      f"data blocks to reach the same conclusion.</p>")
    w(f"<p>The cost lands almost entirely on absence, because that's the one class where the "
      f"filter would have paid for itself: <b>{sa_bytes['absent']:.0f}&times;</b> the bytes, "
      f"against just {sa_bytes['leaf-only']:.2f}&times; and "
      f"{sa_bytes['code-reading']:.2f}&times; on reads that find their key. A read that "
      f"finds its key was going to touch that block anyway; a read that finds nothing didn't "
      f"have to, and does.</p>")
    w(f"<p>It isn't that one store finds more absent accounts than the other. Besu's own "
      f"counters put the miss rate at {miss['compacted']:.3f} on the compacted snapshot and "
      f"{miss['state_actor']:.3f} on the generated store: near-identical, both close to "
      f"certain. Same question, same answer, and {sa_bytes['absent']:.1f}&times; the bytes "
      f"to arrive at it.</p>")
    w(f"<p><b>The fix</b> was already merged upstream before this store existed: "
      f"<a href=\"https://github.com/ethereum/state-actor/pull/{PR[133]['n']}\">"
      f"state-actor#{PR[133]['n']}</a> ({PR[133]['sha']}), merged {PR[133]['merged']}. The "
      f"store measured here was generated {DAYS_STALE} days earlier, from a working tree "
      f"that predates it. So the {sa_bytes['absent']:.0f}&times; is real, it's reproducible "
      f"from the archived store, and it's our own doing. <b>What it did:</b> on a store "
      f"regenerated at a revision that carries it, the absence class went from "
      f"{base_rows[0]['sac']:.3f} to {V3['classes']['absent']['v3']:.3f}. That store also "
      f"carries the code-pool change of Finding 3, which doesn't touch absent accounts.</p>")

    # ===================================================================== finding 3
    w("<h2>Finding 3: a contract's code shares its data block with its neighbours</h2>")
    w(fig("geometry"))
    w(f"<p>Mainnet reuses each bytecode about {reuse['jochemnet']['per_code']:.0f} times: its "
      f"code column holds {thousands(reuse['jochemnet']['codes'])} distinct bytecodes behind "
      f"roughly {thousands(round(reuse['jochemnet']['contracts']))} contract accounts. The "
      f"generated store held {thousands(reuse['state_actor']['codes'])} behind "
      f"{thousands(round(reuse['state_actor']['contracts']))}, almost one each. So a block on "
      f"the generated store holds {CB['state_actor']['tenants']:.0f} distinct small records "
      f"against mainnet's {CB['jochemnet']['tenants']:.1f}, and none of them compress against "
      f"each other: cf06 records compress {comp_ratio:.3f}&times; worse and blocks run "
      f"{blk_ratio:.3f}&times; bigger, close to <a href=\"../state-db-perf-divergence/state-db-perf-report.html\">geth's</a> {GREF['compression_ratio']:.3f} and "
      f"{GREF['block_size_ratio']:.3f} on a different engine.</p>")
    w(f"<p>A code read pays for whatever shares its block. One cold read of the same fixture "
      f"contract, page cache dropped first, moves {thousands(ST['code_read']['sa_bytes'])} bytes "
      f"off disk on the generated store against {thousands(ST['code_read']['snap_bytes'])} on "
      f"the snapshot. Isolated from the account row it rides with, the code read costs "
      f"{code_bpg['state_actor']:.1f} extra bytes per gas on the generated store against "
      f"{code_bpg['compacted']:.1f}, <b>{code_bpg['ratio']:.2f}&times;</b>.</p>")
    w(f"<p><b>The first fix overshot.</b> "
      f"<a href=\"https://github.com/ethereum/state-actor/pull/{PR[137]['n']}\">#{PR[137]['n']}</a> "
      f"and <a href=\"https://github.com/ethereum/state-actor/pull/{PR[138]['n']}\">"
      f"#{PR[138]['n']}</a> made contracts share bytecode from a fixed pool, but the pool was "
      f"one runtime, tiled, and it compresses far better than real code. On a store built from "
      f"it the distinct-code class went from {V3['classes']['dark']['archived']:.3f} to "
      f"<b>{V3['classes']['dark']['v3']:.3f}</b>, past parity the other way. A store that's too "
      f"fast is as wrong as one that's too slow; it just doesn't look broken.</p>")
    w(fig("outcome"))
    excess_cut = (V3['classes']['dark']['v3'] - V4['classes']['dark']['v4']) / (V3['classes']['dark']['v3'] - 1)
    w(f"<p><b>The fix</b> is a pool of {V4['corpus_contracts']} real mainnet contracts, "
      f"<a href=\"https://github.com/ethereum/state-actor/pull/{V4['pr']}\">"
      f"state-actor#{V4['pr']}</a>. <b>What it did:</b> the class moved to "
      f"<b>{V4['classes']['dark']['v4']:.3f}</b>, a {100*excess_cut:.0f}% cut in the overshoot "
      f"but still outside the band on the fast side, and all {V4['categories_closer']} "
      f"distinct-code categories moved toward parity. Throughput follows bytes at every budget: "
      f"{V4['gradient']['dark'][0]:.3f}&times; at {V4['gradient']['gas'][0]}M gas on "
      f"{V4['disk']['v4_over_mainnet'][0]:.2f} of the snapshot's bytes, "
      f"{V4['gradient']['dark'][-1]:.3f} on {V4['disk']['v4_over_mainnet'][-1]:.2f} at "
      f"{V4['gradient']['gas'][-1]}M.</p>")
    w("<p class=note>Also found and fixed, and moving nothing: the generator's closing compaction "
      "left every bottom-level file with a non-zero sequence number, so the client rewrote the "
      "store on every restart "
      "(<a href=\"https://github.com/ethereum/state-actor/pull/139\">state-actor#139</a>). The "
      "dead ends and the probes we had to redo are in the "
      "<a href=\"https://github.com/CPerezz/articles/tree/main/"
      "besu-state-db-divergence#method-and-errata\">README</a>.</p>")

    # ===================================================================== part 3
    w("<h2>Where it stands</h2>")
    w("<table><tr><th>class</th><th>duration</th><th class=n>n</th>"
      "<th class=n>before</th><th class=n>final</th></tr>")
    prev_dur = None
    for r in base_rows:
        if prev_dur is not None and r["dur"] != prev_dur:
            label = "under a second" if r["dur"] == "lt" else "over a second"
            w(f"<tr><td colspan=5><b>{label}</b></td></tr>")
        elif prev_dur is None:
            w("<tr><td colspan=5><b>over a second</b></td></tr>")
        v, pooled = FINAL[(r["cls"], r["dur"])]
        cell = (fnum(v, 3) + "&times;&dagger;" if pooled else
                fnum(v, 3) + "&times;" if v is not None else "not split")
        w(f"<tr><td>{esc(r['label'])}</td><td>{'&ge;1s' if r['dur']=='ge' else '&lt;1s'}</td>"
          f"<td class=n>{r['n']}</td><td class=n>{r['sac']:.3f}&times;</td>"
          f"<td class=n>{cell}</td></tr>")
        prev_dur = r["dur"]
    w(f"<caption>state-actor &divide; compacted snapshot, before the two generator fixes "
      f"(Findings 2 and 3) and after. Finding 1 lives in the reference, so it's in both columns. "
      f"Same rows and tests as the first table. "
      f"&dagger; The final absence arm is stored only as one median over all "
      f"{V3['classes']['absent']['rows']} absence tests, so this cell can't be split by "
      f"duration.</caption></table>")
    w(f"<p>Absence is at parity: {V3['classes']['absent']['v3']:.3f} against "
      f"{V3['classes']['absent']['archived']:.3f} before, both over every absence test. Tests "
      f"whose callee has no "
      f"code or shares it moved from {V3['classes']['light']['archived']:.3f} to "
      f"{V3['classes']['light']['v3']:.3f}, inside the band and "
      f"{pc(V3['classes']['light']['v3'])} short of parity, and we don't have a mechanism for "
      f"that last bit. Distinct code went past parity: {V4['classes']['dark']['v4']:.3f}, "
      f"faster than the snapshot and outside the band on the fast side. The control, which "
      f"does no account-state work, held at {V3['control_ratio']:.3f} against "
      f"{V3['control_archived']:.3f} before, so the harness didn't drift under us.</p>")
    PD = V4["paired"]
    w(f"<p><b>One caveat, and it's unresolved.</b> The same generated store, same method, same "
      f"tests, reads {PD['same_store_bytes_nvme_gb']:.2f} GB per test on NVMe and "
      f"{PD['same_store_bytes_hdd_gb']:.2f} GB on the HDD array, {PD['device_byte_factor']:.1f}"
      f"&times; apart. Paired against a reference rebuilt on the same array, the distinct-code "
      f"class reads <b>{PD['median']:.3f}</b>, {PD['inband']} of {PD['measurement']} "
      f"categories inside the band, against <b>{V4['classes']['dark']['v4']:.3f}</b> on NVMe. "
      f"We can't yet say which number belongs to the store and which to the disk. The table "
      f"quotes NVMe because that's what a node runs on.</p>")

    # ===================================================================== part 4
    w("<h2>What's left, and why</h2>")
    w("<ul class=tight>")
    w(f"<li><b>Which medium the distinct-code number belongs to.</b> "
      f"{V4['classes']['dark']['v4']:.3f} on NVMe, {PD['median']:.3f} on the same-array pair. A "
      f"sequential pair with both stores on NVMe answers it: the "
      f"{thousands(PD['reference']['bytes_gb'])} GB reference and the {V4['store_gb']} GB "
      f"generated store on one drive.</li>")
    w("<li><b>Absence and shared code haven't been re-run against a same-disk reference.</b> "
      "The paired run covered only the distinct-code class. The other two still divide by the "
      "archived compacted arm on NVMe, whose bytes per test we can't yet pin to a medium. The "
      "same paired run would settle all three.</li>")
    w(f"<li><b>Besu pays less per extra byte than geth.</b> Before the code fixes, tests on "
      f"existing accounts ran {existing_residual*100:.1f}% slower than the compacted snapshot; "
      f"the <a href=\"../state-db-perf-divergence/state-db-perf-report.html\">geth study</a> measured {GREF['residual_median_pct']:.1f}% on its own pair. Yet Besu "
      f"read more extra bytes for it, {sa_bytes['leaf-only']:.2f}&times; to "
      f"{sa_bytes['code-reading']:.2f}&times; against geth's {GREF['bytes_ratio']:.3f}&times;. "
      f"Same sign and same mechanism on a different engine; why the cost per byte differs is "
      f"open.</li>")
    w("</ul>")
    w("<p class=note>Every number on this page is computed from the collected run data when "
      "the page is built, and the build fails if the data stops supporting a sentence. The "
      "process history, the dead ends, and the probe bugs we found and fixed along the way "
      "live in the README, not here.</p>")

    w('<div class=endbar><a href="../">&larr; all articles</a>'
      '<a href="https://github.com/CPerezz/articles/tree/main/besu-state-db-divergence">'
      'source &amp; data</a></div>')
    w('<span class=cursor style="position:fixed;bottom:1.4rem;right:1.4rem;z-index:6"></span>')
    w("</body></html>")

    doc = add_toc("\n".join(o))
    for bad in ("\u2014", "\u2013", "&mdash;", "&ndash;"):
        assert bad not in doc, f"dash in the emitted page: {bad!r}"
    with open(OUT, "w") as fh:
        fh.write(doc)
    print(f"wrote {os.path.relpath(OUT, HERE)} ({os.path.getsize(OUT)} bytes), "
          f"{len(figs)} figures")


if __name__ == "__main__":
    main()
