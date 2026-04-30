# YouTube videos extractor (shim)

Real implementation: [`src/scrapers/youtube.py`](../../src/scrapers/youtube.py).

`api.py` in this folder is the FastAPI router exposing `POST /scrape/youtube`.

This folder has no `__init__.py` — it is loaded by file path from
`src/api.py` via `importlib.util`.
