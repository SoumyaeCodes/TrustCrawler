"""FastAPI router for the PubMed scraper.

Presentation-layer shim — see `Task 1 Multi-Source Scraper/README.md`.
Loaded by file path from `src/api.py` via `importlib.util`. Real
implementation lives in `src/scrapers/pubmed.py`.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.schema import ScrapedSource
from src.scrapers import pubmed as pubmed_module
from src.trust_score import compute as compute_module
from src.trust_score.weights import validate_weights

router = APIRouter(tags=["scrape"])


class PubmedScrapeRequest(BaseModel):
    pmid_or_url: str
    max_tags: int = Field(default=8, ge=1, le=20)
    weights: dict[str, float] | None = None


@router.post(
    "/scrape/pubmed",
    response_model=ScrapedSource,
    summary="Scrape a PubMed article and compute its trust score",
)
def scrape_pubmed_endpoint(req: PubmedScrapeRequest) -> ScrapedSource:
    if req.weights is not None:
        validate_weights(req.weights)
    raw, meta = pubmed_module.scrape_pubmed(
        req.pmid_or_url,
        max_tags=req.max_tags,
    )
    return compute_module.compute_trust_score(raw, meta, weights=req.weights)
