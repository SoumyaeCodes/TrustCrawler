import math

from src.trust_score.components import citation_count as cc


def test_pubmed_zero_citations(make_raw):
    raw = make_raw(source_type="pubmed", source_url="https://pubmed.ncbi.nlm.nih.gov/1")
    assert cc.score(raw, {"citations": 0}) == 0.0


def test_pubmed_log_scale(make_raw):
    raw = make_raw(source_type="pubmed", source_url="https://pubmed.ncbi.nlm.nih.gov/1")
    s = cc.score(raw, {"citations": 99})
    assert abs(s - math.log10(100) / 3) < 1e-9


def test_pubmed_caps_at_one(make_raw):
    raw = make_raw(source_type="pubmed", source_url="https://pubmed.ncbi.nlm.nih.gov/1")
    assert cc.score(raw, {"citations": 10_000}) == 1.0


def test_pubmed_missing_citations_treated_as_zero(make_raw):
    raw = make_raw(source_type="pubmed", source_url="https://pubmed.ncbi.nlm.nih.gov/1")
    assert cc.score(raw, {}) == 0.0


def test_blog_no_links(make_raw):
    raw = make_raw(source_type="blog")
    assert cc.score(raw, {"outbound_links": []}) == 0.0
    assert cc.score(raw, {}) == 0.0


def test_blog_authoritative_links_counted(make_raw):
    raw = make_raw(source_type="blog")
    links = [
        "https://nih.gov/study",
        "https://mit.edu/paper",
        "https://doi.org/10.1234",
        "https://pubmed.ncbi.nlm.nih.gov/123",
        "https://example.com/junk",
    ]
    s = cc.score(raw, {"outbound_links": links})
    assert s == 4 / 10


def test_blog_caps_at_one(make_raw):
    raw = make_raw(source_type="blog")
    links = ["https://nih.gov/" + str(i) for i in range(20)]
    assert cc.score(raw, {"outbound_links": links}) == 1.0


def test_youtube_uses_outbound_links(make_raw):
    raw = make_raw(source_type="youtube", source_url="https://youtube.com/watch?v=x")
    links = ["https://nih.gov/a", "https://nih.gov/b"]
    assert cc.score(raw, {"outbound_links": links}) == 2 / 10


def test_malformed_url_safe(make_raw):
    raw = make_raw(source_type="blog")
    assert cc.score(raw, {"outbound_links": ["not a url", "", None, 123]}) == 0.0
