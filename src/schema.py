"""Pydantic schemas + RawMetadata TypedDict for the scraping pipeline.

Per CLAUDE.md §4: scrapers return tuple[ScrapedRaw, RawMetadata]. The
trust-score module consumes both and returns ScrapedSource. Only
ScrapedSource is serialized to output/scraped_data.json.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, TypedDict

from pydantic import BaseModel, Field, HttpUrl, field_validator


class ScrapedRaw(BaseModel):
    source_url: HttpUrl
    source_type: Literal["blog", "youtube", "pubmed"]
    author: str | list[str] | None = None
    published_date: date | None = None
    language: str = Field(pattern=r"^[a-z]{2,3}$")
    region: str | None = Field(default=None)
    topic_tags: list[str] = Field(default_factory=list)
    content_chunks: list[str]

    @field_validator("region")
    @classmethod
    def _region_is_iso_alpha2(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) != 2 or not v.isalpha() or not v.isupper():
            raise ValueError(
                "region must be ISO 3166-1 alpha-2 (two uppercase letters) or None"
            )
        return v

    @field_validator("content_chunks")
    @classmethod
    def _non_empty_chunks(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("content_chunks must be non-empty")
        if any(not s for s in v):
            raise ValueError("content_chunks must not contain empty strings")
        return v


class TrustScoreCalculation(BaseModel):
    """Explainability payload — how `trust_score` was reached.

    Mirrors the 6-step application order in CLAUDE.md §6.4:
      1. Each component score (post any component-level multipliers).
      2. The weights used for this run (canonical defaults unless the
         caller passed an override).
      3. Per-component contribution = weight × component.
      4. `aggregated` = sum(contributions).
      5. `post_multipliers` chain on `aggregated` (empty dict when none
         applied).
      6. `final` = clamp(aggregated × Π post_multipliers, 0, 1) rounded
         to 3 decimals — must equal the parent record's `trust_score`.
    """

    components: dict[str, float]
    weights: dict[str, float]
    contributions: dict[str, float]
    aggregated: float
    post_multipliers: dict[str, float]
    final: float = Field(ge=0.0, le=1.0)


class ScrapedSource(ScrapedRaw):
    trust_score: float = Field(ge=0.0, le=1.0)
    trust_score_calculation: TrustScoreCalculation | None = None


class RawMetadata(TypedDict, total=False):
    citations: int
    subscriber_count: int
    channel_verified: bool
    outbound_links: list[str]
    transcript_available: bool
    word_count: int
    is_medical: bool
    body_text: str
    affiliations: list[str]
    duplicate: bool
