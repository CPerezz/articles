"""Minimal inline-SVG primitives for the state-DB report. Stdlib only."""

import html
import math
import re


def esc(s):
    return html.escape(str(s))


class Scale:
    """Linear value -> pixel mapping."""

    def __init__(self, lo, hi, px_lo, px_hi):
        self.lo, self.hi, self.px_lo, self.px_hi = lo, hi, px_lo, px_hi

    def to(self, v):
        if self.hi == self.lo:
            return self.px_lo
        return self.px_lo + (v - self.lo) * (self.px_hi - self.px_lo) / (self.hi - self.lo)


class LogScale(Scale):
    """Log10 value -> pixel mapping; lo and hi must both be > 0."""

    def to(self, v):
        lo, hi = math.log10(self.lo), math.log10(self.hi)
        if hi == lo:
            return self.px_lo
        return self.px_lo + (math.log10(v) - lo) * (self.px_hi - self.px_lo) / (hi - lo)


def svg(width, height, body, cls="chart"):
    return (f'<svg class="{cls}" viewBox="0 0 {width} {height}" role="img" '
            f'preserveAspectRatio="xMinYMin meet">{body}</svg>')


def label(x, y, text, anchor="start", cls=""):
    c = f' class="{cls}"' if cls else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}"{c}>{esc(text)}</text>'


def line(x1, y1, x2, y2, var, width=2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="var({var})" stroke-width="{width}"{d}/>')


def dot(x, y, r, var, title=None):
    t = f"<title>{esc(title)}</title>" if title else ""
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="var({var})">{t}</circle>'


def polyline(points, var, width=2):
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return (f'<polyline points="{pts}" fill="none" stroke="var({var})" '
            f'stroke-width="{width}" stroke-linejoin="round"/>')


def band(x1, x2, y1, y2, var, opacity=0.14):
    return (f'<rect x="{min(x1,x2):.1f}" y="{min(y1,y2):.1f}" width="{abs(x2-x1):.1f}" '
            f'height="{abs(y2-y1):.1f}" fill="var({var})" opacity="{opacity}"/>')


def hgrid(scale, ticks, y0, y1, fmt=str):
    out = []
    for t in ticks:
        x = scale.to(t)
        out.append(line(x, y0, x, y1, "--line", 1))
        out.append(label(x, y1 + 14, fmt(t), "middle", "tick"))
    return "".join(out)


def _selfcheck():
    s = Scale(0, 10, 0, 100)
    assert s.to(0) == 0 and s.to(10) == 100 and s.to(5) == 50
    assert Scale(5, 5, 3, 9).to(5) == 3            # degenerate domain: no div-by-zero
    ls = LogScale(1, 100, 0, 200)
    assert abs(ls.to(10) - 100) < 1e-9             # decade lands mid-axis
    assert 'viewBox="0 0 10 5"' in svg(10, 5, "")
    assert "&lt;b&gt;" in label(0, 0, "<b>")        # text is escaped
    assert 'stroke-dasharray="4 3"' in line(0, 0, 1, 1, "--line", dash="4 3")
    # Defect class: an unquoted attribute value abutting "/>" is tokenized by HTML5 as
    # part of the value, so the tag never self-closes and later siblings become invalid
    # descendants that never paint. Pin the exact trailing shape...
    assert polyline([(0, 0), (1, 1)], "--x").endswith('stroke-linejoin="round"/>')
    # ...and require every attribute value in every primitive to stay quoted, so an
    # attribute reorder cannot silently put an unquoted value last again.
    samples = [
        svg(10, 5, ""), label(0, 0, "t"), label(0, 0, "t", "end", "big"),
        line(0, 0, 1, 1, "--line"), line(0, 0, 1, 1, "--line", 1, "3 3"),
        dot(0, 0, 3, "--x"), dot(0, 0, 3, "--x", "title"),
        polyline([(0, 0), (1, 1)], "--x"), band(0, 1, 0, 1, "--x"),
        hgrid(Scale(0, 1, 0, 10), [0, 1], 0, 5),
    ]
    for out in samples:
        for tag in re.findall(r"<[^>/][^>]*>", out):   # attribute region of each element
            assert not re.search(r'=(?!")', tag), f"unquoted attribute value in {tag!r}"
    print("report_svg selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
