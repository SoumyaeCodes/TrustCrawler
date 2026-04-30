"""Author credibility component (CLAUDE.md §6.1).

Branches by source_type:
- PubMed:  per-author score 1.0 if prior_articles ≥ 3 else 0.7; mean across authors.
- Blog:    0.6 baseline + 0.2 if `meta["author_bio_on_domain"]`.
- YouTube: 0.5 + 0.5 × min(subscriber_count / 1_000_000, 1.0).

Missing author → 0.3 (penalty, not zero — per the §6.3 edge case).
The 0.3× fake-author multiplier from §6.4 is applied at the component
level here, not after the weighted sum.
"""

from __future__ import annotations

from src.schema import RawMetadata, ScrapedRaw
from src.trust_score.abuse_prevention import is_fake_author

MISSING_AUTHOR_SCORE: float = 0.3
FAKE_AUTHOR_MULTIPLIER: float = 0.3
PUBMED_PRIOR_THRESHOLD: int = 3
PUBMED_BELOW_THRESHOLD: float = 0.7
PUBMED_AT_THRESHOLD: float = 1.0
BLOG_BASELINE: float = 0.6
BLOG_BIO_BONUS: float = 0.2
YOUTUBE_BASELINE: float = 0.5
YOUTUBE_SUBS_FOR_FULL: int = 1_000_000


def _author_list(author: str | list[str] | None) -> list[str]:
    if author is None:
        return []
    if isinstance(author, str):
        return [author] if author.strip() else []
    return [a for a in author if a and a.strip()]


def _pubmed_score(authors: list[str], meta: RawMetadata) -> float:
    priors = meta.get("author_prior_articles") or []
    if not priors:
        return PUBMED_BELOW_THRESHOLD
    per_author = [
        PUBMED_AT_THRESHOLD if p >= PUBMED_PRIOR_THRESHOLD else PUBMED_BELOW_THRESHOLD
        for p in priors
    ]
    return sum(per_author) / len(per_author)


def _blog_score(meta: RawMetadata) -> float:
    bonus = BLOG_BIO_BONUS if meta.get("author_bio_on_domain") else 0.0
    return min(BLOG_BASELINE + bonus, 1.0)


def _youtube_score(meta: RawMetadata) -> float:
    subs = meta.get("subscriber_count") or 0
    return YOUTUBE_BASELINE + 0.5 * min(subs / YOUTUBE_SUBS_FOR_FULL, 1.0)


def score(raw: ScrapedRaw, meta: RawMetadata) -> float:
    authors = _author_list(raw.author)
    if not authors:
        return MISSING_AUTHOR_SCORE

    if raw.source_type == "pubmed":
        base = _pubmed_score(authors, meta)
    elif raw.source_type == "blog":
        base = _blog_score(meta)
    else:  # youtube
        base = _youtube_score(meta)

    if any(is_fake_author(a) for a in authors):
        base *= FAKE_AUTHOR_MULTIPLIER

    return max(0.0, min(1.0, base))
