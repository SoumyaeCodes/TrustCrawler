"""Recency component (CLAUDE.md §6.1).

`exp(-age_days / τ)` where τ is the e-folding time. General content uses
τ = 730 days; medical/scientific uses τ = 1825 days. Implied half-lives
are `ln(2)·τ` — ~506 days for general, ~1265 days for medical.

Missing date → 0.3. Future-dated content → clamp age to 0.
"""

from __future__ import annotations

import math
from datetime import date

from src.schema import RawMetadata, ScrapedRaw

GENERAL_TAU_DAYS: int = 730
MEDICAL_TAU_DAYS: int = 1825
MISSING_DATE_SCORE: float = 0.3


def score(raw: ScrapedRaw, meta: RawMetadata, *, today: date | None = None) -> float:
    if raw.published_date is None:
        return MISSING_DATE_SCORE
    today_eff = today if today is not None else date.today()
    age = (today_eff - raw.published_date).days
    if age < 0:
        age = 0
    tau = MEDICAL_TAU_DAYS if meta.get("is_medical") else GENERAL_TAU_DAYS
    return math.exp(-age / tau)
