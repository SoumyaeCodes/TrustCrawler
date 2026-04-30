import pytest

from src.errors import (
    MetadataMissingError,
    ScrapingError,
    TrustScoreError,
    WeightValidationError,
)


def test_scraping_error_holds_message_and_details():
    exc = ScrapingError("fetch failed", details={"url": "https://x"})
    assert str(exc) == "fetch failed"
    assert exc.details == {"url": "https://x"}


def test_default_details_is_empty_dict():
    assert ScrapingError("oops").details == {}
    assert TrustScoreError("oops").details == {}


def test_metadata_missing_is_scraping_error():
    assert issubclass(MetadataMissingError, ScrapingError)


def test_weight_validation_is_trust_score_error():
    assert issubclass(WeightValidationError, TrustScoreError)


def test_can_raise_and_catch_via_base():
    with pytest.raises(ScrapingError) as exc_info:
        raise MetadataMissingError("no author", details={"field": "author"})
    assert exc_info.value.details["field"] == "author"


def test_weight_validation_catches_via_trust_score_error():
    with pytest.raises(TrustScoreError):
        raise WeightValidationError("bad sum", details={"sum": 0.99})
