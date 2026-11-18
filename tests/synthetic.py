"""Make fake 'photos' of a filled-in template for testing the pipeline."""

import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

from _fontmaker import layout as L  # noqa: E402
from _fontmaker import template  # noqa: E402

CANDIDATE_FONTS = [
    r"C:\Windows\Fonts\Inkfree.ttf",
    r"C:\Windows\Fonts\segoesc.ttf",
    "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _hand_font(size):
    for p in CANDIDATE_FONTS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def filled_page(page, skip=""):
    """Template page with every character 'handwritten' on its baseline."""
    img = template.render_page(page).copy()
    draw = ImageDraw.Draw(img)
    cells = L.cells_for_page(page)
    cap_px = (L.CAP_HEIGHT) / cells[0].units_per_px
    font = _hand_font(round(cap_px * 1.35))
    ascent, _ = font.getmetrics()
    rng = np.random.default_rng(page)
    for cell in cells:
        if cell.char in skip:
            continue
        base_y = cell.y_for_units(0)
        x = cell.x0 + cell.w * 0.3 + rng.uniform(-8, 8)
        draw.text((x, base_y - ascent + rng.uniform(-3, 3)), cell.char, fill=(25, 30, 60), font=font)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def fake_photo(bgr, seed=0, out_w=2000):
    """Perspective tilt, rotation, uneven lighting, blur, noise, JPEG."""
    rng = np.random.default_rng(seed)
    h, w = bgr.shape[:2]
    scale = out_w / w
    out_h = round(h * scale * 1.05)
    j = lambda: rng.uniform(-0.06, 0.06) * out_w  # noqa: E731
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    pad = 0.08 * out_w
    dst = np.float32([
        [pad + j(), pad + j()],
        [out_w - pad + j(), pad + j()],
        [out_w - pad + j(), out_h - pad + j()],
        [pad + j(), out_h - pad + j()],
    ])
    M = cv2.getPerspectiveTransform(src, dst)
    photo = cv2.warpPerspective(bgr, M, (out_w, out_h), borderValue=(90, 80, 70))

    # lighting gradient + warm tint
    yy, xx = np.mgrid[0:out_h, 0:out_w].astype(np.float32)
    light = 0.62 + 0.38 * (xx / out_w * 0.6 + (1 - yy / out_h) * 0.4)
    photo = photo.astype(np.float32) * light[..., None] * np.array([0.92, 0.97, 1.0])
    photo = cv2.GaussianBlur(photo, (0, 0), 1.1)
    photo += rng.normal(0, 4, photo.shape)
    photo = np.clip(photo, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", photo, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()
