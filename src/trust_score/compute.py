"""Trust-score orchestrator (CLAUDE.md §6).

Pure given (raw, meta, weights, today). Implements the 6-step application
order from §6.4:

  1. Compute each component score.
  2. Component-level multipliers (fake-author 0.3× — applied INSIDE
     `author_credibility.score` so each component owns its own pre-
     aggregation multipliers).
  3. Weighted sum.
  4. Post-aggregation multipliers — keyword stuffing (0.7×) and old
     medical (0.5×).
  5. Clamp to [0, 1].
  6. Round to 3 decimals.

Duplicate detection (§6.4) is NOT in the orchestrator — it's a caller-
level concern (a `DuplicateTracker` is created by `main.py` for the run).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.schema import RawMetadata, ScrapedRaw, ScrapedSource, TrustScoreCalculation
from src.trust_score import abuse_prevention as ap
from src.trust_score.components import (
    author_credibility,
    citation_count,
    domain_authority,
    medical_disclaimer,
    recency,
)
from src.trust_score.weights import WEIGHTS, validate_weights


@dataclass(frozen=True)
class TrustScoreBreakdown:
    """Internal record of how a final score was reached. Kept for tests
    that prefer a dataclass; the user-facing payload is the Pydantic
    `TrustScoreCalculation` model embedded in every ScrapedSource.
    """

    components: dict[str, float]
    aggregated: float
    post_multipliers: dict[str, float]
    final: float


def _calc(
    raw: ScrapedRaw,
    meta: RawMetadata,
    weights: dict[str, float],
    today_eff: date,
) -> tuple[dict[str, float], dict[str, float], float, dict[str, float], float]:
    """Single source of truth for the score math. Returns
    (components, contributions, aggregated, post_multipliers, final).
    Both compute_trust_score and compute_with_breakdown go through here.
    """
    components = {
        "author_credibility": author_credibility.score(raw, meta),
        "citation_count": citation_count.score(raw, meta),
        "domain_authority": domain_authority.score(raw, meta),
        "recency": recency.score(raw, meta, today=today_eff),
        "medical_disclaimer_presence": medical_disclaimer.score(raw, meta),
    }
    contributions = {k: round(weights[k] * components[k], 6) for k in weights}
    aggregated = sum(contributions.values())
    multipliers = _post_multiplier(raw, meta, today_eff)
    final_raw = aggregated
    for m in multipliers.values():
        final_raw *= m
    final = round(max(0.0, min(1.0, final_raw)), 3)
    return components, contributions, aggregated, multipliers, final


def _post_multiplier(raw: ScrapedRaw, meta: RawMetadata, today_eff: date) -> dict[str, float]:
    out: dict[str, float] = {}
    body = meta.get("body_text") or ""
    if ap.has_keyword_stuffing(body):
        out["keyword_stuffing"] = 0.7
    if (
        meta.get("is_medical")
        and raw.published_date is not None
        and (today_eff - raw.published_date).days > ap.OLD_MEDICAL_AGE_DAYS
    ):
        out["old_medical"] = 0.5
    return out


def compute_trust_score(
    raw: ScrapedRaw,
    meta: RawMetadata,
    weights: dict[str, float] | None = None,
    *,
    today: date | None = None,
) -> ScrapedSource:
    weights = WEIGHTS if weights is None else weights
    validate_weights(weights)
    today_eff = today if today is not None else date.today()

    components, contributions, aggregated, multipliers, final = _calc(
        raw, meta, weights, today_eff
    )
    calc = TrustScoreCalculation(
        components=components,
        weights=dict(weights),
        contributions=contributions,
        aggregated=round(aggregated, 6),
        post_multipliers=multipliers,
        final=final,
    )
    return ScrapedSource(
        **raw.model_dump(),
        trust_score=final,
        trust_score_calculation=calc,
    )


def compute_with_breakdown(
    raw: ScrapedRaw,
    meta: RawMetadata,
    weights: dict[str, float] | None = None,
    *,
    today: date | None = None,
) -> TrustScoreBreakdown:
    """Same math as `compute_trust_score` but returns the intermediate
    pieces for explainability. Tests use this to assert component-level
    invariants without re-implementing the math.
    """
    weights = WEIGHTS if weights is None else weights
    validate_weights(weights)
    today_eff = today if today is not None else date.today()
    components, _contribs, aggregated, multipliers, final = _calc(
        raw, meta, weights, today_eff
    )
    return TrustScoreBreakdown(
        components=components,
        aggregated=aggregated,
        post_multipliers=multipliers,
        final=final,
    )
