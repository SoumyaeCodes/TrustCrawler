"""Topic tagging via KeyBERT (primary) with YAKE fallback.

KeyBERT loads `all-MiniLM-L6-v2` lazily and is cached at module level. If
the model can't be loaded (offline build, missing weights) we fall back to
YAKE so the pipeline keeps working — the assignment lists this fallback
explicitly in CLAUDE.md §5.4.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable

from src.logging_config import get_logger

_logger = get_logger(__name__)

_KEYBERT = None
_KEYBERT_LOAD_FAILED = False
_LOAD_LOCK = threading.Lock()

_STOPWORDS: frozenset[str] = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "he", "her", "his", "i", "in", "is", "it", "its", "of", "on", "or", "our", "she", "that", "the", "their", "them", "there", "they", "this", "to", "was", "we", "were", "what", "when", "where", "which", "who", "will", "with", "you", "your"]
)


def _maybe_load_keybert():
    global _KEYBERT, _KEYBERT_LOAD_FAILED
    if _KEYBERT is not None or _KEYBERT_LOAD_FAILED:
        return _KEYBERT
    with _LOAD_LOCK:
        if _KEYBERT is not None or _KEYBERT_LOAD_FAILED:
            return _KEYBERT
        try:
            from keybert import KeyBERT
            _KEYBERT = KeyBERT(model="all-MiniLM-L6-v2")
            _logger.info("keybert model loaded")
        except Exception as exc:  # noqa: BLE001 - fall back on any failure
            _KEYBERT_LOAD_FAILED = True
            _logger.warning("keybert unavailable (%s); using YAKE", exc)
    return _KEYBERT


def _is_stopword_only(phrase: str) -> bool:
    words = [w for w in phrase.split() if w]
    return all(w in _STOPWORDS for w in words) if words else True


def _normalize(tags: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        norm = " ".join(t.lower().split())
        if not norm or _is_stopword_only(norm) or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def _yake_tags(text: str, top_n: int) -> list[str]:
    import yake
    extractor = yake.KeywordExtractor(n=3, top=top_n)
    return [kw for kw, _score in extractor.extract_keywords(text)]


def extract_tags(title: str, body: str, top_n: int = 8) -> list[str]:
    text = f"{title.strip()}\n\n{body.strip()[:2000]}".strip()
    if not text:
        return []
    kb = _maybe_load_keybert()
    if kb is not None:
        try:
            raw = kb.extract_keywords(
                text,
                keyphrase_ngram_range=(1, 3),
                top_n=top_n,
                use_mmr=True,
                diversity=0.5,
            )
            tags = [kw for kw, _score in raw]
            _logger.debug("keybert produced %d tags", len(tags))
            return _normalize(tags)[:top_n]
        except Exception as exc:  # noqa: BLE001
            _logger.warning("keybert extract failed (%s); using YAKE", exc)
    tags = _yake_tags(text, top_n)
    _logger.debug("yake produced %d tags", len(tags))
    return _normalize(tags)[:top_n]
