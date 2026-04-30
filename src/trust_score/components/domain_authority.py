"""Domain authority component (CLAUDE.md §6.1).

Blog/PubMed: domain_to_score from abuse_prevention (driven by
domain_tiers.json + spam_domains.txt).

YouTube: derived from channel verification + subscriber count, since
"domain" doesn't apply directly. Verified channels with ≥100K subs get
1.0; verified small channels get 0.7; unverified large channels (≥1M)
get 0.7; everyone else 0.4.
"""

from __future__ import annotations

from urllib.parse import urlparse

from src.schema import RawMetadata, ScrapedRaw
from src.trust_score.abuse_prevention import domain_to_score

YT_VERIFIED_LARGE_SCORE: float = 1.0
YT_VERIFIED_SMALL_SCORE: float = 0.7
YT_UNVERIFIED_LARGE_SCORE: float = 0.7
YT_DEFAULT_SCORE: float = 0.4
YT_LARGE_SUBS: int = 1_000_000
YT_VERIFIED_LARGE_SUBS: int = 100_000


def _youtube_score(meta: RawMetadata) -> float:
    verified = bool(meta.get("channel_verified"))
    subs = meta.get("subscriber_count") or 0
    if verified and subs >= YT_VERIFIED_LARGE_SUBS:
        return YT_VERIFIED_LARGE_SCORE
    if verified:
        return YT_VERIFIED_SMALL_SCORE
    if subs >= YT_LARGE_SUBS:
        return YT_UNVERIFIED_LARGE_SCORE
    return YT_DEFAULT_SCORE


def score(raw: ScrapedRaw, meta: RawMetadata) -> float:
    if raw.source_type == "youtube":
        return _youtube_score(meta)
    host = urlparse(str(raw.source_url)).hostname
    return domain_to_score(host)
