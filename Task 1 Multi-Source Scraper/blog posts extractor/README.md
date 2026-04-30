# Blog posts extractor (shim)

Real implementation: [`src/scrapers/blog.py`](../../src/scrapers/blog.py).

`api.py` in this folder is the FastAPI router exposing `POST /scrape/blog`.
The router calls `src.scrapers.blog.scrape_blog(...)` and pipes the result
through `src.trust_score.compute.compute_trust_score(...)` before returning
a `ScrapedSource` JSON.

This folder has no `__init__.py` — it is loaded by file path from
`src/api.py` via `importlib.util`.
