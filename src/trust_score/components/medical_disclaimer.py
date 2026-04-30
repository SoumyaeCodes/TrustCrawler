"""Medical disclaimer presence (CLAUDE.md §6.1).

Only weighted when `meta["is_medical"]` is true. Regex bank matches the
common "this is not medical advice / consult your doctor / for
informational purposes" patterns.

Also exports MEDICAL_KEYWORDS and is_medical_topic() — the canonical
definition of "medical content" used by scrapers to set
`meta["is_medical"]`. Keeping it here means there's exactly one place
that defines what counts as medical.
"""

from __future__ import annotations

import re

from src.schema import RawMetadata, ScrapedRaw

PRESENT_SCORE: float = 1.0
ABSENT_SCORE: float = 0.2
NON_MEDICAL_SCORE: float = 1.0  # neutral

DISCLAIMER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bnot\s+(?:medical|professional|health(?:care)?)\s+advice\b", re.I),
    re.compile(
        # "consult [your|their|a|the] doctor/physician/healthcare provider"
        r"\bconsult\s+(?:\S+\s+){0,3}(?:doctor|physician|healthcare)\b",
        re.I,
    ),
    re.compile(r"\bfor\s+informational\s+purposes\b", re.I),
    re.compile(r"\bdiagnose\s*,?\s*treat\s*,?\s*cure\b", re.I),
    re.compile(r"\bseek\s+(?:medical|professional)\s+(?:advice|attention|help)\b", re.I),
)

MEDICAL_KEYWORDS: frozenset[str] = frozenset({
    "medicine", "medical", "health", "healthcare", "disease", "treatment",
    "drug", "drugs", "pharmaceutical", "vaccine", "clinical", "patient",
    "diagnosis", "therapy", "doctor", "hospital", "surgery", "symptom",
    "symptoms", "infection", "cancer", "diabetes", "covid", "pandemic",
})


def is_medical_topic(topic_tags: list[str], body: str = "") -> bool:
    """Truthy iff topic_tags or first 1000 chars of body contain a medical
    keyword. Used by scrapers to set `meta["is_medical"]`.
    """
    haystack = (" ".join(topic_tags) + " " + (body[:1000] if body else "")).lower()
    if not haystack.strip():
        return False
    words = set(re.findall(r"[a-z]+", haystack))
    return bool(words & MEDICAL_KEYWORDS)


def score(raw: ScrapedRaw, meta: RawMetadata) -> float:
    if not meta.get("is_medical"):
        return NON_MEDICAL_SCORE
    body = meta.get("body_text") or ""
    if any(p.search(body) for p in DISCLAIMER_PATTERNS):
        return PRESENT_SCORE
    return ABSENT_SCORE
