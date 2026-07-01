#!/usr/bin/env python3
"""Zero-dependency static-site generator for the CPerezz/articles GitHub Pages site.

Stdlib only (no pip installs). It translates each article's Markdown into a styled,
self-contained HTML page (readable-dark, terminal-flavoured theme) and builds the CRT
landing `index.html` that links to every article.

    python3 build_site.py

Re-run after editing an article's markdown (like re-running the analysis pipeline).
Reads each article's `<folder>/<source>.md`, writes `<folder>/index.html`, and the root
`index.html`. Figure image paths in the markdown are used as-is (local `figures/...png`).
"""
import os
import re
import html

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------- #
# manifest — add an entry per article folder
# --------------------------------------------------------------------------- #
ARTICLES = [
    {
        "folder": "slot0-epoch-reorgs",
        "source": "is-slot-0-reorg-cost-fixable.md",
        "eyebrow": "CONSENSUS · REORGS",
        "card_title": "Is the slot-0 reorg cost fixable?",
        "date": "2026",
        "tags": "Ethereum · consensus · reorgs · ePBS",
        "blurb": "Twenty-one months of mainnet data on why the first slot of every epoch is "
                 "reorged ~7× more than the rest — and where Glamsterdam should set the attestation deadline.",
        "repo": "slot0-epoch-reorgs/",
    },
]

SITE_TITLE = "Articles"
AUTHOR = "CPerezz"


# --------------------------------------------------------------------------- #
# markdown -> html  (tailored to the articles' constructs; stdlib re/html only)
# --------------------------------------------------------------------------- #
def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def inline(text):
    """Inline markdown: `code`, [links](url), **bold**, *italic* / _italic_. Code spans are
    stashed first so their contents are never touched by the emphasis/link passes."""
    codes = []

    def stash(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                  lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener">{m.group(1)}</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"(?<![\w*])_([^_]+)_(?![\w])", r"<em>\1</em>", text)
    text = re.sub(r"\x00(\d+)\x00",
                  lambda m: "<code>" + html.escape(codes[int(m.group(1))], quote=False) + "</code>", text)
    return text


def _parse_list(block, ordered):
    marker = r"\d+\.\s+" if ordered else r"-\s+"
    items = []
    for line in block.split("\n"):
        s = line.strip()
        if not s:
            continue
        m = re.match(marker, s)
        if m:
            items.append(s[m.end():])
        elif items:                      # continuation of the previous item
            items[-1] += " " + s
    return items


def _figure(alt, src):
    m = re.match(r"^(Figure \d+)[:.]\s*(.*)$", alt)
    cap = (f'<span class="fnum">{m.group(1)}.</span> {inline(m.group(2))}') if m else inline(alt)
    return (f'<figure><img src="{src}" alt="{html.escape(alt, quote=True)}" loading="lazy">'
            f"<figcaption>{cap}</figcaption></figure>")


def convert(md):
    """Return (title, subtitle_html, body_html)."""
    raw = re.split(r"\n\s*\n", md.strip())
    title, subtitle, body = None, None, []
    for b in raw:
        bs = b.strip()
        if title is None and bs.startswith("# "):
            title = bs[2:].strip()
            continue
        if title is not None and subtitle is None and "\n" not in bs and re.match(r"^\*[^*].*\*$", bs):
            subtitle = bs[1:-1].strip()
            continue
        body.append(b)

    out = []
    for b in body:
        bs = b.strip()
        if not bs:
            continue
        if bs == "---":
            out.append('<hr class="rule">')
        elif bs.startswith("## "):
            t = bs[3:].strip()
            out.append(f'<h2 id="{_slug(t)}"><span class="hsig">&gt;</span> {inline(t)}</h2>')
        elif re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", bs):
            m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", bs)
            out.append(_figure(m.group(1), m.group(2)))
        elif re.match(r"^-\s", bs):
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in _parse_list(b, False)) + "</ul>")
        elif re.match(r"^\d+\.\s", bs):
            out.append("<ol>" + "".join(f"<li>{inline(i)}</li>" for i in _parse_list(b, True)) + "</ol>")
        else:
            para = " ".join(l.strip() for l in bs.split("\n"))
            if para.startswith("**Verdict"):
                out.append(f'<div class="callout">{inline(para)}</div>')
            else:
                out.append(f"<p>{inline(para)}</p>")
    return title, (inline(subtitle) if subtitle else ""), "\n".join(out)


# --------------------------------------------------------------------------- #
# templates  (tokens replaced with str.replace so CSS braces stay literal)
# --------------------------------------------------------------------------- #
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=VT323&'
         'family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&display=swap" rel="stylesheet">')

CRT_VARS = """
    :root{
      --bg:#000; --panel:rgba(51,255,51,.02);
      --green:#33ff33; --green-dim:#28d128; --green-muted:#1a5a1a;
      --glow:rgba(51,255,51,.30); --border:#182818;
      --text:#e2e6e2; --text-2:#aab0aa; --text-dim:#5c645c;
      --crt:'VT323',monospace; --mono:'IBM Plex Mono',ui-monospace,monospace;
    }
    *,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
    body::before{content:'';position:fixed;inset:0;z-index:100;pointer-events:none;
      background:repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(0,255,0,.006) 3px,rgba(0,255,0,.006) 6px)}
    body::after{content:'';position:fixed;inset:0;z-index:101;pointer-events:none;
      background:radial-gradient(ellipse at center,transparent 62%,rgba(0,0,0,.45) 100%)}
    ::selection{background:rgba(51,255,51,.22);color:#fff}
    a{color:var(--green-dim);text-decoration:none;border-bottom:1px solid rgba(51,255,51,.25);transition:.2s}
    a:hover{color:var(--green);border-bottom-color:var(--green);text-shadow:0 0 6px var(--glow)}
    @media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;transition-duration:.2s!important}}
"""

LANDING = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>%%SITE%% — %%AUTHOR%%</title>%%FONTS%%
<style>%%VARS%%
  body{background:var(--bg);font-family:var(--mono);color:var(--text);min-height:100vh;
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    padding:clamp(1.5rem,5vw,4rem);-webkit-font-smoothing:antialiased}
  .container{max-width:720px;width:100%;position:relative;z-index:5}
  .eyebrow{font-family:var(--crt);font-size:clamp(.85rem,1.2vw,1.1rem);color:var(--green);opacity:.5;
    letter-spacing:.2em;margin-bottom:.5rem;text-shadow:0 0 8px rgba(51,255,51,.2)}
  h1{font-family:var(--crt);font-size:clamp(2.2rem,6vw,4rem);color:var(--green);line-height:1.05;
    text-shadow:0 0 6px var(--glow),0 0 22px rgba(51,255,51,.1)}
  h1 .w{color:var(--text);text-shadow:none}
  .cursor{display:inline-block;width:.55em;height:.85em;background:var(--green);vertical-align:middle;
    margin-left:3px;animation:blink 1s step-end infinite;box-shadow:0 0 6px var(--glow)}
  @keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
  .divider{border:none;height:1px;margin:clamp(.9rem,2vh,1.6rem) 0;opacity:.35;
    background:linear-gradient(90deg,var(--border),var(--green) 30%,var(--green) 70%,var(--border))}
  .subtitle{font-size:clamp(.72rem,1.2vw,.9rem);color:var(--text-2);margin-bottom:clamp(1.2rem,3vh,2rem)}
  .deck-list{display:flex;flex-direction:column;gap:clamp(.6rem,1.5vh,.9rem)}
  .deck-link{display:block;border:1px solid var(--border);padding:clamp(.9rem,2vw,1.3rem);
    background:var(--panel);text-decoration:none;color:var(--text);transition:.3s;position:relative;overflow:hidden}
  .deck-link::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;opacity:.2;transition:.3s;
    background:linear-gradient(90deg,transparent,var(--green),transparent)}
  .deck-link:hover{border-color:var(--green-dim);background:rgba(51,255,51,.045);box-shadow:0 0 18px rgba(51,255,51,.09);transform:translateY(-1px)}
  .deck-link:hover::before{opacity:.55}
  .deck-link:hover .deck-title{text-shadow:0 0 7px var(--glow)}
  .deck-title{font-family:var(--crt);font-size:clamp(1.15rem,2.2vw,1.6rem);color:var(--green);margin-bottom:.3rem;transition:.3s}
  .deck-title .prompt{color:var(--green-muted)}
  .deck-meta{font-size:clamp(.6rem,1vw,.72rem);color:var(--text-dim);letter-spacing:.04em}
  .deck-meta .tag{color:var(--text-2)}
  .deck-desc{font-size:clamp(.66rem,1vw,.8rem);color:var(--text-2);margin-top:.4rem;line-height:1.6}
  .footer{margin-top:clamp(1.6rem,4vh,3rem);font-family:var(--crt);font-size:clamp(.7rem,1vw,.85rem);color:var(--green-muted)}
  .footer a{color:var(--green-muted);border:none}.footer a:hover{color:var(--green-dim)}
</style></head><body><div class="container">
  <div class="eyebrow">// ARTICLES</div>
  <h1><span class="w">%%AUTHOR%%</span> Articles<span class="cursor"></span></h1>
  <hr class="divider">
  <p class="subtitle">Data-driven Ethereum research — the write-up, the figures, and the reproducible pipeline behind each.</p>
  <div class="deck-list">
%%CARDS%%
  </div>
  <div class="footer">$ <a href="https://github.com/%%AUTHOR%%/articles">github.com/%%AUTHOR%%/articles</a></div>
</div></body></html>
"""

CARD = """    <a href="%%HREF%%" class="deck-link">
      <div class="deck-title"><span class="prompt">&gt; </span>%%TITLE%%</div>
      <div class="deck-meta"><span class="tag">%%TAGS%%</span> · %%DATE%%</div>
      <div class="deck-desc">%%BLURB%%</div>
    </a>"""

ARTICLE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>%%TITLE_PLAIN%% — %%AUTHOR%%</title>
<meta name="description" content="%%DESC%%">%%FONTS%%
<style>%%VARS%%
  html{scroll-behavior:smooth}
  body{background:var(--bg);font-family:var(--mono);color:var(--text);line-height:1.8;
    font-size:clamp(15px,.62vw + 13px,17px);-webkit-font-smoothing:antialiased;
    padding:clamp(1.4rem,4vw,3rem) clamp(1.1rem,4vw,2rem) 5rem}
  .wrap{max-width:730px;margin:0 auto;position:relative;z-index:5}
  .topbar{display:flex;justify-content:space-between;align-items:center;font-family:var(--crt);
    font-size:clamp(.9rem,1.3vw,1.15rem);color:var(--green-muted);margin-bottom:clamp(1.4rem,4vh,2.4rem)}
  .topbar a{border:none}.topbar a:hover{color:var(--green)}
  .eyebrow{font-family:var(--crt);letter-spacing:.22em;color:var(--green);opacity:.55;
    font-size:clamp(.85rem,1.2vw,1.05rem);text-shadow:0 0 8px rgba(51,255,51,.2);margin-bottom:.5rem}
  h1{font-family:var(--crt);color:var(--green);line-height:1.06;font-weight:400;
    font-size:clamp(2rem,5.4vw,3.4rem);text-shadow:0 0 7px var(--glow),0 0 24px rgba(51,255,51,.08)}
  .lead{font-size:clamp(.95rem,1.4vw,1.12rem);color:var(--text-2);font-style:italic;line-height:1.7;
    margin:clamp(.9rem,2vh,1.3rem) 0 clamp(1rem,2.5vh,1.6rem);padding-left:1rem;border-left:2px solid var(--green-muted)}
  .meta{font-size:.72rem;letter-spacing:.05em;color:var(--text-dim);border-top:1px solid var(--border);
    border-bottom:1px solid var(--border);padding:.6rem 0;margin-bottom:clamp(1.6rem,4vh,2.6rem)}
  .meta .tag{color:var(--text-2)}
  article h2{font-family:var(--mono);font-weight:700;color:var(--green);letter-spacing:.005em;
    font-size:clamp(1.15rem,2.3vw,1.5rem);line-height:1.3;margin:clamp(2.4rem,6vh,3.4rem) 0 .2rem;
    text-shadow:0 0 5px rgba(51,255,51,.18);scroll-margin-top:1.5rem}
  article h2 .hsig{color:var(--green-muted);font-weight:400}
  article h2::after{content:'';display:block;height:1px;margin-top:.7rem;opacity:.3;
    background:linear-gradient(90deg,var(--green-muted),transparent 65%)}
  p{margin:1rem 0;color:var(--text)}
  strong{color:#f2fff2;font-weight:600}
  em{color:var(--text-2)}
  code{font-family:var(--mono);font-size:.9em;background:rgba(51,255,51,.07);border:1px solid var(--border);
    border-radius:3px;padding:.06em .38em;color:#bfeecf}
  ul,ol{margin:1rem 0 1rem 0;padding-left:0;list-style:none;display:flex;flex-direction:column;gap:.55rem}
  li{position:relative;padding-left:1.6rem;color:var(--text)}
  ul>li::before{content:'▸';position:absolute;left:.1rem;color:var(--green-dim);text-shadow:0 0 5px var(--glow)}
  ol{counter-reset:step}
  ol>li{counter-increment:step}
  ol>li::before{content:counter(step);position:absolute;left:0;top:.05em;font-family:var(--crt);
    font-size:.95em;color:var(--green);border:1px solid var(--green-muted);border-radius:3px;
    min-width:1.15em;height:1.15em;display:inline-flex;align-items:center;justify-content:center;line-height:1}
  ol>li{padding-left:2rem}
  .callout{border:1px solid var(--green-muted);border-left:3px solid var(--green);background:rgba(51,255,51,.04);
    padding:clamp(.9rem,2.2vw,1.2rem) clamp(1rem,2.5vw,1.4rem);margin:1.4rem 0;color:#eafaea;
    box-shadow:0 0 18px rgba(51,255,51,.05)}
  .callout strong{color:var(--green);text-shadow:0 0 6px var(--glow)}
  figure{margin:clamp(1.8rem,4vh,2.6rem) 0;border:1px solid var(--border);background:#050805;
    padding:clamp(.6rem,1.6vw,.9rem);transition:.3s}
  figure:hover{border-color:var(--green-muted);box-shadow:0 0 22px rgba(51,255,51,.06)}
  figure img{display:block;width:100%;height:auto;background:#fff;border-radius:2px}
  figcaption{font-size:.72rem;line-height:1.55;color:var(--text-dim);text-align:center;
    margin-top:.7rem;padding:0 .4rem}
  figcaption .fnum{font-family:var(--crt);font-size:1rem;color:var(--green-dim);letter-spacing:.04em}
  hr.rule{border:none;height:1px;margin:clamp(2rem,5vh,3rem) 0;opacity:.4;
    background:linear-gradient(90deg,var(--border),var(--green) 30%,var(--green) 70%,var(--border))}
  .endbar{margin-top:clamp(2.6rem,6vh,4rem);padding-top:1.2rem;border-top:1px solid var(--border);
    font-family:var(--crt);font-size:clamp(.85rem,1.2vw,1.05rem);color:var(--green-muted);
    display:flex;justify-content:space-between;flex-wrap:wrap;gap:.6rem}
  .endbar a{border:none}.endbar a:hover{color:var(--green)}
  .cursor{display:inline-block;width:.5em;height:.9em;background:var(--green);vertical-align:-2px;
    margin-left:2px;animation:blink 1s step-end infinite}
  @keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
</style></head><body><div class="wrap">
  <div class="topbar"><a href="../">&larr; all articles</a><span>%%EYEBROW%%</span></div>
  <header>
    <div class="eyebrow">// ARTICLE</div>
    <h1>%%TITLE%%</h1>
    <p class="lead">%%SUBTITLE%%</p>
    <div class="meta"><span class="tag">%%TAGS%%</span> · %%DATE%% · <a href="%%REPO%%">reproducible pipeline &amp; data &rarr;</a></div>
  </header>
  <article>
%%BODY%%
  </article>
  <div class="endbar"><a href="../">&larr; all articles</a><a href="%%REPO%%">source &amp; data</a></div>
  <span class="cursor" style="position:fixed;bottom:1.4rem;right:1.4rem;z-index:6"></span>
</div></body></html>
"""


def _fill(tmpl, mapping):
    for k, v in mapping.items():
        tmpl = tmpl.replace(f"%%{k}%%", v)
    return tmpl


def build_article(a):
    src = os.path.join(HERE, a["folder"], a["source"])
    with open(src, encoding="utf-8") as fh:
        title, subtitle, body = convert(fh.read())
    out = _fill(ARTICLE, {
        "FONTS": FONTS, "VARS": CRT_VARS, "AUTHOR": AUTHOR,
        "TITLE": html.escape(title), "TITLE_PLAIN": html.escape(re.sub(r"[*_`]", "", title)),
        "SUBTITLE": subtitle, "BODY": body,
        "DESC": html.escape(re.sub(r"[*_`]", "", a["blurb"]), quote=True),
        "EYEBROW": a["eyebrow"], "TAGS": a["tags"], "DATE": a["date"],
        "REPO": "https://github.com/%s/articles/tree/main/%s" % (AUTHOR, a["folder"]),
    })
    dst = os.path.join(HERE, a["folder"], "index.html")
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"  wrote {a['folder']}/index.html   (title: {title[:48]}…)")


def build_landing():
    cards = "\n".join(_fill(CARD, {
        "HREF": a["folder"] + "/", "TITLE": html.escape(a["card_title"]),
        "TAGS": a["tags"], "DATE": a["date"], "BLURB": html.escape(a["blurb"]),
    }) for a in ARTICLES)
    out = _fill(LANDING, {"FONTS": FONTS, "VARS": CRT_VARS, "SITE": SITE_TITLE,
                          "AUTHOR": AUTHOR, "CARDS": cards})
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(out)
    print("  wrote index.html   (landing)")


if __name__ == "__main__":
    print("building site …")
    for a in ARTICLES:
        build_article(a)
    build_landing()
    print("done.")
