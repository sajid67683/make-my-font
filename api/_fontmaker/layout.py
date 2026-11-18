"""Template geometry shared by the template renderer and the scanner.

Everything is expressed in template pixels (A4 at 300 dpi). A photo of a
filled sheet is warped back into exactly this coordinate system using the
four ArUco markers, so cell positions can be read straight from here.
"""

from dataclasses import dataclass

# --- page -------------------------------------------------------------------
PAGE_W, PAGE_H = 2480, 3508  # A4 @ 300 dpi
DPI = 300

# --- corner markers (ArUco DICT_4X4_50) ---------------------------------------
MARKER_SIZE = 200
MARKER_MARGIN = 110
ARUCO_DICT = "DICT_4X4_50"
MARKERS_PER_PAGE = 4  # page p uses ids 4p .. 4p+3 in order TL, TR, BR, BL


def marker_origins():
    """Top-left corner of each marker, ordered TL, TR, BR, BL."""
    m, s = MARKER_MARGIN, MARKER_SIZE
    return [
        (m, m),
        (PAGE_W - m - s, m),
        (PAGE_W - m - s, PAGE_H - m - s),
        (m, PAGE_H - m - s),
    ]


def marker_corners(slot):
    """The 4 corners of marker `slot` (0..3) in ArUco order (TL, TR, BR, BL)."""
    x, y = marker_origins()[slot]
    s = MARKER_SIZE
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s)]


# --- character grid -----------------------------------------------------------
COLS, ROWS = 6, 8
GRID_X0, GRID_Y0 = 140, 470
CELL_W, CELL_H = 366, 336
CELL_GAP = 14  # white gutter between neighbouring cells
LABEL_H = 50  # strip above each drawing box holding the printed character

PAGES = [
    # page 1: 48 cells
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ" "0123456789" ".,!?'\"-:;()&",
    # page 2: 46 cells -> together the full printable ASCII set
    "abcdefghijklmnopqrstuvwxyz" "@#$%*+=/\\_<>[]{}|~^`",
]

# --- vertical metrics of a drawing box ---------------------------------------
# The whole drawing box spans BOX_UNITS font units: its top edge is at
# BOX_TOP units above the baseline, its bottom edge BOX_UNITS - BOX_TOP below.
UPM = 1000
BOX_UNITS = 1200
BOX_TOP = 900
CAP_HEIGHT = 700
X_HEIGHT = 480
DESCENDER = -220


@dataclass(frozen=True)
class Cell:
    char: str
    page: int
    index: int
    # drawing box in template pixels
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0

    @property
    def units_per_px(self):
        return BOX_UNITS / self.h

    def y_for_units(self, units):
        """Template-pixel y of a horizontal line `units` above the baseline."""
        return self.y0 + (BOX_TOP - units) / self.units_per_px

    def label_box(self):
        return (self.x0, self.y0 - LABEL_H, self.x1, self.y0)


def cells_for_page(page):
    chars = PAGES[page]
    half = CELL_GAP // 2
    out = []
    for i, ch in enumerate(chars):
        r, c = divmod(i, COLS)
        cx = GRID_X0 + c * CELL_W
        cy = GRID_Y0 + r * CELL_H
        out.append(
            Cell(
                char=ch,
                page=page,
                index=i,
                x0=cx + half,
                y0=cy + LABEL_H,
                x1=cx + CELL_W - half,
                y1=cy + CELL_H - half,
            )
        )
    return out


ALL_CHARS = "".join(PAGES)
