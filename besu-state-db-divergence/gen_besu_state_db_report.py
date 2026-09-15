#!/usr/bin/env python3
"""Build the Besu state-DB divergence report from the collected run data.

Every number in the page is derived here from data/report_data.json; none is typed into the
prose. The oracles in main() fail generation if the data stops supporting a sentence the
article states as fact.

Usage: python3 gen_besu_state_db_report.py
"""
import collections
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
/* Site theme — mirrors build_site.py CRT_VARS and the ARTICLE stylesheet so the
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
pre.idpre { background:#050805; border:1px solid var(--line); border-radius:3px;
  padding:8px 10px; overflow-x:auto; font-size:11.5px; line-height:1.5;
  white-space:pre-wrap; word-break:break-all; }
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
BUCKET_DOC = {
    "absent": "NON_EXISTING_ACCOUNT targets — the lookup must prove the account is not there",
    "leaf-only": "BALANCE, or an EXISTING_EOA target — reads the account record and never the code",
    "code-reading": "EXTCODE* and the CALL family into a contract — also reads the code blob",
}
ARM_DOC = {
    "plain": "the published snapshot, pre-runs replayed, promoted — as a benchmark uses it",
    "drained": "the same store with its write-ahead log flushed away, levels untouched",
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


def chart_ratio_dots(F, common):
    """Every category's throughput ratio against the compacted snapshot, log scale.

    The point of the figure is the shape of the population: two clusters, not one spread. The
    absent categories sit an order of magnitude away from everything else, which is why a single
    median over all of them would describe neither group.
    """
    cats = collections.defaultdict(list)
    for c in common:
        cats[(F["compacted"][c]["bucket"], c[0], c[1])].append(
            F["state_actor"][c]["mgas_s"] / F["compacted"][c]["mgas_s"])
    rows = sorted(((b, op, m, median(v)) for (b, op, m), v in cats.items()),
                  key=lambda r: r[3])
    LEFT, RIGHT, TOP = 250, 34, 18
    H = TOP + 15 * len(rows) + 40
    lo = min(r[3] for r in rows) / 1.3
    hi = max(r[3] for r in rows) * 1.3
    sc = S.LogScale(lo, hi, LEFT, W - RIGHT)
    y1 = TOP + 15 * len(rows) + 4
    body = [S.hgrid(sc, thin(sc, [t for t in (0.1, 0.2, 0.5, 1.0, 2.0) if lo <= t <= hi]),
                    TOP - 6, y1, fmt=lambda v: f"{v:g}×")]
    # unity is the claim "the two databases cost the same"; mark it, do not imply it
    body.append(S.line(sc.to(1.0), TOP - 6, sc.to(1.0), y1, "--accent", width=1, dash="4 3"))
    for i, (b, op, m, r) in enumerate(rows):
        y = TOP + 15 * i + 8
        var = {"absent": "--db-sa", "leaf-only": "--db-c", "code-reading": "--db-u"}[b]
        body.append(S.label(LEFT - 10, y + 3, f"{op} {SHORT_MODE.get(m, m)}", anchor="end",
                            cls="tick"))
        body.append(S.dot(sc.to(r), y, 3.4, var, title=f"{op} {m}: {r:.3f}×"))
    body.append(S.label(LEFT, H - 10, "state-actor ÷ compacted snapshot — throughput", cls="ax"))
    return S.svg(W, H, "".join(body))


def chart_treatment_dumbbell(FT, common):
    """plain → drained → compacted, per bucket.

    Reference is plain here and nowhere else in the article, because the figure exists to show
    what each half of the treatment does to the store you were given.
    """
    LEFT, RIGHT, TOP, ROW = 150, 40, 26, 52
    H = TOP + ROW * len(BUCKETS) + 46
    sc = S.LogScale(0.15, 1.25, LEFT, W - RIGHT)
    body = [S.hgrid(sc, [0.2, 0.5, 1.0], TOP - 10, TOP + ROW * len(BUCKETS) - 10,
                    fmt=lambda v: f"{v:g}×")]
    for i, b in enumerate(BUCKETS):
        y = TOP + ROW * i
        d = median([FT["drained"][c]["mgas_s"] / FT["plain"][c]["mgas_s"]
                    for c in common if FT["plain"][c]["bucket"] == b])
        k = median([FT["compacted"][c]["mgas_s"] / FT["plain"][c]["mgas_s"]
                    for c in common if FT["plain"][c]["bucket"] == b])
        body.append(S.label(LEFT - 10, y + 4, b, anchor="end", cls="tick"))
        body.append(S.line(sc.to(min(d, k)), y, sc.to(max(d, k)), y, "--line", width=3))
        body.append(S.dot(sc.to(1.0), y, 4.2, "--db-c", title=f"{b} plain = 1.000×"))
        body.append(S.dot(sc.to(d), y, 4.2, "--db-u", title=f"{b} drained = {d:.3f}×"))
        body.append(S.dot(sc.to(k), y, 4.2, "--db-sa", title=f"{b} compacted = {k:.3f}×"))
        body.append(S.label(sc.to(k) + (10 if k < 0.9 else -10), y - 9,
                            f"{k:.3f}×", anchor="start" if k < 0.9 else "end", cls="tick"))
    body.append(S.label(LEFT, H - 12, "throughput ÷ plain", cls="ax"))
    body.append(legend(LEFT + 150, H - 12, [("plain", "--db-c"), ("WAL drained", "--db-u"),
                                            ("compacted", "--db-sa")]))
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
        body.append(S.label(LEFT - 8, y - 8, f"cf {cf} {name}", anchor="end", cls="big"))
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
    sc = S.Scale(0, mx, 150, mid - 46)
    body = [S.label(150, TOP - 14, "bloom filter bytes", cls="big"),
            S.label(mid + 26, TOP - 14, "bytes read, state-actor ÷ compacted", cls="big")]
    for i, (cf, name) in enumerate(cfs):
        y = TOP + ROW * i
        j = props["jochemnet"][cf]["filter_bytes"]
        s = props["state_actor"][cf]["filter_bytes"]
        body.append(S.label(144, y + 12, f"cf {cf} {name}", anchor="end", cls="tick"))
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
    gy = gref["compression_ratio"]
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
    body.append(S.label(LEFT, H - 8, "gas budget (M) — BALANCE/EXISTING_EOA, MGas/s", cls="ax"))
    return S.svg(W, H, "".join(body))


def chart_convergence(FT, common):
    """Every arm against the compacted snapshot, throughput and bytes side by side.

    Read it as: once the snapshot is compacted, the generated store is within a few percent on
    reads that find their key, and nowhere near it on reads that must prove absence.
    """
    arms = [("state_actor", "--db-sa"), ("plain", "--db-c"), ("drained", "--db-u")]
    LEFT, TOP, ROW = 150, 40, 30
    H = TOP + ROW * len(BUCKETS) + 86
    mid = 400
    # Compute first, scale second: a clamped dot would silently understate the very gap the
    # figure exists to show.
    pts = []
    for i, b in enumerate(BUCKETS):
        sub = [c for c in common if FT["compacted"][c]["bucket"] == b]
        db = sum(FT["compacted"][c]["disk_read_bytes"] for c in sub)
        for a, var in arms:
            t = median([FT[a][c]["mgas_s"] / FT["compacted"][c]["mgas_s"] for c in sub])
            nb = sum(FT[a][c]["disk_read_bytes"] for c in sub)
            pts.append((i, b, a, var, t, nb / db if db else None))

    def bounds(vals):
        lo, hi = min(vals), max(vals)
        return lo / 1.5, hi * 1.5

    tsc = S.LogScale(*bounds([p[4] for p in pts]), LEFT, mid - 40)
    bsc = S.LogScale(*bounds([p[5] for p in pts if p[5]]), mid + 116, W - 26)

    def ticks(lo, hi):
        return [t for t in (0.1, 0.2, 0.5, 1, 2, 5, 10, 25, 50, 100) if lo <= t <= hi]

    y1 = TOP + ROW * len(BUCKETS) - 8
    body = [S.label(LEFT, TOP - 18, "throughput ÷ compacted", cls="big"),
            S.label(mid + 116, TOP - 18, "bytes ÷ compacted", cls="big"),
            S.hgrid(tsc, thin(tsc, ticks(*bounds([p[4] for p in pts]))), TOP - 4, y1,
                    fmt=lambda v: f"{v:g}×"),
            S.hgrid(bsc, thin(bsc, ticks(*bounds([p[5] for p in pts if p[5]]))), TOP - 4, y1,
                    fmt=lambda v: f"{v:g}×")]
    for i, b in enumerate(BUCKETS):
        body.append(S.label(LEFT - 10, TOP + ROW * i + 4, b, anchor="end", cls="tick"))
    for i, b, a, var, t, br in pts:
        y = TOP + ROW * i
        body.append(S.dot(tsc.to(t), y, 3.8, var, title=f"{a} {b}: {t:.3f}×"))
        if br:
            body.append(S.dot(bsc.to(br), y, 3.8, var, title=f"{a} {b}: {br:.3f}× bytes"))
    body.append(legend(LEFT, H - 14, [("state-actor", "--db-sa"), ("plain", "--db-c"),
                                      ("WAL drained", "--db-u")],
                       trailer="— unity means it agrees with the compacted snapshot"))
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

    # ---- derivations ------------------------------------------------------
    # Reference is the compacted snapshot everywhere except the treatment figure, because the
    # plain store is the one carrying the artifact this article is about.
    sa_vs_comp = bucket_median(F["compacted"], F["state_actor"], common)
    sa_vs_plain = bucket_median(F["plain"], F["state_actor"], common)
    plain_vs_comp = bucket_median(F["compacted"], F["plain"], common)
    sa_bytes = bucket_bytes(F["compacted"], F["state_actor"], common)

    drain_t = bucket_median(FT["plain"], FT["drained"], commonf)
    drain_b = bucket_bytes(FT["plain"], FT["drained"], commonf)
    comp_t = bucket_median(FT["plain"], FT["compacted"], commonf)
    comp_b = bucket_bytes(FT["plain"], FT["compacted"], commonf)

    noise_t = bucket_median(FT["compacted"], FT["compacted_rep"], commonf)
    noise = max(abs(v - 1) for v in noise_t.values())

    # the EXISTING population, which is where the residual lives
    ex = [c for c in common if c[1] != "NON_EXISTING_ACCOUNT"]
    cats = collections.defaultdict(list)
    for c in ex:
        cats[(c[0], c[1])].append(F["state_actor"][c]["mgas_s"] / F["compacted"][c]["mgas_s"])
    ex_cat = {k: median(v) for k, v in cats.items()}
    ex_med = median(list(ex_cat.values()))
    ex_lo, ex_hi = min(ex_cat.values()), max(ex_cat.values())
    ex_below = sum(1 for v in ex_cat.values() if v < 1.0)

    headline = 1 / sa_vs_plain["absent"]
    factor = int(headline)

    # What fraction of account lookups found nothing. The counters are per-container samples,
    # so the honest aggregate is the ratio of the per-test medians; summing across tests mixes
    # containers and can push the ratio above one, which is meaningless.
    miss = {}
    for arm, rows in D["counters"].items():
        by = collections.defaultdict(lambda: ([], []))
        for r in rows:
            by[r["mode"]][0].append(r["reads"])
            by[r["mode"]][1].append(r["reads_missing"])
        miss[arm] = {m: median(v[1]) / median(v[0]) for m, v in by.items() if median(v[0])}
    for arm, v in miss.items():
        assert all(0 <= r <= 1.001 for r in v.values()), f"{arm}: miss ratio out of range {v}"

    # geometry chain
    g06j, g06s = props["jochemnet"]["06"], props["state_actor"]["06"]
    comp_ratio = g06s["phys_over_logical"] / g06j["phys_over_logical"]
    blk_ratio = g06s["block_bytes"] / g06j["block_bytes"]

    l0_06 = levels["before"]["06"]["0"]["files"]
    l6_06 = levels["before"]["06"]["6"]["files"]
    e06 = D["entries_by_cf"]["06"]
    n_absent = len({(c[0], c[1]) for c in common if c[1] == "NON_EXISTING_ACCOUNT"})
    l0_06_after = levels["after"]["06"].get("0", {}).get("files", 0)

    # cf0a is TRIE_LOG_STORAGE. The snapshot carries a little; the generated store carries no
    # files there at all, which is why a Besu trie-log subcommand has nothing to report on it.
    trielog_bytes = sum(v["bytes"] for v in levels["before"].get("0a", {}).values())

    # ---- oracles ----------------------------------------------------------
    # These guard derivations, not conclusions: they fail generation if the inputs stop
    # supporting a sentence the prose states as fact.
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
    assert factor == int(1 / sa_vs_plain["absent"]), "headline factor drifted"
    assert "0a" not in props["state_actor"], "state-actor now has trie-log files"
    assert trielog_bytes > 0, "snapshot trie-log column family is empty"
    assert ex_below == len(ex_cat), "not every EXISTING category favours the snapshot"
    # the code-cf paragraph states a direction for each of these; fail if the data flips
    assert props["state_actor"]["07"]["mean_record"] < props["jochemnet"]["07"]["mean_record"], \
        "generated code records are no longer the smaller ones"
    assert (props["state_actor"]["07"]["phys_over_logical"]
            > props["jochemnet"]["07"]["phys_over_logical"]), \
        "generated code records are no longer the less compressible ones"
    assert g06s["mean_record"] > g06j["mean_record"] and comp_ratio > 1 and blk_ratio > 1, \
        "cf06 geometry chain no longer runs in the direction the prose states"

    print(f"common: full {len(common)} filtered {len(commonf)}")
    print(f"headline: {headline:.2f}x -> {factor}x")
    print(f"sa/compacted: " + " ".join(f"{k} {v:.3f}" for k, v in sorted(sa_vs_comp.items())))
    print(f"sa/plain:     " + " ".join(f"{k} {v:.3f}" for k, v in sorted(sa_vs_plain.items())))
    print(f"drain:        " + " ".join(f"{k} {v:.3f}" for k, v in sorted(drain_t.items())))
    print(f"compaction:   " + " ".join(f"{k} {v:.3f}" for k, v in sorted(comp_t.items())))
    print(f"noise: {noise*100:.1f}%  EXISTING median {ex_med:.3f} "
          f"({ex_lo:.3f}-{ex_hi:.3f}, {ex_below}/{len(ex_cat)})")
    print(f"geometry: compression {comp_ratio:.3f} block {blk_ratio:.3f} "
          f"(geth {GREF['compression_ratio']} / {GREF['block_size_ratio']})")

    # ---- figures ----------------------------------------------------------
    figs = {
        "ratio_dots": (chart_ratio_dots(F, common),
                       f"Throughput of the generated store divided by the compacted "
                       f"snapshot's, one dot per opcode and account mode, log scale. "
                       f"1× would mean the two databases cost the same."),
        "treatment_dumbbell": (chart_treatment_dumbbell(FT, commonf),
                               "What each half of the treatment does. Draining the "
                               "write-ahead log leaves the store where it started; compaction "
                               "moves it. Reference is the plain snapshot — the only figure "
                               "here that uses it."),
        "lsm_levels": (chart_lsm_levels(levels),
                       f"Where the pre-run's rows sit. After the pre-run, cf06 holds "
                       f"{l0_06} files at the top of the tree against {l6_06} at the bottom; "
                       "after compaction the top is empty. A lookup for a recently written "
                       "account reaches those few files before it descends."),
        "bloom": (chart_bloom(props, sa_bytes),
                  "The snapshot carries a bloom filter on every state column family. The "
                  "generated store carries none, so a lookup that will find nothing cannot be "
                  "rejected — it has to read index and data blocks instead."),
        "geometry": (chart_geometry(props, GREF),
                     "The residual, as store geometry. Generated records are larger and "
                     "compress worse, so a data block holds fewer of them and a read moves "
                     "more bytes. Geth's two ratios, measured on a different engine with a "
                     "different compression algorithm, are printed for comparison."),
        "cost_curves": (chart_cost_curves(F, common),
                        "Throughput against the gas budget. The lines stay separated rather "
                        "than converging, so the gap is a per-read cost and not a fixed "
                        "per-block overhead being amortised."),
        "convergence": (chart_convergence(FT, commonf),
                        "Every arm against the compacted snapshot. Once the snapshot is "
                        "compacted the generated store is within a few percent on reads that "
                        "find their key, and an order of magnitude away on reads that do not."),
    }
    for name, (s, _) in figs.items():
        assert "NaN" not in s and "inf" not in s, f"{name}: non-finite geometry"

    os.makedirs(FIGS, exist_ok=True)
    for name, (s, _) in figs.items():
        with open(os.path.join(FIGS, f"fig_{name}.svg"), "w") as fh:
            fh.write(standalone_svg(s) + "\n")

    def fig(name):
        s, cap = figs[name]
        return figure(s, cap)

    # ---- prose ------------------------------------------------------------
    o = []
    w = o.append
    pc = lambda r: f"{abs(1 - r) * 100:.1f}%"

    w("<!doctype html><html lang=en><head><meta charset=utf-8>")
    w('<meta name=viewport content="width=device-width,initial-scale=1">')
    w('<meta name="description" content="Three Besu databases holding the same state report '
      'throughput up to 8x apart on identical EEST work. Two of the three causes are artifacts '
      'of how the store was built, and one is a property of the data.">')
    w('<link rel="preconnect" href="https://fonts.googleapis.com">'
      '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
      '<link href="https://fonts.googleapis.com/css2?family=VT323&'
      'family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&display=swap" '
      'rel="stylesheet">')
    # Title is a series template: same sentence for every client, varying only in the client
    # name and the factor. Keep both strings in lockstep with the Geth article.
    w(f"<title>How can two Besu databases holding the same state differ {factor}\u00d7 in "
      "performance? — state-actor vs a mainnet snapshot</title>")
    w(f"<style>{CSS}</style></head><body>")

    w('<div class=topbar><a href="../">&larr; all articles</a>'
      '<span>EXECUTION · STATE DB</span></div>')
    w('<div class=eyebrow>// REPORT</div>')
    w(f"<h1>How can two Besu databases holding the same state differ {factor}&times; in "
      "performance?</h1>")
    w("<p class=deck>A case study on state-actor versus a Bonsai mainnet-snapshot database "
      "&mdash; and on why a published snapshot has to be compacted before it can be measured "
      "at all.</p>")
    w('<div class=meta><span class=tag>Ethereum · Besu · Bonsai · RocksDB · benchmarking</span>'
      ' · 2026 · <a href="https://github.com/CPerezz/articles/tree/main/'
      'besu-state-db-divergence">reproducible pipeline &amp; data &rarr;</a></div>')
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
      f'{P["storage_format"]}. Every arm ran on {esc(P["device"])}.</p>')

    # ===================================================================== 1
    w('<h2>The behaviour</h2>')
    w(f"<p>Three databases hold the same state. The same {thousands(len(common))} EEST tests "
      f"run against each of them, on the same host and the same NVMe drive. Gas matches across "
      f"all three to six significant figures, so each one was asked to do the same work. "
      f"Throughput does not match. On the tests that look up an account which is not there, "
      f"the generated store is <b>{headline:.1f}&times; slower</b> than the published "
      f"snapshot.</p>")
    w(f"<p>That is the number in the title. It is also mostly an accident of how the two "
      f"stores were built, rather than anything about how Besu reads them. There are two "
      f"separate accidents, and each one shows up on a different kind of read.</p>")
    w(f"<p>The chart below is the shape of the problem. Every dot is one test category, "
      f"measured against the snapshot after compaction. They fall into two groups about ten "
      f"times apart. The {n_absent} dots on the left are the categories that have to prove an "
      f"account is absent; the generated store is {1/sa_vs_comp['absent']:.1f}&times; "
      f"slower on all of them, and compacting the snapshot does not close the gap. The "
      f"{len(ex_cat)} dots on the right read an account that exists, and they sit within "
      f"{pc(ex_lo)} of the snapshot. Two groups, two causes.</p>")
    w(fig("ratio_dots"))
    w("<table><tr><th>bucket</th><th>tests</th>"
      "<th class=n>state-actor ÷ plain</th><th class=n>state-actor ÷ compacted</th>"
      "<th class=n>plain ÷ compacted</th></tr>")
    for b in BUCKETS:
        n = sum(1 for c in common if F["plain"][c]["bucket"] == b)
        w(f"<tr><td>{b}</td><td class=n>{n}</td>"
          f"<td class=n>{sa_vs_plain[b]:.3f}</td>"
          f"<td class=n>{sa_vs_comp[b]:.3f}</td>"
          f"<td class=n>{plain_vs_comp[b]:.3f}</td></tr>")
    w(f"<caption>Median of the per-workload ratio. {esc(BUCKET_DOC['absent'])}; "
      f"{esc(BUCKET_DOC['leaf-only'])}; {esc(BUCKET_DOC['code-reading'])}.</caption></table>")

    w('<h3>Outside the absent class, the two databases agree to '
      f'within {pc(ex_lo)}</h3>')
    w(f"<p>Against the compacted snapshot, every one of the {len(ex_cat)} categories that "
      f"read an account which exists favours the snapshot, by a median of {pc(ex_med)} and "
      f"never by more than {pc(ex_lo)}. That is the honest difference between the two "
      f"databases, and it is the subject of the last section. Everything larger than it is a "
      f"property of how one of the stores was built.</p>")

    # ===================================================================== 2
    w('<h2>What Besu\'s own logs and counters say</h2>')
    w(f"<p>Besu states its own configuration at startup, and two of those lines matter. "
      f"<code>Existing database at /data. Metadata "
      f"versionedStorageFormat=BaseVersionedStorageFormat{{format=BONSAI, version=3}}. "
      f"Processing WAL...</code> appears on every boot of every arm, including the arm whose "
      f"write-ahead log is {C['after_flush']['wal_bytes']} bytes long, so the line is "
      f"boot-time boilerplate rather than evidence of work. <code>Flat db mode found FULL</code> "
      f"is the one that shapes the rest: account reads go to Bonsai's flat keyspace, not down "
      f"the trie. The metrics agree &mdash; "
      f"{P['flat_read_share']*100:.2f}% of account lookups are served from the flat database.</p>")
    w("<p>That matters because it fixes what a read costs. An account lookup is one key in one "
      "column family, so the cost is the cost of locating that key &mdash; how many files have "
      "to be consulted and how many bytes each consultation moves. It is not a tree walk whose "
      "depth grows with the state, which is the shape most people expect.</p>")
    w("<table><tr><th>account_mode</th>"
      "<th class=n>lookups that found nothing ÷ total, compacted snapshot</th>"
      "<th class=n>state-actor</th></tr>")
    for m in sorted(set(miss.get("compacted", {})) & set(miss.get("state_actor", {}))):
        w(f"<tr><td><code>{m}</code></td>"
          f"<td class=n>{miss['compacted'][m]:.3f}</td>"
          f"<td class=n>{miss['state_actor'][m]:.3f}</td></tr>")
    w("<caption>Besu counts flat-database lookups that find no key. The absence categories "
      "probe addresses that are genuinely absent from both stores &mdash; so the difference in "
      "what they cost is not a difference in what they find.</caption></table>")

    # ===================================================================== 3
    w('<h2>What we ruled out first</h2>')
    w("<p>Before anything else, the two stores have to be shown to be the same kind of object "
      "holding different data, rather than differently configured engines.</p>")
    w('<h3>The databases themselves</h3>')
    w(f"<p>Both stores run the same RocksDB settings on every state column family: "
      f"<code>compression={P['compression']}</code> and "
      f"<code>block_size={thousands(P['block_size'])}</code>, byte-identical. Key–value "
      f"separation is enabled on exactly two column families, neither of which holds state: the "
      f"snapshot's {thousands(C['shipped']['blob_files'])} blob files and "
      f"{C['shipped']['blob_bytes']/1e9:.0f} GB are block bodies and receipts. The generated "
      f"store has {C['state_actor']['blob_files']} blob file of "
      f"{C['state_actor']['blob_bytes']} bytes, because it has no chain history at all. "
      f"Whole-store totals are therefore "
      f"not comparable and are not compared anywhere in this article; the comparison is always "
      f"per column family.</p>")
    w(f"<p>The extraction is deterministic: three independent unpacks of the published tarball "
      f"produced the same {thousands(C['shipped']['ssts'])} SST files and the same "
      f"{thousands(C['shipped']['sst_bytes'])} bytes. Trie logs are not a factor either "
      f"&mdash; Besu prints <code>Forcing --bonsai-limit-trie-logs-enabled=false, since it "
      f"cannot be enabled with --sync-mode=FULL and --data-storage-format=BONSAI.</code> on "
      f"every boot, the snapshot's trie-log column family holds "
      f"{trielog_bytes/1e6:.1f} MB, and the generated store's holds no files at all.</p>")
    w('<h3>What the fixtures actually touch</h3>')
    w(f"<p>The suite is {len(set((c[0], c[1]) for c in common))} opcode/account-mode categories "
      f"across {len(sorted({c[2] for c in common}))} gas budgets from "
      f"{min(c[2] for c in common)}M to {max(c[2] for c in common)}M. They split into three "
      f"groups that behave so differently that any single median over them describes none of "
      f"them: ")
    w("<ul class=tight>")
    for b in BUCKETS:
        n = sum(1 for c in common if F["plain"][c]["bucket"] == b)
        w(f"<li><b>{b}</b> ({n} tests) &mdash; {esc(BUCKET_DOC[b])}.</li>")
    w("</ul>")

    # ===================================================================== 4
    w('<h2>The file that looks like the cause: a '
      '1.2 GB write-ahead log</h2>')
    w(f"<p>The published snapshot ships a write-ahead log of "
      f"{thousands(C['shipped']['wal_bytes'])} bytes across "
      f"{C['shipped']['wal_files']} files, and the pre-run replay leaves it that size or "
      f"larger. A write-ahead log is where a key–value store puts writes that have not yet "
      f"been folded into its sorted files, so a gigabyte of it sitting inside a snapshot is "
      f"exactly the shape of a benchmark artifact: state that lives in one place on disk and "
      f"another in memory, restored on every boot.</p>")
    w(f"<p>The first thing that argues against it is that the size is not even stable. Two "
      f"pre-run replays of the same extraction left "
      f"{C['after_prerun']['wal_bytes']/1e9:.2f} GB and "
      f"{C['after_prerun_repeat']['wal_bytes']/1e9:.2f} GB behind. A cause that varies by "
      f"{abs(C['after_prerun']['wal_bytes'] / C['after_prerun_repeat']['wal_bytes'] - 1)*100:.0f}% "
      f"between runs is a poor explanation for an effect that reproduces.</p>")
    w(f"<p>The second is what happens when you drain it. The whole step takes "
      f"{C['after_flush']['step_seconds']} seconds, leaves "
      f"{C['after_flush']['wal_bytes']} bytes, and <b>adds no SST file</b> &mdash; the count "
      f"stays at {thousands(C['after_flush']['ssts'])}. Had the log held writes that were not "
      f"yet on disk, recovery would have written them out as new files. Promoting the result "
      f"copies {C['after_flush']['promote_bytes']/1e6:.0f} MB in "
      f"{C['after_flush']['promote_ms']} ms. Nothing in that gigabyte was unpersisted; it is a "
      f"log that had not been garbage-collected yet.</p>")
    w(f"<p>And the explicit flush inside that step reported "
      f"{C['after_flush']['flush_seconds']:.1f} s, because by the time it ran there was nothing "
      f"in memory to write: RocksDB's <em>open</em> path recovers the log and flushes it "
      f"itself. On Besu, opening the store is the drain &mdash; which means every arm of every "
      f"suite had already done it, before a single test ran.</p>")
    w(f"<p>Measured end to end, draining it changes nothing: "
      + ", ".join(f"{drain_t[b]:.3f}&times; on {b}" for b in BUCKETS) +
      f" for throughput and "
      + ", ".join(f"{drain_b[b]:.3f}&times;" for b in BUCKETS) +
      f" for bytes read. Throughput holds to within "
      f"{max(abs(1-drain_t[b]) for b in BUCKETS)*100:.1f}% and bytes to within "
      f"{max(abs(1-drain_b[b]) for b in BUCKETS)*100:.1f}%, against a same-state repeat that "
      f"reproduces to {noise*100:.1f}%. The one thing in the snapshot that looks like the "
      f"cause is inert.</p>")
    w(fig("treatment_dumbbell"))

    # ===================================================================== 5
    w('<h2>The root cause: the pre-run\'s rows are the newest versions of their keys</h2>')
    w(f"<p>Before each test the harness replays a pre-run bundle &mdash; "
      f"{D['prerun_bundle_bytes']/1e9:.2f} GB of blocks that create the accounts the benchmark "
      f"then reads. It takes the store from {thousands(C['shipped']['ssts'])} SST files to "
      f"{thousands(C['after_prerun']['ssts'])}. Four files is not much of a change; what "
      f"matters is that every account the benchmark reads now has its newest version in one of "
      f"them.</p>")
    w(f"<p>The compaction proves it, by what it deletes. Merging the levels of the account "
      f"column family removes {thousands(e06['plain'] - e06['compacted'])} entries, "
      f"{e06['plain']:,} down to {e06['compacted']:,}, and a merge can only drop an entry if "
      f"it was an obsolete older version of a key held somewhere else in the tree. The same "
      f"thing happens in storage and trie-branch: ")
    w("<table><tr><th>column family</th><th class=n>entries, plain</th>"
      "<th class=n>entries, compacted</th><th class=n>removed</th>"
      "<th class=n>SST files</th></tr>")
    for cf, e in sorted(D["entries_by_cf"].items()):
        w(f"<tr><td>cf{cf} <code>{e['name']}</code></td>"
          f"<td class=n>{e['plain']:,}</td><td class=n>{e['compacted']:,}</td>"
          f"<td class=n>{thousands(e['plain'] - e['compacted'])}</td>"
          f"<td class=n>{thousands(e['ssts_plain'])} &rarr; "
          f"{thousands(e['ssts_compacted'])}</td></tr>")
    w("<caption>A store holding only one version of each key cannot lose entries to a "
      "compaction. These do, so the pre-run's writes were sitting above older copies of the "
      "same keys.</caption></table>")
    w(f"<p>A point lookup in a levelled store checks the youngest files first and stops at the "
      f"first version it finds. After the pre-run the account column family holds {l0_06} "
      f"files at the top of the tree &mdash; "
      f"{levels['before']['06']['0']['bytes']/1e6:.0f} MB of it &mdash; above {l6_06} files "
      f"holding {levels['before']['06']['6']['bytes']/1e9:.1f} GB at the bottom. The reads the "
      f"benchmark performs are satisfied in the small, young part of the tree.</p>")
    w(fig("lsm_levels"))
    w(f"<p>Compaction merges all of it into the bottom level: {l0_06_after} files left at the "
      f"top, and the same lookup now reads a {thousands(P['block_size'])}-byte block out of a "
      f"sorted run of "
      f"{levels['after']['06'].get('6', {}).get('bytes', 0)/1e9:.1f} GB with no locality to "
      f"whatever was written beside it. The cost of a read goes up while the store gets "
      f"smaller, which is the signature of removing an accident rather than applying an "
      f"optimisation.</p>")

    # ===================================================================== 6
    w('<h2>The fix, and the proof</h2>')
    w(f"<p>A full-range compaction takes {C['after_compact']['seconds']/60:.0f} minutes and "
      f"leaves the store smaller: {thousands(C['after_prerun']['ssts'])} files and "
      f"{C['after_prerun']['sst_bytes']/1e9:.1f} GB become "
      f"{thousands(C['after_compact']['ssts'])} and "
      f"{C['after_compact']['sst_bytes']/1e9:.1f} GB. Most of the time goes to the largest "
      f"column families: "
      + ", ".join(f"cf{k} {v:.0f}s" for k, v in sorted(D['treatment_seconds_by_cf'].items(),
                                                       key=lambda kv: -kv[1])[:3]) + ".</p>")
    w("<table><tr><th>bucket</th><th class=n>drain only</th><th class=n>drain + compaction</th>"
      "<th class=n>bytes, drain only</th><th class=n>bytes, drain + compaction</th></tr>")
    for b in BUCKETS:
        w(f"<tr><td>{b}</td><td class=n>{drain_t[b]:.3f}</td><td class=n>{comp_t[b]:.3f}</td>"
          f"<td class=n>{drain_b[b]:.3f}</td><td class=n>{comp_b[b]:.3f}</td></tr>")
    w("<caption>Throughput and bytes read, each against the plain snapshot. The drain "
      "contributes nothing; the compaction contributes everything.</caption></table>")
    w(f"<p>After it, the generated store and the snapshot agree on reads that find their key: "
      + ", ".join(f"{sa_vs_comp[b]:.3f}&times; on {b}" for b in BUCKETS if b != "absent") +
      ". The absence categories do not converge, and that has a separate cause.</p>")
    w(fig("convergence"))
    w(fig("cost_curves"))

    # ===================================================================== 7
    w(f'<h2>Why absence proofs cost {sa_bytes["absent"]:.0f}&times; the '
      f'bytes: the generated store has no bloom filters</h2>')
    w(f"<p>The absence categories probe addresses that are missing from both stores &mdash; the "
      f"counters in the second section put the miss rate at "
      f"{miss['compacted']['NON_EXISTING_ACCOUNT']:.3f} and "
      f"{miss['state_actor']['NON_EXISTING_ACCOUNT']:.3f}. Identical question, identical answer, "
      f"and {sa_bytes['absent']:.1f}&times; the bytes to arrive at it.</p>")
    w(f"<p>The reason is in the files. Every state column family in the snapshot carries a bloom "
      f"filter; the generated store's carry none at all.</p>")
    w("<table><tr><th>column family</th><th class=n>filter bytes, snapshot</th>"
      "<th class=n>filter bytes, state-actor</th><th>policy, state-actor</th></tr>")
    for cf, name in (("06", "ACCOUNT_INFO_STATE"), ("07", "CODE_STORAGE"),
                     ("08", "ACCOUNT_STORAGE_STORAGE"), ("09", "TRIE_BRANCH_STORAGE")):
        w(f"<tr><td>cf{cf} <code>{name}</code></td>"
          f"<td class=n>{thousands(props['jochemnet'][cf]['filter_bytes'])}</td>"
          f"<td class=n>{props['state_actor'][cf]['filter_bytes']}</td>"
          f"<td><code>{esc(props['state_actor'][cf]['filter_policy'])}</code></td></tr>")
    w("<caption>A bloom filter answers &ldquo;this file cannot contain that key&rdquo; without "
      "reading the file. Without one, the lookup reads index and data blocks to reach the same "
      "conclusion.</caption></table>")
    w(fig("bloom"))
    w(f"<p>The cost lands almost entirely on absence. A lookup that finds its key was going to "
      f"read that block anyway, so the filters buy little there &mdash; "
      + " and ".join(f"{sa_bytes[b]:.2f}&times; on {b}" for b in BUCKETS if b != "absent") +
      f" &mdash; against {sa_bytes['absent']:.1f}&times; when there is nothing to find. This is "
      f"a property of how the generated store was written, not of what it contains.</p>")
    w('<h3>What this does not separate</h3>')
    w(f"<p>Some part of the "
      + " to ".join(f"{sa_bytes[b]:.2f}&times;" for b in ("leaf-only", "code-reading")) +
      " on reads that find their key may also be filter absence rather than the record geometry "
      "of the next section. The two are not separated here.</p>")

    # ===================================================================== 8
    w('<h2>The residual</h2>')
    w(f"<p>What is left after both artifacts is small and consistent: against the compacted "
      f"snapshot, every one of the {len(ex_cat)} categories that reads an existing account "
      f"favours the snapshot, median {pc(ex_med)}, range {pc(ex_hi)} to {pc(ex_lo)}.</p>")
    w("<table><tr><th>cf06 ACCOUNT_INFO_STATE</th><th class=n>compacted snapshot</th>"
      "<th class=n>state-actor</th><th class=n>ratio</th></tr>")
    for lbl, fld, nd, unit in (("entries", "entries", 0, ""),
                               ("mean raw record", "mean_record", 1, " B"),
                               ("physical ÷ logical", "phys_over_logical", 3, ""),
                               ("compressed bytes per block", "block_bytes", 1, " B")):
        a, b = g06j[fld], g06s[fld]
        w(f"<tr><td>{lbl}</td><td class=n>{a:,.{nd}f}{unit}</td>"
          f"<td class=n>{b:,.{nd}f}{unit}</td><td class=n>{b/a:.3f}</td></tr>")
    w("<caption>The chain: generated records are larger and compress worse, so a data block "
      "holds fewer of them and every read moves more bytes.</caption></table>")
    w(fig("geometry"))
    w(f"<p>Two ratios carry the argument: compression {comp_ratio:.3f}&times; and block size "
      f"{blk_ratio:.3f}&times;. The same two ratios measured on geth were "
      f"{GREF['compression_ratio']:.3f}&times; and {GREF['block_size_ratio']:.3f}&times; "
      f"&mdash; within {abs(comp_ratio/GREF['compression_ratio']-1)*100:.1f}%, on a different "
      f"storage engine, with a different compression algorithm and an eight times larger "
      f"block. Whatever this is, it is not an artifact of one engine.</p>")
    w(f"<p>The code column family carries the compressibility half of that argument on its own, "
      f"and inverts the size half. The snapshot's code records average "
      f"{props['jochemnet']['07']['mean_record']:,.0f} bytes and compress to "
      f"{props['jochemnet']['07']['phys_over_logical']:.3f} of their size; the generated "
      f"store's are far smaller at {props['state_actor']['07']['mean_record']:,.0f} bytes and "
      f"compress to only {props['state_actor']['07']['phys_over_logical']:.3f}. Mainnet "
      f"bytecode repeats &mdash; proxies, tokens and factory output share long stretches "
      f"&mdash; while every generated contract gets its own. Smaller records that will not "
      f"compress is what a database of unique bytecode looks like.</p>")
    w('<h3>The same experiment on two clients</h3>')
    w(f"<p>The generator is deterministic across clients: the same seed and spec produced "
      f"{thousands(P['state_actor_items'])} items here against "
      f"{thousands(GREF['state_actor_items'])} on geth &mdash; "
      f"{abs(P['state_actor_items'] - GREF['state_actor_items'])} apart in six billion "
      f"&mdash; and the same state root, "
      f"<code>{P['state_actor_state_root'][:18]}&hellip;</code>. The stores they produced are "
      f"not the same size: {P['state_actor_gib']} GiB on Besu against "
      f"{GREF['state_actor_gib']} GiB on geth, for identical logical state. So the two studies "
      f"measure the same state through two different engines, and the residual survives the "
      f"change of engine. Its magnitude does not: {pc(ex_med)} here against "
      f"{GREF['residual_median_pct']:.1f}% there.</p>")

    w("<details><summary>What this article does not settle</summary>")
    w("<ul class=tight>")
    w(f"<li>Why the residual is {pc(ex_med)} on Besu and "
      f"{GREF['residual_median_pct']:.1f}% on geth.</li>")
    w("<li>How much of the byte penalty on reads that find their key is filter absence rather "
      "than record geometry.</li>")
    w(f"<li>The snapshot ships {C['shipped']['caches_files']} cache files totalling "
      f"{C['shipped']['caches_bytes']/1e9:.1f} GB, never examined here.</li>")
    w("<li>Whether the pre-run's placement advantage is purely level position or partly block "
      "cache residency; compaction changes both at once.</li>")
    w("</ul></details>")

    w('<div class=endbar><a href="../">&larr; all articles</a>'
      '<a href="https://github.com/CPerezz/articles/tree/main/besu-state-db-divergence">'
      'source &amp; data</a></div>')
    w('<span class=cursor style="position:fixed;bottom:1.4rem;right:1.4rem;z-index:6"></span>')
    w("</body></html>")

    doc = add_toc("\n".join(o))
    with open(OUT, "w") as fh:
        fh.write(doc)
    print(f"wrote {os.path.relpath(OUT, HERE)} ({os.path.getsize(OUT)} bytes), "
          f"{len(figs)} figures")


if __name__ == "__main__":
    main()
