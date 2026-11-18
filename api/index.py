"""Vercel serverless entry point (Flask). All /api/* routes are rewritten here."""

import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, Response, jsonify, request  # noqa: E402

from _fontmaker import layout as L  # noqa: E402
from _fontmaker import template  # noqa: E402
from _fontmaker.build import Options, build_font  # noqa: E402
from _fontmaker.extract import SheetError, read_sheet  # noqa: E402

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

MAX_FILES = 6
CACHE = "public, max-age=86400, s-maxage=604800"


def _num(name, default, lo, hi, cast=float):
    try:
        v = cast(request.form.get(name, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _flag(name, default=True):
    v = request.form.get(name)
    return default if v is None else v.lower() in ("1", "true", "on", "yes")


@app.get("/api/health")
def health():
    return jsonify(ok=True)


@app.get("/api/template.pdf")
def template_pdf():
    return Response(
        template.template_pdf(),
        mimetype="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="make-my-font-template.pdf"',
            "Cache-Control": CACHE,
        },
    )


@app.get("/api/template/<int:page>.png")
def template_png(page):
    if not 1 <= page <= len(L.PAGES):
        return jsonify(ok=False, error="no such page"), 404
    return Response(
        template.page_png(page - 1),
        mimetype="image/png",
        headers={"Cache-Control": CACHE},
    )


@app.get("/api/charset")
def charset():
    return jsonify(pages=L.PAGES)


@app.post("/api/generate")
def generate():
    t0 = time.time()
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if not files:
        return jsonify(ok=False, error="upload at least one photo of a filled template"), 400
    if len(files) > MAX_FILES:
        return jsonify(ok=False, error=f"upload at most {MAX_FILES} images"), 400

    threshold = _num("threshold", 0.6, 0.3, 0.9)
    weight = _num("weight", 0, -3, 3, int)
    opts = Options(
        family=request.form.get("family", "My Handwriting"),
        spacing=_num("spacing", 40, -100, 300, int),
        normalize=_flag("normalize"),
        fill_case=_flag("fill_case"),
    )

    glyphs, sheets = {}, []
    for f in files:
        info = {"file": f.filename}
        try:
            sheet = read_sheet(f.read(), threshold=threshold, weight=weight)
        except SheetError as e:
            info.update(ok=False, error=str(e))
            sheets.append(info)
            continue
        glyphs.update(sheet.glyphs)
        info.update(
            ok=True,
            page=sheet.page + 1,
            markers=sheet.markers_found,
            chars=len(sheet.glyphs),
            warnings=sheet.warnings,
            preview="data:image/jpeg;base64," + base64.b64encode(sheet.preview).decode(),
        )
        sheets.append(info)

    if not glyphs:
        msg = next((s["error"] for s in sheets if not s.get("ok")), "no handwriting found")
        return jsonify(ok=False, error=msg, sheets=sheets), 422

    try:
        result = build_font(glyphs, opts)
    except ValueError as e:
        return jsonify(ok=False, error=str(e), sheets=sheets), 422

    return jsonify(
        ok=True,
        family=result.family,
        filename=result.filename,
        font=base64.b64encode(result.ttf).decode(),
        found="".join(result.found),
        missing="".join(result.missing),
        borrowed=result.borrowed,
        sheets=sheets,
        seconds=round(time.time() - t0, 2),
    )


@app.errorhandler(413)
def too_large(_):
    return jsonify(ok=False, error="upload too large - try smaller photos"), 413
