"""Assemble traced outlines into a TrueType font with fontTools."""

import io
import re
import statistics
from dataclasses import dataclass, field

from fontTools.agl import UV2AGL
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen

from . import layout as L
from . import vectorize as V

# Letters whose top sits on the cap line / x-height line, used to normalise size.
CAP_REF = set("ABCDEFGHIKLMNOPRSTUVWXYZ0123456789")
X_REF = set("acemnorsuvwxz")

# Extra code points that reuse an existing glyph (smart quotes from word processors etc.)
ALIASES = {
    0x2018: "'", 0x2019: "'", 0x201A: ",",
    0x201C: '"', 0x201D: '"',
    0x2013: "-", 0x2212: "-",
}


@dataclass
class Options:
    family: str = "My Handwriting"
    spacing: int = 40  # side bearing on each side, font units
    normalize: bool = True
    fill_case: bool = True


@dataclass
class Result:
    ttf: bytes
    family: str
    filename: str
    found: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    borrowed: dict = field(default_factory=dict)  # char -> char it reuses


def clean_family(name):
    name = re.sub(r"[^A-Za-z0-9 \-]", "", name or "").strip()
    name = re.sub(r"\s+", " ", name)[:48]
    return name or "My Handwriting"


def glyph_name(ch):
    return UV2AGL.get(ord(ch), f"uni{ord(ch):04X}")


def _scale_factor(outlines):
    """Uniform scale so that capitals average CAP_HEIGHT (or x-height letters X_HEIGHT)."""
    caps = [b[3] for ch, (c, b) in outlines.items() if ch in CAP_REF and b]
    if len(caps) >= 3:
        return min(max(L.CAP_HEIGHT / statistics.median(caps), 0.5), 2.0)
    xs = [b[3] for ch, (c, b) in outlines.items() if ch in X_REF and b]
    if len(xs) >= 3:
        return min(max(L.X_HEIGHT / statistics.median(xs), 0.5), 2.0)
    return 1.0


def build_font(glyphs, opts: Options) -> Result:
    """glyphs: {char: extract.Glyph}. Returns the compiled .ttf."""
    family = clean_family(opts.family)

    outlines = {}
    for ch, g in glyphs.items():
        contours = V.trace(g)
        if contours:
            outlines[ch] = (contours, V.bounds(contours))
    if not outlines:
        raise ValueError("no handwriting found in the uploaded sheets")

    k = _scale_factor(outlines) if opts.normalize else 1.0
    sb = max(-100, min(300, int(opts.spacing)))

    order = [".notdef", "space"]
    cmap = {0x20: "space", 0xA0: "space"}
    glyf, advances = {}, {}

    # .notdef: a hollow rectangle
    pen = TTGlyphPen(None)
    for box in ((50, 0, 450, 700), (100, 50, 400, 650)):
        x0, y0, x1, y1 = box
        pts = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
        if box[0] == 100:
            pts.reverse()
        pen.moveTo(pts[0])
        for p in pts[1:]:
            pen.lineTo(p)
        pen.closePath()
    glyf[".notdef"] = pen.glyph()
    advances[".notdef"] = 500

    widths = []
    ymin_all, ymax_all = 0, L.CAP_HEIGHT
    for ch in L.ALL_CHARS:
        if ch not in outlines:
            continue
        contours, _ = outlines[ch]
        contours = V.transform(contours, scale=k)
        xmin, ymin, xmax, ymax = V.bounds(contours)
        contours = V.transform(contours, dx=sb - xmin)
        name = glyph_name(ch)

        pen = TTGlyphPen(None)
        V.draw(contours, Cu2QuPen(pen, max_err=1.0, reverse_direction=False))
        glyf[name] = pen.glyph()
        adv = max(1, round(xmax - xmin + 2 * sb))
        advances[name] = adv
        order.append(name)
        cmap[ord(ch)] = name
        ymin_all, ymax_all = min(ymin_all, ymin), max(ymax_all, ymax)
        if ch.isalpha():
            widths.append(adv)

    space_w = round(0.55 * statistics.median(widths)) if widths else 300
    glyf["space"] = TTGlyphPen(None).glyph()
    advances["space"] = max(150, space_w)

    # borrow the other letter case for anything left blank
    borrowed = {}
    if opts.fill_case:
        for ch in L.ALL_CHARS:
            if ch.isalpha() and ord(ch) not in cmap:
                other = ch.swapcase()
                if ord(other) in cmap:
                    cmap[ord(ch)] = cmap[ord(other)]
                    borrowed[ch] = other
    for cp, src in ALIASES.items():
        if ord(src) in cmap:
            cmap[cp] = cmap[ord(src)]

    fb = FontBuilder(L.UPM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyf)
    glyf_table = fb.font["glyf"]
    metrics = {
        n: (advances[n], getattr(glyf_table[n], "xMin", 0)) for n in order
    }
    fb.setupHorizontalMetrics(metrics)

    ascent = max(L.BOX_TOP, round(ymax_all) + 20)
    descent = max(-L.DESCENDER + 80, round(-ymin_all) + 20)
    fb.setupHorizontalHeader(ascent=ascent, descent=-descent)

    ps = re.sub(r"[^A-Za-z0-9\-]", "", family.replace(" ", "")) or "MyHandwriting"
    fb.setupNameTable({
        "familyName": family,
        "styleName": "Regular",
        "uniqueFontIdentifier": f"MakeMyFont: {family}",
        "fullName": family,
        "psName": f"{ps}-Regular",
        "version": "Version 1.000",
        "manufacturer": "Make My Font",
        "description": "Generated from handwriting with Make My Font",
    })
    fb.setupOS2(
        sTypoAscender=ascent,
        sTypoDescender=-descent,
        sTypoLineGap=0,
        usWinAscent=ascent,
        usWinDescent=descent,
        sxHeight=round(L.X_HEIGHT * (k if opts.normalize else 1)),
        sCapHeight=L.CAP_HEIGHT,
        usWeightClass=400,
        fsSelection=0x40,  # REGULAR
        fsType=0,  # installable embedding
        achVendID="MMFT",
    )
    fb.setupPost()

    buf = io.BytesIO()
    fb.save(buf)

    present = [c for c in L.ALL_CHARS if c in outlines]
    missing = [c for c in L.ALL_CHARS if c not in outlines and c not in borrowed]
    return Result(
        ttf=buf.getvalue(),
        family=family,
        filename=f"{ps}.ttf",
        found=present,
        missing=missing,
        borrowed=borrowed,
    )
