#!/usr/bin/env python3
"""Draws the article's figures as self-contained SVGs in the site's CRT palette.

    python3 make_figures.py      # writes figures/f1-two-properties.svg ... figures/f10-cheat-sheet.svg

Stdlib only. Every label goes through text(), which refuses strings wider than the
room they were given, so a wording change that would overflow a box fails loudly here
instead of quietly in the browser.

Every number drawn here is defined once in DATA below, with where it was measured.
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

# --------------------------------------------------------------------------- #
# the numbers
# --------------------------------------------------------------------------- #
DATA = {
    # Whole-chain census of deployed code, mainnet to block 26,430,999 (corrected totals).
    "creations": 104_313_762,
    "codes": 3_031_417,
    "a7_at_instruction": 212_172,
    "a7_trailer_only": 84_825,
    "candidates": 29,
    "reach_from_entry": 11,
    "execute_it": 2,
    "go_on": 0,
    "dc_codes": 989_538,
    "dc_creations": 65_326_187,
    # Shape of the creations that can reach DELEGATECALL, on the census as first run
    # (65,261,971 of 104,236,728 creations; the later correction added 0.1 %).
    "dc_first_run": 65_261_971,
    "top400": 61_682_120,
    "erc1167_in_top400": 51_350_051,
}


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


def chip(x, y, s, color=MUTED, size=22, anchor="start", dash=None, h=38):
    """Rounded pill around one line of text; (x, y) is the left (or centre) of its middle line."""
    w = tw(s, size) + 26
    left = x - w / 2 if anchor == "middle" else x
    out = rect(left, y - h / 2, w, h, stroke=color, fill=TINT.get(color, PANEL), sw=2, rx=h / 2, dash=dash)
    out += text(left + w / 2, y + size * 0.36, s, size, color, "middle")
    return out


def mark(cx, cy, ok, r=17):
    """Circled tick or circled cross."""
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


def card(x, y, w, h, title, lines, color=LINE, title_color=TEXT, size=22, tsize=24):
    """A panel with a bold first line and muted lines under it."""
    out = rect(x, y, w, h, stroke=color, sw=2.5)
    out += text(x + 20, y + 42, title, tsize, title_color, bold=True, room=w - 36)
    if lines:
        out += text(x + 20, y + 76, lines, size, MUTED, room=w - 36, lh=1.3)
    return out


def account(x, y, w, h, name, code, color=GREEN):
    """An account: its name, and a chip with the code it holds."""
    out = rect(x, y, w, h, stroke=color, sw=2.5)
    out += text(x + 18, y + 40, name, 24, TEXT, bold=True, room=w - 30)
    out += chip(x + 18, y + 78, code, color)
    return out


def n(v):
    return f"{v:,}"


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
# F1: the two things that hold today
# --------------------------------------------------------------------------- #
def f1():
    W, H = 1200, 640
    b = [head("// two things every contract can count on today")]
    # left: what you show is what you run
    b.append(rect(30, 80, 555, 400, stroke=GREEN, sw=2.5))
    b.append(text(54, 124, "1. what you show is what you run", 24, GREEN, bold=True, room=510))
    b.append(account(54, 156, 230, 110, "account A", "code X"))
    b.append(text(54, 304, "A's frames run X", 22, TEXT, room=240))
    b.append(arrow(540, 196, 296, 196, BLUE, 3))
    b.append(text(560, 176, "EXTCODEHASH(A)?", 22, BLUE, "end", room=240))
    b.append(arrow(296, 236, 540, 236, GREEN, 3))
    b.append(text(560, 262, "X", 22, GREEN, "end", bold=True, room=240))
    b.append(text(54, 350, ["so a contract can recognise a caller", "by its code, and trust it"], 22, MUTED,
                  room=510, lh=1.3))
    b.append(mark(72, 440, False))
    b.append(text(102, 448, "draft: A shows X while it runs Y", 22, RED, room=460))
    # right: your code is yours
    b.append(rect(615, 80, 555, 400, stroke=GREEN, sw=2.5))
    b.append(text(639, 124, "2. your code is yours", 24, GREEN, bold=True, room=510))
    b.append(account(639, 156, 172, 110, "account A", "code X"))
    b.append(arrow(818, 211, 966, 211, PURPLE, 3))
    b.append(text(892, 196, "DELEGATECALL", 18, PURPLE, "middle", room=146))
    b.append(account(974, 156, 172, 110, "library L", "code L", PURPLE))
    b.append(mark(657, 316, True))
    b.append(text(687, 324, "L can write A's storage", 22, TEXT, room=460))
    b.append(mark(657, 366, True))
    b.append(text(687, 374, "L cannot replace A's code", 22, TEXT, room=460))
    b.append(mark(657, 440, False))
    b.append(text(687, 448, "draft: L replaces A's code", 22, RED, room=460))
    b.append(text(30, 536, ["both hold since Cancun: EIP-6780 took away the last way to change",
                             "deployed code. Routers, wallets, guards and registries lean on them."],
                  22, MUTED, room=1140, lh=1.3))
    b.append(text(30, 610, "the draft of SETCODEFROM gave both up. The update gives both back.", 22, TEXT,
                  bold=True, room=1140))
    svg("f1-two-properties.svg", W, H, "Two properties of deployed code that the draft gave up", b)


# --------------------------------------------------------------------------- #
# F2: the masquerade, on sudoswap's router
# --------------------------------------------------------------------------- #
def lanes(b, names, y0, y1):
    for x, name, color in names:
        w = tw(name, 22) + 36
        b.append(rect(x - w / 2, y0, w, 50, stroke=color, sw=2.5))
        b.append(text(x, y0 + 33, name, 22, TEXT, "middle", bold=True))
        b.append(line(x, y0 + 50, x, y1, LINE, 2, "4 7"))


def f2():
    W, H = 1200, 900
    b = [head("// finding 1: show one code, run another")]
    M, R, F, N = 170, 520, 830, 1080
    lanes(b, [(M, "attacker M", RED), (R, "router", BLUE), (F, "factory", BLUE), (N, "victim's NFT", KEY)], 80, 690)
    # 1. adopt
    b.append(chip(M, 178, "SETCODEFROM(pair)", RED, anchor="middle"))
    b.append(f'<rect x="{M + 140}" y="148" width="360" height="62" fill="{BG}"/>')
    b.append(text(M + 150, 172, "M now shows a pair's code", 22, TEXT, room=420))
    b.append(text(M + 150, 200, "and keeps running its own", 22, MUTED, room=420))
    # 2. ask the router
    b.append(arrow(M, 262, R - 6, 262, RED, 3))
    b.append(text((M + R) / 2, 250, "move the NFT to me", 22, RED, "middle", room=330))
    # 3. router asks the factory
    b.append(arrow(R, 332, F - 6, 332, BLUE, 3))
    b.append(text((R + F) / 2, 320, "is M a pair?", 22, BLUE, "middle", room=290))
    b.append(text(F + 20, 392, ["reads 73 bytes", "of M's code"], 22, MUTED, room=330, lh=1.25))
    b.append(arrow(F, 462, R + 6, 462, GREEN, 3, "8 6"))
    b.append(text((R + F) / 2, 450, "yes", 22, GREEN, "middle", bold=True, room=290))
    # 4. the transfer
    b.append(arrow(R, 532, N - 6, 532, BLUE, 3))
    b.append(text((R + N) / 2, 520, "transfer: victim → M", 22, BLUE, "middle", room=540))
    # 5. cover the tracks
    b.append(chip(M, 612, "SETCODEFROM(twin)", RED, anchor="middle"))
    b.append(f'<rect x="{M + 140}" y="582" width="380" height="62" fill="{BG}"/>')
    b.append(text(M + 150, 606, "back to its old code:", 22, TEXT, room=420))
    b.append(text(M + 150, 634, "no code change left to see", 22, MUTED, room=420))
    # outcomes
    b.append(rect(30, 716, 555, 110, stroke=RED, fill=TINT[RED], sw=2.5))
    b.append(text(54, 758, "draft", 24, RED, bold=True, room=500))
    b.append(text(54, 792, "the NFT moves to the attacker", 22, TEXT, room=500))
    b.append(rect(615, 716, 555, 110, stroke=GREEN, fill=TINT[GREEN], sw=2.5))
    b.append(text(639, 758, "with the update", 24, GREEN, bold=True, room=500))
    b.append(text(639, 792, "the factory says no: \"Not pair\"", 22, TEXT, room=500))
    b.append(text(30, 868, "sudoswap v1 router and factory, mainnet bytecode, run on two implementations", 22,
                  MUTED, room=1140))
    svg("f2-masquerade.svg", W, H, "An account that shows a pair's code while it runs its own", b)


# --------------------------------------------------------------------------- #
# F3: borrowed code replaces the borrower, on a Safe
# --------------------------------------------------------------------------- #
def f3():
    W, H = 1200, 800
    b = [head("// finding 2: code you borrow replaces your code")]
    # who runs what: a module asks the Safe, the Safe borrows the singleton, the singleton borrows a payload
    y0, h = 140, 150
    b.append(rect(30, y0, 200, h, stroke=MUTED, sw=2.5))
    b.append(text(50, y0 + 42, "a module", 22, TEXT, bold=True, room=160))
    b.append(text(50, y0 + 76, ["enabled on", "the Safe"], 19, MUTED, room=160, lh=1.3))
    b.append(rect(290, y0, 260, h, stroke=GREEN, sw=2.5))
    b.append(text(310, y0 + 42, "the Safe", 22, TEXT, bold=True, room=220))
    b.append(chip(310, y0 + 86, "own code: proxy", GREEN, size=20))
    b.append(text(310, y0 + 132, "171 bytes", 19, MUTED, room=220))
    b.append(rect(620, y0, 240, h, stroke=PURPLE, sw=2.5))
    b.append(text(640, y0 + 42, "Safe singleton", 22, TEXT, bold=True, room=200))
    b.append(text(640, y0 + 76, ["1.4.1, borrowed"], 19, PURPLE, room=200))
    b.append(rect(930, y0, 240, h, stroke=PURPLE, sw=2.5))
    b.append(text(950, y0 + 42, "a payload", 22, TEXT, bold=True, room=200))
    b.append(text(950, y0 + 76, "borrowed", 19, PURPLE, room=200))
    b.append(chip(950, y0 + 118, "SETCODEFROM(T)", RED, size=19))
    b.append(arrow(234, y0 + 75, 284, y0 + 75, MUTED, 3))
    b.append(text(259, y0 + 62, "call", 18, MUTED, "middle", room=50))
    b.append(arrow(554, y0 + 75, 614, y0 + 75, PURPLE, 3.5))
    b.append(arrow(864, y0 + 75, 924, y0 + 75, PURPLE, 3.5))
    # the borrowed code reaches back into the Safe's own code
    b.append(path(f"M1050,{y0 - 4} C1050,80 420,80 420,{y0 - 8}", RED, 3.5))
    b.append(text(735, 84, "draft: the payload replaces the Safe's code", 20, RED, "middle", bold=True, room=600))
    b.append(line(290, y0 + h + 22, 1170, y0 + h + 22, PURPLE, 2))
    b.append(line(290, y0 + h + 12, 290, y0 + h + 22, PURPLE, 2))
    b.append(line(1170, y0 + h + 12, 1170, y0 + h + 22, PURPLE, 2))
    b.append(text(730, y0 + h + 52, "purple arrows: DELEGATECALL, so all three run as the Safe", 20, PURPLE, "middle",
                  room=860))
    # what each version does
    y1 = 380
    b.append(rect(30, y1, 555, 330, stroke=RED, fill=TINT[RED], sw=2.5))
    b.append(text(54, y1 + 44, "draft: the Safe afterwards", 24, RED, bold=True, room=510))
    rows = [(False, "its code is T, the payload's pick"), (True, "owners, threshold, modules: same"),
            (True, "singleton slot and balance: same")]
    for i, (ok, s) in enumerate(rows):
        yy = y1 + 96 + i * 52
        b.append(mark(72, yy, ok))
        b.append(text(104, yy + 8, s, 21, TEXT, room=460))
    b.append(text(54, y1 + 270, ["the module call reports success, and a", "guard checking storage sees nothing"], 20,
                  MUTED, room=510, lh=1.3))
    b.append(rect(615, y1, 555, 330, stroke=GREEN, fill=TINT[GREEN], sw=2.5))
    b.append(text(639, y1 + 44, "with rule 2", 24, GREEN, bold=True, room=510))
    b.append(text(639, y1 + 96, ["SETCODEFROM asks first: is the code", "running here the Safe's own code?",
                                 "The payload is not, so the frame halts",
                                 "before any gas, as 0xA7 does today."], 21, TEXT, room=510, lh=1.32))
    b.append(mark(657, y1 + 244, True))
    b.append(text(689, y1 + 252, "the Safe keeps its proxy", 21, TEXT, room=460))
    b.append(text(639, y1 + 296, "the module call reports failure", 20, MUTED, room=510))
    b.append(text(30, 760, "Safe 1.4.1 proxy and singleton, mainnet bytecode, run on two implementations", 22,
                  MUTED, room=1140))
    svg("f3-borrowed-code.svg", W, H, "A payload run by DELEGATECALL replaces a Safe's code", b)


# --------------------------------------------------------------------------- #
# F4: who runs borrowed code
# --------------------------------------------------------------------------- #
def f4():
    W, H = 1200, 820
    b = [head("// who runs borrowed code?")]
    total, dc, clones = DATA["creations"], DATA["dc_creations"], DATA["erc1167_in_top400"]
    b.append(text(30, 122, f"{dc / total * 100:.1f} %", 46, PURPLE, bold=True, room=200))
    b.append(text(236, 102, f"of the {n(total)} contract creations that left code", 22, TEXT, room=930))
    b.append(text(236, 132, "can run code they borrow: a DELEGATECALL or CALLCODE is reachable", 20, MUTED,
                  room=930))
    rows = [("minimal clones (ERC-1167)", ["45 bytes that forward every call", "to one fixed implementation"],
             clones, PURPLE, True, "at least "),
            ("other code that can DELEGATECALL", ["Safe proxies, other proxies,", "wallets, a long tail"],
             dc - clones, PURPLE, False, ""),
            ("never borrows code", ["no DELEGATECALL or CALLCODE", "it can reach"], total - dc, MUTED, False, "")]
    x0, full = 600, 560
    for i, (name, desc, v, c, filled, pre) in enumerate(rows):
        y = 176 + i * 100
        b.append(text(30, y + 30, name, 22, TEXT, bold=True, room=550))
        b.append(text(30, y + 60, desc, 19, MUTED, room=550, lh=1.25))
        w = full * v / total
        b.append(f'<rect x="{x0}" y="{y + 10}" width="{w:.1f}" height="48" rx="4" '
                 f'fill="{c if filled else TINT[c]}" stroke="{c}" stroke-width="2"/>')
        b.append(text(x0 + w + 14, y + 43, f"{pre}{v / total * 100:.1f} %", 22, TEXT if c == MUTED else c,
                      bold=True, room=1170 - (x0 + w + 14)))
    b.append(text(30, 500, "clones checked byte for byte on the 400 most created codes, "
                           f"{DATA['top400'] / DATA['dc_first_run'] * 100:.1f} % of these creations", 18, MUTED,
                  room=1140))
    b.append(line(30, 528, 1170, 528, LINE, 2))
    b.append(text(30, 572, "under the draft, each one's code is only as fixed as what it borrows", 22, RED,
                  bold=True, room=1140))
    chains = [("a clone", "its implementation", "whatever that can be made to run"),
              ("a Safe proxy", "the Safe singleton", "every payload it is handed"),
              ("an upgradable proxy", "its implementation", "the next one its admin installs")]
    for i, (acc, first, then) in enumerate(chains):
        y = 622 + i * 54
        b.append(chip(30, y, acc, TEXT, size=20))
        b.append(arrow(30 + tw(acc, 20) + 34, y, 324, y, PURPLE, 3))
        b.append(chip(332, y, first, PURPLE, size=20))
        b.append(arrow(588, y, 614, y, PURPLE, 3))
        b.append(chip(622, y, then, PURPLE, size=20))
    b.append(text(30, 794, "with rule 2, only the account's own code can replace it", 22, GREEN, bold=True,
                  room=1140))
    svg("f4-delegatecall.svg", W, H, "Most contracts ever created run borrowed code", b)


# --------------------------------------------------------------------------- #
# F5: rule 1, the deferred effect
# --------------------------------------------------------------------------- #
def f5():
    W, H = 1200, 740
    b = [head("// rule 1: record now, switch when your outermost frame ends")]
    x0, x1, xe = 60, 900, 1140
    b.append(text(30, 104, "frames of account A", 22, MUTED, room=500))
    b.append(rect(x0, 190, x1 - x0, 64, stroke=GREEN, sw=2.5))
    b.append(text(x0 + 18, 231, "A's outermost frame: old code", 22, TEXT, room=400))
    b.append(rect(470, 120, 300, 56, stroke=PURPLE, sw=2.5))
    b.append(text(488, 156, "an inner frame of A", 22, TEXT, room=270))
    b.append(path("M440,190 C440,150 450,148 466,148", PURPLE, 2.5))
    b.append(path("M774,148 C790,148 800,150 800,186", PURPLE, 2.5))
    b.append(line(620, 176, 620, 300, KEY, 2.5, "5 6"))
    b.append(chip(550, 322, "SETCODEFROM(T): recorded", KEY, anchor="middle"))
    b.append(line(x1, 110, x1, 480, GREEN, 3))
    b.append(chip(x1 + 30, 322, "frame ends: written", GREEN, anchor="middle"))
    # what everyone sees
    b.append(text(30, 404, "what every observer sees as A's code", 22, MUTED, room=600))
    b.append(rect(x0, 420, x1 - x0, 56, stroke=MUTED, fill=TINT[MUTED], sw=2))
    b.append(text((x0 + x1) / 2, 456, "the old code: EXTCODEHASH, EXTCODECOPY, calls into A", 22, TEXT, "middle",
                  room=x1 - x0 - 20))
    b.append(rect(x1, 420, xe - x1, 56, stroke=GREEN, fill=TINT[GREEN], sw=2))
    b.append(text((x1 + xe) / 2, 456, "T", 24, GREEN, "middle", bold=True))
    b.append(arrow(x0, 520, xe, 520, MUTED, 2))
    b.append(text(xe, 548, "time", 20, MUTED, "end"))
    pts = ["inner frames are A's too: a DELEGATECALL, or someone calling A back",
           "a revert or a halt drops the recording, like any other state change",
           "several recordings: the last one that was not reverted is written",
           "a creation is the same rule: the code appears when the creation completes"]
    for i, p in enumerate(pts):
        b.append(text(30, 596 + i * 36, "▸ " + p, 22, TEXT if i < 2 else MUTED, room=1140))
    svg("f5-deferred.svg", W, H, "The adopted code is written when the account's outermost frame ends", b)


# --------------------------------------------------------------------------- #
# F6: rule 2, only your own code can replace your code
# --------------------------------------------------------------------------- #
def f6():
    W, H = 1200, 720
    b = [head("// rule 2: only your own code can replace your code")]
    b.append(text(30, 100, "what the account holds", 22, MUTED, room=420))
    b.append(text(640, 100, "what code runs the instruction", 22, MUTED, room=520))
    rows = [("a 7702 delegation (an EOA)", "its delegate", True, PURPLE),
            ("a 7702 delegation (an EOA)", "code its delegate DELEGATECALLs", True, PURPLE),
            ("nothing yet: being created", "its initcode, or a helper of it", True, BLUE),
            ("its own code", "that same code", True, GREEN),
            ("its own code", "code it DELEGATECALLs", False, GREEN)]
    for i, (who, what, ok, c) in enumerate(rows):
        y = 122 + i * 84
        b.append(rect(30, y, 1140, 68, stroke=c if ok else RED, fill=PANEL if ok else TINT[RED], sw=2.5))
        b.append(text(54, y + 43, who, 22, TEXT, bold=True, room=560))
        b.append(text(640, y + 43, what, 22, TEXT, room=440))
        b.append(mark(1132, y + 34, ok))
    b.append(text(30, 580, ["The last row halts before it costs or touches anything: exactly what byte 0xA7",
                             "does in that frame today. Libraries, modules and implementations cannot",
                             "replace the code of the account that runs them."], 22, TEXT, room=1140, lh=1.32))
    b.append(text(30, 690, "\"own code\" is compared by hash: the same bytes, wherever they were loaded from", 22,
                  MUTED, room=1140))
    svg("f6-own-code.svg", W, H, "An account that holds code adopts only from that code", b)


# --------------------------------------------------------------------------- #
# F7: the census funnel
# --------------------------------------------------------------------------- #
def f7():
    W, H = 1200, 700
    b = [head("// the census: does any deployed code already run byte 0xA7?")]
    rows = [(DATA["creations"], "contract creations that left code", MUTED),
            (DATA["codes"], "distinct codes", MUTED),
            (DATA["a7_at_instruction"], "have 0xA7 where an instruction can start", KEY),
            (DATA["candidates"], "a static analysis cannot rule out", KEY),
            (DATA["reach_from_entry"], "reach it from their first instruction", KEY),
            (DATA["execute_it"], "execute it", RED),
            (DATA["go_on"], "execute it and keep going", GREEN)]
    full = 400
    top = math.log10(DATA["creations"])
    for i, (v, lab, c) in enumerate(rows):
        y = 92 + i * 74
        w = max(full * math.log10(v) / top, 6) if v > 0 else 0
        if w:
            b.append(f'<rect x="30" y="{y}" width="{w:.1f}" height="44" rx="4" fill="{TINT[c]}" stroke="{c}" '
                     f'stroke-width="2"/>')
        b.append(text(30 + w + 16, y + 30, n(v), 24, c if c != MUTED else TEXT, bold=True, room=180))
        b.append(text(620, y + 30, lab, 22, TEXT if c != MUTED else MUTED, room=550))
    b.append(text(30, 636, [f"{n(DATA['a7_trailer_only'])} of the {n(DATA['a7_at_instruction'])} have the byte only in"
                             " their metadata hash.",
                             "The two that execute it halt on the very next instruction, on every input."],
                  22, MUTED, room=1140, lh=1.3))
    b.append(text(1170, 80, "bars: log scale", 18, MUTED, "end", room=200))
    svg("f7-census.svg", W, H, "No deployed code executes 0xA7 and keeps going", b)


# --------------------------------------------------------------------------- #
# F8: each rule has its own job
# --------------------------------------------------------------------------- #
def f8():
    W, H = 1200, 600
    b = [head("// one rule per finding: neither is enough alone")]
    cols = [("draft", 520), ("rule 1 only", 690), ("rule 2 only", 860), ("both", 1050)]
    for name, x in cols:
        b.append(text(x, 110, name, 22, GREEN if name == "both" else MUTED, "middle", bold=name == "both"))
    rows = [("the router gives away the NFT", "show one code, run another", [False, True, False, True]),
            ("the Safe loses its code", "borrowed code replaces yours", [False, False, True, True])]
    for i, (t, s, marks) in enumerate(rows):
        y = 140 + i * 150
        b.append(rect(30, y, 1140, 120, stroke=LINE, sw=2))
        b.append(text(54, y + 52, t, 22, TEXT, bold=True, room=400))
        b.append(text(54, y + 88, s, 22, MUTED, room=400))
        for (name, x), ok in zip(cols, marks):
            b.append(mark(x, y + 60, ok, 22))
    b.append(text(30, 476, ["rule 1: the adopted code takes effect when the outermost frame ends",
                             "rule 2: only an account's own code can replace its code"], 22, TEXT, room=1140, lh=1.32))
    b.append(text(30, 566, "every cell was run on mainnet bytecode; \"draft\" and \"both\" on two implementations",
                  22, MUTED, room=1140))
    svg("f8-two-rules.svg", W, H, "Each of the two rules closes one of the two findings", b)


# --------------------------------------------------------------------------- #
# F9: what goes, what stays
# --------------------------------------------------------------------------- #
def f9():
    W, H = 1200, 800
    b = [head("// what you can no longer do, and what stays")]
    b.append(rect(30, 80, 555, 680, stroke=RED, sw=2.5))
    b.append(text(54, 124, "GONE", 26, RED, bold=True, spacing=2))
    gone = [("proxies graduating", ["a proxy, clone or Safe taking", "its implementation's code"]),
            ("borrowed code adopting", ["a library, module, facet or", "payload, for an account with code"]),
            ("reading your new code", ["EXTCODEHASH(self) right after", "adopting still shows the old one"]),
            ("adopt, then call yourself", ["the call runs the old code until", "your outermost frame is over"])]
    for i, (t, s) in enumerate(gone):
        y = 176 + i * 142
        b.append(mark(72, y, False))
        b.append(text(104, y + 8, t, 24, TEXT, bold=True, room=460))
        b.append(text(104, y + 42, s, 21, MUTED, room=466, lh=1.3))
    b.append(rect(615, 80, 555, 680, stroke=GREEN, sw=2.5))
    b.append(text(639, 124, "STAYS", 26, GREEN, bold=True, spacing=2))
    stay = [("a cheap copy of deployed code", ["initcode writes state and adopts,", "flat 9300 or 12200 gas"]),
            ("retiring the key", ["an EOA adopts through its", "delegate, modules included"]),
            ("a code account on your key", ["through 8141 frame transactions"]),
            ("upgrading in place", ["the template adopts again,", "from its own code"]),
            ("result flag and gas table", ["unchanged"])]
    for i, (t, s) in enumerate(stay):
        y = 176 + i * 114
        b.append(mark(657, y, True))
        b.append(text(689, y + 8, t, 24, TEXT, bold=True, room=460))
        b.append(text(689, y + 42, s, 21, MUTED, room=466, lh=1.3))
    svg("f9-gone-and-stays.svg", W, H, "Use cases the update removes and use cases it keeps", b)


# --------------------------------------------------------------------------- #
# F10: cheat sheet
# --------------------------------------------------------------------------- #
def f10():
    rows = [("the new code takes effect", ["at the instruction"], ["when the account's", "outermost frame ends"]),
            (["an account with code,", "from that code"], ["adopts"], ["adopts"]),
            (["an account with code,", "from code it borrows"], ["adopts"], ["halts, as 0xA7 does today"]),
            (["a 7702 account,", "through its delegate"], ["adopts"], ["adopts"]),
            ("initcode", ["adopts, visible at once"], ["adopts, visible when", "the creation completes"]),
            ("flag, gas table, last one wins", ["as merged"], ["unchanged"]),
            ("mempool: code with DELEGATECALL", ["tracked, with a quota"], ["nothing to track"])]
    W = 1200
    c1, c2, c3 = 30, 500, 830
    rh = 96
    H = 150 + len(rows) * rh + 30
    b = [head("// cheat sheet")]
    b.append(text(c2, 110, "DRAFT", 22, RED, bold=True, spacing=2))
    b.append(text(c3, 110, "WITH THE UPDATE", 22, GREEN, bold=True, spacing=2))
    for i, (what, old, new) in enumerate(rows):
        y = 130 + i * rh
        b.append(line(30, y, 1170, y, LINE, 2))
        b.append(text(c1, y + 42, what, 22, TEXT, bold=True, room=450))
        b.append(text(c2, y + 42, old, 21, MUTED, room=310, lh=1.3))
        b.append(text(c3, y + 42, new, 21, TEXT, room=340, lh=1.3))
    b.append(line(30, 130 + len(rows) * rh, 1170, 130 + len(rows) * rh, LINE, 2))
    svg("f10-cheat-sheet.svg", W, H, "The draft and the update, side by side", b)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for f in (f1, f2, f3, f4, f5, f6, f7, f8, f9, f10):
        f()
