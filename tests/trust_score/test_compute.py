"""End-to-end tests for compute_trust_score covering CLAUDE.md §6.3 + §6.4."""

from datetime import timedelta

import pytest

from src.errors import WeightValidationError
from src.schema import ScrapedSource
from src.trust_score.compute import compute_trust_score, compute_with_breakdown
from src.trust_score.weights import WEIGHTS


def test_returns_scraped_source(make_raw, today):
    raw = make_raw()
    src = compute_trust_score(raw, {}, today=today)
    assert isinstance(src, ScrapedSource)
    assert 0.0 <= src.trust_score <= 1.0


def test_score_rounded_to_three_decimals(make_raw, today):
    raw = make_raw()
    src = compute_trust_score(raw, {}, today=today)
    # Three-decimal round means the value times 1000 is a whole-ish int.
    assert abs(round(src.trust_score, 3) - src.trust_score) < 1e-12


def test_round_trips_through_json(make_raw, today):
    raw = make_raw()
    src = compute_trust_score(raw, {}, today=today)
    parsed = ScrapedSource.model_validate_json(src.model_dump_json())
    assert parsed == src


def test_high_trust_gov_medical_article(make_raw, today):
    raw = make_raw(
        source_url="https://nih.gov/treatment-guide",
        source_type="blog",
        author="Jane Researcher",
        published_date=today - timedelta(days=180),
        topic_tags=["clinical", "treatment"],
    )
    body = (
        "The following content is for informational purposes only. "
        "Please consult your doctor for medical advice."
    )
    src = compute_trust_score(
        raw,
        {
            "is_medical": True,
            "body_text": body,
            "outbound_links": ["https://nih.gov/x", "https://doi.org/1"],
            "author_bio_on_domain": True,
        },
        today=today,
    )
    assert src.trust_score >= 0.7  # nih.gov + medical + disclaimer + recent → high


def test_low_trust_spam_blog(make_raw, today):
    raw = make_raw(
        source_url="https://ehow.com/get-rich",
        source_type="blog",
        author="SEO Bot",
        published_date=today - timedelta(days=2000),
        topic_tags=["money"],
    )
    body = "click here " * 200  # heavy keyword stuffing
    src = compute_trust_score(
        raw,
        {"is_medical": False, "body_text": body},
        today=today,
    )
    assert src.trust_score < 0.3  # spam + stuffing + old → very low


def test_missing_author_yields_03_component(make_raw, today):
    raw = make_raw(author=None)
    b = compute_with_breakdown(raw, {}, today=today)
    assert b.components["author_credibility"] == 0.3


def test_missing_date_yields_03_recency(make_raw, today):
    raw = make_raw(published_date=None)
    b = compute_with_breakdown(raw, {}, today=today)
    assert b.components["recency"] == 0.3


def test_no_transcript_youtube_uses_meta_flag(make_raw, today):
    raw = make_raw(
        source_type="youtube",
        source_url="https://youtube.com/watch?v=x",
        author="Channel Owner",
    )
    src = compute_trust_score(
        raw,
        {"transcript_available": False, "subscriber_count": 50_000},
        today=today,
    )
    assert 0.0 <= src.trust_score <= 1.0  # doesn't crash


def test_multiple_authors_pubmed_uses_mean(make_raw, today):
    raw = make_raw(
        source_type="pubmed",
        source_url="https://pubmed.ncbi.nlm.nih.gov/9",
        author=["A. One", "B. Two", "C. Three"],
    )
    b = compute_with_breakdown(
        raw,
        {"author_prior_articles": [10, 1, 2], "citations": 50},
        today=today,
    )
    expected = (1.0 + 0.7 + 0.7) / 3
    assert abs(b.components["author_credibility"] - expected) < 1e-9


def test_non_english_no_score_penalty(make_raw, today):
    en = compute_trust_score(make_raw(language="en"), {}, today=today)
    es = compute_trust_score(make_raw(language="es"), {}, today=today)
    assert en.trust_score == es.trust_score


def test_future_date_recency_clamped(make_raw, today):
    raw = make_raw(published_date=today + timedelta(days=100))
    b = compute_with_breakdown(raw, {}, today=today)
    assert b.components["recency"] == 1.0


def test_keyword_stuffing_applies_post_aggregation(make_raw, today):
    raw = make_raw()
    body_clean = (
        "Reliable publishing requires transparent sourcing, careful editing, "
        "and accountable authorship. Newsrooms that maintain a stylebook tend "
        "to produce more consistent prose. Researchers who pre-register their "
        "hypotheses help reduce selective reporting. Editors who insist on "
        "verifiable citations build institutional trust over time. Software "
        "developers who write thorough tests catch regressions early. Designers "
        "who annotate their reasoning leave a clearer trail for the next person."
    )
    body_spam = "buy crypto " * 200 + "now and forever"
    no_stuff = compute_with_breakdown(raw, {"body_text": body_clean}, today=today)
    with_stuff = compute_with_breakdown(raw, {"body_text": body_spam}, today=today)
    # Components are identical; only the multiplier differs.
    assert no_stuff.components == with_stuff.components
    assert "keyword_stuffing" not in no_stuff.post_multipliers
    assert with_stuff.post_multipliers.get("keyword_stuffing") == 0.7
    assert with_stuff.final < no_stuff.final


def test_old_medical_applies_post_aggregation(make_raw, today):
    raw = make_raw(
        published_date=today - timedelta(days=4000),  # > 10 years
        topic_tags=["clinical"],
    )
    b_medical = compute_with_breakdown(raw, {"is_medical": True}, today=today)
    b_general = compute_with_breakdown(raw, {"is_medical": False}, today=today)
    assert b_medical.post_multipliers.get("old_medical") == 0.5
    assert "old_medical" not in b_general.post_multipliers


def test_application_order_components_first_then_multipliers(make_raw, today):
    """Verify the §6.4 step ordering: components compute fully (including
    fake-author 0.3× at component level) BEFORE post-aggregation
    multipliers fire.
    """
    raw = make_raw(
        source_url="https://ehow.com/article",  # spam → tier_4 in domain_authority
        author="Dr. MD PhD",  # fake → 0.3× on author_credibility
        published_date=today - timedelta(days=4000),
        topic_tags=["clinical"],
    )
    body = "buy stuff " * 200
    b = compute_with_breakdown(
        raw,
        {"is_medical": True, "body_text": body},
        today=today,
    )
    # Component-level fake-author multiplier already burned in.
    assert b.components["author_credibility"] < 0.6 * 0.5
    # Domain authority forced to tier_4.
    assert b.components["domain_authority"] == 0.1
    # Post-aggregation multipliers BOTH present.
    assert "keyword_stuffing" in b.post_multipliers
    assert "old_medical" in b.post_multipliers
    # Final score after weighted sum × 0.7 × 0.5.
    assert b.final < b.aggregated * 0.5  # both multipliers applied


def test_score_always_in_unit_interval(make_raw, today):
    # Stress test: extreme inputs shouldn't escape [0,1].
    cases = [
        make_raw(),
        make_raw(author=None, published_date=None),
        make_raw(source_url="https://nih.gov/x", source_type="pubmed"),
        make_raw(source_type="youtube", source_url="https://youtube.com/watch?v=x"),
    ]
    for raw in cases:
        for meta in [{}, {"citations": 99999, "subscriber_count": 99_999_999}]:
            src = compute_trust_score(raw, meta, today=today)
            assert 0.0 <= src.trust_score <= 1.0


def test_deterministic(make_raw, today):
    raw = make_raw()
    a = compute_trust_score(raw, {}, today=today)
    b = compute_trust_score(raw, {}, today=today)
    assert a == b


def test_invalid_weights_raises(make_raw, today):
    raw = make_raw()
    bad = {**WEIGHTS, "recency": WEIGHTS["recency"] + 0.5}  # sum != 1.0
    with pytest.raises(WeightValidationError):
        compute_trust_score(raw, {}, weights=bad, today=today)


def test_custom_weights_change_score(make_raw, today):
    raw = make_raw(
        source_url="https://nih.gov/x",
        author="Jane Doe",
        published_date=today,
    )
    default = compute_trust_score(raw, {}, today=today).trust_score
    # Heavy weight on domain_authority should push the score up since
    # the source is on nih.gov (tier 1 = 1.0).
    custom = {
        "author_credibility": 0.05,
        "citation_count": 0.05,
        "domain_authority": 0.80,
        "recency": 0.05,
        "medical_disclaimer_presence": 0.05,
    }
    weighted = compute_trust_score(raw, {}, weights=custom, today=today).trust_score
    assert weighted > default
