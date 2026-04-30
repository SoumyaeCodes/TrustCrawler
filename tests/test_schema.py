from datetime import date

import pytest
from pydantic import ValidationError

from src.schema import ScrapedRaw, ScrapedSource


def _kwargs(**overrides):
    base = dict(
        source_url="https://example.com/article",
        source_type="blog",
        author="Jane Doe",
        published_date=date(2024, 1, 15),
        language="en",
        region="US",
        topic_tags=["llm", "evaluation"],
        content_chunks=["First paragraph.", "Second paragraph."],
    )
    base.update(overrides)
    return base


def test_scraped_raw_accepts_valid():
    raw = ScrapedRaw(**_kwargs())
    assert raw.source_type == "blog"
    assert raw.region == "US"
    assert raw.topic_tags == ["llm", "evaluation"]


def test_scraped_raw_allows_optional_none():
    raw = ScrapedRaw(**_kwargs(author=None, published_date=None, region=None))
    assert raw.author is None
    assert raw.published_date is None
    assert raw.region is None


def test_scraped_raw_accepts_author_list():
    raw = ScrapedRaw(**_kwargs(author=["A. One", "B. Two"]))
    assert raw.author == ["A. One", "B. Two"]


def test_scraped_raw_rejects_bad_source_type():
    with pytest.raises(ValidationError):
        ScrapedRaw(**_kwargs(source_type="tweet"))


def test_scraped_raw_rejects_empty_content_chunks():
    with pytest.raises(ValidationError):
        ScrapedRaw(**_kwargs(content_chunks=[]))


def test_scraped_raw_rejects_empty_string_chunk():
    with pytest.raises(ValidationError):
        ScrapedRaw(**_kwargs(content_chunks=["fine", ""]))


def test_language_pattern():
    with pytest.raises(ValidationError):
        ScrapedRaw(**_kwargs(language="EN"))
    with pytest.raises(ValidationError):
        ScrapedRaw(**_kwargs(language="english"))
    with pytest.raises(ValidationError):
        ScrapedRaw(**_kwargs(language=""))
    # 2 and 3-char lowercase OK
    assert ScrapedRaw(**_kwargs(language="en")).language == "en"
    assert ScrapedRaw(**_kwargs(language="eng")).language == "eng"


def test_region_pattern():
    with pytest.raises(ValidationError):
        ScrapedRaw(**_kwargs(region="us"))
    with pytest.raises(ValidationError):
        ScrapedRaw(**_kwargs(region="USA"))
    with pytest.raises(ValidationError):
        ScrapedRaw(**_kwargs(region="U1"))


def test_scraped_source_round_trips_through_json():
    src = ScrapedSource(**_kwargs(), trust_score=0.823)
    payload = src.model_dump_json()
    parsed = ScrapedSource.model_validate_json(payload)
    assert parsed == src


def test_scraped_source_rejects_out_of_range_trust():
    with pytest.raises(ValidationError):
        ScrapedSource(**_kwargs(), trust_score=1.1)
    with pytest.raises(ValidationError):
        ScrapedSource(**_kwargs(), trust_score=-0.01)


def test_scraped_source_extends_raw_fields():
    src = ScrapedSource(**_kwargs(), trust_score=0.5)
    assert "example.com" in str(src.source_url)
    assert src.trust_score == 0.5
    assert src.topic_tags == ["llm", "evaluation"]


def test_scraped_source_default_topic_tags_empty_list():
    src = ScrapedSource(**_kwargs(topic_tags=[]), trust_score=0.0)
    assert src.topic_tags == []
