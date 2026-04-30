"""Citation count component (CLAUDE.md §6.1).

PubMed:        min(log10(1 + citations) / 3, 1.0).
Blog/YouTube:  outbound links to .gov/.edu/PubMed/DOI domains, normalized
               via min(count / 10, 1.0). Reads `meta["outbound_links"]`.
"""

from __future__ import annotations

import math
from urllib.parse import urlparse

from src.schema import RawMetadata, ScrapedRaw

PUBMED_LOG_DIVISOR: float = 3.0
LINKS_FOR_FULL: int = 10
AUTHORITATIVE_SUFFIXES: tuple[str, ...] = (".gov", ".edu")
AUTHORITATIVE_HOSTS: frozenset[str] = frozenset({
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "doi.org",
})


def _is_authoritative_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except (ValueError, AttributeError):
        return False
    if not host:
        return False
    if host in AUTHORITATIVE_HOSTS:
        return True
    return any(host.endswith(s) for s in AUTHORITATIVE_SUFFIXES)


def score(raw: ScrapedRaw, meta: RawMetadata) -> float:
    if raw.source_type == "pubmed":
        n = max(0, int(meta.get("citations") or 0))
        return min(math.log10(1 + n) / PUBMED_LOG_DIVISOR, 1.0)
    links = meta.get("outbound_links") or []
    count = sum(1 for u in links if isinstance(u, str) and _is_authoritative_url(u))
    return min(count / LINKS_FOR_FULL, 1.0)
