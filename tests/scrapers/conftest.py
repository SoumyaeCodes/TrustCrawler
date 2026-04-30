"""Shared fixtures for scraper tests.

- `_fast_tagging` swaps `extract_tags` in every scraper module with a fast
  stub so KeyBERT's ~90 MB model load doesn't run on every test.
- `_no_real_sleep` no-ops `time.sleep` to keep PubMed-author rate-limiting
  from slowing the suite.
"""

from __future__ import annotations

import time

import pytest


def _fast_tag(title, body, top_n=8):
    return ["test", "tag"]


@pytest.fixture(autouse=True)
def _fast_tagging(monkeypatch):
    from src.scrapers import blog, pubmed, youtube
    for mod in (blog, pubmed, youtube):
        if hasattr(mod, "extract_tags"):
            monkeypatch.setattr(mod, "extract_tags", _fast_tag)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)
