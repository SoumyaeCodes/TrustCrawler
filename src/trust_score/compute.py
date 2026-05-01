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
from urllib.parse import urlparse

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


_DISCLAIMER_KEY = "medical_disclaimer_presence"


def _effective_weights(weights: dict[str, float], is_medical: bool) -> dict[str, float]:
    """For non-medical content, drop the disclaimer component (set its
    weight to 0) and rescale the remaining weights to sum to 1.0.

    Rationale: `medical_disclaimer.score` returns a "neutral" 1.0 for
    non-medical content, but with a non-zero weight that 1.0 acts as a
    free maximum-contribution floor — every non-medical article inherits
    `weights[disclaimer]` of trust score regardless of quality. Rescaling
    makes the score reflect only the components that actually apply.
    """
    if is_medical:
        return weights
    disc_w = weights.get(_DISCLAIMER_KEY, 0.0)
    rest = 1.0 - disc_w
    if rest <= 0:
        # Degenerate: caller put 100% weight on the disclaimer for
        # non-medical content. Falling back keeps the contract from
        # collapsing to a divide-by-zero.
        return weights
    return {
        k: 0.0 if k == _DISCLAIMER_KEY else v / rest
        for k, v in weights.items()
    }


def _calc(
    raw: ScrapedRaw,
    meta: RawMetadata,
    weights: dict[str, float],
    today_eff: date,
) -> tuple[dict[str, float], dict[str, float], dict[str, float], float, dict[str, float], float]:
    """Single source of truth for the score math. Returns
    (components, effective_weights, contributions, aggregated,
    post_multipliers, final). Both compute_trust_score and
    compute_with_breakdown go through here.
    """
    components = {
        "author_credibility": author_credibility.score(raw, meta),
        "citation_count": citation_count.score(raw, meta),
        "domain_authority": domain_authority.score(raw, meta),
        "recency": recency.score(raw, meta, today=today_eff),
        _DISCLAIMER_KEY: medical_disclaimer.score(raw, meta),
    }
    eff_weights = _effective_weights(weights, bool(meta.get("is_medical")))
    contributions = {k: round(eff_weights[k] * components[k], 6) for k in eff_weights}
    aggregated = sum(contributions.values())
    multipliers = _post_multiplier(raw, meta, today_eff)
    final_raw = aggregated
    for m in multipliers.values():
        final_raw *= m
    final = round(max(0.0, min(1.0, final_raw)), 3)
    return components, eff_weights, contributions, aggregated, multipliers, final


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
        host = urlparse(str(raw.source_url)).hostname
        if not ap.is_tier_1_source(raw.source_type, host):
            age_days = (today_eff - raw.published_date).days
            mult = ap.old_medical_multiplier(age_days)
            if mult < 1.0:
                out["old_medical"] = round(mult, 6)
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

    components, eff_weights, contributions, aggregated, multipliers, final = _calc(
        raw, meta, weights, today_eff
    )
    calc = TrustScoreCalculation(
        components=components,
        weights=eff_weights,
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
    components, _eff, _contribs, aggregated, multipliers, final = _calc(
        raw, meta, weights, today_eff
    )
    return TrustScoreBreakdown(
        components=components,
        aggregated=aggregated,
        post_multipliers=multipliers,
        final=final,
    )
