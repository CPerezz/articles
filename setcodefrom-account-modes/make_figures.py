#!/usr/bin/env python3
"""Draws the article's figures as self-contained SVGs in the site's CRT palette.

    python3 make_figures.py      # writes figures/f1-map.svg ... figures/f7-cheatsheet.svg

Stdlib only. Every label goes through text(), which refuses strings wider than the
room they were given, so a wording change that would overflow a box fails loudly here
instead of quietly in the browser.
"""
import math
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


def arc(x1, y1, x2, y2, h, color, dash=None):
    """Cubic hop from (x1,y1) to (x2,y2); h < 0 bulges up, h > 0 bulges down."""
    return path(f"M{x1},{y1} C{x1},{y1 + h} {x2},{y2 + h} {x2},{y2}", color, 3.5, dash)


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


def key(x, y, s=40, crossed=False):
    """A key glyph starting at x, vertically centred on y; red slash when crossed."""
    r = s * 0.2
    sw = s * 0.1
    out = (f'<g fill="none" stroke="{KEY}" stroke-width="{sw:.1f}" stroke-linecap="round">'
           f'<circle cx="{x + r + sw:.1f}" cy="{y}" r="{r:.1f}"/>'
           f'<path d="M{x + 2 * r + sw:.1f},{y} H{x + s:.1f} M{x + s * 0.76:.1f},{y} v{s * 0.2:.1f} '
           f'M{x + s * 0.92:.1f},{y} v{s * 0.15:.1f}"/></g>')
    if crossed:
        out += (f'<path d="M{x - 3:.1f},{y + s * 0.36:.1f} L{x + s + 3:.1f},{y - s * 0.36:.1f}" '
                f'stroke="{RED}" stroke-width="{sw:.1f}" stroke-linecap="round"/>')
    return out


def mark(cx, cy, ok, r=17):
    """Circled tick (open door) or circled cross (shut door)."""
    c = GREEN if ok else RED
    out = f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{TINT[c]}" stroke="{c}" stroke-width="2.5"/>'
    if ok:
        out += (f'<path d="M{cx - 8},{cy + 1} l5,6 l11,-13" fill="none" stroke="{c}" stroke-width="3.2" '
                f'stroke-linecap="round" stroke-linejoin="round"/>')
    else:
        out += (f'<path d="M{cx - 6.5},{cy - 6.5} l13,13 M{cx + 6.5},{cy - 6.5} l-13,13" stroke="{c}" '
                f'stroke-width="3.2" stroke-linecap="round"/>')
    return out


def loop(cx, cy, color, r=11):
    """Small circular arrow: 'you can change this without leaving the shape'."""
    a0, a1 = math.radians(-40), math.radians(250)
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    return path(f"M{x0:.1f},{y0:.1f} A{r},{r} 0 1,1 {x1:.1f},{y1:.1f}", color, 3, head=True)


def head(s):
    return text(30, 46, s, 22, GREEN, bold=True, spacing=2)


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
# F1: the map of shapes and moves, drawn with and without EIP-7851's key-off delegate
# --------------------------------------------------------------------------- #
def f1(with_7851):
    CY, CH = 330, 340
    bot = CY + CH
    if with_7851:
        lx = 600
        cards = [
            (30, 245, "EOA", "plain account", MUTED, "empty", KEY, False, "in charge", ["your key"], None),
            (315, 245, "DELEGATED", "key on", KEY, "0xef0100+wallet", PURPLE, False, "in charge",
             ["your key, or", "wallet code"], ("new 7702 auth", PURPLE)),
            (640, 245, "DELEGATED", "key off", RED, "0xef0101+wallet", PURPLE, True, "switched off",
             ["wallet code"], ("new delegate", PURPLE)),
            (925, 245, "CODE", "regular code", MUTED, "real bytecode", GREEN, True, "off, or none",
             ["its own code"], ("SETCODEFROM", GREEN)),
        ]
        back = (634, 566)
        rules = ["7702: auths skipped once code is real", "8298: no empty or 0xEF source code",
                 "7851: key off never turns back on"]
    else:
        lx = 770
        cards = [
            (30, 270, "EOA", "plain account", MUTED, "empty", KEY, False, "in charge", ["your key"], None),
            (350, 290, "DELEGATED", "key on", KEY, "0xef0100+wallet", PURPLE, False, "in charge",
             ["your key, or", "wallet code"], ("new 7702 auth", PURPLE)),
            (900, 270, "CODE", "regular code", MUTED, "real bytecode", GREEN, True, "off, or none",
             ["its own code"], ("SETCODEFROM", GREEN)),
        ]
        back = (894, 646)
        rules = ["7702: auths skipped once code is real", "8298: no empty or 0xEF source code"]
    note_h = 76 + 28 * (len(rules) + 1)
    H = 905 + max(note_h, 84) + 90
    W = 1200

    b = [head("// the map" + (", with 7851" if with_7851 else ""))]
    b.append(line(lx, 110, lx, 890, RED, 2.5, "10 8"))
    b.append(chip(lx, 80, "one way", RED, anchor="middle"))
    b.append(text(30, 150, "KEY SIDE", 24, KEY, bold=True, spacing=2))
    b.append(text(30, 180, "your key can always take the wheel back", 22, MUTED, room=lx - 40))
    b.append(text(lx + 40, 150, "CODE SIDE", 24, GREEN, bold=True, spacing=2))
    b.append(text(lx + 40, 180, "only code decides", 22, MUTED, room=W - lx - 70))

    for x, cw, title, sub, subc, code, border, crossed, keytxt, moved, lp in cards:
        room = cw - 36
        b.append(rect(x, CY, cw, CH, stroke=border, sw=2.5))
        b.append(text(x + 18, CY + 46, title, 28, GREEN if title == "CODE" else TEXT, bold=True, room=room))
        b.append(text(x + 18, CY + 80, sub, 24, subc, room=room))
        b.append(chip(x + 18, CY + 122, code, border if border != KEY else MUTED))
        b.append(key(x + 20, CY + 178, 40, crossed))
        b.append(text(x + 74, CY + 186, keytxt, 22, RED if crossed else KEY, room=room - 40))
        b.append(text(x + 18, CY + 232, "moved by", 22, MUTED, room=room))
        b.append(text(x + 18, CY + 260, moved, 22, TEXT, room=room, lh=1.25))
        if lp:
            b.append(loop(x + 30, CY + 311, lp[1]))
            b.append(text(x + 52, CY + 319, lp[0], 22, lp[1], room=room - 16))

    # the way back is shut: a red arrow into the key side, stopped at the line
    my = CY + CH / 2
    b.append(path(f"M{back[0]},{my} L{back[1]},{my}", RED, 3, dash="6 6"))
    b.append(mark(lx, my, False))
    if not with_7851:
        b.append(label(lx, my - 36, "no way back", RED, room=240))

    if with_7851:
        b.append(arc(200, CY, 390, CY, -80, PURPLE))
        b.append(label(295, 222, "sign a 7702 auth", PURPLE, "live since Pectra"))
        b.append(arc(500, CY, 700, CY, -80, PURPLE))
        b.append(label(600, 222, "SETSELFDELEGATE", PURPLE, "7851 (draft)"))
        b.append(arc(830, CY, 985, CY, -80, GREEN, dash="2 9"))
        b.append(label(907, 222, "SETCODEFROM too", GREEN, "not spelled out yet"))
        b.append(arc(480, bot, 990, bot, 160, GREEN))
        b.append(label(735, 846, "wallet code runs SETCODEFROM", GREEN, "8298 (draft)"))
        b.append(arc(360, bot, 200, bot, 80, PURPLE))
        b.append(label(280, 786, "7702 auth to 0x0", PURPLE, "not a pointer: code cleared"))
    else:
        b.append(arc(200, CY, 440, CY, -80, PURPLE))
        b.append(label(320, 222, "sign a 7702 auth", PURPLE, "live since Pectra"))
        b.append(arc(560, bot, 980, bot, 160, GREEN))
        b.append(label(770, 846, "wallet code runs SETCODEFROM", GREEN, "8298 (draft)"))
        b.append(arc(420, bot, 200, bot, 80, PURPLE))
        b.append(label(300, 786, "7702 auth to 0x0", PURPLE, "not a pointer: code cleared"))

    # fresh contracts enter straight into CODE
    b.append(rect(700, 905, 470, 84, stroke=GREEN, sw=2, dash="7 6"))
    b.append(text(720, 940, "a fresh address, no key ever", 24, TEXT, room=430))
    b.append(text(720, 970, "initcode runs SETCODEFROM", 22, MUTED, room=430))
    b.append(arrow(1112, 905, 1112, bot + 8, GREEN))

    # why nothing crosses back
    b.append(rect(30, 905, 640, note_h, stroke=RED, fill=TINT[RED], sw=2))
    b.append(text(52, 942, "no way back to the left", 24, RED, bold=True, room=600))
    b.append(text(52, 976, rules, 22, TEXT, room=600, lh=1.27))
    b.append(text(52, 976 + 28 * len(rules), "on purpose: a retired key stays retired", 22, MUTED,
                  room=600))

    y = H - 34
    b.append(key(30, y - 7, 34))
    b.append(text(76, y, "the key", 22, MUTED))
    b.append(line(210, y - 7, 250, y - 7, PURPLE, 4))
    b.append(text(262, y, "7702 family", 22, MUTED))
    b.append(line(440, y - 7, 480, y - 7, GREEN, 4))
    b.append(text(492, y, "SETCODEFROM", 22, MUTED))
    ox = 670
    if with_7851:
        b.append(line(670, y - 7, 710, y - 7, GREEN, 4, "2 9"))
        b.append(text(722, y, "not spelled out yet", 22, MUTED))
        ox = 1000
    b.append(line(ox, y - 7, ox + 40, y - 7, RED, 3, "10 8"))
    b.append(text(ox + 52, y, "one way", 22, MUTED))
    if with_7851:
        svg("f1-map-with-7851.svg", W, H, "The four account shapes, EIP-7851 included, and every move between them", b)
    else:
        svg("f1-map.svg", W, H, "The three account shapes that matter and every move between them", b)


# --------------------------------------------------------------------------- #
# F2: who can do what, per shape
# --------------------------------------------------------------------------- #
def f2():
    W, H = 1200, 800
    b = [head("// who can do what")]
    cols = [(290, "key sends a", "plain tx"), (510, "key signs a", "7702 auth"),
            (730, "ecrecover", "returns you"), (950, "8141 (draft)", "frame tx")]
    CW = 210
    for x, top, bottom in cols:
        b.append(text(x + 10, 104, top, 22, MUTED, room=CW))
        b.append(text(x + 10, 134, bottom, 24, TEXT, bold=True, room=CW))
    rows = [
        ("EOA", "empty code", KEY, [("YES", KEY, ["the classic"]), ("YES", KEY, ["any time"]),
                                   ("YES", KEY, ["as today"]), ("YES", BLUE, ["default code"])]),
        ("DELEGATED", "key on", PURPLE, [("YES", KEY, ["3607 skips", "0xef0100 (7702)"]),
                                        ("YES", KEY, ["switch wallets"]), ("YES", KEY, ["as today"]),
                                        ("YES", BLUE, ["your wallet", "decides"])]),
        ("DELEGATED", "key off, skip it", PURPLE, [("NO", RED, ["7851"]), ("NO", RED, ["7851"]),
                                                  ("NO", RED, ["8151"]),
                                                  ("YES *", BLUE, ["your wallet", "decides"])]),
        ("CODE", "fresh or migrated", GREEN, [("NO", RED, ["3607"]), ("NO", RED, ["7702 auth check"]),
                                              ("NO", RED, ["8151"]), ("YES", BLUE, ["your code", "decides"])]),
    ]
    subc = {"empty code": MUTED, "key on": KEY, "key off, skip it": MUTED, "fresh or migrated": MUTED}
    RH, y0 = 135, 162
    for i, (name, sub, accent, cells) in enumerate(rows):
        y = y0 + i * RH
        dim = "skip" in sub
        if dim:
            b.append('<g opacity="0.38">')
        b.append(rect(20, y + 6, 1160, RH - 12, stroke=LINE, fill=PANEL, rx=8))
        b.append(f'<rect x="20" y="{y + 6}" width="7" height="{RH - 12}" fill="{MUTED if dim else accent}"/>')
        b.append(text(44, y + 58, name, 28, GREEN if name == "CODE" else TEXT, bold=True, room=240))
        b.append(text(44, y + 92, sub, 22, subc[sub], room=240))
        for (x, _, _), (verdict, c, note) in zip(cols, cells):
            b.append(chip(x + 10, y + 44, verdict, c, size=24, dash="3 5" if "*" in verdict else None, h=40))
            b.append(text(x + 12, y + 96, note, 22, MUTED, room=CW, lh=1.2))
        if dim:
            b.append("</g>")
    # the one way line sits between key on and key off, as on the map
    ly = y0 + 2 * RH
    b.append(line(20, ly, 1180, ly, RED, 2.5, "10 8"))
    b.append(chip(1125, ly, "one way", RED, anchor="middle", h=34))
    b.append(text(30, 736, "* 7851 says 0xef0101 runs like 0xef0100. 8141 doesn't mention 7851 yet.", 22, MUTED,
                  room=1140))
    b.append(text(30, 768, "Drafts: 7851, 8141, 8151. Live: 3607, 7702.", 22, MUTED, room=1140))
    svg("f2-who-can-do-what.svg", W, H, "What the key and the code can do in each shape", b)


# --------------------------------------------------------------------------- #
# F3/F5/F6 share one drawing: a key on the left, lanes into an account on the right
# --------------------------------------------------------------------------- #
def lanes(y0, rows, account, rules_note):
    """rows: (label, state, reason). state: 'open' skips the rules, 'rules' goes through
    them, 'native' goes through the protocol's signature check and then the rules, 'shut'
    stops at a red door. account: (title, chip text, chip colour)."""
    b = []
    ys = [y0 + 40 + i * 72 for i in range(len(rows))]
    kx, ky = 40, (ys[0] + ys[-1]) / 2
    b.append(key(kx, ky, 64))
    b.append(text(kx, ky + 56, "your key", 22, KEY))
    ax, aw = 900, 270
    b.append(rect(ax, ys[0] - 36, aw, ys[-1] - ys[0] + 72, stroke=account[2], sw=2.5))
    b.append(text(ax + 20, ky - 10, account[0], 24, TEXT, bold=True, room=aw - 40))
    b.append(chip(ax + 20, ky + 28, account[1], account[2]))
    for (lbl, state, reason), y in zip(rows, ys):
        b.append(path(f"M{kx + 70},{ky} C{kx + 130},{ky} {kx + 110},{y} {kx + 170},{y}",
                      MUTED, 2, head=False))
        b.append(text(212, y - 12, lbl, 22, TEXT, room=320))
        if state == "shut":
            b.append(line(212, y, 580, y, MUTED, 2.5))
            b.append(mark(600, y, False))
            b.append(text(630, y + 8, reason, 22, RED, room=250))
        elif state == "open":
            b.append(arrow(212, y, ax - 6, y, KEY, 3))
            b.append(text(630, y - 12, reason, 22, MUTED, room=260))
        elif state == "native":
            b.append(line(212, y, 505, y, BLUE, 3))
            b.append(rect(505, y - 24, 190, 48, stroke=TEXT, fill=PANEL, rx=8))
            b.append(text(600, y + 8, "native ECDSA", 22, TEXT, "middle", room=176))
            b.append(text(600, y + 50, "protocol", 22, MUTED, "middle", room=190))
            b.append(arrow(695, y, 711, y, BLUE, 3))
            b.append(rect(717, y - 24, 160, 48, stroke=BLUE, fill=TINT[BLUE], rx=8))
            b.append(text(797, y + 8, "your rules", 22, BLUE, "middle", room=150))
            b.append(text(797, y + 50, "your code", 22, MUTED, "middle", room=160))
            b.append(arrow(877, y, ax - 6, y, BLUE, 3))
        else:
            b.append(line(212, y, 560, y, BLUE, 3))
            b.append(rect(560, y - 24, 200, 48, stroke=BLUE, fill=TINT[BLUE], rx=8))
            b.append(text(660, y + 8, "your rules", 22, BLUE, "middle", room=180))
            b.append(arrow(760, y, ax - 6, y, BLUE, 3))
            if rules_note:
                b.append(text(560, y + 50, rules_note, 22, MUTED, room=640))
    return b


def f3():
    W, H = 1200, 1070
    b = [head("// want 1: keep the key")]
    b.append(text(30, 110, "A. STAY A DELEGATE, KEY ON", 24, PURPLE, bold=True))
    b.append(text(30, 140, "the cheap detour: you may not need to cross at all", 22, MUTED))
    b += lanes(150, [("plain tx", "open", "3607 skips 0xef0100"),
                     ("7702 auth", "open", "switch or clear"),
                     ("permit via ecrecover", "open", "works as today"),
                     ("frame tx (8141 draft)", "rules", None)],
               ("your account", "0xef0100+wallet", PURPLE), None)
    b.append(chip(30, 470, "your rules are advice: the key walks around them", KEY))
    b.append(text(30, 514, "and heads up: your wallet code can move you across the line too", 22, MUTED,
                  room=1140))
    b.append(line(20, 546, 1180, 546, LINE, 2))
    b.append(text(30, 600, "B. CROSS WITH SETCODEFROM, THE KEY STAYS A SIGNER", 24, GREEN, bold=True))
    b.append(text(30, 630, "the protocol checks the signature natively, your code decides", 22, MUTED))
    b += lanes(640, [("plain tx", "shut", "3607"),
                     ("7702 auth", "shut", "7702 auth check"),
                     ("permit via ecrecover", "shut", "8151 (draft)"),
                     ("frame tx (8141 draft)", "native", None)],
               ("your account", "real bytecode", GREEN), None)
    b.append(rect(20, 972, 1160, 78, stroke=LINE, fill=PANEL, rx=8))
    b.append(text(40, 1002, "signed messages for other contracts (ERC 1271): your code checks ECDSA itself",
                  22, TEXT, room=1120))
    b.append(text(40, 1032, "8151 hides your own address from ecrecover: use the ECMUL trick or a second key",
                  22, MUTED, room=1120))
    svg("f3-keep-the-key.svg", W, H, "Keeping the ECDSA key: stay a delegate, or cross and keep it as a signer", b)


# --------------------------------------------------------------------------- #
# F4: a contract with no key, ever
# --------------------------------------------------------------------------- #
def f4():
    W, H = 1200, 760
    b = [head("// want 2: a cheap copy of deployed code")]
    steps = [("deploy", "tx or CREATE2", MUTED), ("initcode", "SSTORE state", MUTED),
             ("SETCODEFROM", "(template)", GREEN), ("your clone", "template code", GREEN)]
    bw, gap, x0, y = 255, 40, 30, 96
    for i, (t, s, c) in enumerate(steps):
        x = x0 + i * (bw + gap)
        b.append(rect(x, y, bw, 110, stroke=c if c != MUTED else LINE, sw=2.5))
        b.append(text(x + bw / 2, y + 46, t, 24, GREEN if c == GREEN else TEXT, "middle", bold=True, room=bw - 16))
        b.append(text(x + bw / 2, y + 80, s, 22, MUTED, "middle", room=bw - 16))
        if i:
            b.append(arrow(x - gap + 4, y + 55, x - 6, y + 55, GREEN, 3))
    # template and the pinned pointer
    tx = x0 + 2 * (bw + gap)
    b.append(rect(tx, 290, bw * 2 + gap, 100, stroke=GREEN, sw=2, dash="7 6"))
    b.append(text(tx + 20, 330, "template, deployed once", 24, TEXT, room=400))
    b.append(text(tx + 20, 362, "every clone points here", 22, MUTED, room=400))
    cx = x0 + 3 * (bw + gap) + bw / 2
    b.append(path(f"M{cx},{y + 110} L{cx},{286}", GREEN, 3, dash="3 6"))
    b.append(text(cx - 14, 256, "same codeHash", 22, MUTED, "end", room=300))
    b.append(text(30, 318, "pinned: if the template changes or dies,", 22, TEXT, room=660))
    b.append(text(30, 346, "your clone keeps its code", 22, TEXT, room=660))
    # what the clone saves: the code deposit, priced per byte under 8037
    b.append(text(30, 392, "code cost, 32 KiB template (8037 prices)", 22, MUTED, room=660))
    b.append(text(30, 428, "via CREATE", 22, TEXT, room=210))
    b.append(f'<rect x="250" y="412" width="310" height="20" rx="3" fill="{MUTED}"/>')
    b.append(text(572, 428, "50.1M gas", 22, TEXT, bold=True, room=150))
    b.append(text(30, 462, "via SETCODEFROM", 22, GREEN, room=210))
    b.append(f'<rect x="250" y="446" width="4" height="20" rx="1" fill="{GREEN}"/>')
    b.append(text(264, 462, "9.3k gas, any size", 22, GREEN, bold=True, room=390))
    # contrast: a delegate is a live key by design, a clone has none
    y2 = 500
    b.append(rect(30, y2, 555, 230, stroke=PURPLE, sw=2.5))
    b.append(text(54, y2 + 44, "a 7702 wallet", 24, PURPLE, bold=True, room=500))
    b.append(key(54, y2 + 106, 64))
    b.append(text(140, y2 + 100, "a live key, by design", 22, TEXT, room=420))
    b.append(text(140, y2 + 128, "it can always send a plain tx", 22, MUTED, room=420))
    b.append(text(54, y2 + 196, "that's the point of 7702", 22, MUTED, room=500))
    b.append(rect(615, y2, 555, 230, stroke=GREEN, sw=2.5))
    b.append(text(639, y2 + 44, "this clone", 24, GREEN, bold=True, room=500))
    b.append(key(639, y2 + 106, 64, crossed=True))
    b.append(text(725, y2 + 100, "no key exists", 22, TEXT, room=420))
    b.append(text(725, y2 + 128, "nothing to switch off later", 22, MUTED, room=420))
    b.append(text(639, y2 + 180, ["even a 2^80 collision key gets nothing:",
                                   "3607, the 7702 auth check, 8151"], 21, MUTED, room=510, lh=1.3))
    svg("f4-no-key-contract.svg", W, H, "A cheap copy of deployed code with SETCODEFROM, and no key", b)


# --------------------------------------------------------------------------- #
# F5: retire the key
# --------------------------------------------------------------------------- #
def f5():
    W, H = 1200, 880
    b = [head("// want 3: retire the key")]
    b.append(text(30, 104, "one type 4 transaction", 22, MUTED))
    b.append(path("M30,118 L30,128 L1170,128 L1170,118", MUTED, 2, head=False))
    stages = [(30, "1. delegate me", ["to the migrator"], PURPLE),
              (420, "2. call myself", ["SSTORE pq pubkey", "SSTORE recovery"], MUTED),
              (810, "3. SETCODEFROM", ["(PQ wallet)"], GREEN)]
    for x, t, s, c in stages:
        b.append(rect(x, 146, 360, 130, stroke=c if c != MUTED else LINE, sw=2.5))
        b.append(text(x + 22, 188, t, 24, GREEN if c == GREEN else TEXT, bold=True, room=320))
        b.append(text(x + 22, 222, s, 22, MUTED, room=320))
    b.append(arrow(394, 211, 414, 211, GREEN, 3))
    b.append(arrow(784, 211, 804, 211, GREEN, 3))
    # what can go wrong
    b.append(path("M990,276 L990,318", RED, 2.5, dash="3 6"))
    b.append(rect(810, 322, 360, 128, stroke=RED, fill=TINT[RED], sw=2, dash="7 6"))
    b.append(text(830, 356, "returned 0 or reverted?", 22, RED, bold=True, room=320))
    b.append(text(830, 386, ["still delegated to the", "migrator, key on. Sign", "a new auth to leave."],
                  22, TEXT, room=320, lh=1.2))
    b.append(text(420, 316, ["gate the migrator: only", "a call from yourself,", "or your own signature"],
                  22, MUTED, room=360, lh=1.25))
    # before and after, three doors
    y = 520
    b.append(rect(30, y, 250, 170, stroke=PURPLE, sw=2.5))
    b.append(text(52, y + 46, "DELEGATED", 26, TEXT, bold=True, room=210))
    b.append(text(52, y + 80, "key on", 22, KEY, room=210))
    b.append(key(52, y + 128, 50))
    b.append(arrow(292, y + 85, 360, y + 85, GREEN, 3.5))
    b.append(rect(372, y, 250, 170, stroke=GREEN, sw=2.5))
    b.append(text(394, y + 46, "CODE", 26, GREEN, bold=True, room=210))
    b.append(text(394, y + 80, "PQ wallet", 22, MUTED, room=210))
    b.append(key(394, y + 128, 50, crossed=True))
    doors = [("plain tx", "3607"), ("redelegate", "7702 auth check"), ("ecrecover permit", "8151 (draft)")]
    for i, (what, why) in enumerate(doors):
        dy = y + 32 + i * 54
        b.append(mark(686, dy, False))
        b.append(text(716, dy + 8, what, 22, TEXT, room=260))
        b.append(text(1170, dy + 8, why, 22, RED, "end", room=230))
    b.append(text(30, 760, ["on this chain only: the key still signs on other chains,",
                             "off chain, and in contracts that do ECDSA in their own code"],
                  22, MUTED, room=1140, lh=1.3))
    b.append(text(30, 834, "leaked key? the same move is a panic button, if your tx lands first", 22, MUTED,
                  room=1140))
    svg("f5-retire-the-key.svg", W, H, "Retiring the ECDSA key with SETCODEFROM", b)


# --------------------------------------------------------------------------- #
# F6: back to ECDSA
# --------------------------------------------------------------------------- #
def f6():
    W, H = 1200, 950
    b = [head("// want 4: back to ECDSA")]
    b.append(text(30, 110, "A. FROM A DELEGATE, KEY ON", 24, PURPLE, bold=True))
    y = 140
    b.append(rect(30, y, 300, 140, stroke=PURPLE, sw=2.5))
    b.append(text(52, y + 48, "DELEGATED", 26, TEXT, bold=True, room=260))
    b.append(text(52, y + 82, "key on", 22, KEY, room=260))
    b.append(key(200, y + 76, 50))
    b.append(arrow(342, y + 70, 830, y + 70, PURPLE, 3.5))
    b.append(label(586, y + 52, "7702 auth to 0x0", PURPLE, "not a pointer: code cleared"))
    b.append(rect(842, y, 328, 140, stroke=KEY, sw=2.5))
    b.append(text(864, y + 48, "EOA", 26, TEXT, bold=True, room=280))
    b.append(text(864, y + 82, "a true EOA again", 22, MUTED, room=280))
    b.append(key(1080, y + 76, 50))
    b.append(line(20, 330, 1180, 330, LINE, 2))
    b.append(text(30, 384, "B. FROM CODE", 24, GREEN, bold=True))
    y = 414
    b.append(rect(30, y, 300, 170, stroke=GREEN, sw=2.5))
    b.append(text(52, y + 48, "CODE", 26, GREEN, bold=True, room=260))
    b.append(text(52, y + 82, "PQ, passkey,", 22, MUTED, room=260))
    b.append(text(52, y + 110, "anything", 22, MUTED, room=260))
    b.append(key(52, y + 142, 44, crossed=True))
    b.append(arrow(342, y + 85, 580, y + 85, GREEN, 3.5))
    b.append(text(461, y + 60, "SETCODEFROM", 22, GREEN, "middle", bold=True, room=230))
    b.append(text(461, y + 126, ["ECDSA owner", "template"], 22, MUTED, "middle", room=230))
    b.append(rect(592, y, 578, 170, stroke=GREEN, sw=2.5))
    b.append(text(614, y + 48, "CODE, ECDSA owner", 26, GREEN, bold=True, room=540))
    b.append(key(614, y + 102, 44))
    b.append(rect(686, y + 80, 220, 44, stroke=TEXT, fill=PANEL, rx=8))
    b.append(text(796, y + 109, "Solidity ECDSA", 22, TEXT, "middle", room=204))
    b.append(text(796, y + 152, "more gas, slower", 20, RED, "middle", room=220))
    b.append(arrow(906, y + 102, 920, y + 102, BLUE, 3))
    b.append(rect(924, y + 80, 150, 44, stroke=BLUE, fill=TINT[BLUE], rx=8))
    b.append(text(999, y + 109, "your rules", 22, BLUE, "middle", room=140))
    b.append(text(614, y + 210, "no ecrecover for your own address (8151)", 22, MUTED, room=556))
    b.append(text(30, 672, "stays shut, on purpose", 22, RED, bold=True))
    shut = [("plain legacy tx", "3607"), ("old contracts trusting the key via ecrecover", "8151 (draft)")]
    for i, (what, why) in enumerate(shut):
        dy = 716 + i * 54
        b.append(mark(48, dy, False))
        b.append(text(80, dy + 8, what, 22, TEXT, room=760))
        b.append(text(1170, dy + 8, why, 22, RED, "end", room=300))
    b.append(chip(30, 846, "ECDSA is all you want? a 7702 delegation already does it natively", PURPLE, size=21))
    b.append(chip(30, 898, "still open: native checks through 8141 frame txs", BLUE, size=21, dash="7 6"))
    svg("f6-back-to-ecdsa.svg", W, H, "Two ways back to ECDSA control, and what stays shut", b)


# --------------------------------------------------------------------------- #
# F7: cheat sheet
# --------------------------------------------------------------------------- #
def f7():
    rows = [
        (["AA perks, zero setup"], ["nothing: send 8141", "frame txs"], ("EOA", KEY), [("8141", True)]),
        (["smart wallet, the key", "stays the boss"], ["sign a 7702 auth"], ("DELEGATED", PURPLE), [("7702", False)]),
        (["code account, the key", "still signs"], ["SETCODEFROM a wallet", "that speaks 8141"], ("CODE", GREEN),
         [("8298", True), ("8141", True)]),
        (["cheap copy of a", "deployed contract"], ["deploy with initcode", "that runs SETCODEFROM"],
         ("CODE", GREEN), [("8298", True)]),
        (["retire the key, go", "post quantum"], ["store the PQ key, then", "SETCODEFROM a PQ wallet"],
         ("CODE", GREEN), [("8298", True), ("8151", True)]),
        (["switch wallets later"], ["delegate: new 7702 auth", "CODE: SETCODEFROM"],
         ("same", MUTED), [("7702", False), ("8298", True)]),
        (["back to a plain EOA"], ["sign a 7702 auth to 0x0", "(only while you're still", "a 7702 delegate)"],
         ("EOA", KEY), [("7702", False)]),
        (["an ECDSA owner again", "after going code"], ["SETCODEFROM an ECDSA", "owner template, checks", "run in Solidity"],
         ("CODE", GREEN), [("8298", True)]),
    ]
    RH, y0 = 118, 130
    W, H = 1200, y0 + RH * len(rows) + 70
    b = [head("// cheat sheet")]
    for x, t in [(30, "you want"), (420, "do this"), (820, "you end up"), (1010, "needs")]:
        b.append(text(x, 104, t, 22, MUTED))
    for i, (want, do, (shape, sc), needs) in enumerate(rows):
        y = y0 + i * RH
        b.append(rect(20, y, 1160, RH - 10, stroke=LINE, fill=PANEL, rx=8))
        n = max(len(want), len(do))
        ty = y + (RH - 10) / 2 - (n - 1) * 14 + 8
        b.append(text(40, ty, want, 24, TEXT, bold=True, room=370, lh=1.17))
        b.append(text(420, ty, do, 22, TEXT, room=380, lh=1.27))
        b.append(chip(820, y + (RH - 10) / 2, shape, sc, size=22))
        for j, (eip, draft) in enumerate(needs):
            cy = y + (RH - 10) / 2 + (j - (len(needs) - 1) / 2) * 32
            b.append(chip(1010, cy, eip, MUTED if draft else TEXT, size=19, dash="4 4" if draft else None, h=28))
    b.append(text(30, H - 26, "dashed = draft, solid = live", 22, MUTED))
    svg("f7-cheat-sheet.svg", W, H, "Cheat sheet: what you want, what to do, where you end up", b)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    f1(True)
    f1(False)
    for f in (f2, f3, f4, f5, f6, f7):
        f()
