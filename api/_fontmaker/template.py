"""Render the printable handwriting template."""

import io
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import layout as L

INK = (20, 20, 20)
LABEL = (90, 90, 90)
BOX = (185, 185, 185)  # light enough to fall above the ink threshold
BASELINE = (150, 190, 235)
GUIDE = (200, 218, 240)


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow without scalable default font
        return ImageFont.load_default()


def _aruco_dict():
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, L.ARUCO_DICT))


def _dashed_hline(draw, x0, x1, y, color, width=2, dash=14, gap=12):
    x = x0
    while x < x1:
        draw.line([(x, y), (min(x + dash, x1), y)], fill=color, width=width)
        x += dash + gap


@lru_cache(maxsize=4)
def render_page(page):
    """Return the template page as an RGB PIL image."""
    img = Image.new("RGB", (L.PAGE_W, L.PAGE_H), "white")
    draw = ImageDraw.Draw(img)
    adict = _aruco_dict()

    for slot, (mx, my) in enumerate(L.marker_origins()):
        marker_id = page * L.MARKERS_PER_PAGE + slot
        m = cv2.aruco.generateImageMarker(adict, marker_id, L.MARKER_SIZE)
        img.paste(Image.fromarray(m).convert("RGB"), (mx, my))

    # header between the top markers
    left = L.MARKER_MARGIN + L.MARKER_SIZE + 60
    draw.text((left, 130), "Make My Font", fill=INK, font=_font(84))
    draw.text(
        (left, 235),
        f"Page {page + 1} of {len(L.PAGES)}  ·  write one character per box",
        fill=LABEL,
        font=_font(44),
    )

    # footer between the bottom markers
    tips = [
        "Use a black felt-tip or gel pen. Sit letters on the blue baseline; let g j p q y hang below it.",
        "Keep every stroke inside its box. Photograph flat, in even light, with all four corner squares visible.",
    ]
    for i, t in enumerate(tips):
        draw.text((left, L.PAGE_H - 290 + i * 62), t, fill=LABEL, font=_font(34))

    label_font = _font(40)
    for cell in L.cells_for_page(page):
        lx0, ly0, lx1, ly1 = cell.label_box()
        draw.text((lx0 + 4, ly0 + 4), cell.char, fill=LABEL, font=label_font)

        # guide lines inside the drawing box
        for units, color, dashed in (
            (L.CAP_HEIGHT, GUIDE, True),
            (L.X_HEIGHT, GUIDE, True),
            (L.DESCENDER, GUIDE, True),
            (0, BASELINE, False),
        ):
            y = round(cell.y_for_units(units))
            if dashed:
                _dashed_hline(draw, cell.x0 + 6, cell.x1 - 6, y, color)
            else:
                draw.line([(cell.x0 + 2, y), (cell.x1 - 2, y)], fill=color, width=3)

        draw.rectangle([cell.x0, cell.y0, cell.x1, cell.y1], outline=BOX, width=2)

    return img


def page_png(page):
    buf = io.BytesIO()
    render_page(page).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def template_pdf():
    pages = [render_page(p) for p in range(len(L.PAGES))]
    buf = io.BytesIO()
    pages[0].save(
        buf, "PDF", resolution=L.DPI, save_all=True, append_images=pages[1:]
    )
    return buf.getvalue()


def page_array(page):
    """Template page as a BGR numpy array (used by tests)."""
    return cv2.cvtColor(np.array(render_page(page)), cv2.COLOR_RGB2BGR)
