"""OpenCV side: photo of a filled template -> clean glyph bitmaps."""

from collections import Counter
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import layout as L

INSET = 9  # px cut from each side of a drawing box to drop its printed border
UPSCALE = 2  # glyph bitmaps are traced at 2x for smoother curves
MAX_SIDE = 3600  # larger uploads are downscaled before detection


class SheetError(ValueError):
    pass


@dataclass
class Glyph:
    char: str
    ink: np.ndarray  # bool, True = ink, at UPSCALE x template resolution
    cell: L.Cell

    def to_units(self, px, py):
        """Map a pixel of `ink` to font units (x right, y up, baseline at 0)."""
        s = self.cell.units_per_px
        bx = px / UPSCALE + INSET
        by = py / UPSCALE + INSET
        return bx * s, L.BOX_TOP - by * s


@dataclass
class Sheet:
    page: int
    markers_found: int
    glyphs: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    preview: bytes = b""


# --- loading ------------------------------------------------------------------

def decode(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SheetError("could not read this file as an image (use JPG or PNG)")
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        f = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA)
    return img


# --- marker detection + unwarping ----------------------------------------------

def _detector():
    adict = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, L.ARUCO_DICT))
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    params.adaptiveThreshWinSizeMax = 53
    return cv2.aruco.ArucoDetector(adict, params)


def _detect(gray):
    """Return {marker_id: 4x2 corners}. Tries a few preprocessing variants."""
    det = _detector()
    best = {}
    variants = [(1.0, gray)]  # (scale, image)
    h, w = gray.shape
    if max(h, w) > 1800:
        f = 1800 / max(h, w)
        variants.append((f, cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)))
    variants.append((1.0, cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)))

    max_id = len(L.PAGES) * L.MARKERS_PER_PAGE
    for scale, v in variants:
        corners, ids, _ = det.detectMarkers(v)
        if ids is None:
            continue
        found = {}
        for c, i in zip(corners, ids.flatten()):
            if 0 <= i < max_id:
                found[int(i)] = c.reshape(4, 2) / scale
        if len(found) > len(best):
            best = found
        if len(best) >= L.MARKERS_PER_PAGE:
            break
    return best


def unwarp(img):
    """Warp a photo into template coordinates. Returns (page, warped_bgr, n_markers, warnings)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    found = _detect(gray)
    if not found:
        raise SheetError(
            "no corner markers found - make sure all four black corner squares are in the photo"
        )

    page = Counter(i // L.MARKERS_PER_PAGE for i in found).most_common(1)[0][0]
    mine = {i: c for i, c in found.items() if i // L.MARKERS_PER_PAGE == page}
    if len(mine) < 2:
        raise SheetError(
            f"only {len(mine)} of 4 corner markers visible - retake the photo with all corners in frame"
        )

    src, dst = [], []
    for i, corners in mine.items():
        src.extend(corners)
        dst.extend(L.marker_corners(i % L.MARKERS_PER_PAGE))
    src = np.array(src, np.float32)
    dst = np.array(dst, np.float32)
    H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
    if H is None:
        raise SheetError("could not compute the page perspective from the markers")

    warped = cv2.warpPerspective(
        img, H, (L.PAGE_W, L.PAGE_H), flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255),
    )
    warnings = []
    if len(mine) < 4:
        warnings.append(
            f"only {len(mine)} of 4 corner markers detected; alignment may be slightly off"
        )
    return page, warped, len(mine), warnings


# --- ink extraction -------------------------------------------------------------

def flatten_illumination(bgr):
    """Gray image divided by its estimated paper colour -> 1.0 paper, ~0 ink."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    small = cv2.resize(gray, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    # max-filter wipes out pen strokes, leaving the paper brightness
    bg = cv2.dilate(small, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
    bg = cv2.GaussianBlur(bg, (0, 0), 6)
    bg = cv2.resize(bg, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_LINEAR)
    return np.clip(gray / np.maximum(bg, 1.0), 0.0, 1.0)


def _clean(ink, min_area):
    """Drop specks and leftover straight fragments of the printed box border."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    h, w = ink.shape
    keep = np.zeros(n, bool)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < min_area:
            continue
        touches = x == 0 or y == 0 or x + bw >= w or y + bh >= h
        line_like = (bw > 0.6 * w and bh < 10 * UPSCALE) or (bh > 0.6 * h and bw < 10 * UPSCALE)
        if touches and line_like:
            continue
        keep[i] = True
    return keep[labels]


def extract_glyph(norm, cell, threshold=0.6, weight=0):
    """Cut one cell out of the flattened page. Returns a bool ink mask or None if empty."""
    crop = norm[cell.y0 + INSET: cell.y1 - INSET, cell.x0 + INSET: cell.x1 - INSET]
    crop = cv2.resize(crop, None, fx=UPSCALE, fy=UPSCALE, interpolation=cv2.INTER_CUBIC)
    crop = cv2.GaussianBlur(crop, (0, 0), 0.8 * UPSCALE)
    ink = crop < threshold

    if weight:
        k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * abs(weight) * UPSCALE + 1,) * 2
        )
        op = cv2.dilate if weight > 0 else cv2.erode
        ink = op(ink.astype(np.uint8), k).astype(bool)

    # close tiny gaps in pen strokes, then drop noise
    ink = cv2.morphologyEx(
        ink.astype(np.uint8), cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    ).astype(bool)
    ink = _clean(ink, min_area=30 * UPSCALE * UPSCALE)
    if ink.sum() < 60 * UPSCALE * UPSCALE:
        return None
    return ink


def _preview(warped, page, found_chars):
    """Small JPEG of the unwarped sheet with detected cells outlined."""
    vis = warped.copy()
    for cell in L.cells_for_page(page):
        color = (60, 170, 60) if cell.char in found_chars else (60, 60, 220)
        cv2.rectangle(vis, (cell.x0, cell.y0), (cell.x1, cell.y1), color, 10)
    vis = cv2.resize(vis, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 78])
    return buf.tobytes() if ok else b""


def read_sheet(data: bytes, threshold=0.6, weight=0, want_preview=True) -> Sheet:
    img = decode(data)
    page, warped, n, warnings = unwarp(img)
    norm = flatten_illumination(warped)

    sheet = Sheet(page=page, markers_found=n, warnings=warnings)
    for cell in L.cells_for_page(page):
        ink = extract_glyph(norm, cell, threshold, weight)
        if ink is not None:
            sheet.glyphs[cell.char] = Glyph(cell.char, ink, cell)
    if want_preview:
        sheet.preview = _preview(warped, page, sheet.glyphs)
    return sheet
