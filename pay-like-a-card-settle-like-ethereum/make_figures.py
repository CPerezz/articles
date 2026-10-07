#!/usr/bin/env python3
"""Draws the article's figures as self-contained SVGs in the site's CRT palette.

    python3 make_figures.py      # writes figures/f1-two-waits.svg ... figures/f9-cheat-sheet.svg

Stdlib only. Every label goes through text(), which refuses strings wider than the
room they were given, so a wording change that would overflow a box fails loudly here
instead of quietly in the browser. Helpers (text/rect/line/path/arrow/arc/label/chip/svg)
are the same ones used by ../setcodefrom-account-modes/make_figures.py — copied, not
imported, so each article's figures stay reproducible from its own folder alone.
"""
import os
from html import escape

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figures")

BG, PANEL, LINE = "#050805", "#0a120a", "#182818"
TEXT, MUTED = "#e2e6e2", "#aab0aa"
GREEN, KEY, PURPLE, BLUE, RED = "#33ff33", "#e8a83a", "#b491f0", "#6fb2e8", "#ff9a9f"
TINT = {GREEN: "#0f2a12", KEY: "#2a1f08", PURPLE: "#1f1530", BLUE: "#0b1d2c", RED: "#2a1214", MUTED: "#141a14"}
FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', monospace"
ADV = 0.62  # monospace advance per unit of font size, with a little slack over Menlo's 0.602


def tw(s, size):
    return len(s) * size * ADV


def text(x, y, s, size=24, fill=TEXT, anchor="start", bold=False, room=None, lh=1.28, spacing=None):
    """One or more lines of text. `room` is the width the lines must fit in."""
    lines = s if isinstance(s, (list, tuple)) else [s]
    out = []
    for i, ln in enumerate(lines):
        if room is not None:
            assert tw(ln, size) <= room, f"{ln!r} at {size}px needs {tw(ln, size):.0f}px, has {room}"
        a = f'x="{x}" y="{y + i * size * lh:.1f}" font-size="{size}" fill="{fill}"'
        if anchor != "start":
            a += f' text-anchor="{anchor}"'
        if bold:
            a += ' font-weight="700"'
        if spacing:
            a += f' letter-spacing="{spacing}"'
        out.append(f"<text {a}>{escape(ln, quote=False)}</text>")
    return "".join(out)


def rect(x, y, w, h, stroke=LINE, fill=PANEL, sw=2, rx=10, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"{d}/>')


def line(x1, y1, x2, y2, color=LINE, sw=2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"{d}/>'


MARKERS = {c: f"ah{i}" for i, c in enumerate([GREEN, KEY, PURPLE, BLUE, RED, MUTED])}


def path(d, color=GREEN, sw=3.5, dash=None, head=True):
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    if head:
        extra += f' marker-end="url(#{MARKERS[color]})"'
    return (f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}" '
            f'stroke-linecap="round" stroke-linejoin="round"{extra}/>')


def arrow(x1, y1, x2, y2, color=GREEN, sw=3.5, dash=None):
    return path(f"M{x1},{y1} L{x2},{y2}", color, sw, dash)


def label(cx, y, main, color, sub=None, room=440):
    """Arrow label: bold line plus an optional muted line, on a mask so lines behind stay quiet."""
    w = max(tw(main, 24), tw(sub, 22) if sub else 0) + 24
    h = 62 if sub else 36
    out = f'<rect x="{cx - w / 2:.1f}" y="{y - 27}" width="{w:.1f}" height="{h}" fill="{BG}" opacity="0.92"/>'
    out += text(cx, y, main, 24, color, "middle", bold=True, room=room)
    if sub:
        out += text(cx, y + 28, sub, 22, MUTED, "middle", room=room)
    return out


def chip(x, y, s, color=MUTED, size=22, anchor="start", dash=None, h=38):
    """Rounded pill around one line of text; (x, y) is the left (or centre) of its middle line."""
    w = tw(s, size) + 26
    left = x - w / 2 if anchor == "middle" else x
    out = rect(left, y - h / 2, w, h, stroke=color, fill=TINT.get(color, PANEL), sw=2, rx=h / 2, dash=dash)
    out += text(left + w / 2, y + size * 0.36, s, size, color, "middle")
    return out


def mark(cx, cy, ok, r=17):
    """Circled tick (open) or circled cross (shut)."""
    c = GREEN if ok else RED
    out = f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{TINT[c]}" stroke="{c}" stroke-width="2.5"/>'
    if ok:
        out += (f'<path d="M{cx - 8},{cy + 1} l5,6 l11,-13" fill="none" stroke="{c}" stroke-width="3.2" '
                f'stroke-linecap="round" stroke-linejoin="round"/>')
    else:
        out += (f'<path d="M{cx - 6.5},{cy - 6.5} l13,13 M{cx + 6.5},{cy - 6.5} l-13,13" stroke="{c}" '
                f'stroke-width="3.2" stroke-linecap="round"/>')
    return out


def head(s):
    return text(30, 46, s, 22, GREEN, bold=True, spacing=2)


# Line icons drawn in local coordinates around (0, 0), about 64 px tall: (strokes, filled shapes).
GLYPHS = {
    "rollup": (["M-30,-14 L0,-26 L30,-14 L0,-2 Z", "M-30,0 L0,12 L30,0", "M-30,14 L0,26 L30,14"], []),
    "bridge": (["M-38,-12 H38", "M-38,-12 V20", "M38,-12 V20", "M-34,18 Q0,-26 34,18",
                "M-17,-12 V1.5", "M0,-12 V-4", "M17,-12 V1.5",
                "M-38,28 q6,-5 12,0 t12,0 t12,0 t12,0 t12,0 t12,0"], []),
    "ethereum": (["M0,-32 L-19,0 L0,10 L19,0 Z", "M-19,0 L0,-8 L19,0", "M0,-32 V10",
                  "M-19,5 L0,16 L19,5 L0,32 Z"], []),
    "hourglass": (["M-18,-28 H18", "M-18,28 H18", "M-13,-28 V-22 L0,0 L-13,22 V28",
                   "M13,-28 V-22 L0,0 L13,22 V28"], ["M-7,-20 H7 L0,-12 Z", "M-9,26 L0,14 L9,26 Z"]),
    "parcel": (["M0,-28 L26,-15 L0,-2 L-26,-15 Z", "M-26,-15 V15 L0,28 V-2", "M26,-15 V15 L0,28",
                "M-13,-21.5 L13,-8.5", "M-52,-6 H-36", "M-56,4 H-36", "M-50,14 H-36"], []),
    "block": (["M0,-28 L26,-15 L0,-2 L-26,-15 Z", "M-26,-15 V15 L0,28 V-2", "M26,-15 V15 L0,28"], []),
    "lock": (["M-13,-6 V-15 A13,13 0 0 1 13,-15 V-6", "M-21,-6 H21 V26 H-21 Z", "M0,6 V14"], []),
    "shield": (["M0,-28 L22,-20 V-2 C22,14 11,23 0,28 C-11,23 -22,14 -22,-2 V-20 Z", "M-9,0 L-2,8 L11,-8"], []),
    "clock": (["M-24,0 A24,24 0 1 0 24,0 A24,24 0 1 0 -24,0", "M0,0 V-15", "M0,0 L10,7"], []),
    "receipt": (["M-22,-30 H10 L22,-18 V30 H-22 Z", "M10,-30 V-18 H22", "M-12,-12 H8", "M-12,0 H12",
                 "M-12,12 H4"], []),
    "link": (["M-30,0 a18,11 0 1 0 36,0 a18,11 0 1 0 -36,0", "M-6,0 a18,11 0 1 0 36,0 a18,11 0 1 0 -36,0"], []),
    "pen": (["M-4,2 L16,-18 L24,-10 L4,10 Z", "M-4,2 L-10,16 L4,10", "M-30,24 q7,-10 14,0 t14,0"], []),
    "card": (["M-26,-17 H26 V17 H-26 Z", "M-26,-7 H26", "M-18,8 H-2"], []),
    "pie": (["M-24,0 A24,24 0 1 0 24,0 A24,24 0 1 0 -24,0"], ["M0,0 V-24 A24,24 0 0 1 24,0 Z"]),
}


def glyph(kind, cx, cy, color, s=1):
    """One of GLYPHS, centred on (cx, cy), in the node's colour; `s` scales it, the stroke stays 3 px."""
    strokes, fills = GLYPHS[kind]
    out = (f'<g transform="translate({cx},{cy}) scale({s})" fill="none" stroke="{color}" '
           f'stroke-width="{3 / s:.2f}" stroke-linecap="round" stroke-linejoin="round">')
    out += "".join(f'<path d="{d}"/>' for d in strokes)
    out += "".join(f'<path d="{d}" fill="{color}" fill-opacity="0.55" stroke="none"/>' for d in fills)
    return out + "</g>"


def coin(cx, cy, r=8):
    """Your money: the amber coin that travels through every figure."""
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{KEY}" stroke="{BG}" stroke-width="2"/>'


def meter(x, y, w, n, color, h=12, gap=6):
    """A segmented bar that fills up left to right: votes or confidence building."""
    sw = (w - (n - 1) * gap) / n
    return "".join(f'<rect x="{x + i * (sw + gap):.1f}" y="{y}" width="{sw:.1f}" height="{h}" rx="3" fill="{color}" '
                   f'fill-opacity="{0.12 + i * 0.85 / (n - 1):.2f}" stroke="{color}" stroke-width="1.5"/>'
                   for i in range(n))


def svg(name, w, h, title, body):
    defs = "".join(
        f'<marker id="{mid}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="4.2" markerHeight="4.2" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
        for c, mid in MARKERS.items())
    doc = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
           f'font-family="{FONT}"><title>{escape(title)}</title><defs>{defs}</defs>'
           f'<rect width="{w}" height="{h}" fill="{BG}"/>{"".join(body)}</svg>\n')
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"  wrote figures/{name}")


# --------------------------------------------------------------------------- #
# F1: the two waits
# --------------------------------------------------------------------------- #
def f1():
    W, H = 1200, 480
    b = [head("// the two waits")]
    GY = 290  # glyph row
    # the hand-off between the two waits
    b.append(line(600, 80, 600, 455, LINE, 2, "2 8"))
    b.append(text(30, 100, "GETTING THERE", 26, GREEN, bold=True, spacing=1))
    b.append(text(30, 130, "your value has to reach the base layer", 20, MUTED, room=540))
    b.append(text(630, 100, "BEING BELIEVED", 26, BLUE, bold=True, spacing=1))
    b.append(text(630, 130, "the shop waits until it can't be undone", 20, MUTED, room=540))
    # left: rollup -> crossing over the gap -> base layer, the coin mid-flight
    b.append(glyph("rollup", 90, GY, GREEN))
    b.append(glyph("ethereum", 520, GY, GREEN))
    b.append(path("M190,325" + " q10,-7 20,0" * 11, MUTED, 2, head=False))
    b.append(path(f"M135,{GY - 20} C225,{GY - 100} 385,{GY - 100} 475,{GY - 20}", GREEN, 3, "8 8"))
    b.append(coin(305, GY - 80, 11))
    b.append(text(305, GY - 128, "a trusted bridge or market maker", 19, RED, "middle", room=440))
    b.append(text(305, GY - 104, "or the rollup's own exit: up to ~1 week", 17, MUTED, "middle", room=440))
    b.append(text(90, 350, "your rollup", 20, MUTED, "middle"))
    b.append(text(520, 350, "base layer", 20, MUTED, "middle"))
    # right: the block it landed in, blocks piling on, confidence building to a lock
    xs = [690, 775, 860, 945, 1030]
    b.append(arrow(545, GY, 655, GY, MUTED, 3))
    b.append(chip(600, GY, "lands", MUTED, size=20, anchor="middle", h=34))
    for x0, x1 in zip(xs, xs[1:] + [1092]):
        b.append(line(x0 + 26, GY, x1 - 26, GY, BLUE, 2))
    for x in xs:
        b.append(glyph("block", x, GY, BLUE))
    b.append(coin(xs[0], GY - 15))
    b.append(glyph("lock", 1120, GY - 6, BLUE))
    MX, MW = 664, 476
    b.append(meter(MX, 340, MW, 6, BLUE))
    b.append(text(MX, 380, "could still be reorged", 18, MUTED, room=300))
    b.append(text(MX + MW, 380, "can't be undone", 18, BLUE, "end", room=300))
    # how long each wait takes, and what fixes it
    b.append(chip(30, 430, "minutes to ~1 week", MUTED))
    b.append(chip(320, 430, "fixed by EEZ", GREEN))
    b.append(chip(630, 430, "~13 min", MUTED))
    b.append(chip(770, 430, "fixed by FCR", BLUE))
    svg("f1-two-waits.svg", W, H, "The two waits in any cross-layer payment, and what fixes each one", b)


# --------------------------------------------------------------------------- #
# F2: today's checkout
# --------------------------------------------------------------------------- #
def f2():
    W, H = 1200, 460
    b = [head("// checkout, today")]
    y, h = 195, 170
    nodes = [
        (30, 170, "YOUR\nROLLUP", MUTED, "rollup"),
        (260, 170, "TRUSTED\nBRIDGE", RED, "bridge"),
        (490, 170, "BASE\nLAYER", MUTED, "ethereum"),
        (720, 220, "SHOP'S OWN\n~13 MIN WAIT", BLUE, "hourglass"),
        (1000, 170, "SHOP\nSHIPS", GREEN, "parcel"),
    ]
    for x, w, label_s, c, g in nodes:
        b.append(rect(x, y, w, h, stroke=c, fill=TINT.get(c, PANEL), rx=10))
        b.append(glyph(g, x + w / 2, y + 52, c))
        b.append(text(x + w / 2, y + 116, label_s.split("\n"), 23, c, "middle", bold=True, room=w - 20, lh=1.3))
    # arrows run edge to edge between neighbours, so a box width can't drift from its arrow
    for (x1, w1, *_), (x2, *_) in zip(nodes, nodes[1:]):
        b.append(arrow(x1 + w1, y + h / 2, x2, y + h / 2, MUTED, 3))
    b.append(label((30 + 170 + 260) / 2, 140, "minutes", MUTED, "(trustless exit: ~1 week)", room=360))
    b.append(text(30, 90, "one integration, per rollup, before the shop will even look at your money",
                  22, MUTED, room=1140))
    b.append(text(30, H - 40,
                  "every rollup needs this chain built again \u2014 trust a market maker, or wait out the exit",
                  21, MUTED, room=1140))
    svg("f2-today.svg", W, H, "Today's checkout: a trusted bridge, then the base layer's own finality wait", b)


# --------------------------------------------------------------------------- #
# F3: FCR, the slot's votes fill up, then the long road to finality
# --------------------------------------------------------------------------- #
def f3():
    W, H = 1200, 560
    b = [head("// FCR: one slot, not thirteen minutes")]
    # your block lands, the slot's votes pour in, enough of them and it's safe
    GY = 170
    b.append(glyph("block", 100, GY, BLUE))
    b.append(coin(100, GY - 15))
    b.append(text(100, GY + 60, "your block", 20, MUTED, "middle"))
    MX, MW, n = 170, 470, 10
    b.append(meter(MX, GY - 13, MW, n, BLUE, h=26, gap=5))
    tx = MX + 8 * (MW + 5) / n - 2.5  # the gap after the 8th segment
    b.append(line(tx, GY - 30, tx, GY + 22, TEXT, 2, "4 4"))
    b.append(text(MX, GY - 40, "validator votes pour in", 18, MUTED, room=300))
    b.append(text(tx, GY - 40, "enough votes", 18, TEXT, "middle"))
    by = GY + 34
    b.append(path(f"M{MX},{by - 8} V{by} H{MX + MW} V{by - 8}", MUTED, 2, head=False))
    b.append(text(MX + MW / 2, by + 26, "one slot (12 s)", 20, MUTED, "middle"))
    b.append(arrow(MX + MW + 10, GY, 700, GY, BLUE, 3))
    b.append(glyph("shield", 735, GY, BLUE))
    b.append(text(780, GY - 6, "SAFE", 24, BLUE, bold=True, spacing=1))
    b.append(text(780, GY + 22, "\u2248 13 s after it lands", 20, MUTED, room=390))
    # without FCR: the 64 slots finality takes, the first one is all FCR needs
    RY = 315
    b.append(text(30, RY - 27, "without FCR, the shop waits out finality: 64 slots", 20, MUTED, room=1140))
    b.append(rect(60, RY, 10, 26, stroke=BLUE, fill=BLUE, sw=1.5, rx=2))
    b.append('<g opacity="0.5">')
    b.extend(rect(60 + i * 1000 / 64, RY, 10, 26, stroke=MUTED, fill=PANEL, sw=1.5, rx=2) for i in range(1, 64))
    b.append("</g>")
    b.append(glyph("lock", 1110, RY + 10, TEXT))
    b.append(text(65, RY + 60, "safe", 19, BLUE, "middle"))
    b.append(text(560, RY + 60, "\u2248 65\u00d7 longer", 19, MUTED, "middle"))
    b.append(text(1140, RY + 60, "finalized \u2248 13 min", 19, TEXT, "end"))
    # what FCR leans on
    CY = 470
    b.append(text(30, CY - 42, "FCR's conditions; break them and it falls back to waiting for finality:", 20, MUTED,
                  room=1140))
    b.append(glyph("clock", 48, CY, KEY, s=0.6))
    b.append(chip(76, CY, "votes arrive on time", KEY, size=21, h=40))
    b.append(glyph("pie", 420, CY, KEY, s=0.6))
    b.append(chip(446, CY, "< 25% of stake acting adversarially", KEY, size=21, h=40))
    b.append(text(30, H - 25, "merged into consensus-specs 2026-04-16 \u00b7 a client rule, not a network upgrade", 20,
                  MUTED, room=1140))
    svg("f3-fcr.svg", W, H, "FCR marks a landed block safe in about one slot instead of ~13 minutes", b)


# --------------------------------------------------------------------------- #
# F4: EEZ, one block instead of money in limbo
# --------------------------------------------------------------------------- #
def f4():
    W, H = 1200, 520
    b = [head("// EEZ: one block, not a wire transfer")]
    # today: two separate ledgers, your money in limbo between them
    TY = 160
    b.append(text(30, 100, "TODAY", 22, RED, bold=True, spacing=1))
    b.append(glyph("rollup", 100, TY, MUTED))
    b.append(glyph("ethereum", 520, TY, MUTED))
    b.append(line(140, TY, 480, TY, MUTED, 2, "6 8"))
    b.append(coin(310, TY, 11))
    b.append(mark(310, TY - 40, False, r=14))
    b.append(text(310, TY + 34, "trusted bridge", 18, RED, "middle"))
    b.append(text(100, TY + 58, "your rollup", 19, MUTED, "middle"))
    b.append(text(520, TY + 58, "base layer", 19, MUTED, "middle"))
    b.append(text(610, TY - 20, ["two separate ledgers, a bridge you", "must trust in between, and your",
                                 "money in limbo while it crosses"], 20, MUTED, room=560, lh=1.4))
    # with EEZ: both legs tied together inside one block, and the rollup mirrors it
    b.append(text(30, 270, "WITH EEZ", 22, GREEN, bold=True, spacing=1))
    b.append(text(165, 270, "no bridge, nothing new to trust", 19, GREEN))
    BX, BY, BW, BH = 30, 290, 820, 200
    b.append(rect(BX, BY, BW, BH, stroke=GREEN, fill=TINT[GREEN], rx=14))
    b.append(glyph("block", BX + 34, BY + 34, GREEN, s=0.55))
    b.append(text(BX + 64, BY + 42, "ONE ETHEREUM BLOCK", 21, GREEN, bold=True, spacing=1))
    SY = BY + 105
    for sx, title, sub in [(210, "proof + update", "postAndVerifyBatch"), (670, "your checkout", "the base-layer leg")]:
        b.append(glyph("receipt", sx, SY, GREEN))
        b.append(text(sx, SY + 60, title, 20, TEXT, "middle", bold=True))
        b.append(text(sx, SY + 84, sub, 18, MUTED, "middle"))
    b.append(line(240, SY, 395, SY, KEY, 2))
    b.append(line(485, SY, 640, SY, KEY, 2))
    b.append(glyph("link", 440, SY, KEY))
    b.append(text(440, SY - 40, "both land, or neither does", 19, KEY, "middle"))
    b.append(arrow(BX + BW + 12, SY, 990, SY, GREEN, 3))
    b.append(text(926, SY - 18, "mirrors it", 19, MUTED, "middle"))
    b.append(glyph("rollup", 1060, SY, GREEN))
    b.append(text(1060, SY + 60, "your rollup", 19, MUTED, "middle"))
    b.append(text(1060, SY + 84, "on the spot", 18, MUTED, "middle"))
    svg("f4-eez.svg", W, H, "EEZ: your rollup's leg and the base layer's leg land in the same block", b)


# --------------------------------------------------------------------------- #
# F5: alike / different
# --------------------------------------------------------------------------- #
def f5():
    W, H = 1200, 620
    b = [head("// alike, different, where they meet")]
    rows = ["fixes", "lives in", "applies to", "status"]
    cols = [
        (330, "FCR", BLUE, "shield", [
            ["how long a landed", "block takes to trust"],
            ["every consensus client", "on Ethereum"],
            ["any block, checkout", "or not"],
            ["merged into spec,", "rolling out", "client by client"],
        ]),
        (750, "EEZ", GREEN, "link", [
            ["the crossing, and the", "trusted bridge with it"],
            ["a specific set of rollup", "+ base-layer contracts"],
            ["only actions inside", "the zone"],
            ["live on mainnet,", "unaudited"],
        ]),
    ]
    y0, RH = 174, 76
    for i, r in enumerate(rows):
        b.append(text(30, y0 + i * RH + 20, r, 22, MUTED, room=260))
    for x, title, c, icon, cells in cols:
        b.append(rect(x - 20, 100, 340, 400, stroke=c, fill=TINT[c], rx=12))
        b.append(text(x, 140, title, 26, c, bold=True, spacing=1))
        b.append(glyph(icon, x + 275, 131, c, s=0.7))
        for i in range(4):
            b.append(text(x, y0 + i * RH + 20, cells[i], 20, TEXT, room=300, lh=1.3))
    b.append(rect(30, 520, 1140, 70, stroke=MUTED, fill=PANEL, rx=10))
    b.append(glyph("block", 72, 555, GREEN, s=0.6))
    b.append(glyph("shield", 110, 553, BLUE, s=0.55))
    b.append(text(140, 550, "where they meet: EEZ's result is still just an ordinary block \u2014", 21, TEXT,
                  room=1010))
    b.append(text(140, 578, "FCR confirms it exactly as fast as any other", 21, TEXT, room=1010))
    svg("f5-alike-different.svg", W, H, "FCR and EEZ side by side: what each fixes, where each lives", b)


# --------------------------------------------------------------------------- #
# F6 and F9 share the four builds: how the money crosses + how the shop gets to trust it
# --------------------------------------------------------------------------- #
CROSS = {"bridge": ("bridge", RED, "trusted bridge", RED), "block": ("block", GREEN, "one block", MUTED)}
CONFIRM = {"wait": ("hourglass", MUTED, "full finality", MUTED), "fcr": ("shield", BLUE, "FCR", MUTED)}
BUILDS = [  # title, colour, crossing, confirmation, end-to-end time
    ("NEITHER", MUTED, "bridge", "wait", "~13 min to ~1 week"),
    ("FCR ONLY", BLUE, "bridge", "fcr", "bridge-bound"),
    ("EEZ ONLY", GREEN, "block", "wait", "~13 min"),
    ("BOTH", GREEN, "block", "fcr", "\u2248 25 sec"),
]


def recipe(cx, cy, cross, confirm, s=1, labels=True):
    """A build drawn as its two ingredients: crossing glyph + confirmation glyph."""
    out = []
    for (kind, c, name, lc), x in [(CROSS[cross], cx - 125 * s), (CONFIRM[confirm], cx + 125 * s)]:
        out.append(glyph(kind, x, cy, c, s))
        if kind == "block":
            out.append(coin(x, cy - 15 * s, 8 * s))
        if labels:
            out.append(text(x, cy + 60, name, 19, lc, "middle"))
    out.append(text(cx, cy + 10 * s, "+", 30 * s, MUTED, "middle"))
    return "".join(out)


def f6():
    W, H = 1200, 680
    b = [head("// four ways to build the checkout")]
    x0, y0, cw, ch, gap = 140, 120, 470, 250, 30
    b.append(text(x0 + cw + gap / 2, 96, "FCR \u2192", 22, BLUE, "middle", bold=True))
    b.append(text(70, y0 + ch + gap / 2, "EEZ", 22, GREEN, bold=True))
    b.append(text(70, y0 + ch + gap / 2 + 26, "\u2193", 22, GREEN, bold=True))
    for i, (title, c, cross, confirm, t) in enumerate(BUILDS):
        x = x0 + (i % 2) * (cw + gap)
        y = y0 + (i // 2) * (ch + gap)
        best = title == "BOTH"
        b.append(rect(x, y, cw, ch, stroke=c, fill=TINT[c], sw=3 if best else 2, rx=14))
        b.append(text(x + 24, y + 44, title, 25, c, bold=True, spacing=1, room=cw - 48))
        b.append(recipe(x + cw / 2, y + 112, cross, confirm))
        b.append(chip(x + 24, y + ch - 34, t, c, size=22, h=40))
        if best:
            b.append(text(x + cw - 24, y + 44, "\u2605", 26, GREEN, "end"))
    svg("f6-four-builds.svg", W, H, "Four ways to build the checkout, and the end-to-end time for each", b)


# --------------------------------------------------------------------------- #
# F7: both, end to end
# --------------------------------------------------------------------------- #
def f7():
    W, H = 1200, 470
    b = [head("// both, end to end")]
    y, h = 150, 170
    steps = [  # x, width, label, colour, glyph, elapsed
        (30, 150, "you sign\nONCE", MUTED, "pen", "0 s"),
        (207, 240, "builder packages\nboth legs", KEY, "legs", None),
        (475, 300, "ONE BLOCK\nlands, rollup mirrors", GREEN, "block", "\u2248 12 s"),
        (802, 200, "FCR marks it\nsafe, +1 slot", BLUE, "shield", "\u2248 25 s"),
        (1030, 140, "shop\nships", GREEN, "parcel", None),
    ]
    for x, w, s, c, g, t in steps:
        b.append(rect(x, y, w, h, stroke=c, fill=TINT.get(c, PANEL), rx=10))
        if g == "legs":  # the two receipts of F4, tied together
            b.append(glyph("receipt", x + w / 2 - 52, y + 52, c, s=0.8))
            b.append(glyph("link", x + w / 2, y + 52, c, s=0.6))
            b.append(glyph("receipt", x + w / 2 + 52, y + 52, c, s=0.8))
        else:
            b.append(glyph(g, x + w / 2, y + 52, c))
        if g == "block":
            b.append(coin(x + w / 2, y + 37))
        b.append(text(x + w / 2, y + 116, s.split("\n"), 21, c, "middle", bold=True, room=w - 16, lh=1.3))
        if t:
            b.append(text(x + w / 2, y + h + 34, t, 20, MUTED, "middle"))
    for (x1, w1, *_), (x2, *_) in zip(steps, steps[1:]):
        b.append(arrow(x1 + w1, y + h / 2, x2, y + h / 2, MUTED, 3))
    b.append(text(30, 100, "no bridge, no middleman: the shop only ever watches the base layer", 22, MUTED,
                  room=1140))
    b.append(text(30, H - 34, "\u2248 2 slots end to end \u2248 25 seconds, under FCR's own conditions", 21, GREEN,
                  room=1140))
    svg("f7-end-to-end.svg", W, H, "Stacked: one signature, one block, confirmed in about two slots", b)


# --------------------------------------------------------------------------- #
# F8: the two-slot checkout at shorter slot times
# --------------------------------------------------------------------------- #
def f8():
    W, H = 1200, 610
    b = [head("// the wait is counted in slots")]
    X0, PX = 330, 30.8  # bar origin, px per second
    rows = [  # slot seconds, label, status
        (12, "12 s slots", "today"),
        (6, "6 s slots", "EIP-7782, draft"),
        (4, "4 s slots", "roadmap sketch"),
        (2, "2 s slots", "speculative last step"),
    ]
    RY0, RH, BH = 160, 82, 34
    # the band a checkout has to fit in to feel like tapping a card
    b.append(rect(X0, RY0 - 30, 5 * PX, RH * len(rows) + 10, stroke=KEY, fill=TINT[KEY], sw=2, rx=8, dash="6 6"))
    b.append(glyph("card", X0 + 24, 102, KEY, s=0.7))
    b.append(text(X0 + 52, 109, "feels like a card tap", 19, KEY))
    b.append(rect(760, 92, 26, 16, stroke=GREEN, fill=TINT[GREEN], sw=2, rx=3))
    b.append(text(796, 106, "block lands", 18, MUTED))
    b.append(rect(940, 92, 26, 16, stroke=BLUE, fill=TINT[BLUE], sw=2, rx=3))
    b.append(text(976, 106, "FCR: safe", 18, MUTED))
    for i, (s, name, status) in enumerate(rows):
        y = RY0 + i * RH
        w = s * PX
        b.append(text(30, y + 12, name, 22, TEXT, bold=True))
        b.append(text(30, y + 38, status, 18, MUTED))
        b.append(rect(X0, y, w - 3, BH, stroke=GREEN, fill=TINT[GREEN], sw=2, rx=4))
        b.append(rect(X0 + w + 1, y, w - 3, BH, stroke=BLUE, fill=TINT[BLUE], sw=2, rx=4))
        lx = max(X0 + 2 * w + 16, X0 + 5 * PX + 14)  # never on the band's edge
        b.append(text(lx, y + 25, f"\u2248 {2 * s + 1} s", 22, GREEN if s == 2 else TEXT, bold=True))
    # seconds axis
    AY = RY0 + RH * len(rows) + 20
    b.append(line(X0, AY, X0 + 25 * PX, AY, MUTED, 1.5))
    for t in range(0, 26, 5):
        b.append(line(X0 + t * PX, AY, X0 + t * PX, AY + 8, MUTED, 1.5))
        b.append(text(X0 + t * PX, AY + 28, f"{t} s", 16, MUTED, "middle"))
    b.append(text(30, H - 22, "both pieces count in slots, so every cut to slot time shortens the whole checkout", 20,
                  MUTED, room=1140))
    svg("f8-card-speed.svg", W, H, "The two-slot checkout at 12, 6, 4 and 2 second slots", b)


# --------------------------------------------------------------------------- #
# F9: cheat sheet
# --------------------------------------------------------------------------- #
def f9():
    needs = ["a trusted bridge + full finality", "a trusted bridge, then FCR once it lands",
             "one atomic block, no bridge, full finality", "one atomic block, no bridge, FCR-confirmed"]
    RH, y0 = 110, 130
    W, H = 1260, y0 + RH * len(BUILDS) + 20
    b = [head("// cheat sheet")]
    for x, t in [(30, "build"), (205, "made of"), (420, "what it needs"), (950, "end to end")]:
        b.append(text(x, 104, t, 22, MUTED))
    for i, ((title, c, cross, confirm, t), need) in enumerate(zip(BUILDS, needs)):
        y = y0 + i * RH
        cy = y + (RH - 10) / 2
        best = title == "BOTH"
        b.append(rect(20, y, 1200, RH - 10, stroke=c if best else LINE, fill=TINT[c] if best else PANEL,
                      sw=3 if best else 2, rx=8))
        b.append(text(40, cy + 8, title, 24, c, bold=True, room=160))
        b.append(recipe(295, cy, cross, confirm, s=0.55, labels=False))
        b.append(text(420, cy + 8, need, 21, TEXT, room=560))
        b.append(chip(1075, cy, t, c, size=21, anchor="middle", h=38))
    svg("f9-cheat-sheet.svg", W, H, "Cheat sheet: four builds, what each needs, end-to-end time", b)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for f in (f1, f2, f3, f4, f5, f6, f7, f8, f9):
        f()
