"""FastAPI integration tests.

The shims under `Task 1 Multi-Source Scraper/*/api.py` use attribute-style
calls (`blog_module.scrape_blog(...)`) so monkeypatching the source module
attribute (`src.scrapers.blog.scrape_blog`) propagates into the shim.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi.testclient import TestClient

from src.api import app
from src.errors import MetadataMissingError, ScrapingError, TrustScoreError
from src.schema import ScrapedRaw
from src.trust_score.weights import WEIGHTS

client = TestClient(app)


def _fake_raw(source_type: str = "blog") -> ScrapedRaw:
    return ScrapedRaw(
        source_url="https://example.com/article",
        source_type=source_type,
        author="Jane Doe",
        published_date=date(2024, 1, 15),
        language="en",
        region="US",
        topic_tags=["test"],
        content_chunks=["A chunk."],
    )


def _fake_meta() -> dict[str, Any]:
    return {
        "outbound_links": [],
        "is_medical": False,
        "body_text": "Some body text here for the trust score.",
    }


# ---------- App-level structure ----------

def test_app_registers_all_three_routes():
    paths = [r.path for r in app.routes]
    assert "/scrape/blog" in paths
    assert "/scrape/youtube" in paths
    assert "/scrape/pubmed" in paths
    assert "/health" in paths


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert sorted(body["routes"]) == ["blog", "pubmed", "youtube"]


def test_openapi_docs_available():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert "/scrape/blog" in spec["paths"]
    assert "/scrape/youtube" in spec["paths"]
    assert "/scrape/pubmed" in spec["paths"]


# ---------- /scrape/blog ----------

def test_scrape_blog_happy(monkeypatch):
    def fake_scrape(url, *, max_tags=8, chunk_min=200, chunk_max=500):
        assert url == "https://example.com"
        assert max_tags == 5
        assert chunk_min == 100
        assert chunk_max == 400
        return _fake_raw("blog"), _fake_meta()

    monkeypatch.setattr("src.scrapers.blog.scrape_blog", fake_scrape)

    response = client.post(
        "/scrape/blog",
        json={
            "url": "https://example.com",
            "max_tags": 5,
            "chunk_min": 100,
            "chunk_max": 400,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "blog"
    assert body["author"] == "Jane Doe"
    assert 0.0 <= body["trust_score"] <= 1.0


def test_scrape_blog_missing_url_returns_422():
    response = client.post("/scrape/blog", json={})
    assert response.status_code == 422  # FastAPI/Pydantic body-validation error


def test_scrape_blog_max_tags_out_of_range_returns_422():
    response = client.post(
        "/scrape/blog",
        json={"url": "https://example.com", "max_tags": 100},
    )
    assert response.status_code == 422


def test_scrape_blog_propagates_scraping_error(monkeypatch):
    def fake_scrape(*a, **kw):
        raise ScrapingError("404 from upstream", details={"url": a[0], "status": 404})

    monkeypatch.setattr("src.scrapers.blog.scrape_blog", fake_scrape)

    response = client.post("/scrape/blog", json={"url": "https://example.com"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "scraping_failed"
    assert body["details"]["status"] == 404


def test_scrape_blog_invalid_weights_returns_400(monkeypatch):
    bad = {**WEIGHTS, "recency": WEIGHTS["recency"] + 0.5}  # sum off
    response = client.post(
        "/scrape/blog",
        json={"url": "https://example.com", "weights": bad},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "invalid_weights"
    assert "sum" in body["details"]


def test_scrape_blog_custom_weights_pass_validation(monkeypatch):
    def fake_scrape(*a, **kw):
        return _fake_raw("blog"), _fake_meta()
    monkeypatch.setattr("src.scrapers.blog.scrape_blog", fake_scrape)

    custom = {
        "author_credibility": 0.10,
        "citation_count": 0.10,
        "domain_authority": 0.60,
        "recency": 0.10,
        "medical_disclaimer_presence": 0.10,
    }
    response = client.post(
        "/scrape/blog",
        json={"url": "https://example.com", "weights": custom},
    )
    assert response.status_code == 200


# ---------- /scrape/youtube ----------

def test_scrape_youtube_happy(monkeypatch):
    def fake_scrape(url_or_id, *, language_hint=None, max_tags=8):
        assert url_or_id == "aircAruvnKk"
        return _fake_raw("youtube"), {"transcript_available": True, "subscriber_count": 100, "channel_verified": False}

    monkeypatch.setattr("src.scrapers.youtube.scrape_youtube", fake_scrape)

    response = client.post(
        "/scrape/youtube",
        json={"url_or_id": "aircAruvnKk"},
    )
    assert response.status_code == 200
    assert response.json()["source_type"] == "youtube"


def test_scrape_youtube_propagates_scraping_error(monkeypatch):
    def fake_scrape(*a, **kw):
        raise ScrapingError("yt-dlp failed", details={"error": "test"})
    monkeypatch.setattr("src.scrapers.youtube.scrape_youtube", fake_scrape)

    response = client.post("/scrape/youtube", json={"url_or_id": "aircAruvnKk"})
    assert response.status_code == 422
    assert response.json()["error"] == "scraping_failed"


# ---------- /scrape/pubmed ----------

def test_scrape_pubmed_happy(monkeypatch):
    def fake_scrape(pmid_or_url, *, max_tags=8):
        assert pmid_or_url == "12345"
        raw = ScrapedRaw(
            source_url="https://pubmed.ncbi.nlm.nih.gov/12345/",
            source_type="pubmed",
            author=["A One", "B Two"],
            published_date=date(2024, 1, 15),
            language="en",
            region=None,
            topic_tags=["clinical"],
            content_chunks=["Abstract."],
        )
        meta = {"citations": 10, "is_medical": True, "body_text": "abstract"}
        return raw, meta

    monkeypatch.setattr("src.scrapers.pubmed.scrape_pubmed", fake_scrape)

    response = client.post("/scrape/pubmed", json={"pmid_or_url": "12345"})
    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "pubmed"
    assert body["author"] == ["A One", "B Two"]


def test_scrape_pubmed_metadata_missing_returns_422(monkeypatch):
    def fake_scrape(*a, **kw):
        raise MetadataMissingError(
            "PUBMED_EMAIL env var is required",
            details={"field": "PUBMED_EMAIL"},
        )
    monkeypatch.setattr("src.scrapers.pubmed.scrape_pubmed", fake_scrape)

    response = client.post("/scrape/pubmed", json={"pmid_or_url": "12345"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "metadata_missing"
    assert body["details"]["field"] == "PUBMED_EMAIL"


def test_scrape_pubmed_trust_score_error_returns_500(monkeypatch):
    """A non-WeightValidationError TrustScoreError → 500 with sanitized body."""
    def fake_scrape(*a, **kw):
        return _fake_raw("pubmed"), _fake_meta()
    monkeypatch.setattr("src.scrapers.pubmed.scrape_pubmed", fake_scrape)

    def boom(*a, **kw):
        raise TrustScoreError("computation crashed")
    monkeypatch.setattr("src.trust_score.compute.compute_trust_score", boom)

    response = client.post("/scrape/pubmed", json={"pmid_or_url": "12345"})
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "trust_score_failed"
    # Error message is sanitized — should not echo the internal exception text.
    assert "computation crashed" not in body["message"]


# ---------- CORS ----------

def test_cors_allows_streamlit_origin():
    response = client.options(
        "/scrape/blog",
        headers={
            "Origin": "http://localhost:8501",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    # FastAPI/CORS middleware returns 200 for valid preflight
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:8501"
