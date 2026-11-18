"""Local development server: serves public/ and the /api routes on one port.

    python dev_server.py        ->  http://localhost:5173
"""

import os
import sys

from flask import send_from_directory

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "api"))

from index import app  # noqa: E402

PUBLIC = os.path.join(ROOT, "public")


@app.get("/")
def _index():
    return send_from_directory(PUBLIC, "index.html")


@app.get("/<path:path>")
def _static(path):
    return send_from_directory(PUBLIC, path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5173))
    app.run(host="127.0.0.1", port=port, debug=True)
