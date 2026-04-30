"""FastAPI router for the blog scraper.

Presentation-layer shim — see `Task 1 Multi-Source Scraper/README.md`.
This file is loaded by file path from `src/api.py` via `importlib.util`
because the folder name contains spaces and is therefore not a valid
Python identifier. Real implementation lives in `src/scrapers/blog.py`.

Module-level imports are kept attribute-style (`blog_module.scrape_blog`,
not `from src.scrapers.blog import scrape_blog`) so tests can monkeypatch
the underlying scraper at its source module.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.schema import ScrapedSource
from src.scrapers import blog as blog_module
from src.trust_score import compute as compute_module
from src.trust_score.weights import validate_weights

router = APIRouter(tags=["scrape"])


class BlogScrapeRequest(BaseModel):
    url: str
    max_tags: int = Field(default=8, ge=1, le=20)
    chunk_min: int = Field(default=200, ge=50, le=2000)
    chunk_max: int = Field(default=500, ge=100, le=5000)
    weights: dict[str, float] | None = None


@router.post(
    "/scrape/blog",
    response_model=ScrapedSource,
    summary="Scrape a blog URL and compute its trust score",
)
def scrape_blog_endpoint(req: BlogScrapeRequest) -> ScrapedSource:
    if req.weights is not None:
        validate_weights(req.weights)
    raw, meta = blog_module.scrape_blog(
        req.url,
        max_tags=req.max_tags,
        chunk_min=req.chunk_min,
        chunk_max=req.chunk_max,
    )
    return compute_module.compute_trust_score(raw, meta, weights=req.weights)
