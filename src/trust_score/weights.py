"""Component weights for trust-score aggregation, plus a validator.

The weights live here (not inline in compute.py) so the API and UI can
import the canonical values and offer overrides through validate_weights.
"""

from __future__ import annotations

from src.errors import WeightValidationError

WEIGHTS: dict[str, float] = {
    "author_credibility": 0.25,
    "citation_count": 0.20,
    "domain_authority": 0.20,
    "recency": 0.20,
    "medical_disclaimer_presence": 0.15,
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
