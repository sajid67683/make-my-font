# Make My Font

Turn handwriting into an installable **.ttf** font. Print a template, fill it in, snap a photo, download your font.

## How it works

```
photo ──► OpenCV ──────────────────────────► potrace ─────────► fontTools ──► .ttf
          • find 4 ArUco corner markers       • bitmap → smooth   • glyf/cmap/hmtx…
          • perspective-correct to A4 grid      bezier outlines   • auto size + spacing
          • flatten lighting, threshold ink   • fix TrueType      • case fallback
          • cut out each cell, drop noise       winding
```

- **Template** (`/api/template.pdf`): 2 A4 pages, 94 printable ASCII characters. Every box has cap-height, x-height, baseline and descender guides; each page carries its own marker IDs, so pages are recognised in any order.
- **Alignment:** ArUco markers give 16 reference points, so tilted, rotated or off-centre photos are warped back exactly onto the template grid.
- **Glyphs:** glyph position comes from the printed baseline, so descenders and punctuation (`, ' "`) land where you wrote them.

## Project layout

```
api/index.py              Flask app = Vercel serverless function (all /api/* routes)
api/_fontmaker/layout.py  template geometry + character set (shared)
api/_fontmaker/template.py  renders template PNG/PDF
api/_fontmaker/extract.py   OpenCV: markers, unwarp, ink extraction
api/_fontmaker/vectorize.py potrace tracing + contour winding
api/_fontmaker/build.py     fontTools TTF builder
public/                   static frontend (index.html, app.js, styles.css)
tests/test_pipeline.py    end-to-end test using synthetic "photos"
```

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python dev_server.py              # http://localhost:5173
python tests/test_pipeline.py     # end-to-end test, writes tests/out/
```

## Deploy to Vercel

Option A, from GitHub: push this folder to a repo, then on vercel.com choose **Add New → Project**, import the repo and click Deploy. No settings needed; `vercel.json` sets everything up.

Option B, CLI:

```bash
npm i -g vercel
vercel          # preview deployment
vercel --prod   # production
```

Notes:
- Vercel limits request bodies to 4.5 MB, so the browser shrinks photos to 2400 px JPEGs before uploading.
- `maxDuration` is 60 s; a full 2-page font takes about 5–8 s.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/template.pdf` | printable template (both pages) |
| GET | `/api/template/{1,2}.png` | single page PNG |
| POST | `/api/generate` | multipart: `files` (images), `family`, `threshold` (0.3–0.9), `weight` (-3–3), `spacing` (-100–300), `normalize`, `fill_case` → JSON with base64 `font` |
