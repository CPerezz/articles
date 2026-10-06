#!/usr/bin/env python3
"""Draws the article's figures as self-contained SVGs in the site's CRT palette.

    python3 make_figures.py      # writes figures/f1-same-root-different-code.svg ... figures/f10-cheat-sheet.svg

Stdlib only. Every label goes through text(), which refuses strings wider than the
room they were given, so a wording change that would overflow a box fails loudly here
instead of quietly in the browser.
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


def chip(x, y, s, color=MUTED, size=22, anchor="start", dash=None, h=38):
    """Rounded pill around one line of text; (x, y) is the left (or centre) of its middle line."""
    w = tw(s, size) + 26
    left = x - w / 2 if anchor == "middle" else x
    out = rect(left, y - h / 2, w, h, stroke=color, fill=TINT.get(color, PANEL), sw=2, rx=h / 2, dash=dash)
    out += text(left + w / 2, y + size * 0.36, s, size, color, "middle")
    return out


def mark(cx, cy, ok, r=17):
    """Circled tick, circled cross, or (ok=None) a circled dash for 'depends'."""
    c = {True: GREEN, False: RED, None: MUTED}[ok]
    out = f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{TINT[c]}" stroke="{c}" stroke-width="2.5"/>'
    if ok:
        out += (f'<path d="M{cx - 8},{cy + 1} l5,6 l11,-13" fill="none" stroke="{c}" stroke-width="3.2" '
                f'stroke-linecap="round" stroke-linejoin="round"/>')
    elif ok is None:
        out += f'<path d="M{cx - 7},{cy} h14" stroke="{c}" stroke-width="3.2" stroke-linecap="round"/>'
    else:
        out += (f'<path d="M{cx - 6.5},{cy - 6.5} l13,13 M{cx + 6.5},{cy - 6.5} l-13,13" stroke="{c}" '
                f'stroke-width="3.2" stroke-linecap="round"/>')
    return out


def code(x, y, s, color, letter=None, size=None):
    """One stored bytecode: a square in its owner colour, optionally lettered."""
    out = rect(x, y, s, s, stroke=color, fill=TINT[color], sw=2, rx=4)
    if letter:
        fs = size or int(s * 0.5)
        out += text(x + s / 2, y + s / 2 + fs * 0.36, letter, fs, color, "middle", bold=True)
    return out


def step(x, y, w, h, title, sub, stroke=LINE):
    """A box with a bold title and a muted second line."""
    return (rect(x, y, w, h, stroke=stroke, sw=2.5) + text(x + 14, y + 40, title, 22, TEXT, bold=True, room=w - 28)
            + text(x + 14, y + 72, sub, 20, MUTED, room=w - 28))


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
# F1: two nodes, one state root, two different code DBs
# --------------------------------------------------------------------------- #
def f1():
    W, H = 1200, 770
    b = [head("// same chain, same root, different code")]
    b.append(rect(70, 74, 1060, 60, stroke=GREEN, fill=TINT[GREEN], sw=2.5))
    b.append(text(600, 113, "state root 0x9a3f…  identical on both nodes", 24, GREEN, "middle", bold=True,
                  room=1020))
    dead = {6, 10, 19, 24, 31, 37, 42, 48, 55}
    for x, title, sub, full in ((20, "FULL SYNC", "ran every block since genesis", True),
                                (610, "SNAP SYNC", "downloaded the state at one block", False)):
        y0 = 160
        b.append(rect(x, y0, 570, 500, stroke=LINE, sw=2))
        b.append(text(x + 20, y0 + 42, title, 26, TEXT, bold=True, room=400))
        b.append(text(x + 20, y0 + 72, sub, 22, MUTED, room=470))
        b.append(arrow(x + 500, y0 + 94, x + 500, 140, GREEN, 3))
        # the committed side: one account's fields, codeHash among them
        b.append(rect(x + 20, y0 + 96, 530, 112, stroke=GREEN, sw=2))
        b.append(text(x + 40, y0 + 126, "account trie, committed by the root", 22, MUTED, room=490))
        for i, f in enumerate(("nonce", "balance", "storage", "codeHash")):
            c = GREEN if f == "codeHash" else LINE
            b.append(rect(x + 30 + i * 130, y0 + 144, 120, 48, stroke=c, fill=TINT[GREEN] if c == GREEN else PANEL,
                          rx=6))
            b.append(text(x + 90 + i * 130, y0 + 176, f, 22, GREEN if c == GREEN else TEXT, "middle", room=112))
        # the client-local side: a table of stored codes
        b.append(rect(x + 20, y0 + 228, 530, 250, stroke=MUTED, fill=PANEL, dash="8 6"))
        b.append(text(x + 40, y0 + 258, "code DB, client-local", 22, MUTED, room=300))
        b.append(arrow(x + 480, y0 + 192, x + 480, y0 + 270, GREEN, 3))
        gx, gy = x + 25, y0 + 276
        for k in range(60):
            if k in dead and not full:
                continue
            col, row = k % 15, k // 15
            b.append(code(gx + 34 * col, gy + 34 * row, 26, RED if k in dead else GREEN))
        if full:
            b.append(code(x + 40, y0 + 436, 22, RED))
            b.append(text(x + 74, y0 + 454, "27,869 codes nobody points at", 22, RED, bold=True, room=460))
        else:
            b.append(code(x + 40, y0 + 436, 22, GREEN))
            b.append(text(x + 74, y0 + 454, "only code some account points at", 22, GREEN, room=460))
    b.append(text(30, 704, "the root commits code hashes, not code, so consensus never sees the extra codes",
                  22, MUTED, room=1140))
    b.append(text(30, 736, "count: EIP-8058, a full-synced node, as of Cancun", 22, MUTED, room=1140))
    svg("f1-same-root-different-code.svg", W, H, "Same chain, same state root, different code databases", b)


# --------------------------------------------------------------------------- #
# F2: three ways to leave code behind, one lane each
# --------------------------------------------------------------------------- #
def f2():
    W, H = 1200, 680
    lanes = [
        ("REORG", "geth · Nethermind · reth and Besu, once on disk",
         [("block 101′", "deploys code Y"), ("chain picks 101", "101′ is dropped"), ("state undone", "Y's account gone")],
         "Y", "Y stays"),
        ("SELFDESTRUCT, BEFORE CANCUN", "every client that keys code by hash",
         [("block 10", "C deployed with Y"), ("block 50", "C self-destructs"), ("code can't go", "D may share Y")],
         "Y", "Y stays"),
        ("REVERTED SUB-CREATE", "Nethermind only",
         [("inner CREATE ok", "code Y is staged"), ("outer frame", "REVERTs"), ("block end", "batch is flushed")],
         "Y", "Y stays"),
    ]
    b = [head("// three ways to leave code behind")]
    for i, (title, who, steps, letter, result) in enumerate(lanes):
        y = 100 + i * 175
        b.append(text(30, y, title, 24, TEXT, bold=True, room=560))
        b.append(text(1170, y, who, 22, MUTED, "end", room=700))
        for j, (t, s) in enumerate(steps):
            x = 30 + j * 280
            b.append(step(x, y + 20, 250, 100, t, s))
            b.append(arrow(x + 254, y + 70, x + 274, y + 70, MUTED, 3))
        x = 870
        b.append(rect(x, y + 20, 300, 100, stroke=RED, fill=TINT[RED], sw=2.5))
        b.append(text(x + 16, y + 50, "code DB", 20, MUTED))
        b.append(code(x + 16, y + 60, 44, RED, letter, 20))
        b.append(text(x + 76, y + 92, result, 24, RED, bold=True, room=208))
    b.append(text(30, 640, "no account points at the code anymore, and only full-synced nodes keep it", 22, MUTED,
                  room=1140))
    svg("f2-how-code-dangles.svg", W, H, "Three ways a client ends up keeping code nobody points at", b)


# --------------------------------------------------------------------------- #
# F3: who leaves code behind, per client
# --------------------------------------------------------------------------- #
def f3():
    W, H = 1200, 790
    clients = ["geth", "reth", "Nethermind", "Besu*", "Erigon 3"]
    X0, CW = 360, 162
    cx = [X0 + CW * i + CW / 2 for i in range(5)]
    b = [head("// who leaves code behind")]
    b.append(text(X0 + 2 * CW, 96, "keyed by code hash", 22, RED, "middle", bold=True, room=4 * CW - 20))
    b.append(line(X0 + 8, 110, X0 + 4 * CW - 8, 110, RED, 2.5))
    b.append(text(X0 + 4.5 * CW, 96, "by address", 22, GREEN, "middle", bold=True, room=CW - 10))
    b.append(line(X0 + 4 * CW + 8, 110, X0 + 5 * CW - 8, 110, GREEN, 2.5))
    for c, name in zip(cx, clients):
        b.append(text(c, 146, name, 22, TEXT, "middle", bold=True, room=CW - 10))
    colour = {"stays": RED, "never": MUTED, "undone": BLUE, "deleted": GREEN}
    rows = [
        ("reverted sub-CREATE", "an outer frame reverts", ["never", "never", "stays", "never", "never"]),
        ("create + destroy", "same tx (EIP-6780)", ["never", "never", "stays", "never", "never"]),
        ("reorged-out block", "side branch dropped", ["stays", "stays¹", "stays", "stays¹", "undone"]),
        ("SELFDESTRUCT", "before Cancun", ["stays", "stays", "stays", "stays", "deleted²"]),
        ("cleanup tool", "deletes dead code",
         [["prune-state³"], ["none"], ["none"], ["none"], ["history", "pruning"]]),
    ]
    RH, y0 = 86, 170
    for i, (main, sub, cells) in enumerate(rows):
        y = y0 + i * RH
        b.append(rect(20, y + 4, 1160, RH - 8, stroke=LINE, fill=PANEL, rx=8))
        b.append(text(40, y + 38, main, 22, TEXT, bold=True, room=300))
        b.append(text(40, y + 66, sub, 20, MUTED, room=300))
        for c, v in zip(cx, cells):
            if isinstance(v, list):
                b.append(text(c, y + 50 - (len(v) - 1) * 13, v, 20, TEXT, "middle", room=CW - 12, lh=1.3))
            else:
                b.append(chip(c, y + 43, v, colour[v.rstrip("¹²³⁴")], size=20, anchor="middle", h=36))
    notes = ["* Bonsai default. Databases from its older account-keyed mode drop code with the account",
             "¹ only blocks already on disk: blocks kept in memory never reach it",
             "² old bytes stay in history until pruned (forever on archive nodes)",
             "³ offline and hash scheme only: the default path scheme can't drop code",
             "never = never written · undone = rolled back · deleted = goes with the account"]
    b.append(text(30, 640, notes, 20, MUTED, room=1140, lh=1.4))
    svg("f3-client-matrix.svg", W, H, "Which events leave code behind, client by client", b)


# --------------------------------------------------------------------------- #
# F4: dedup or delete, pick one
# --------------------------------------------------------------------------- #
def f4():
    W, H = 1200, 690
    b = [head("// dedup or delete: pick one")]
    ys = [196, 268, 340]
    for x0, title, sub, tc in ((20, "KEY BY ADDRESS", "Erigon", GREEN),
                               (610, "KEY BY CODE HASH", "geth · reth · Nethermind · Besu · PBT", BLUE)):
        b.append(rect(x0, 80, 570, 520, stroke=tc, sw=2.5))
        b.append(text(x0 + 20, 124, title, 26, tc, bold=True, room=530))
        b.append(text(x0 + 20, 156, sub, 22, MUTED, room=530))
        for y, a in zip(ys, "ABC"):
            b.append(rect(x0 + 30, y, 100, 52, stroke=TEXT, rx=8))
            b.append(text(x0 + 80, y + 35, a, 24, TEXT, "middle", bold=True))
    # left: one copy per account, deletion is local
    for y in ys:
        b.append(arrow(154, y + 26, 264, y + 26, GREEN, 3))
        b.append(code(270, y, 52, GREEN, "Y", 24))
    b.append(text(360, 288, ["3 clones,", "3 copies"], 24, TEXT, bold=True, room=210))
    b.append(mark(58, 446, True))
    b.append(text(88, 454, "C deleted: drop C's row", 22, TEXT, room=480))
    b.append(text(88, 488, "nothing else to check", 22, GREEN, room=480))
    b.append(text(40, 544, "price: a full copy per clone", 22, KEY, room=530))
    b.append(text(40, 576, "Erigon compresses it ~4x on disk", 22, MUTED, room=530))
    # right: one shared copy, deletion needs to know nobody else points at it
    for y in ys:
        b.append(path(f"M{744},{y + 26} L{892},{294}", BLUE, 3))
    b.append(code(898, 268, 52, BLUE, "Y", 24))
    b.append(text(980, 288, ["3 clones,", "1 copy"], 24, TEXT, bold=True, room=180))
    b.append(mark(648, 446, False))
    b.append(text(678, 454, "C deleted: drop Y?", 22, TEXT, room=480))
    b.append(text(678, 488, "only if no one else points at it", 22, TEXT, room=480))
    b.append(text(678, 522, "→ needs a reference count", 22, RED, bold=True, room=480))
    b.append(text(630, 560, "none of these clients keeps one", 22, MUTED, room=530))
    b.append(chip(600, 646, "PBT picked dedup: its code zone is keyed by code hash (EIP-8297)", BLUE,
                  anchor="middle"))
    svg("f4-dedup-or-delete.svg", W, H, "Keying code by address makes deletion free; keying by hash makes it shared", b)


# --------------------------------------------------------------------------- #
# F5: how big the leftover is, and what it already cost
# --------------------------------------------------------------------------- #
def f5():
    W, H = 1200, 820
    b = [head("// how big is it today")]
    scale = 700 / 280  # px per GB
    rows = [("state per full node", 280, GREEN, "≈ 280 GB"),
            ("27,869 × 24 KiB", 0.685, RED, "0.68 GB · 0.24 %"),
            ("27,869 × 64 KiB", 1.826, RED, "1.83 GB · 0.65 %"),
            ("snap-synced node", 0, GREEN, "0, never fetched")]
    for i, (lbl, gb, c, val) in enumerate(rows):
        y = 120 + i * 60
        b.append(text(30, y, lbl, 22, TEXT, room=300))
        w = gb * scale
        if gb:
            w = max(w, 4)
            b.append(rect(350, y - 20, w, 26, stroke=c, fill=TINT[c] if gb > 10 else c, sw=1.5, rx=2))
        b.append(text(350 + w + 14, y, val, 22, c, bold=True, room=360))
    b.append(text(30, 364, "worst case: all 27,869 at the size limit (count: EIP-8058, as of Cancun)", 22, MUTED,
                  room=1140))
    b.append(line(20, 396, 1180, 396, LINE, 2))
    b.append(text(30, 446, "what it did cost: no one can ask a client for code by hash", 24, TEXT, bold=True,
                  room=1140))
    b.append(chip(600, 500, '"do you have code H?"', MUTED, anchor="middle"))
    b.append(mark(820, 500, False))
    b.append(text(600, 552, "the answer depends on how the node synced", 22, RED, "middle", room=1100))
    cards = [(30, "EIP-8058, dedup discount", ["skips the deposit for duplicate code", "but asks the code hash of addresses",
                                              "in the access list, not the code DB"]),
             (610, "EIP-8298, SETCODEFROM", ["takes a source address and copies", "its live code hash, never a raw",
                                            "hash looked up in the code DB"])]
    for x, t, ls in cards:
        b.append(rect(x, 586, 560, 170, stroke=PURPLE, sw=2.5))
        b.append(text(x + 20, 626, t, 24, PURPLE, bold=True, room=520))
        b.append(text(x + 20, 664, ls, 22, TEXT, room=520, lh=1.3))
    b.append(text(600, 798, "both route around a table nobody agrees on", 22, MUTED, "middle", room=1100))
    svg("f5-how-big-today.svg", W, H, "The leftover is tiny next to the state, and it already shaped two EIPs", b)


# --------------------------------------------------------------------------- #
# F6: chunked code inside the state tree (PBT, or any code-chunking design)
# --------------------------------------------------------------------------- #
def f6():
    W, H = 1200, 730
    b = [head("// code chunking puts code in the root")]
    b.append(text(30, 82, "PBT (EIP-8297), or any design that chunks code into the state", 22, MUTED, room=1140))
    boxes = [(30, "one 64 KiB contract", "the EIP-7954 limit"), (435, "2,115 chunks", "31 code bytes each"),
             (840, "2,115 leaves", "+ ~2,115 branch nodes")]
    for x, t, s in boxes:
        b.append(step(x, 104, 330, 100, t, s, BLUE))
    b.append(arrow(364, 154, 429, 154, BLUE, 3))
    b.append(arrow(769, 154, 834, 154, BLUE, 3))
    # the tree: the root now commits to code bytes, not just to code hashes
    b.append(f'<circle cx="600" cy="256" r="18" fill="{TINT[GREEN]}" stroke="{GREEN}" stroke-width="2.5"/>')
    b.append(text(630, 264, "state root", 22, GREEN, bold=True))
    for zx, z, c in ((380, "accounts", MUTED), (820, "code chunks", BLUE)):
        b.append(line(600, 274, zx, 318, c, 2.5 if c == BLUE else 1.5))
        b.append(chip(zx, 338, z, c, anchor="middle"))
    for i in range(12):
        lx = 820 + (i - 5.5) * 30
        b.append(line(820, 357, lx, 398, BLUE, 1.2))
        b.append(code(lx - 9, 398, 18, BLUE))
    b.append(text(30, 384, ["every leaf and branch", "node is consensus state"], 22, TEXT, room=330))
    b.append(text(30, 470, "held by", 22, MUTED))
    x = 140
    for c in ("every full node", "snap sync servers", "AA-VOPS nodes (EIP-8369)"):
        b.append(chip(x, 462, c, GREEN))
        x += tw(c, 22) + 26 + 16
    # shared code: deleting it needs to know nobody else holds it
    b.append(rect(20, 510, 1160, 190, stroke=BLUE, fill=TINT[BLUE], sw=2.5))
    b.append(text(44, 550, "deleting shared code without a reference count", 24, BLUE, bold=True, room=1100))
    b.append(text(44, 592, ["a shared code leaf exists while some account holds that code",
                            "since Cancun, an account with code dies only in the tx that created it"],
                  22, TEXT, room=1100, lh=1.4))
    b.append(text(44, 674, "→ a local check works, as long as no live account can replace its code", 22,
                  BLUE, bold=True, room=1100))
    svg("f6-code-in-the-tree.svg", W, H, "Chunked code inside the state tree: the root commits to code bytes", b)


# --------------------------------------------------------------------------- #
# F7: SETCODEFROM, and the last holder walks away
# --------------------------------------------------------------------------- #
def f7():
    W, H = 1200, 960

    def account(y, name, sub, code_chip):
        return (rect(30, y, 300, 130, stroke=TEXT, sw=2) + text(50, y + 40, name, 26, TEXT, bold=True)
                + text(50, y + 72, sub, 20, MUTED, room=260) + chip(50, y + 104, code_chip, GREEN, h=34))

    def template(y):
        return (rect(640, y, 300, 130, stroke=TEXT, sw=2) + text(660, y + 40, "S", 26, TEXT, bold=True)
                + text(660, y + 72, "a template", 20, MUTED, room=260) + chip(660, y + 104, "code X", GREEN, h=34))

    b = [head("// SETCODEFROM: the last holder walks away")]
    b.append(text(30, 96, "BEFORE", 22, MUTED, bold=True, spacing=2))
    b.append(account(110, "A", "deployed by CREATE", "code Y"))
    b.append(arrow(334, 175, 414, 175, GREEN, 3))
    b.append(code(420, 145, 60, GREEN, "Y", 28))
    b.append(text(450, 232, "1 holder", 20, GREEN, "middle"))
    b.append(template(110))
    b.append(arrow(944, 175, 1024, 175, GREEN, 3))
    b.append(code(1030, 145, 60, GREEN, "X", 28))
    b.append(text(1060, 232, "n holders", 20, GREEN, "middle"))
    b.append(arrow(180, 250, 180, 346, PURPLE, 4))
    b.append(text(210, 306, "A runs SETCODEFROM(S)", 24, PURPLE, bold=True, room=420))
    b.append(text(30, 382, "AFTER", 22, MUTED, bold=True, spacing=2))
    b.append(account(396, "A", "adopted X", "code X"))
    b.append(code(420, 431, 60, RED, "Y", 28))
    b.append(text(450, 518, "0 holders", 20, RED, "middle", bold=True))
    b.append(template(396))
    b.append(arrow(944, 461, 1024, 461, GREEN, 3))
    b.append(path("M300,396 C300,350 1060,350 1060,425", GREEN, 3))
    b.append(code(1030, 431, 60, GREEN, "X", 28))
    b.append(text(1060, 518, "n + 1 holders", 20, GREEN, "middle"))
    # what happens to Y
    b.append(rect(30, 570, 560, 280, stroke=MUTED, sw=2))
    b.append(text(50, 610, "UNDER THE MPT", 24, TEXT, bold=True))
    b.append(text(50, 650, ["Y stays in this node's code DB", "snap sync never fetches it"], 22, TEXT, room=520,
                  lh=1.4))
    b.append(mark(66, 730, True))
    b.append(text(96, 738, "local: sync sheds it", 22, GREEN, bold=True, room=470))
    b.append(rect(610, 570, 560, 280, stroke=BLUE, fill=TINT[BLUE], sw=2.5))
    b.append(text(630, 610, "UNDER PBT", 24, BLUE, bold=True))
    b.append(text(630, 650, "Y's 2,115 leaves are in the root", 22, TEXT, room=520))
    b.append(mark(646, 706, False))
    b.append(text(676, 714, ["no count: every node stores,", "syncs and serves them forever"], 22, RED, room=480,
                  lh=1.3))
    b.append(mark(646, 794, True))
    b.append(text(676, 802, ["with a count: they go with", "their last holder"], 22, GREEN, room=480, lh=1.3))
    b.append(text(30, 896, "code adopted from a template never dangles: the template keeps it", 22, MUTED,
                  room=1140))
    b.append(text(30, 932, "Y was paid at deploy: 100.3M state gas for 64 KiB. Orphaning it: 12,200 gas.", 22,
                  KEY, room=1140))
    svg("f7-last-holder.svg", W, H, "SETCODEFROM lets the last holder of a code walk away from it", b)


# --------------------------------------------------------------------------- #
# F8: three ways to ship SETCODEFROM, against what each costs
# --------------------------------------------------------------------------- #
def f8():
    cols = [(300, "A · COUNT NOW", "refcount in Hegotá", GREEN), (596, "B · SHIP AS IS", "PBT decides later", KEY),
            (892, "C · NEVER REMOVE", "said in the spec", BLUE)]
    CW = 286
    rows = [
        (["spec work", "in Hegotá"], [(["8298: refcount", "rule and its gas"], False), (["none"], True),
                                      (["none"], True)]),
        (["client work", "in Hegotá"], [(["build the count,", "fix reorg + revert", "writes, clean up"], False),
                                        (["none"], True), (["none"], True)]),
        (["work at the", "PBT fork"], [(["count in the tree", "or kept local"], None),
                                       (["never remove, or", "a count + new gas,", "rebuilt by every",
                                         "conversion path"], False),
                                       (["one sentence:", "replaced leaves", "are never removed"], True)]),
        (["dead code in", "the code zone"], [(["goes with its", "last holder"], True),
                                             (["whatever PBT", "ends up picking"], None),
                                             (["stays forever,", "amount unknown"], False)]),
        (["first refcount", "bug shows up as"], [(["a leak or a stall,", "under the MPT"], True),
                                                 (["if PBT counts:", "a different", "state root"], False),
                                                 (["no count, so", "no count bug"], True)]),
    ]
    heights = [max(len(c[0]) for c in cells) * 26 + 40 for _, cells in rows]
    y0 = 184
    W, H = 1200, y0 + sum(heights) + 70
    b = [head("// three ways to ship it")]
    for x, t, s, c in cols:
        b.append(rect(x, 76, CW, 94, stroke=c, fill=TINT[c], sw=2.5))
        b.append(text(x + 16, 114, t, 24, c, bold=True, room=CW - 32))
        b.append(text(x + 16, 146, s, 20, MUTED, room=CW - 32))
    y = y0
    for (lbl, cells), rh in zip(rows, heights):
        b.append(rect(20, y, 1160, rh - 8, stroke=LINE, fill=PANEL, rx=8))
        b.append(text(40, y + 36, lbl, 22, TEXT, bold=True, room=240, lh=1.25))
        for (x, _, _, _), (ls, ok) in zip(cols, cells):
            b.append(mark(x + 24, y + 30, ok, r=14))
            b.append(text(x + 50, y + 37, ls, 20, TEXT, room=CW - 56, lh=1.3))
        y += rh
    b.append(mark(42, H - 40, True, r=12))
    b.append(text(64, H - 33, "costs little here", 20, MUTED))
    b.append(mark(330, H - 40, False, r=12))
    b.append(text(352, H - 33, "costs something here", 20, MUTED))
    b.append(mark(660, H - 40, None, r=12))
    b.append(text(682, H - 33, "depends", 20, MUTED))
    svg("f8-options.svg", W, H, "Three ways to ship SETCODEFROM, and what each one costs where", b)


# --------------------------------------------------------------------------- #
# F9: who does the work, and when
# --------------------------------------------------------------------------- #
def f9():
    W, H = 1200, 900
    b = [head("// who does the work, and when")]
    b.append(text(475, 100, "IN HEGOTÁ", 22, MUTED, "middle", bold=True, spacing=2))
    b.append(text(945, 100, "AT THE PBT FORK", 22, MUTED, "middle", bold=True, spacing=2))
    b.append(line(705, 116, 705, H - 30, MUTED, 2, "8 8"))

    def block(x, y, w, s, c=LINE, dash=None):
        return (rect(x, y, w, 36, stroke=c, fill=TINT.get(c, PANEL), sw=2, rx=6, dash=dash)
                + text(x + 12, y + 25, s, 20, c if c != LINE else TEXT, room=w - 24))

    def lane(y, letter, name, c):
        return text(30, y + 36, letter, 40, c, bold=True) + text(30, y + 72, name, 22, MUTED, room=210)

    y = 130
    b.append(lane(y, "A", "count now", GREEN))
    for i, s in enumerate(("8298: refcount rule + gas", "clients build and keep a count",
                           "fix reorg and revert writes", "clean up, archives keep history")):
        b.append(block(270, y + i * 44, 420, s, GREEN if i == 0 else LINE))
    b.append(block(730, y, 440, "count in the tree, or kept local", GREEN))
    b.append(line(20, y + 196, 1180, y + 196, LINE, 2))
    y = 346
    b.append(lane(y, "B", "ship as is", KEY))
    b.append(block(270, y, 420, "ship 8298 as is", MUTED, "6 6"))
    b.append(block(730, y, 440, "8297: never remove, or a count", KEY))
    b.append(text(730, y + 70, "if a count:", 20, KEY, bold=True, room=440))
    for i, s in enumerate(("SETCODEFROM gas changes", "count is consensus from day one")):
        b.append(block(730, y + 84 + i * 44, 440, s))
    b.append(text(730, y + 196, "every conversion path computes it", 20, KEY, room=440))
    for i, s in enumerate(("offline converter", "snapshot import", "BAL replay", "self-convert")):
        cx = 730 + (i % 2) * 226
        b.append(chip(cx, y + 228 + (i // 2) * 44, s, KEY, size=18, h=34))
    b.append(line(20, y + 310, 1180, y + 310, LINE, 2))
    y = 676
    b.append(lane(y, "C", "never remove", BLUE))
    b.append(block(270, y, 420, "ship 8298 as is", MUTED, "6 6"))
    b.append(block(730, y, 440, "one sentence: never removed", BLUE))
    b.append(f'<path d="M730,{y + 84} L1170,{y + 58} L1170,{y + 110} z" fill="{TINT[RED]}" stroke="{RED}" '
             f'stroke-width="2"/>')
    b.append(text(730, y + 150, "dead leaves pile up, forever", 20, RED, bold=True, room=440))
    svg("f9-who-does-the-work.svg", W, H, "Who does the work for each option, in Hegotá and at the PBT fork", b)


# --------------------------------------------------------------------------- #
# F10: cheat sheet
# --------------------------------------------------------------------------- #
def f10():
    rows = [
        (["the smallest Hegotá scope"], [("B", KEY), ("C", BLUE)], "nothing to build now"),
        (["the simplest PBT spec"], [("C", BLUE)], "one sentence, no count"),
        (["keeping the PBT EIPs free of", "other EIPs' debt"], [("A", GREEN)], "PBT gets it solved"),
        (["taking dead code back out"], [("A", GREEN)], "goes with its last holder"),
        (["catching count bugs before", "they can move the root"], [("A", GREEN)], "an MPT bug leaks or stalls"),
    ]
    RH, y0 = 100, 126
    W, H = 1200, y0 + RH * len(rows) + 30
    b = [head("// cheat sheet")]
    for x, t in ((40, "if you care most about"), (700, "pick"), (830, "because")):
        b.append(text(x, 104, t, 22, MUTED))
    for i, (want, picks, why) in enumerate(rows):
        y = y0 + i * RH
        mid = y + (RH - 10) / 2
        b.append(rect(20, y, 1160, RH - 10, stroke=LINE, fill=PANEL, rx=8))
        b.append(text(40, mid + 8 - (len(want) - 1) * 15, want, 24, TEXT, bold=True, room=620, lh=1.25))
        for j, (p, c) in enumerate(picks):
            b.append(chip(700 + j * 60, mid, p, c, size=24, h=40))
        b.append(text(830, mid + 8, why, 21, MUTED, room=340))
    svg("f10-cheat-sheet.svg", W, H, "Cheat sheet: which option fits which priority", b)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for f in (f1, f2, f3, f4, f5, f6, f7, f8, f9, f10):
        f()
