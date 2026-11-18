"""Handwriting -> TrueType font pipeline.

layout     shared template geometry + character set
template   renders the printable template (PNG / PDF)
extract    OpenCV: find corner markers, unwarp the photo, cut out glyph bitmaps
vectorize  potrace: bitmap -> bezier outlines in font units
build      fontTools: outlines -> .ttf
"""
