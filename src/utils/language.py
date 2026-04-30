"""Language detection wrapping `langdetect`.

`detect_langs(text)` returns a list of (lang, prob) ordered descending. We
accept the top result if its probability clears `MIN_CONFIDENCE` and the
text is at least `MIN_TEXT_LEN` chars. Otherwise we return `fallback` —
short/ambiguous strings deserve a configurable default rather than a guess.
"""

from __future__ import annotations

from langdetect import DetectorFactory, LangDetectException, detect_langs

from src.logging_config import get_logger

DetectorFactory.seed = 0

_logger = get_logger(__name__)

MIN_CONFIDENCE = 0.85
MIN_TEXT_LEN = 50


def detect_language(text: str, *, fallback: str = "en") -> str:
    if not text or len(text) < MIN_TEXT_LEN:
        _logger.debug("text too short for langdetect; returning %s", fallback)
        return fallback
    try:
        results = detect_langs(text)
    except LangDetectException as exc:
        _logger.debug("langdetect failed (%s); returning %s", exc, fallback)
        return fallback
    if not results:
        return fallback
    top = results[0]
    if top.prob < MIN_CONFIDENCE:
        _logger.debug(
            "langdetect top=%s prob=%.2f below %.2f; returning %s",
            top.lang, top.prob, MIN_CONFIDENCE, fallback,
        )
        return fallback
    return top.lang
