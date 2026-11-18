"""Bitmap -> bezier outlines in font units, using potrace (pure-Python port)."""

import numpy as np
import potrace

PAD = 2

# A contour is a list of segments, each either
#   ("L", p0, p1)              straight line
#   ("C", p0, c1, c2, p1)      cubic bezier
# with points as (x, y) tuples in font units (y up).


def trace(glyph, turdsize=8, alphamax=1.0, opttolerance=0.2):
    """Trace an extract.Glyph into a list of closed contours (font units)."""
    ink = np.pad(glyph.ink, PAD, constant_values=False)
    # potracer treats True as background and inverts internally
    paths = potrace.Bitmap(~ink).trace(
        turdsize=turdsize,
        turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY,
        alphamax=alphamax,
        opticurve=True,
        opttolerance=opttolerance,
    )

    def pt(p):
        return glyph.to_units(p.x - PAD, p.y - PAD)

    contours = []
    for curve in paths:
        segs = []
        cur = pt(curve.start_point)
        for s in curve.segments:
            end = pt(s.end_point)
            if s.is_corner:
                mid = pt(s.c)
                segs.append(("L", cur, mid))
                segs.append(("L", mid, end))
            else:
                segs.append(("C", cur, pt(s.c1), pt(s.c2), end))
            cur = end
        if segs:
            contours.append(segs)
    return fix_winding(contours)


# --- geometry helpers -------------------------------------------------------------

def _polyline(contour, steps=6):
    pts = []
    for seg in contour:
        if seg[0] == "L":
            pts.append(seg[1])
        else:
            _, p0, c1, c2, p1 = seg
            for i in range(steps):
                t = i / steps
                u = 1 - t
                pts.append((
                    u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p1[0],
                    u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p1[1],
                ))
    return np.array(pts, float)


def _signed_area(poly):
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _inside(point, poly):
    x, y = point
    xs, ys = poly[:, 0], poly[:, 1]
    xj, yj = np.roll(xs, 1), np.roll(ys, 1)
    cross = (ys > y) != (yj > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xint = (xj - xs) * (y - ys) / (yj - ys) + xs
    return bool(np.count_nonzero(cross & (x < xint)) % 2)


def reverse(contour):
    out = []
    for seg in reversed(contour):
        if seg[0] == "L":
            out.append(("L", seg[2], seg[1]))
        else:
            _, p0, c1, c2, p1 = seg
            out.append(("C", p1, c2, c1, p0))
    return out


def fix_winding(contours):
    """TrueType (non-zero fill): outer contours clockwise, holes counter-clockwise."""
    polys = [_polyline(c) for c in contours]
    fixed = []
    for i, (c, poly) in enumerate(zip(contours, polys)):
        if len(poly) < 3:
            continue
        probe = tuple(poly[0])
        depth = sum(1 for j, other in enumerate(polys) if j != i and len(other) > 2 and _inside(probe, other))
        clockwise = _signed_area(poly) < 0
        want_clockwise = depth % 2 == 0
        fixed.append(c if clockwise == want_clockwise else reverse(c))
    return fixed


def transform(contours, scale=1.0, dx=0.0, dy=0.0):
    def t(p):
        return (p[0] * scale + dx, p[1] * scale + dy)

    return [[(s[0],) + tuple(t(p) for p in s[1:]) for s in c] for c in contours]


def bounds(contours):
    """(xmin, ymin, xmax, ymax) from the flattened outlines, or None."""
    if not contours:
        return None
    pts = np.concatenate([_polyline(c, steps=10) for c in contours])
    return (*pts.min(axis=0), *pts.max(axis=0))


def draw(contours, pen):
    """Draw onto a fontTools segment pen. Coordinates are rounded to integers."""
    def r(p):
        return (round(p[0]), round(p[1]))

    for c in contours:
        pen.moveTo(r(c[0][1]))
        for seg in c:
            if seg[0] == "L":
                pen.lineTo(r(seg[2]))
            else:
                pen.curveTo(r(seg[2]), r(seg[3]), r(seg[4]))
        pen.closePath()
