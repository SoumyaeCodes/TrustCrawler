"""FastAPI router for the YouTube scraper.

Presentation-layer shim — see `Task 1 Multi-Source Scraper/README.md`.
Loaded by file path from `src/api.py` via `importlib.util`. Real
implementation lives in `src/scrapers/youtube.py`.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.schema import ScrapedSource
from src.scrapers import youtube as youtube_module
from src.trust_score import compute as compute_module
from src.trust_score.weights import validate_weights

router = APIRouter(tags=["scrape"])


class YoutubeScrapeRequest(BaseModel):
    url_or_id: str
    language_hint: str | None = None
    max_tags: int = Field(default=8, ge=1, le=20)
    weights: dict[str, float] | None = None


@router.post(
    "/scrape/youtube",
    response_model=ScrapedSource,
    summary="Scrape a YouTube video and compute its trust score",
)
def scrape_youtube_endpoint(req: YoutubeScrapeRequest) -> ScrapedSource:
    if req.weights is not None:
        validate_weights(req.weights)
    raw, meta = youtube_module.scrape_youtube(
        req.url_or_id,
        language_hint=req.language_hint,
        max_tags=req.max_tags,
    )
    return compute_module.compute_trust_score(raw, meta, weights=req.weights)
