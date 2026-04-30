from src.trust_score.components import author_credibility as ac


def test_missing_author_returns_03(make_raw):
    raw = make_raw(author=None)
    assert ac.score(raw, {}) == ac.MISSING_AUTHOR_SCORE


def test_empty_author_string_returns_03(make_raw):
    raw = make_raw(author="   ")
    assert ac.score(raw, {}) == ac.MISSING_AUTHOR_SCORE


def test_empty_author_list_returns_03(make_raw):
    raw = make_raw(author=[])
    assert ac.score(raw, {}) == ac.MISSING_AUTHOR_SCORE


def test_blog_baseline(make_raw):
    raw = make_raw(source_type="blog", author="Jane Doe")
    assert ac.score(raw, {}) == ac.BLOG_BASELINE


def test_blog_with_author_bio_bonus(make_raw):
    raw = make_raw(source_type="blog", author="Jane Doe")
    assert ac.score(raw, {"author_bio_on_domain": True}) == ac.BLOG_BASELINE + ac.BLOG_BIO_BONUS


def test_youtube_low_subs(make_raw):
    raw = make_raw(source_type="youtube", source_url="https://youtube.com/watch?v=x")
    s = ac.score(raw, {"subscriber_count": 100})
    assert abs(s - 0.50005) < 1e-3


def test_youtube_million_subs_full(make_raw):
    raw = make_raw(source_type="youtube", source_url="https://youtube.com/watch?v=x")
    assert ac.score(raw, {"subscriber_count": 1_000_000}) == 1.0
    assert ac.score(raw, {"subscriber_count": 5_000_000}) == 1.0  # capped


def test_youtube_no_subs(make_raw):
    raw = make_raw(source_type="youtube", source_url="https://youtube.com/watch?v=x")
    assert ac.score(raw, {}) == ac.YOUTUBE_BASELINE


def test_pubmed_no_priors_data(make_raw):
    raw = make_raw(source_type="pubmed", source_url="https://pubmed.ncbi.nlm.nih.gov/123")
    assert ac.score(raw, {}) == ac.PUBMED_BELOW_THRESHOLD


def test_pubmed_all_authors_above_threshold(make_raw):
    raw = make_raw(
        source_type="pubmed",
        source_url="https://pubmed.ncbi.nlm.nih.gov/123",
        author=["A. One", "B. Two"],
    )
    assert ac.score(raw, {"author_prior_articles": [10, 5]}) == 1.0


def test_pubmed_mixed_priors_arithmetic_mean(make_raw):
    raw = make_raw(
        source_type="pubmed",
        source_url="https://pubmed.ncbi.nlm.nih.gov/123",
        author=["A", "B", "C"],
    )
    # one above (1.0), two below (0.7) → mean = (1 + 0.7 + 0.7)/3 ≈ 0.8
    s = ac.score(raw, {"author_prior_articles": [12, 1, 2]})
    assert abs(s - (1.0 + 0.7 + 0.7) / 3) < 1e-9


def test_fake_author_multiplier_applied(make_raw):
    raw = make_raw(source_type="blog", author="Dr. MD PhD")  # fake-flagged
    s = ac.score(raw, {})
    assert s == ac.BLOG_BASELINE * ac.FAKE_AUTHOR_MULTIPLIER


def test_fake_author_one_of_many_triggers(make_raw):
    raw = make_raw(source_type="blog", author=["Real Name", "Dr. MD PhD"])
    s = ac.score(raw, {})
    # Multi-author blog uses the source-level baseline, then fake mult on any author.
    assert s == ac.BLOG_BASELINE * ac.FAKE_AUTHOR_MULTIPLIER


def test_score_clamped_to_unit_interval(make_raw):
    # YouTube can otherwise yield 1.0; with a fake-author multiplier it shouldn't escape range.
    raw = make_raw(
        source_type="youtube",
        source_url="https://youtube.com/watch?v=x",
        author="Dr. MD PhD",
    )
    s = ac.score(raw, {"subscriber_count": 10_000_000})
    assert 0.0 <= s <= 1.0
