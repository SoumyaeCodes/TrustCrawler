# PubMed article extractor (shim)

Real implementation: [`src/scrapers/pubmed.py`](../../src/scrapers/pubmed.py).

`api.py` in this folder is the FastAPI router exposing `POST /scrape/pubmed`.

This folder has no `__init__.py` — it is loaded by file path from
`src/api.py` via `importlib.util`.
