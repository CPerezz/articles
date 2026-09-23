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
BUCKET_DOC = {
    "absent": "NON_EXISTING_ACCOUNT targets, where the lookup must prove the account is not there",
    "leaf-only": "BALANCE, or an EXISTING_EOA target, which reads the account record and never the code",
    "code-reading": "EXTCODE* and the CALL family into a contract, which also reads the code blob",
}
ARM_DOC = {
    "plain": "the published snapshot, pre-runs replayed, promoted, exactly as a benchmark uses it",
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
    body.append(S.label(LEFT, H - 10, "state-actor ÷ compacted snapshot, throughput", cls="ax"))
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
    body.append(S.label(LEFT, H - 8, "MGas/s against gas budget (M), BALANCE/EXISTING_EOA", cls="ax"))
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
    body.append(S.label(LEFT, H - 28, "state-actor ÷ snapshot, throughput", cls="ax"))
    items = [("before", "--muted"), ("absence", "--db-c"), ("shared code", "--db-u"),
             ("distinct code", "--db-sa")]
    if v4:
        items.insert(1, ("after #138, tiled pool", "--dim"))
    body.append(legend(LEFT, H - 10, items, trailer=f"shaded band = ±{band*100:.0f}% of parity"))
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
                       trailer="(unity means it agrees with the compacted snapshot)"))
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
    # The controls read a median 1.9 MB against the measurement rows' 8.6 GB, so pooling the
    # two halves into one median drags every category towards parity and understates the
    # effect. Comparisons below use the measurement half; the controls are reported once, as
    # the control they are.
    DARK = ("EXISTING_CONTRACT_DIFF_MAX", "EXISTING_CONTRACT_JUMPDEST")
    meas = [c for c in common if not c[4]]
    ctrls = [c for c in common if c[4]]
    measf = [c for c in commonf if not c[4]]
    ctrlsf = [c for c in commonf if c[4]]
    assert meas and ctrls and measf and ctrlsf, "measurement/control split came out empty"

    # ---- derivations ------------------------------------------------------
    # Reference is the compacted snapshot everywhere except the treatment figure, because the
    # plain store is the one carrying the artifact this article is about.
    sa_vs_comp = bucket_median(F["compacted"], F["state_actor"], meas)
    sa_vs_plain = bucket_median(F["plain"], F["state_actor"], meas)
    plain_vs_comp = bucket_median(F["compacted"], F["plain"], meas)
    sa_bytes = bucket_bytes(F["compacted"], F["state_actor"], meas)
    # the control, on the same pair of arms
    ctrl_vs_comp = median([F["state_actor"][c]["mgas_s"] / F["compacted"][c]["mgas_s"]
                           for c in ctrls])
    ctrl_cats = {k: median(v) for k, v in
                 ratios(F["compacted"], F["state_actor"], ctrls).items()}

    drain_t = bucket_median(FT["plain"], FT["drained"], measf)
    drain_b = bucket_bytes(FT["plain"], FT["drained"], measf)
    comp_t = bucket_median(FT["plain"], FT["compacted"], measf)
    comp_b = bucket_bytes(FT["plain"], FT["compacted"], measf)
    drain_ctrl = median([FT["drained"][c]["mgas_s"] / FT["plain"][c]["mgas_s"] for c in ctrlsf])
    comp_ctrl = median([FT["compacted"][c]["mgas_s"] / FT["plain"][c]["mgas_s"] for c in ctrlsf])

    noise_t = bucket_median(FT["compacted"], FT["compacted_rep"], measf)
    noise = max(abs(v - 1) for v in noise_t.values())

    # the EXISTING population, which is where the residual lives
    ex = [c for c in meas if c[1] != "NON_EXISTING_ACCOUNT"]
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

    # What the code read itself costs, isolated by subtracting the classes that read only the
    # account record. The dark classes read one distinct contract per access on top of that.
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
    # How many accounts share each distinct bytecode. This is the one property both remaining
    # tiers come out of, so it is derived rather than described.
    reuse = {}
    for k, store in (("jochemnet", "jochemnet"), ("state_actor", "state_actor")):
        accts = props[store]["06"]["entries"]
        contracts = accts * (100 - AM[k]["eoa_pct"]) / 100
        reuse[k] = {"contracts": contracts, "codes": props[store]["07"]["entries"],
                    "per_code": contracts / props[store]["07"]["entries"]}

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

    # Before and after the snapshot is treated, per category and per workload. "Before" is the
    # snapshot as published, "after" is the same snapshot compacted; the generated store is
    # untouched in both, so the whole movement belongs to the treatment.
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
    # The two groups the survivors split into: modes that read a distinct contract per access,
    # and everything else. This is the same pair the geth and Nethermind studies isolate.
    dark = [r for r in verdict if r[2] in DARK]
    light = [r for r in verdict if r[0] != "absent" and r[2] not in DARK]
    # Clearing the band is not the same as agreeing, so name the closest category and the
    # fastest single workload. verdict is sorted by the compacted ratio, so the last row is
    # the closest to parity.
    best_cat = verdict[-1]
    max_row = max(F["state_actor"][c]["mgas_s"] / F["compacted"][c]["mgas_s"] for c in meas)
    # Upstream outcome, plus the gap between the fix landing and our store being built. That
    # gap is the reason one of the three findings is our own goal rather than a generator bug.
    ST = D["status"]
    PR = {p["n"]: p for p in ST["prs"]}
    DAYS_STALE = (datetime.date.fromisoformat(ST["measured_store_built"])
                  - datetime.date.fromisoformat(PR[133]["merged"])).days
    # The rerun against a store regenerated from all three merged fixes.
    V3 = ST["v3"]
    # The dark class rerun against a store built from the corpus fix (#141). Only the sixteen
    # distinct-code categories were refilled and rerun; the other classes do not read the pool.
    V4 = ST.get("v4")
    V4CAT = {(r[1], r[2]): r[5] for r in V4["categories"]} if V4 else {}
    # The residual against gas budget. A fixed per-read cost would be flat here and a fixed
    # per-block cost would improve with the budget; the point of carrying all the budgets is
    # that neither happens, so the oracle below is what keeps the prose honest.
    GAS = sorted({c[2] for c in meas})
    def _grad(keys, pick):
        return [median([F["state_actor"][c]["mgas_s"] / F["compacted"][c]["mgas_s"]
                        for c in keys if c[2] == g and pick(c)]) for g in GAS]
    grad = {"absent": _grad(meas, lambda c: c[1] == "NON_EXISTING_ACCOUNT"),
            "dark": _grad(meas, lambda c: c[1] in DARK),
            "light": _grad(meas, lambda c: c[1] != "NON_EXISTING_ACCOUNT" and c[1] not in DARK),
            "ctrl": _grad(ctrls, lambda c: True)}

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
    assert cat_before == 0, f"{cat_before} categories were already inside the band"
    assert cat_after == len(light), \
        f"{cat_after} categories inside the band after treatment, expected {len(light)}"
    # The three groups the article claims, each one asserted rather than described.
    assert all(inband(r[4]) for r in light), "a code-reusing category missed the band"
    assert not any(inband(r[4]) for r in dark), "a distinct-code category reached the band"
    assert not any(inband(r[4]) for r in verdict if r[0] == "absent"), \
        "an absence category reached the band"
    # Clearing the band is the weaker claim; these guard the stronger one the prose makes.
    assert max_row < 1.0, \
        f"a measurement workload is faster than the snapshot: {max_row:.3f}"
    assert best_cat[4] == max(r[4] for r in verdict), "verdict stopped being sorted by ratio"
    assert best_cat[4] < 1.0, \
        f"a category reached parity: {best_cat[1]}/{best_cat[2]} at {best_cat[4]:.3f}"
    assert ctrl_vs_comp > 1.0, \
        f"the control is no longer faster on the generated store: {ctrl_vs_comp:.3f}"
    # The gradient claim: every measurement class degrades as the budget grows, the control
    # does not. Endpoints carry the prose; the middle is checked for monotonic drift so the
    # sentence cannot survive a series that wanders.
    for cls in ("absent", "dark", "light"):
        assert grad[cls][-1] < grad[cls][0], \
            f"{cls} no longer degrades with gas: {grad[cls][0]:.3f} -> {grad[cls][-1]:.3f}"
        assert all(b <= a + 0.01 for a, b in zip(grad[cls], grad[cls][1:])), \
            f"{cls} gradient is not non-increasing: {[round(v, 3) for v in grad[cls]]}"
    assert max(grad["ctrl"]) - min(grad["ctrl"]) < 0.02, \
        f"the control is not flat across budgets: {[round(v, 3) for v in grad['ctrl']]}"
    assert all(v > 1.0 for v in grad["ctrl"]), "the control stopped favouring the generated store"
    # The rerun's claims. Each one fails generation if the data stops supporting the sentence.
    assert V3["fail"] == 0 and V3["success"] > 0, \
        f"the v3 arm had {V3['fail']} failing executions"
    assert V3["measurement"] == len(meas) and V3["control"] == len(ctrls), \
        "the v3 arm is not the same grid as the original"
    assert abs(V3["control_ratio"] - V3["control_archived"]) <= 0.013, (
        f"control canary moved {abs(V3['control_ratio'] - V3['control_archived']):.4f}; "
        f"the archived arm is no longer a legitimate reference")
    assert max(V3["gradient"]["control"]) - min(V3["gradient"]["control"]) <= 0.02, \
        "the v3 control is not flat across budgets"
    assert V3["classes"]["absent"]["v3"] > 0.95, "the absence class did not reach parity"
    assert V3["classes"]["dark"]["v3"] > 1.0, "the distinct-code class did not invert"
    assert V3["classes"]["light"]["v3"] > V3["classes"]["light"]["archived"], \
        "the shared-code class did not improve"
    # The inversion grows with read volume; that direction is the argument, not the endpoint.
    assert V3["gradient"]["dark"][-1] > V3["gradient"]["dark"][0], \
        "the distinct-code inversion no longer grows with the gas budget"
    assert V3["faster_rows"] > 0 and max_row < 1.0, \
        "v3 has no faster rows, or the original arm gained one"
    for b, op, m, before, after in verdict:
        assert (after > before) == (b != "absent") or abs(after - before) < 0.05, \
            f"{op}/{m}: treatment moved the wrong way ({before:.3f} -> {after:.3f})"
    # The controls do no account-state work, so they are the thing that must NOT move.
    assert all(abs(v - 1) <= 0.05 for v in ctrl_cats.values()), \
        f"control categories are not at parity: {min(ctrl_cats.values()):.3f}-{max(ctrl_cats.values()):.3f}"
    # The corpus-fix rerun's claims: a partial arm, so the oracle checks its scope as much as
    # its numbers. Whatever the verdict, the prose is generated from it, never around it.
    if V4:
        assert V4["pr"] == 141 and V4["sha"] == "9b23eea", "v4 provenance drifted"
        assert V4["partial"] and set(V4["classes"]) == {"dark"}, "v4 is not the dark-only arm"
        assert V4["classes"]["dark"]["categories"] == 16 and len(V4["categories"]) == 16, \
            "v4 does not cover the sixteen distinct-code categories"
        assert V4["fail"] == 0 and V4["success"] > 0, f"the v4 arm had {V4['fail']} failing executions"
        assert V4["gas_identity_bad"] == 0, "v4 burned different gas from the archived arm"
        assert V4["measurement"] == V4["classes"]["dark"]["rows"] + sum(s["rows"] for s in V4["spot"].values()), \
            "v4 measurement count does not add up"
        assert V4["control"] == V4["classes"]["dark"]["rows"], \
            "the dark rows are not paired one to one with controls"
        assert len(V4["gradient"]["gas"]) == len(V4["gradient"]["dark"]) == len(V4["gradient"]["control"]) \
            == len(V4["budgets"]), "v4 gradient is ragged"
        assert V4["classes"]["dark"]["v3"] == V3["classes"]["dark"]["v3"], "v4 lost the v3 reference"
        assert all(r[4] == next(x[4] for x in V3["categories"] if x[1:3] == r[1:3]) for r in V4["categories"]), \
            "v4 per-category v3 values disagree with the v3 arm"
        d4 = V4["classes"]["dark"]["v4"]
        canary = abs(V4["control_ratio"] - V4["control_archived"]) <= 0.013 and V4["control_drift"] <= 0.03
        expected = ("canary_fail" if not canary else
                    "in_band" if abs(d4 - 1) <= V4["band"] else "above" if d4 > 1 else "below")
        assert V4["verdict"] == expected, f"v4 verdict {V4['verdict']} does not follow from the numbers ({expected})"
        assert V4["store_geom"]["cf07"] > 5 * ST["after"]["cf07_phys"], \
            "the v4 store's code column family still compresses like the tiled pool"
        assert abs(V4["store_geom"]["record_deflate"] - ST["target"]["record_deflate"]) <= 0.05, \
            "the v4 store's records do not deflate like mainnet's"
        assert all(abs(s["v4_ratio"] - s["v3_ratio"]) <= 0.10 for s in V4["spot"].values()), \
            "a class that does not read the pool moved on the v4 store"
        if V4["verdict"] == "above":
            DK = V4["disk"]
            assert all(0.5 < v < 1.0 for v in DK["v4_over_mainnet"]) and all(v > 1.0 for v in DK["v1_over_mainnet"]), \
                "the byte-ratio story does not hold"
            assert all(abs(t * b - 1) <= 0.10 for t, b in zip(V4["gradient"]["dark"], DK["v4_over_mainnet"])), \
                "throughput does not follow bytes per read"
            assert DK["gas"] == V4["gradient"]["gas"], "disk budgets do not match the gradient"
            R = V4["residual"]
            assert R["work_mismatch"] <= 0.02, \
                "the arms do not prefetch the same accounts, so cost per lookup is not comparable"
            assert R["code_cf_share_of_store"] < 0.01, \
                "the code column family is no longer a negligible share of the store"
            assert 0.6 < R["ratio_v4_over_snapshot"] < 1.0, "cost per account left its measured range"
            assert R["ratio_v4_over_snapshot"] > R["ratio_v3_over_snapshot"], \
                "the corpus pool did not move cost per prefetched account toward the snapshot"
            assert min(R["compaction_swing"]) > 3, \
                "compaction no longer swings the reference, so the floor argument does not hold"
            # The point of the paragraph: neither per-lookup ratio is the workload ratio, and they
            # straddle it. If that stops being true, the prose claiming it must change with it.
            lo, hi = sorted(R["cf_lookup_ratio"].values())
            assert lo < 1 < hi, "the per-lookup ratios stopped pointing opposite ways"
            assert all(abs(v - R["ratio_v4_over_snapshot"]) > 0.10 for v in (lo, hi)), \
                "a per-lookup ratio now matches the workload ratio, so it may well be the mechanism"
            assert all(0.95 <= v["v4_blocks"] <= 1.05 and 0.95 <= v["snapshot_blocks"] <= 1.05
                       for v in (R["cf_lookup"]["cf06"], R["cf_lookup"]["cf09"])), \
                "a lookup stopped costing one data block on one of the stores"
        # The paired re-run is the only comparison here whose denominator was built and measured
        # for it. If it ever agrees with the old reference, one of the two is being misread.
        if V4.get("paired"):
            PD = V4["paired"]
            assert len(PD["categories"]) == PD["measurement"] == PD["control"], \
                "the paired arms are not one control per measurement row"
            assert PD["device_byte_factor"] > 2, \
                "the two media no longer disagree on bytes, so the caveat can go"
            assert PD["control_offset"] > PD["original_control_offset"] + 0.05, \
                "the array arm's control offset stopped being the larger one"
            assert all(abs(c[4] - 1) <= PD["band"] for c in PD["categories"]) and PD["inband"] == PD["measurement"], \
                "a paired category left the band, so the parity sentence must change"
            assert all(c[3] > c[4] for c in PD["categories"]), \
                "the control correction stopped reducing the raw ratios"
            assert PD["median"] < V4["classes"]["dark"]["v4"], \
                "the two media no longer disagree, so the unresolved framing must change"
        if V4.get("arm_b"):
            AB = V4["arm_b"]
            assert not AB["canary_ok"] and abs(AB["control_ratio"] - V4["control_archived"]) > 0.013, \
                "arm B's canary passed; it should be merged, not shown aside"
            assert AB["gas_identity_bad"] == 0 and AB["fail"] == 0, "arm B is not a clean run"
            assert not set(AB["budgets"]) & set(V4["budgets"]), "arm B overlaps arm A's budgets"
            allg = sorted(V4["budgets"] + AB["budgets"])
            alld = dict(zip(V4["budgets"], V4["gradient"]["dark"])) | dict(zip(AB["budgets"], AB["gradient"]["dark"]))
            seq = [alld[g] for g in allg]
            assert all(b >= a for a, b in zip(seq, seq[1:])), "the eleven-budget gradient is not monotone"
            allb = dict(zip(V4["budgets"], DK["v4_over_mainnet"])) | dict(zip(AB["budgets"], AB["disk"]["v4_over_mainnet"]))
            seqb = [allb[g] for g in allg]
            assert all(b <= a for a, b in zip(seqb, seqb[1:])), "the byte ratio does not fall monotonically with the budget"
    # The code-block argument: the contract itself is near-free on both stores, the block is
    # not, and shrinking the block removes the co-tenants entirely.
    assert CB["jochemnet"]["fixture_deflate"] < 0.05 and CB["state_actor"]["fixture_deflate"] < 0.05, \
        "the fixture contracts are no longer near-free to store"
    assert CB["small_block"]["tenants"] == 0, "the smaller block still admits co-tenants"
    assert reuse["jochemnet"]["per_code"] > 10 > reuse["state_actor"]["per_code"], \
        "the bytecode-reuse gap the residual rests on has closed"
    assert 1.4 < CB["state_actor"]["block_comp"] / CB["jochemnet"]["block_comp"] < 2.6, \
        "the modelled block no longer brackets the measured code-read ratio"
    assert 1.4 < code_bpg["ratio"] < 2.6, f"code-read ratio moved: {code_bpg['ratio']:.2f}"
    assert abs(drain_ctrl - 1) <= 0.05 and abs(comp_ctrl - 1) <= 0.05, \
        f"the treatment moved the control: drain {drain_ctrl:.3f}, compact {comp_ctrl:.3f}"
    # the code-cf paragraph states a direction for each of these; fail if the data flips
    assert props["state_actor"]["07"]["mean_record"] < props["jochemnet"]["07"]["mean_record"], \
        "generated code records are no longer the smaller ones"
    assert (props["state_actor"]["07"]["phys_over_logical"]
            > props["jochemnet"]["07"]["phys_over_logical"]), \
        "generated code records are no longer the less compressible ones"
    assert g06s["mean_record"] > g06j["mean_record"] and comp_ratio > 1 and blk_ratio > 1, \
        "cf06 geometry chain no longer runs in the direction the prose states"

    print(f"common: full {len(common)} ({len(meas)} measured + {len(ctrls)} control) "
          f"filtered {len(commonf)} ({len(measf)} + {len(ctrlsf)})")
    print(f"control: sa/compacted {ctrl_vs_comp:.3f} per-category "
          f"{min(ctrl_cats.values()):.3f}-{max(ctrl_cats.values()):.3f}; "
          f"treatment moves it drain {drain_ctrl:.3f} compact {comp_ctrl:.3f}")
    print(f"survivors: dark {len(dark)} median {median([r[4] for r in dark]):.3f}; "
          f"light {len(light)} median {median([r[4] for r in light]):.3f}")
    print(f"code read: {code_bpg['compacted']:.1f} vs {code_bpg['state_actor']:.1f} B/gas "
          f"= {code_bpg['ratio']:.2f}x; modelled block "
          f"{CB['state_actor']['block_comp']/CB['jochemnet']['block_comp']:.2f}x; "
          f"at {CB['small_block']['block_size']//1024} KiB "
          f"{CB['small_block']['jochemnet_comp']} vs {CB['small_block']['state_actor_comp']} B")
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
        "outcome": (chart_outcome(V3["categories"], BAND, V4CAT),
                    f"The same {len(V3['categories'])} categories before the three fixes and "
                    f"after them. Two mechanisms pull their categories into the band; the "
                    + (f"sixteen that read a distinct contract went straight through it under "
                       f"#{PR[138]['n']}, to {V3['classes']['dark']['v3']:.3f}&times;, and sit at "
                       f"{V4['classes']['dark']['v4']:.3f}&times; on the store built from "
                       f"#{V4['pr']}, the third dot on those rows. The other "
                       f"{len(V3['categories']) - 16} categories were not rerun for it."
                       if V4 else
                       f"sixteen that read a distinct contract go straight through it, to "
                       f"{V3['classes']['dark']['v3']:.3f}&times;.")
                    + " Log scale, same reference as the first figure."),
        "ratio_dots": (chart_ratio_dots(F, meas),
                       f"Throughput of the generated store divided by the compacted "
                       f"snapshot's, one dot per opcode and account mode, log scale. "
                       f"1× would mean the two databases cost the same."),
        "treatment_dumbbell": (chart_treatment_dumbbell(FT, measf),
                               "What each half of the treatment does. Draining the "
                               "write-ahead log leaves the store where it started; compaction "
                               "moves it. Reference is the plain snapshot, the only figure "
                               "here that uses it."),
        "lsm_levels": (chart_lsm_levels(levels),
                       f"Where the pre-run's rows sit. After the pre-run, cf06 holds "
                       f"{l0_06} files at the top of the tree against {l6_06} at the bottom; "
                       "after compaction the top is empty. A lookup for a recently written "
                       "account reaches those few files before it descends."),
        "bloom": (chart_bloom(props, sa_bytes),
                  "The snapshot carries a bloom filter on every state column family. The "
                  "generated store carries none, so a lookup that will find nothing cannot be "
                  "rejected, so it has to read index and data blocks instead."),
        "geometry": (chart_geometry(props, GREF),
                     "The residual, as store geometry. Generated records are larger and "
                     "compress worse, so a data block holds fewer of them and a read moves "
                     "more bytes. Geth's two ratios, measured on a different engine with a "
                     "different compression algorithm, are printed for comparison."),
        "cost_curves": (chart_cost_curves(F, meas),
                        "Throughput against the gas budget. The lines stay separated rather "
                        "than converging, so the gap is a per-read cost and not a fixed "
                        "per-block overhead being amortised."),
        "convergence": (chart_convergence(FT, measf),
                        "Every arm against the compacted snapshot. Once the snapshot is "
                        "compacted the generated store is within a few percent on reads that "
                        "find their key, and an order of magnitude away on reads that do not."),
        "verdict": (chart_verdict(verdict, BAND),
                    f"The same {len(verdict)} categories as the first figure, each one measured "
                    f"against the snapshot as published and then against the same snapshot "
                    f"compacted. Nothing about the generated store changed between the two "
                    f"dots. {cat_after} of {len(verdict)} land inside ±{BAND*100:.0f}% of "
                    f"parity. Of the {len(verdict) - cat_after} that do not, {n_absent} are the "
                    f"absence categories, which barely move at all, and {len(dark)} are the "
                    f"categories that read a distinct contract on every access, which move most "
                    f"of the way and stop short."),
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
      "performance? State-actor vs a mainnet snapshot</title>")
    w(f"<style>{CSS}</style></head><body>")

    w('<div class=topbar><a href="../">&larr; all articles</a>'
      '<span>EXECUTION · STATE DB</span></div>')
    w('<div class=eyebrow>// REPORT</div>')
    w(f"<h1>How can two Besu databases holding the same state differ {factor}&times; in "
      "performance?</h1>")
    w("<p class=deck>A case study on state-actor versus a Bonsai mainnet-snapshot database, "
      "and on why a published snapshot has to be compacted before it can be measured "
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
      f"run against each of them, on the same host and the same NVMe drive. "
      f"{thousands(len(meas))} of those tests do account-state work; the other "
      f"{thousands(len(ctrls))} are controls that run the same loop and deliberately touch no "
      f"state, and they are kept out of every comparison below and reported on their own. Gas matches across "
      f"all three to six significant figures, so each one was asked to do the same work. "
      f"Throughput does not match. On the tests that look up an account which is not there, "
      f"the generated store is <b>{headline:.1f}&times; slower</b> than the published "
      f"snapshot.</p>")
    w(f"<p>That is the number in the title. It is also mostly an accident of how the two "
      f"stores were built, rather than anything about how Besu reads them. There are two "
      f"separate accidents, and each one shows up on a different kind of read.</p>")
    w(f"<p>Every dot below is one test category against the compacted snapshot, and they fall "
      f"into two groups about ten times apart: the {n_absent} that must prove an account is "
      f"absent, and the {len(ex_cat)} that read one which exists. Two groups, two "
      f"causes.</p>")
    w(fig("ratio_dots"))
    w("<table><tr><th>bucket</th><th>tests</th>"
      "<th class=n>state-actor ÷ plain</th><th class=n>state-actor ÷ compacted</th>"
      "<th class=n>plain ÷ compacted</th></tr>")
    for b in BUCKETS:
        n = sum(1 for c in meas if F["plain"][c]["bucket"] == b)
        w(f"<tr><td>{b}</td><td class=n>{n}</td>"
          f"<td class=n>{sa_vs_plain[b]:.3f}</td>"
          f"<td class=n>{sa_vs_comp[b]:.3f}</td>"
          f"<td class=n>{plain_vs_comp[b]:.3f}</td></tr>")
    w(f"<tr><td><b>control</b></td><td class=n>{len(ctrls)}</td>"
      f"<td class=n>{median([F['state_actor'][c]['mgas_s'] / F['plain'][c]['mgas_s'] for c in ctrls]):.3f}</td>"
      f"<td class=n>{ctrl_vs_comp:.3f}</td>"
      f"<td class=n>{median([F['plain'][c]['mgas_s'] / F['compacted'][c]['mgas_s'] for c in ctrls]):.3f}</td>"
      f"</tr>")
    w("</table>")

    w('<h3>Outside the absent class, the residual comes in two tiers</h3>')
    w(f"<p>Against the compacted snapshot, every one of the {len(ex_cat)} categories that "
      f"read an account which exists favours the snapshot, by a median of {pc(ex_med)}. They "
      f"do not all favour it equally, and the split is not noise: the "
      f"{len(light)} categories whose contract code is shared or absent sit at "
      f"{pc(median([r[4] for r in light]))}, while the {len(dark)} that read a distinct "
      f"contract on every access sit at {pc(median([r[4] for r in dark]))}. That gap is the "
      f"subject of the last section. Everything larger than it is a property of how one of the "
      f"stores was built.</p>")

    # ===================================================================== 2
    w('<h2>What Besu\'s own logs and counters say</h2>')
    w("<p>Besu states its own configuration at startup, and two of those lines matter.</p>")
    w("<pre class=log>Existing database at /data. Metadata "
      "versionedStorageFormat=BaseVersionedStorageFormat{format=BONSAI, version=3}. "
      "Processing WAL...</pre>")
    w(f"<p>That one appears on every boot of every arm, including the arm whose write-ahead "
      f"log is {C['after_flush']['wal_bytes']} bytes long, so it is boot-time boilerplate "
      f"rather than evidence of work. The second is the one that shapes the rest:</p>")
    w("<pre class=log>Flat db mode found FULL</pre>")
    w(f"<p>Account reads go to Bonsai's flat keyspace, not down the trie. The metrics agree "
      f"{P['flat_read_share']*100:.2f}% of account lookups are served from the flat "
      f"database.</p>")
    w("<p>That matters because it fixes what a read costs. An account lookup is one key in one "
      "column family, so the cost is the cost of locating that key: how many files have to "
      "be consulted, and how many bytes each consultation moves. It is not a tree walk whose "
      "depth grows with the state, which is the shape most people expect.</p>")
    w("<table><tr><th>account_mode</th>"
      "<th class=n>lookups that found nothing ÷ total, compacted snapshot</th>"
      "<th class=n>state-actor</th></tr>")
    for m in sorted(set(miss.get("compacted", {})) & set(miss.get("state_actor", {}))):
        w(f"<tr><td><code>{m}</code></td>"
          f"<td class=n>{miss['compacted'][m]:.3f}</td>"
          f"<td class=n>{miss['state_actor'][m]:.3f}</td></tr>")
    w("<caption>Besu counts flat-database lookups that find no key. The absence categories "
      "probe addresses that are genuinely absent from both stores, so the difference in "
      "what they cost is not a difference in what they find.</caption></table>")

    # ===================================================================== 3
    w('<h2>What we ruled out first</h2>')
    w(f"<p>Both stores run byte-identical RocksDB settings on every state column family, "
      f"<code>compression={P['compression']}</code> and "
      f"<code>block_size={thousands(P['block_size'])}</code>. The extraction is "
      f"deterministic across three independent unpacks. Trie logs are disabled on both. "
      f"Whole-store totals are not comparable, because the snapshot carries "
      f"{C['shipped']['blob_bytes']/1e9:.0f} GB of chain history the generated store does "
      f"not have, so every comparison in this article is per column family.</p>")
    w('<h3>What the fixtures actually touch</h3>')
    w(f"<p>The suite is {len(set((c[0], c[1]) for c in common))} opcode/account-mode categories "
      f"across {len(sorted({c[2] for c in common}))} gas budgets from "
      f"{min(c[2] for c in common)}M to {max(c[2] for c in common)}M. They split into three "
      f"groups that behave so differently that any single median over them describes none of "
      f"them: ")
    w("<ul class=tight>")
    for b in BUCKETS:
        n = sum(1 for c in common if F["plain"][c]["bucket"] == b)
        w(f"<li><b>{b}</b> ({n} tests): {esc(BUCKET_DOC[b])}.</li>")
    w("</ul>")

    # ===================================================================== 4
    w('<h2>The file that looks like the cause: a '
      '1.2 GB write-ahead log</h2>')
    w(f"<p>The published snapshot ships a write-ahead log of "
      f"{thousands(C['shipped']['wal_bytes'])} bytes, which is exactly the shape of a "
      f"benchmark artifact: state that lives in one place on disk and another in memory, "
      f"restored on every boot.</p>")
    w(f"<p>It is inert. Its size varies "
      f"{abs(C['after_prerun']['wal_bytes'] / C['after_prerun_repeat']['wal_bytes'] - 1)*100:.0f}% "
      f"between identical replays, a poor cause for an effect that reproduces. Draining it "
      f"adds no SST file, because RocksDB's open path had already recovered and flushed it "
      f"before any test ran. And measured end to end, draining changes nothing.</p>")
    w(fig("treatment_dumbbell"))

    # ===================================================================== 5
    w('<h2>The root cause: the pre-run\'s rows are the newest versions of their keys</h2>')
    w(f"<p>Before each test the harness replays a pre-run bundle: "
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
      f"files at the top of the tree, "
      f"{levels['before']['06']['0']['bytes']/1e6:.0f} MB of it, above {l6_06} files "
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
    w(f"<tr><td><b>control</b></td><td class=n>{drain_ctrl:.3f}</td>"
      f"<td class=n>{comp_ctrl:.3f}</td><td class=n colspan=2>&nbsp;</td></tr>")
    w("<caption>Throughput and bytes read, each against the plain snapshot. The drain "
      "contributes nothing; the compaction contributes everything. Neither moves the control, "
      "so neither is doing something to the harness rather than to the store.</caption></table>")
    w(f"<p>Now measure the generated store against the treated snapshot instead of the "
      f"published one. Nothing about the generated store changed, so whatever moves is the "
      f"artifact leaving. Take agreement to within ±{BAND*100:.0f}% of parity as the bar: "
      f"<b>{cat_before} of {len(verdict)}</b> categories cleared it against the snapshot as "
      f"published, and <b>{cat_after} of {len(verdict)}</b> clear it against the compacted "
      f"one. Per measurement workload rather than per category, "
      f"{100*wl_before/len(meas):.0f}% becomes {100*wl_after/len(meas):.0f}%.</p>")
    w(f"<p>Clearing a ±{BAND*100:.0f}% band is not agreeing. Not one of the {len(verdict)} "
      f"categories reaches parity, the closest being {best_cat[1]}&nbsp;"
      f"{SHORT_MODE[best_cat[2]]} at {best_cat[4]:.3f}&times;, and not one of the "
      f"{len(meas)} measurement workloads is faster than the snapshot.</p>")
    w(fig("verdict"))
    w(f"<p>The {cat_after} that converge are the categories whose contract code is shared "
      f"or absent, and they land at a median of {pc(median([r[4] for r in light]))} off "
      f"parity, down from "
      f"{pc(median([r[3] for r in light]))}. Two groups stay outside, with two different "
      f"causes already named: the {n_absent} absence categories, still "
      f"{1/median([r[4] for r in verdict if r[0] == 'absent']):.1f}&times; apart, and the "
      f"{len(dark)} that read a distinct contract on every access, which close to "
      f"{pc(median([r[4] for r in dark]))} and no further. The first is the next section; the "
      f"second is the last one.</p>")
    w(fig("convergence"))
    w(fig("cost_curves"))

    # ===================================================================== 7
    w(f'<h2>Why absence proofs cost {sa_bytes["absent"]:.0f}&times; the '
      f'bytes: the generated store has no bloom filters</h2>')
    w(f"<p>The absence categories probe addresses that are missing from both stores. The "
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
      f"read that block anyway, so the filters buy little there, "
      + " and ".join(f"{sa_bytes[b]:.2f}&times; on {b}" for b in BUCKETS if b != "absent") +
      f", against {sa_bytes['absent']:.1f}&times; when there is nothing to find. This is "
      f"a property of how the generated store was written, not of what it contains.</p>")
    w(f"<p>This one was already fixed upstream before the store was built. "
      f"<a href=\"https://github.com/ethereum/state-actor/pull/{PR[133]['n']}\">"
      f"state-actor #{PR[133]['n']}</a> ({PR[133]['sha']}) put a full bloom filter at "
      f"{ST['filters']['bits_per_key']:.0f} bits/key on every column family and merged on "
      f"{PR[133]['merged']}; the store measured here was generated on "
      f"{ST['measured_store_built']} from a working tree "
      f"(<code>{D['provenance']['state_actor_source']}</code>) that predated it by "
      f"{DAYS_STALE} days. So the 50&times; is real, reproducible from the archived store, and "
      f"our own doing: we measured a build that had already been superseded.</p>")


    # ===================================================================== 8
    w('<h2>The residual</h2>')
    w(f"<p>What is left after both artifacts is small, consistent, and in two tiers. Against "
      f"the compacted snapshot every one of the {len(ex_cat)} categories that reads an "
      f"existing account favours the snapshot, but the {len(light)} whose code is shared or "
      f"absent sit at {pc(median([r[4] for r in light]))} while the {len(dark)} that read a "
      f"distinct contract per access sit at {pc(median([r[4] for r in dark]))}. Order the "
      f"classes by how much unique contract code they touch and you have ordered the "
      f"residual, which is the whole of this section.</p>")
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
    w(f"<p>Compression {comp_ratio:.3f}&times; and block size {blk_ratio:.3f}&times;; geth "
      f"measured {GREF['compression_ratio']:.3f}&times; and "
      f"{GREF['block_size_ratio']:.3f}&times; on a different engine, so this is not an "
      f"artifact of one. The cause is a single property: mainnet reuses each bytecode about "
      f"{reuse['jochemnet']['per_code']:.0f} times, and the generated store reused none, "
      f"{thousands(round(reuse['jochemnet']['contracts']))} contract accounts resolving to "
      f"{thousands(reuse['jochemnet']['codes'])} distinct bytecodes against "
      f"{thousands(round(reuse['state_actor']['contracts']))} resolving to "
      f"{thousands(reuse['state_actor']['codes'])}. A shared code hash compresses and a "
      f"unique one does not, and a code read pays block padding for its neighbours. "
      f"<a href=\"https://github.com/ethereum/state-actor/pull/{PR[137]['n']}\">#{PR[137]['n']}</a> "
      f"and <a href=\"https://github.com/ethereum/state-actor/pull/{PR[138]['n']}\">#{PR[138]['n']}</a> "
      f"fix both: designators from a fixed pool of 256, bytecode from a shared pool sized to "
      f"mainnet's reuse. On a store built from them, account records go from "
      f"{props['state_actor']['06']['phys_over_logical']:.3f} to "
      f"{ST['after']['cf06_phys']:.3f} physical over logical against the snapshot's "
      f"{ST['target']['cf06_phys']:.3f}.</p>")
    w('<h3>The code half is not the code being read</h3>')
    w(f"<p>The same chain does not explain the {len(dark)} distinct-code categories. "
      f"Subtracting the account-only classes isolates the code read: "
      f"{code_bpg['compacted']:.1f} extra bytes per gas on the snapshot against "
      f"{code_bpg['state_actor']:.1f} on the generated store, a factor of "
      f"<b>{code_bpg['ratio']:.2f}</b>. The obvious reading, less compressible code, is "
      f"wrong: the {thousands(CB['fixture_bytes'])}-byte fixture contracts deflate to "
      f"{CB['jochemnet']['fixture_deflate']:.4f} and "
      f"{CB['state_actor']['fixture_deflate']:.4f} of their size, near-free to store in "
      f"both.</p>")
    w(f"<p>What a lookup pays for is the block. RocksDB closes a data block past "
      f"{thousands(CB['block_size'])} bytes, so a {thousands(CB['fixture_bytes'])}-byte "
      f"contract shares it with whatever follows in code-hash order, a sample of each "
      f"store's contract population.</p>")
    w("<table><tr><th>per data block holding one fixture contract</th>"
      "<th class=n>snapshot</th><th class=n>state-actor</th></tr>")
    for lbl, k, fmt in (("the contract itself, compressed", "fixture_deflate", "{:.4f} of raw"),
                        ("co-tenant records", "tenants", "{:.1f}"),
                        ("mean co-tenant size", "tenant_bytes", "{:,.0f} B"),
                        ("block, uncompressed", "block_raw", "{:,.0f} B"),
                        ("block, compressed", "block_comp", "{:,.0f} B")):
        w(f"<tr><td>{lbl}</td><td class=n>{fmt.format(CB['jochemnet'][k])}</td>"
          f"<td class=n>{fmt.format(CB['state_actor'][k])}</td></tr>")
    w(f"<caption>Modelled from each store's own code column family by packing records the way "
      f"RocksDB does. The snapshot's co-tenants are a couple of mainnet contracts that "
      f"compress; the generated store's are {CB['state_actor']['tenants']:.0f} small ones that "
      f"do not. That is "
      f"{CB['state_actor']['block_comp']/CB['jochemnet']['block_comp']:.2f}&times; on the "
      f"block against {code_bpg['ratio']:.2f}&times; measured on the read.</caption></table>")
    w(f"<p>The generated store held "
      f"{thousands(props['state_actor']['07']['entries'])} contracts averaging "
      f"{props['state_actor']['07']['mean_record']:,.0f} bytes against the snapshot's "
      f"{thousands(props['jochemnet']['07']['entries'])} averaging "
      f"{props['jochemnet']['07']['mean_record']:,.0f}: many times as many, each a "
      f"fraction of the size, every one unique. A code read pays for its neighbours. That "
      f"is fixable by shrinking the block or by giving the generator a mainnet-shaped "
      f"population, and the second was taken.</p>")
    w(f"<p><a href=\"https://github.com/ethereum/state-actor/pull/{PR[138]['n']}\">"
      f"#{PR[138]['n']}</a> went too far. Its pool is one real ERC20 runtime of about "
      f"1.7 KB, tiled to the sampled size and rotated per entry, so entries are self-similar "
      f"inside themselves and to each other. On a store built from it the code column "
      f"family compresses to {ST['after']['cf07_phys']:.3f} physical over logical against "
      f"mainnet's {ST['target']['cf07_phys']:.3f}, "
      f"{ST['target']['cf07_phys'] / ST['after']['cf07_phys']:.1f}&times; too "
      f"compressible. Mainnet code compresses because many <em>different</em> contracts "
      f"repeat across accounts, not because one repeats inside itself. The fix is a "
      f"corpus.</p>")
    w(f"<p>Measured rather than modelled: one cold read of a "
      f"{thousands(CB['fixture_bytes'])}-byte contract, page cache dropped, moves "
      f"{thousands(ST['code_read']['sa_bytes'])} bytes from disk on the generated store "
      f"against {thousands(ST['code_read']['snap_bytes'])} on the snapshot, a factor of "
      f"{ST['code_read']['sa_bytes'] / ST['code_read']['snap_bytes']:.0f}, for the same "
      f"contracts in both.</p>")
    w('<h2>Where this stands</h2>')
    w(fig("outcome"))
    w(f"<p>All three fixes are merged, and the suite has been run again against a store "
      f"regenerated from them. The expectations in the table below were written down before "
      f"that store existed, from store-level measurements alone; the last column is what the "
      f"rerun measured. {V3['measurement']} measurement workloads and {V3['control']} controls, "
      f"the same grid as the rest of this article, with gas identical to six figures on every "
      f"one of the {thousands(V3['tests'])} tests.</p>")
    w("<table><tr><th>class</th><th class=n>cats</th><th>mechanism</th><th>fix</th>"
      "<th class=n>before</th><th class=n>expected</th><th class=n>measured</th>"
      + (f"<th class=n>after #{V4['pr']}</th>" if V4 else "") + "</tr>")
    for cls, key, mech, pr, exp in (
            ("absent", "absent", "no bloom filter on any column family",
             f"#{PR[133]['n']}, not ours", "parity"),
            ("shared or absent code", "light", "unique code hashes and designators",
             f"#{PR[137]['n']} + #{PR[138]['n']}", "rises"),
            ("distinct code", "dark", "block co-tenancy, not compressibility",
             f"#{PR[138]['n']} overshoots", "inverts")):
        c = V3["classes"][key]
        w(f"<tr><td>{cls}</td><td class=n>{c['categories']}</td><td>{mech}</td><td>{pr}</td>"
          f"<td class=n>{c['archived']:.3f}&times;</td><td class=n>{exp}</td>"
          f"<td class=n><b>{c['v3']:.3f}&times;</b></td>"
          + (f"<td class=n><b>{V4['classes']['dark']['v4']:.3f}&times;</b></td>" if V4 and key == "dark"
             else "<td class=n>not rerun</td>" if V4 else "") + "</tr>")
    w(f"<caption>state-actor &divide; snapshot, per class, before and after the three fixes. "
      f"Above 1.0 means the generated store is now the faster of the two. "
      f"{V3['faster_rows']} of {thousands(V3['measurement'])} workloads are, against none "
      f"of them before.</caption></table>")
    w(f"<p>Two of the three went where the store-level numbers said they would. The absence "
      f"class, {1/sa_vs_comp['absent']:.1f}&times; apart and the reason this article has an "
      f"{factor}&times; in its title, is at "
      f"{V3['classes']['absent']['v3']:.3f}&times;: gone, not reduced. The classes whose code "
      f"is shared or absent moved from {V3['classes']['light']['archived']:.3f} to "
      f"{V3['classes']['light']['v3']:.3f}&times;, which is close to parity and not at it.</p>")
    w(f"<p>The third did not close. It <em>inverted</em>: the categories that read a distinct "
      f"contract on every access went from {V3['classes']['dark']['archived']:.3f}&times; to "
      f"<b>{V3['classes']['dark']['v3']:.3f}&times;</b>, so the generated store is now "
      f"{pc(V3['classes']['dark']['v3'])} <em>faster</em> than the snapshot on exactly the "
      f"reads it used to be slower on. That is the "
      f"{ST['target']['cf07_phys'] / ST['after']['cf07_phys']:.1f}&times; over-compression of "
      f"the previous section arriving as throughput. A store that is too fast is as wrong as a "
      f"store that is too slow, and it is harder to notice, because nothing looks broken.</p>")
    w(f"<p>The gas budget separates the two outcomes cleanly. Across {len(GAS)} budgets from "
      f"{min(GAS)}M to {max(GAS)}M the absence class now sits flat between "
      f"{min(V3['gradient']['absent']):.3f} and {max(V3['gradient']['absent']):.3f} with no "
      f"trend, where before it fell from {grad['absent'][0]:.3f} to {grad['absent'][-1]:.3f}. "
      f"A flat line is what a removed mechanism looks like; a shallower slope would only be a "
      f"smaller one. The distinct-code class does the opposite and climbs monotonically from "
      f"{V3['gradient']['dark'][0]:.3f} to {V3['gradient']['dark'][-1]:.3f}: the more reads a "
      f"block does, the further ahead the over-compressed store gets.</p>")
    w(f"<p>One caveat. A stateful fixture is anchored to the genesis of the store it was "
      f"filled against, so the rerun needed refilled payloads and the two arms cannot share "
      f"a bundle. The control workloads, which touch no account state, say the comparison "
      f"survived that: {V3['control_ratio']:.4f}&times; against "
      f"{V3['control_archived']:.4f}&times; on the original arm, flat within "
      f"{max(V3['gradient']['control']) - min(V3['gradient']['control']):.3f} across "
      f"every budget.</p>")
    if V4:
        G, T = V4["store_geom"], ST["target"]
        d4, d3, d1 = V4["classes"]["dark"]["v4"], V3["classes"]["dark"]["v3"], V3["classes"]["dark"]["archived"]
        w(f'<h3>The corpus fix, measured</h3>')
        w(f"<p><a href=\"https://github.com/ethereum/state-actor/pull/{V4['pr']}\">#{V4['pr']}</a> "
          f"replaces the tiled runtime with windows into {V4['corpus_contracts']} real mainnet "
          f"contracts, one contract per pool entry, never tiled. On the same 4 GB basis as the "
          f"{ST['after']['cf07_phys']:.3f} above, a store built from it compresses its code column "
          f"family to {G['cf07']:.3f} physical over logical, its records deflate to "
          f"{G['record_deflate']:.3f} against mainnet's {T['record_deflate']:.3f}, and the "
          f"co-tenant payload beside a fixture contract to {G['packed']:.3f} against "
          f"{V4['mainnet_packed_same_probe']:.3f} measured on the snapshot with the same probe: "
          f"the pool now compresses like the population it stands in for. The account column "
          f"family, which the pool does not touch, reads {G['cf06']:.3f}.</p>")
        w(f"<p>Only the sixteen distinct-code categories were refilled and rerun, against a "
          f"{V4['store_gb']} GB store generated the same way as the previous rerun's, "
          f"at {len(V4['budgets'])} gas budgets: {V4['measurement']} measurement workloads and "
          f"{V4['control']} controls, gas identical to six figures on every one. The other "
          f"classes never read the pool, and a spot check of {V4['spot']['absent']['rows']} absent "
          f"and {V4['spot']['light']['rows']} shared-code workloads at {min(V4['budgets'])}M put them "
          f"at {V4['spot']['absent']['v4_ratio']:.3f} and {V4['spot']['light']['v4_ratio']:.3f}&times;, "
          f"where the previous rerun had {V4['spot']['absent']['v3_ratio']:.3f} and "
          f"{V4['spot']['light']['v3_ratio']:.3f}.</p>")
        if V4["verdict"] == "in_band":
            w(f"<p>The distinct-code class is at <b>{d4:.3f}&times;</b>: {d1:.3f} before the fixes, "
              f"{d3:.3f} under the tiled pool, inside the &plusmn;{V4['band']*100:.0f}% band now. "
              f"{V4['inband_rows']} of {V4['measurement']} workloads are inside it and "
              f"{V4['categories_closer']} of 16 categories sit closer to parity than they did, "
              f"the rows spanning {V4['row_min']:.3f} to {V4['row_max']:.3f}&times;. "
              f"Across the budgets the class moves from {V4['gradient']['dark'][0]:.3f} to "
              f"{V4['gradient']['dark'][-1]:.3f}: the slope that grew with every extra read under "
              f"the tiled pool is gone. Three mechanisms, three closures.</p>")
        elif V4["verdict"] == "above":
            DK = V4["disk"]
            w(f"<p>The distinct-code class is at <b>{d4:.3f}&times;</b>: {d1:.3f} before the fixes, "
              f"{d3:.3f} under the tiled pool, still {pc(d4)} faster than the snapshot and outside "
              f"the &plusmn;{V4['band']*100:.0f}% band. {V4['categories_closer']} of 16 categories "
              f"moved toward parity, the rows spanning {V4['row_min']:.3f} to "
              f"{V4['row_max']:.3f}&times;, and the budget gradient still climbs, "
              f"{V4['gradient']['dark'][0]:.3f} to {V4['gradient']['dark'][-1]:.3f}.</p>")
            R = V4["residual"]
            PL, PF, CL = R["per_lookup_kib"], R["prefetched"], R["cf_lookup"]
            w(f"<p>What is left is not compressibility, and it is not the pool. Per workload the "
              f"generated store moves {DK['v4_over_mainnet'][0]:.2f} to "
              f"{DK['v4_over_mainnet'][-1]:.2f} of what the snapshot moves for the same gas, where "
              f"the original store moved {DK['v1_over_mainnet'][0]:.2f} to "
              f"{DK['v1_over_mainnet'][-1]:.2f}, and throughput follows that byte ratio at every "
              f"budget. Those bytes are not the opcode's own lookups: a "
              f"{R['counted_reads_per_test']['gas']}M test counts "
              f"{thousands(R['counted_reads_per_test']['reads'])} account reads and moves "
              f"{R['counted_reads_per_test']['bytes_gb']:.1f} GB. Besu prefetches every account in "
              f"the block access list, and the two arms prefetch the same ones, "
              f"{thousands(PF['snapshot_compacted']['100'])} against {thousands(PF['v4']['100'])} at "
              f"100M and within {R['work_mismatch']*100:.1f}% at every budget. Same work, and the "
              f"generated store still reads a quarter less for it.</p>")
            w("<table><tr><th>store</th><th class=n>100M</th><th class=n>200M</th>"
              "<th class=n>300M</th></tr>")
            for lbl, k in (("snapshot, as it ships", "snapshot_plain"),
                           ("snapshot, compacted: the reference used here", "snapshot_compacted"),
                           (f"generated, tiled pool (#{PR[138]['n']})", "v3"),
                           (f"generated, corpus pool (#{V4['pr']})", "v4")):
                w(f"<tr><td>{lbl}</td>" + "".join(f"<td class=n>{PL[k][g]:.0f}</td>"
                                                  for g in ("100", "200", "300")) + "</tr>")
            w(f"<caption>KiB read from disk per prefetched account, the workload's dominant cost. "
              f"The code column family is {R['code_cf_share_of_store']*100:.2f}% of the generated "
              f"store's bytes, so whatever this is, the pool is not it.</caption></table>")
            w(f"<p>It is also not the cost of a lookup. Drawing "
              f"{thousands(30000)} keys uniformly across each store and reading them cold, with the "
              f"bloom filters Besu configures, an account costs "
              f"{CL['cf06']['snapshot_bytes']/1024:.1f} KiB on the snapshot against "
              f"{CL['cf06']['v4_bytes']/1024:.1f} on the generated store, and a trie node "
              f"{CL['cf09']['snapshot_bytes']/1024:.1f} against "
              f"{CL['cf09']['v4_bytes']/1024:.1f}: {R['cf_lookup_ratio']['cf06']:.2f} and "
              f"{R['cf_lookup_ratio']['cf09']:.2f}, pointing opposite ways, neither of them "
              f"{R['ratio_v4_over_snapshot']:.2f}. Both stores answer a lookup with almost exactly "
              f"one data block read.</p>")
            PD = V4["paired"]
            RF = PD["reference"]
            w(f"<h3>The residual depends on the disk</h3>")
            w(f"<p>The compacted snapshot every ratio here divides by was prepared once and reused, "
              f"so it was rebuilt from scratch to check it: the published snapshot copied off the "
              f"read-only original ({thousands(RF['bytes_gb'])} GB) and put through the same flush "
              f"and compaction ({RF['compaction_seconds']:,} s). It comes out in the same shape, "
              f"file for file. What it does not reproduce is the cost, and the reason turned out to "
              f"be the disk: the <em>same</em> generated store, same method, same tests, moves "
              f"{PD['same_store_bytes_nvme_gb']:.2f} GB per test on the NVMe path and "
              f"{PD['same_store_bytes_hdd_gb']:.2f} GB on the HDD array, a factor of "
              f"{PD['device_byte_factor']:.1f}. Byte counts here are not portable between media, "
              f"and neither, it turns out, is the ratio.</p>")
            w(f"<p>Re-run as a pair on the array, both stores on the same device and method, same "
              f"host and image, {PD['tests_per_arm']} tests each at {PD['gas']}M gas, "
              f"{PD['measurement']} categories with their {PD['control']} controls:</p>")
            w("<table><tr><th>opcode</th><th>mode</th>"
              "<th class=n>NVMe arms</th><th class=n>array, corrected</th></tr>")
            for op, m, old, _raw, cor in PD["categories"]:
                w(f"<tr><td>{op}</td><td>{SHORT_MODE.get(m, m)}</td>"
                  f"<td class=n>{old:.3f}&times;</td><td class=n><b>{cor:.3f}&times;</b></td></tr>")
            w(f"<caption>The same categories on two media. On the array the median is "
              f"{PD['median']:.3f}, spanning {PD['min']:.3f} to {PD['max']:.3f}, all "
              f"{PD['inband']} inside &plusmn;{PD['band']*100:.0f}%. That arm's controls, which do "
              f"no account-state work, sit {PD['control_offset']:.3f} apart against "
              f"{PD['original_control_offset']:.3f} on the NVMe arms, and the correction for it is "
              f"doing real work in that column.</caption></table>")
            w(f"<p>So the class reads {V4['classes']['dark']['v4']:.3f} on NVMe and "
              f"{PD['median']:.3f} on the array, and this study cannot currently say which is the "
              f"property of the store rather than of the disk under it. The NVMe figure is the one "
              f"measured on the medium a node actually runs on, and it stands. The array pair is the "
              f"only comparison whose reference was built for it, and it says parity. Settling that "
              f"needs both stores on NVMe at once, which needs {thousands(RF['bytes_gb'] + 489)} GB "
              f"of it, and this host has {thousands(932)}.</p>")
            if V4.get("arm_b"):
                AB = V4["arm_b"]
                w(f"<p>The other {len(AB['budgets'])} budgets, run afterwards as a second arm of "
                  f"{AB['tests']} tests, fill the gradient in monotonically, "
                  f"{AB['gradient']['dark'][0]:.3f} at {AB['budgets'][0]}M to "
                  f"{AB['gradient']['dark'][-1]:.3f} at {AB['budgets'][-1]}M, and the byte ratio "
                  f"with it, {AB['disk']['v4_over_mainnet'][0]:.3f} to "
                  f"{AB['disk']['v4_over_mainnet'][-1]:.3f}. That arm's controls sat at "
                  f"{AB['control_ratio']:.3f}&times; against the archived {V4['control_archived']:.3f}, "
                  f"outside the tolerance this comparison is held to, so its points are shown and "
                  f"not counted.</p>")
        elif V4["verdict"] == "below":
            w(f"<p>The distinct-code class is at <b>{d4:.3f}&times;</b>: {d1:.3f} before the fixes, "
              f"{d3:.3f} under the tiled pool, now {pc(d4)} slower than the snapshot again and outside "
              f"the &plusmn;{V4['band']*100:.0f}% band on the original side. "
              f"{V4['categories_closer']} of 16 categories moved toward parity and {V4['inband_rows']} "
              f"of {V4['measurement']} workloads are inside the band, the rows spanning "
              f"{V4['row_min']:.3f} to {V4['row_max']:.3f}&times;. The budget gradient runs "
              f"{V4['gradient']['dark'][0]:.3f} to {V4['gradient']['dark'][-1]:.3f}. Two pools "
              f"bracket parity from either side; the class is sensitive to code content beyond what "
              f"the compressibility ratios capture, and that sensitivity is the open thread.</p>")
        else:
            w(f"<p>The distinct-code class measured <b>{d4:.3f}&times;</b> against {d3:.3f} under the "
              f"tiled pool, but the control canary on this arm sat at {V4['control_ratio']:.4f}&times; "
              f"against the archived {V4['control_archived']:.3f}, outside the {0.013} tolerance, so "
              f"the archived arm cannot carry a band claim for it. The direction is safe to state; "
              f"the magnitude waits for a rebuilt snapshot arm.</p>")
        w(f"<p>The control canary on this arm: {V4['control_ratio']:.4f}&times; against "
          f"{V4['control_archived']:.3f}&times; on the original, per-budget medians within "
          f"{V4['control_drift']:.3f}.</p>")



    w("<details><summary>What this article does not settle</summary>")
    w("<ul class=tight>")
    w(f"<li>Why the code-reusing classes stop at {pc(V3['classes']['light']['v3'])} off parity "
      f"rather than reaching it. The cf06 block geometry is the right shape, "
      f"{g06s['block_bytes']/g06j['block_bytes']:.2f}&times; predicted against "
      f"{sa_bytes['leaf-only']:.2f}&times; measured, but the remainder has no mechanism "
      f"named.</li>")
    if not V4:
        w(f"<li>What a bytecode pool shaped like mainnet's would measure. The one that merged is a "
          f"single runtime tiled, which is why these classes overshot to "
          f"{V3['classes']['dark']['v3']:.3f}&times; instead of closing.</li>")
    elif V4["verdict"] != "in_band":
        w(f"<li>How many lookups a workload makes per prefetched account, which is where the "
          f"remaining {pc(V4['classes']['dark']['v4'])} lives. Cost per lookup is measured and "
          f"does not explain it: accounts {V4['residual']['cf_lookup_ratio']['cf06']:.2f}, trie "
          f"nodes {V4['residual']['cf_lookup_ratio']['cf09']:.2f}, against a workload ratio of "
          f"{V4['residual']['ratio_v4_over_snapshot']:.2f}.</li>")
    w(f"<li>Why the control sits at {pc(ctrl_vs_comp)} and {pc(V3['control_ratio'])} rather "
      f"than at parity on either arm. Close enough to keep the comparison, never "
      f"attributed.</li>")
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
    # House style is hyphens. Dashes creep back in through hand-written prose, so fail the
    # build rather than publish them, entity or literal.
    for bad in ("\u2014", "\u2013", "&mdash;", "&ndash;"):
        assert bad not in doc, f"dash in the emitted page: {bad!r}"
    with open(OUT, "w") as fh:
        fh.write(doc)
    print(f"wrote {os.path.relpath(OUT, HERE)} ({os.path.getsize(OUT)} bytes), "
          f"{len(figs)} figures")


if __name__ == "__main__":
    main()
