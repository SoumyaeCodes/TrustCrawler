"""Abuse-prevention helpers: domain authority lookup, fake-author detector,
keyword-stuffing check, old-medical threshold, and a run-scoped duplicate
tracker.

Per CLAUDE.md §6.5: data files (`domain_tiers.json`, `spam_domains.txt`,
`known_orgs.txt`) are loaded ONCE at module import as immutable constants.
The runtime helper functions are pure and do no I/O. Tests can monkeypatch
the module-level constants.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from src.logging_config import get_logger

_logger = get_logger(__name__)

_DATA_DIR: Path = (
    Path(__file__).resolve().parents[2]
    / "Task 2 Trust Score System Design"
    / "data"
)


def _load_domain_tiers() -> dict:
    with (_DATA_DIR / "domain_tiers.json").open() as f:
        raw = json.load(f)
    # Strip documentation-only keys (per the data/README.md convention).
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _load_lines(name: str, *, lower: bool) -> frozenset[str]:
    text = (_DATA_DIR / name).read_text()
    out: set[str] = set()
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        out.add(s.lower() if lower else s)
    return frozenset(out)


_TIERS: dict = _load_domain_tiers()
SCORES: dict[str, float] = dict(_TIERS["scores"])
SUFFIX_TO_TIER: dict[str, str] = dict(_TIERS["suffix_to_tier"])
TIER_DOMAINS: dict[str, list[str]] = {k: list(v) for k, v in _TIERS["domains"].items()}
SPAM_DOMAINS: frozenset[str] = _load_lines("spam_domains.txt", lower=True)
KNOWN_ORGS_LOWER: frozenset[str] = _load_lines("known_orgs.txt", lower=True)

_logger.debug(
    "abuse_prevention loaded: %d spam, %d known orgs, tiers=%s",
    len(SPAM_DOMAINS), len(KNOWN_ORGS_LOWER), list(SCORES),
)


# ---------- Domain → score lookup -----------------------------------------

def _matches_host(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def domain_to_score(host: str | None) -> float:
    """Return the tier score for `host`. Spam wins, then explicit tiers,
    then suffix matches, then the tier_3 default.
    """
    if not host:
        return SCORES["tier_3"]
    h = host.lower()
    for spam in SPAM_DOMAINS:
        if _matches_host(h, spam):
            return SCORES["tier_4"]
    for tier_name, dom_list in TIER_DOMAINS.items():
        for d in dom_list:
            if _matches_host(h, d):
                return SCORES[tier_name]
    for suffix, tier_name in SUFFIX_TO_TIER.items():
        if h.endswith(suffix):
            return SCORES[tier_name]
    return SCORES["tier_3"]


def is_spam_host(host: str | None) -> bool:
    if not host:
        return False
    h = host.lower()
    return any(_matches_host(h, s) for s in SPAM_DOMAINS)


# ---------- Fake-author detector ------------------------------------------

_HONORIFICS_RE = re.compile(
    r"\b(?:Dr|Prof|Sir|Dame|Mr|Mrs|Ms|Mx|Lord|Hon)\b\.?",
    flags=re.IGNORECASE,
)
_POSTNOMINAL_RE = re.compile(
    r"\b(?:MD|PhD|DPhil|MSc|BSc|MBA|MPH|MA|BA|JD|EdD|DDS|DVM|RN|LLM|Esq)\b\.?",
    flags=re.IGNORECASE,
)
_ALL_CAPS_GIBBERISH = re.compile(r"^[A-Z\W\d]{8,}$")


def is_fake_author(author: str) -> bool:
    """Heuristic red-flag detector for an author string.

    Triggers a 0.3× component-level multiplier on author_credibility per
    CLAUDE.md §6.4. Designed to err toward false negatives — a real author
    should never be flagged.
    """
    name = (author or "").strip()
    if not name:
        return False
    name_lower = name.lower()
    if name_lower in KNOWN_ORGS_LOWER:
        return False
    if any(o in name_lower for o in KNOWN_ORGS_LOWER):
        return False
    if _ALL_CAPS_GIBBERISH.match(name):
        return True
    honor_count = (
        len(_HONORIFICS_RE.findall(name)) + len(_POSTNOMINAL_RE.findall(name))
    )
    if honor_count > 5:
        return True
    stripped = _POSTNOMINAL_RE.sub("", _HONORIFICS_RE.sub("", name))
    leftover = [
        t for t in re.split(r"[\s.,]+", stripped) if t and t not in {".", ","}
    ]
    return honor_count >= 2 and len(leftover) <= 1


# ---------- Keyword-density (post-aggregation 0.7×) -----------------------

KEYWORD_DENSITY_THRESHOLD: float = 0.04
KEYWORD_DENSITY_MIN_WORDS: int = 350

_WORD_RE = re.compile(r"[a-z]+")
_MEANINGLESS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "he", "her", "his", "i", "in", "is", "it", "its", "of", "on", "or", "our", "she", "that", "the", "their", "them", "there", "they", "this", "to", "was", "we", "were", "what", "when", "where", "which", "who", "will", "with", "you", "your"]
)


def has_keyword_stuffing(body: str) -> bool:
    if not body:
        return False
    words = _WORD_RE.findall(body.lower())
    total = len(words)
    if total < KEYWORD_DENSITY_MIN_WORDS:
        return False
    counts: dict[str, int] = {}
    for w in words:
        if w in _MEANINGLESS:
            continue
        counts[w] = counts.get(w, 0) + 1
    if not counts:
        return False
    return (max(counts.values()) / total) > KEYWORD_DENSITY_THRESHOLD


# ---------- Old-medical (scaled post-aggregation multiplier) --------------
#
# Replaces the original flat 0.5× cliff with two refinements:
#   (a) tier-1 sources (PubMed, .gov, .edu, nih.gov, who.int, nature.com, …)
#       are exempt — canonical references shouldn't be punished for age.
#   (b) for everyone else, the multiplier ramps gracefully from 1.0 at the
#       10-year threshold down to a 0.6 floor, instead of slamming to 0.5×
#       the moment age crosses 3650 days.
#
# Intent: discourage stale medical *advice* (old blogs/videos giving
# guidance that may have been superseded) without flattening trust on
# foundational research that simply happens to be old.

OLD_MEDICAL_AGE_DAYS: int = 3650
OLD_MEDICAL_MIN_MULTIPLIER: float = 0.6
OLD_MEDICAL_RAMP_DAYS: int = 12000


def old_medical_multiplier(age_days: int) -> float:
    """Scaled multiplier for old non-tier-1 medical content.

    At `age_days == OLD_MEDICAL_AGE_DAYS` the multiplier is 1.0 (no
    penalty at the threshold); it then decays linearly down to
    `OLD_MEDICAL_MIN_MULTIPLIER` over `OLD_MEDICAL_RAMP_DAYS`.
    """
    if age_days <= OLD_MEDICAL_AGE_DAYS:
        return 1.0
    decayed = 1.0 - (age_days - OLD_MEDICAL_AGE_DAYS) / OLD_MEDICAL_RAMP_DAYS
    return max(OLD_MEDICAL_MIN_MULTIPLIER, decayed)


def is_tier_1_source(source_type: str, host: str | None) -> bool:
    """Tier-1 exemption for the old-medical multiplier.

    PubMed is always tier-1 (NCBI). For blog/youtube, defer to the
    domain tier map: a host whose tier score equals SCORES["tier_1"] is
    exempt.
    """
    if source_type == "pubmed":
        return True
    if not host:
        return False
    return domain_to_score(host) >= SCORES["tier_1"]


# ---------- Run-scoped duplicate tracker ----------------------------------

class DuplicateTracker:
    """Tracks first-1000-char SHA-1 hashes seen in the current run."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_duplicate(self, body: str) -> bool:
        h = hashlib.sha1(body[:1000].encode("utf-8", errors="replace")).hexdigest()
        if h in self._seen:
            return True
        self._seen.add(h)
        return False
