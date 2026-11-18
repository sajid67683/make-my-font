"""End-to-end check: synthetic photos -> sheets -> .ttf.

Run:  python tests/test_pipeline.py [output_dir]
Writes the font, a rendered sample and the sheet previews into output_dir.
"""

import io
import os
import sys
import time

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from synthetic import L, fake_photo, filled_page  # noqa: E402

from _fontmaker.build import Options, build_font  # noqa: E402
from _fontmaker.extract import read_sheet  # noqa: E402


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    glyphs = {}
    skipped = "QZ"  # leave a couple blank on page 1 to test case borrowing
    for page in range(len(L.PAGES)):
        t = time.time()
        photo = fake_photo(filled_page(page, skip=skipped if page == 0 else ""), seed=page)
        with open(os.path.join(out_dir, f"photo{page + 1}.jpg"), "wb") as f:
            f.write(photo)
        sheet = read_sheet(photo)
        assert sheet.page == page, f"detected page {sheet.page}, expected {page}"
        expected = len(L.PAGES[page]) - (len(skipped) if page == 0 else 0)
        print(f"page {page + 1}: {sheet.markers_found} markers, {len(sheet.glyphs)}/{expected} glyphs, "
              f"{time.time() - t:.2f}s, warnings={sheet.warnings}")
        assert len(sheet.glyphs) == expected, sorted(set(L.PAGES[page]) - set(sheet.glyphs))
        with open(os.path.join(out_dir, f"preview{page + 1}.jpg"), "wb") as f:
            f.write(sheet.preview)
        glyphs.update(sheet.glyphs)

    t = time.time()
    res = build_font(glyphs, Options(family="Test Hand"))
    print(f"build: {time.time() - t:.2f}s, {len(res.ttf) / 1024:.0f} KB, missing={res.missing!r}, "
          f"borrowed={res.borrowed}")
    assert res.borrowed.get("Q") == "q" and res.borrowed.get("Z") == "z"

    path = os.path.join(out_dir, res.filename)
    with open(path, "wb") as f:
        f.write(res.ttf)

    tt = TTFont(io.BytesIO(res.ttf))
    cmap = tt.getBestCmap()
    assert all(ord(c) in cmap for c in L.ALL_CHARS), "cmap incomplete"
    print("tables:", sorted(tt.keys()))

    font = ImageFont.truetype(path, 90)
    lines = ["The quick brown fox jumps", "over the lazy dog! 0123456789",
             "Sphinx of black quartz, judge my vow.", "@#$%&*()[]{}<>/\\|~^`_+=?"]
    img = Image.new("RGB", (2000, 130 * len(lines) + 40), "white")
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((30, 20 + 130 * i), line, font=font, fill="black")
    img.save(os.path.join(out_dir, "sample.png"))
    print("ok ->", out_dir)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "out"))
