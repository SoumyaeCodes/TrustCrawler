"""Shared fixtures for trust_score tests."""

from datetime import date

import pytest

from src.schema import ScrapedRaw

DEFAULT_KWARGS = dict(
    source_url="https://example.com/article",
    source_type="blog",
    author="Jane Doe",
    published_date=date(2024, 1, 15),
    language="en",
    region="US",
    topic_tags=["software"],
    content_chunks=["First.", "Second."],
)

TODAY = date(2026, 4, 29)


@pytest.fixture
def make_raw():
    def _make(**overrides) -> ScrapedRaw:
        kw = {**DEFAULT_KWARGS, **overrides}
        return ScrapedRaw(**kw)
    return _make


@pytest.fixture
def today() -> date:
    return TODAY
