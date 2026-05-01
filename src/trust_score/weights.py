"""Component weights for trust-score aggregation, plus a validator.

The weights live here (not inline in compute.py) so the API and UI can
import the canonical values and offer overrides through validate_weights.
"""

from __future__ import annotations

from src.errors import WeightValidationError

# Weights tuned against the 6 default sources after observing how each
# component actually behaves on real content. See REPORT.md §3 for the
# full rationale; the headline shifts vs. the original 0.25/0.20×4/0.15
# allocation are:
#   - domain_authority is the cleanest cross-source signal (every source
#     gets a meaningful, differentiated value), so it carries the most
#     weight (was 0.20).
#   - medical_disclaimer_presence matters more when applicable; non-medical
#     content gets neutral 1.0 anyway, so a higher weight is safe (was 0.15).
#   - recency was overweight given that Wikipedia exposes the article's
#     first-revision date in JSON-LD (often 2001), making the signal nearly
#     useless for living content (was 0.20).
#   - citation_count is partial: half the batch (YouTube + the default PMID)
#     can't earn it because there are no outbound links / no ELink data, so
#     dial it back (was 0.20).
#   - author_credibility kept modest since detection varies widely by
#     source type — Wikipedia "Contributors to Wikimedia projects" vs.
#     a verified YouTube channel are very different signals (was 0.25).
WEIGHTS: dict[str, float] = {
    "author_credibility": 0.20,
    "citation_count": 0.15,
    "domain_authority": 0.30,
    "recency": 0.10,
    "medical_disclaimer_presence": 0.25,
}

WEIGHT_KEYS: frozenset[str] = frozenset(WEIGHTS)
SUM_TOLERANCE: float = 1e-6


def validate_weights(w: dict[str, float], *, tolerance: float = SUM_TOLERANCE) -> None:
    if not isinstance(w, dict):
        raise WeightValidationError("weights must be a dict", details={"got": type(w).__name__})
    if set(w) != WEIGHT_KEYS:
        raise WeightValidationError(
            "weights must have exactly the canonical keys",
            details={
                "missing": sorted(WEIGHT_KEYS - set(w)),
                "extra": sorted(set(w) - WEIGHT_KEYS),
            },
        )
    for k, v in w.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise WeightValidationError(
                f"weight {k!r} is not numeric",
                details={"key": k, "value": v},
            )
        if v < 0.0 or v > 1.0:
            raise WeightValidationError(
                f"weight {k!r} out of range",
                details={"key": k, "value": v},
            )
    s = sum(w.values())
    if abs(s - 1.0) > tolerance:
        raise WeightValidationError(
            "weights do not sum to 1.0",
            details={"sum": s, "tolerance": tolerance},
        )
