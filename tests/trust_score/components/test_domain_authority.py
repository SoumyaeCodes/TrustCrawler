from src.trust_score import abuse_prevention as ap
from src.trust_score.components import domain_authority as da


def test_blog_tier_1_gov(make_raw):
    raw = make_raw(source_type="blog", source_url="https://nih.gov/article")
    assert da.score(raw, {}) == ap.SCORES["tier_1"]


def test_blog_tier_2_news(make_raw):
    raw = make_raw(source_type="blog", source_url="https://www.bbc.com/article")
    assert da.score(raw, {}) == ap.SCORES["tier_2"]


def test_blog_unknown_domain_tier_3(make_raw):
    raw = make_raw(source_type="blog", source_url="https://random-blog.example/post")
    assert da.score(raw, {}) == ap.SCORES["tier_3"]


def test_blog_spam_domain_forces_tier_4(make_raw):
    raw = make_raw(source_type="blog", source_url="https://ehow.com/article")
    assert da.score(raw, {}) == ap.SCORES["tier_4"]


def test_pubmed_treated_as_blog_for_domain(make_raw):
    raw = make_raw(
        source_type="pubmed",
        source_url="https://pubmed.ncbi.nlm.nih.gov/123",
    )
    assert da.score(raw, {}) == ap.SCORES["tier_1"]


def test_youtube_verified_large():
    from src.schema import ScrapedRaw
    raw = ScrapedRaw(
        source_url="https://youtube.com/watch?v=x",
        source_type="youtube",
        author="Channel",
        published_date=None,
        language="en",
        topic_tags=[],
        content_chunks=["x"],
    )
    assert da.score(raw, {"channel_verified": True, "subscriber_count": 500_000}) == da.YT_VERIFIED_LARGE_SCORE


def test_youtube_verified_small():
    from src.schema import ScrapedRaw
    raw = ScrapedRaw(
        source_url="https://youtube.com/watch?v=x",
        source_type="youtube",
        author="Channel",
        published_date=None,
        language="en",
        topic_tags=[],
        content_chunks=["x"],
    )
    assert da.score(raw, {"channel_verified": True, "subscriber_count": 1000}) == da.YT_VERIFIED_SMALL_SCORE


def test_youtube_unverified_large():
    from src.schema import ScrapedRaw
    raw = ScrapedRaw(
        source_url="https://youtube.com/watch?v=x",
        source_type="youtube",
        author="Channel",
        published_date=None,
        language="en",
        topic_tags=[],
        content_chunks=["x"],
    )
    assert da.score(raw, {"channel_verified": False, "subscriber_count": 5_000_000}) == da.YT_UNVERIFIED_LARGE_SCORE


def test_youtube_default():
    from src.schema import ScrapedRaw
    raw = ScrapedRaw(
        source_url="https://youtube.com/watch?v=x",
        source_type="youtube",
        author="Channel",
        published_date=None,
        language="en",
        topic_tags=[],
        content_chunks=["x"],
    )
    assert da.score(raw, {}) == da.YT_DEFAULT_SCORE
