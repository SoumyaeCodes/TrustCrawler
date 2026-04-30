from unittest.mock import MagicMock

import pytest

from src.errors import ScrapingError
from src.scrapers import blog as blog_module
from src.scrapers.blog import scrape_blog

HAPPY_HTML = """<!DOCTYPE html>
<html>
<head>
<title>Sample Article</title>
<meta name="author" content="Jane Doe">
<meta property="article:published_time" content="2024-01-15T10:00:00Z">
<script type="application/ld+json">
{"@type":"Article","author":{"@type":"Person","name":"Jane Doe"},"datePublished":"2024-01-15"}
</script>
</head>
<body>
<article>
<h1>Sample Article</h1>
<p>This is a sample article with substantial content. It discusses
artificial intelligence and machine learning, and references several
authoritative sources for further reading. The content is original and
well-researched.</p>
<p>Additional paragraph with more substantive content to ensure the
article meets the minimum length thresholds for extraction. Editorial
standards remain a priority. Authors who name their sources earn reader
confidence over time.</p>
<p>A third paragraph adds more diversity to the prose. Readers who care
about provenance benefit from clearly attributed claims. Researchers
appreciate when bibliographies link back to primary sources.</p>
<p>Final paragraph wraps up the discussion with a clear conclusion.
We have covered the main topics and provided context. The discussion
referenced government and academic sources for authority.</p>
<a href="https://nih.gov/study">authoritative link</a>
<a href="/internal-link">internal</a>
<a href="https://otherdomain.example/external">external</a>
</article>
</body>
</html>"""


def _mock_get(monkeypatch, html: str, status: int = 200):
    response = MagicMock()
    response.text = html
    response.status_code = status
    monkeypatch.setattr(blog_module.requests, "get", lambda *a, **k: response)


def test_blog_happy_path(monkeypatch):
    _mock_get(monkeypatch, HAPPY_HTML)
    raw, meta = scrape_blog("https://example.com/article")

    assert raw.source_type == "blog"
    assert "example.com" in str(raw.source_url)
    assert raw.author == "Jane Doe"
    assert str(raw.published_date) == "2024-01-15"
    assert raw.language == "en"
    assert raw.region is None  # generic .com TLD
    assert raw.topic_tags == ["test", "tag"]  # stubbed
    assert raw.content_chunks
    assert all(c.strip() for c in raw.content_chunks)

    assert meta["word_count"] > 50
    assert meta["is_medical"] is False  # stubbed tags don't include medical kw
    assert meta["body_text"]


def test_blog_extracts_outbound_links(monkeypatch):
    _mock_get(monkeypatch, HAPPY_HTML)
    _, meta = scrape_blog("https://example.com/article")
    links = meta["outbound_links"]
    assert any("nih.gov" in link for link in links)
    assert any("otherdomain.example" in link for link in links)
    # Internal link must NOT appear in outbound_links.
    assert not any(link.endswith("/internal-link") for link in links)


def test_blog_404_raises(monkeypatch):
    _mock_get(monkeypatch, "", status=404)
    with pytest.raises(ScrapingError) as exc:
        scrape_blog("https://example.com/missing")
    assert exc.value.details["status"] == 404


def test_blog_request_failure_raises(monkeypatch):
    import requests
    def boom(*a, **k):
        raise requests.RequestException("connection refused")
    monkeypatch.setattr(blog_module.requests, "get", boom)
    with pytest.raises(ScrapingError):
        scrape_blog("https://example.com/down")


def test_blog_missing_metadata(monkeypatch):
    minimal = (
        "<html><body><article>"
        + "<p>This is content. It contains many words to satisfy any "
        "fallback selectors. The article has no author and no date "
        "metadata anywhere on the page. Trafilatura should still find "
        "the body text from the article tag.</p>" * 6
        + "</article></body></html>"
    )
    _mock_get(monkeypatch, minimal)
    raw, _ = scrape_blog("https://example.com/no-meta")
    assert raw.author is None
    assert raw.published_date is None


def test_blog_non_english(monkeypatch):
    spanish = (
        "<html><body><article>"
        + (
            "<p>Este es un artículo escrito enteramente en español, con "
            "contenido suficiente para que la detección automática de "
            "idioma funcione correctamente. La biblioteca langdetect "
            "necesita varias frases largas para identificar el idioma con "
            "alta confianza. Esperamos que esta prueba sea reproducible.</p>"
        ) * 5
        + "</article></body></html>"
    )
    _mock_get(monkeypatch, spanish)
    raw, _ = scrape_blog("https://example.com/spanish")
    assert raw.language == "es"


def test_blog_uk_tld_yields_region(monkeypatch):
    minimal = (
        "<html><body><article>"
        + "<p>Some long English content to satisfy the fallback selector. "
        "We are testing region detection from country-code TLDs.</p>" * 6
        + "</article></body></html>"
    )
    _mock_get(monkeypatch, minimal)
    raw, _ = scrape_blog("https://example.co.uk/article")
    assert raw.region == "GB"


def test_blog_no_main_content_raises(monkeypatch):
    # Truly empty body so neither trafilatura nor the BS4 fallback finds text.
    _mock_get(monkeypatch, "<html><head></head><body></body></html>")
    with pytest.raises(ScrapingError):
        scrape_blog("https://example.com/empty")
