import pytest

from src.errors import MetadataMissingError, ScrapingError
from src.scrapers import pubmed as pm_module


class _Handle:
    def close(self):
        pass


def _fake_entrez(monkeypatch, *, article=None, citation_count=0, prior_count=5):
    """Patch Bio.Entrez.efetch/elink/esearch + read with deterministic fakes."""
    from Bio import Entrez

    state = {"last": None}

    def efetch(**k):
        state["last"] = "efetch"
        return _Handle()

    def elink(**k):
        state["last"] = "elink"
        return _Handle()

    def esearch(**k):
        state["last"] = "esearch"
        return _Handle()

    def read(handle):
        if state["last"] == "efetch":
            return {"PubmedArticle": [article or {}]}
        if state["last"] == "elink":
            return [{"LinkSetDb": [{"Link": [{}] * citation_count}]}]
        if state["last"] == "esearch":
            return {"Count": str(prior_count)}
        return {}

    monkeypatch.setattr(Entrez, "efetch", efetch)
    monkeypatch.setattr(Entrez, "elink", elink)
    monkeypatch.setattr(Entrez, "esearch", esearch)
    monkeypatch.setattr(Entrez, "read", read)


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(pm_module, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(pm_module, "_AUTHORS_CACHE_FILE", tmp_path / "pubmed_authors.json")


@pytest.fixture(autouse=True)
def _set_pubmed_email(monkeypatch):
    monkeypatch.setenv("PUBMED_EMAIL", "test@example.com")


def _full_article(*, authors=None, abstract="A simple abstract about clinical trials and patients."):
    # Affiliation uses Japan rather than the USA so that pycountry's fuzzy
    # search returns a single match (the "drop ambiguous matches" rule in
    # CLAUDE.md §5.6 means USA-equivalent strings can return multiple
    # candidates and yield region=None).
    return {
        "MedlineCitation": {
            "Article": {
                "ArticleTitle": "Sample Clinical Trial Article",
                "AuthorList": authors if authors is not None else [
                    {
                        "LastName": "Doe",
                        "ForeName": "Jane",
                        "AffiliationInfo": [{"Affiliation": "Tokyo University, Tokyo, Japan"}],
                    },
                    {"LastName": "Smith", "ForeName": "John"},
                ],
                "Abstract": {"AbstractText": [abstract]},
                "Journal": {
                    "JournalIssue": {
                        "PubDate": {"Year": "2024", "Month": "1", "Day": "15"}
                    }
                },
            },
        },
    }


def test_pmid_resolves_from_url():
    assert pm_module._resolve_pmid("https://pubmed.ncbi.nlm.nih.gov/34813764/") == "34813764"
    assert pm_module._resolve_pmid("34813764") == "34813764"


def test_pmid_invalid_raises():
    with pytest.raises(ScrapingError):
        pm_module._resolve_pmid("nothing-here")


def test_pubmed_happy_path(monkeypatch, isolated_cache):
    _fake_entrez(monkeypatch, article=_full_article(), citation_count=10, prior_count=4)
    raw, meta = pm_module.scrape_pubmed("12345")

    assert raw.source_type == "pubmed"
    assert "pubmed.ncbi.nlm.nih.gov/12345" in str(raw.source_url)
    assert raw.author == ["Jane Doe", "John Smith"]
    assert str(raw.published_date) == "2024-01-15"
    assert meta["citations"] == 10
    assert meta["author_prior_articles"] == [4, 4]
    assert meta["is_medical"] is True
    assert raw.region == "JP"


def test_pubmed_single_author_returns_string(monkeypatch, isolated_cache):
    article = _full_article(authors=[{"LastName": "Solo", "ForeName": "A.", "AffiliationInfo": []}])
    _fake_entrez(monkeypatch, article=article)
    raw, _ = pm_module.scrape_pubmed("12345")
    assert raw.author == "A. Solo"


def test_pubmed_no_authors(monkeypatch, isolated_cache):
    article = _full_article(authors=[])
    _fake_entrez(monkeypatch, article=article)
    raw, meta = pm_module.scrape_pubmed("12345")
    assert raw.author is None
    assert meta["author_prior_articles"] == []


def test_pubmed_missing_date(monkeypatch, isolated_cache):
    article = _full_article()
    article["MedlineCitation"]["Article"]["Journal"]["JournalIssue"]["PubDate"] = {}
    _fake_entrez(monkeypatch, article=article)
    raw, _ = pm_module.scrape_pubmed("12345")
    assert raw.published_date is None


def test_pubmed_no_abstract_falls_back_to_title(monkeypatch, isolated_cache):
    article = _full_article(abstract="")
    article["MedlineCitation"]["Article"]["Abstract"] = {"AbstractText": []}
    _fake_entrez(monkeypatch, article=article)
    raw, _ = pm_module.scrape_pubmed("12345")
    assert raw.content_chunks
    assert "Sample Clinical Trial Article" in raw.content_chunks[0]


def test_pubmed_missing_affiliation(monkeypatch, isolated_cache):
    # Plan §9.1 / CLAUDE.md §5.6 — when authors carry no AffiliationInfo,
    # region must fall back to None (not crash, not guess) and
    # meta["affiliations"] must be an empty list rather than missing.
    article = _full_article(
        authors=[
            {"LastName": "Doe", "ForeName": "Jane"},  # no AffiliationInfo
            {"LastName": "Smith", "ForeName": "John", "AffiliationInfo": []},  # empty
        ]
    )
    _fake_entrez(monkeypatch, article=article)
    raw, meta = pm_module.scrape_pubmed("12345")
    assert raw.region is None
    assert meta["affiliations"] == []


def test_pubmed_missing_email_raises(monkeypatch, isolated_cache):
    monkeypatch.delenv("PUBMED_EMAIL", raising=False)
    _fake_entrez(monkeypatch, article=_full_article())
    with pytest.raises(MetadataMissingError):
        pm_module.scrape_pubmed("12345")


def test_pubmed_citations_cached(monkeypatch, isolated_cache, tmp_path):
    _fake_entrez(monkeypatch, article=_full_article(), citation_count=42, prior_count=2)
    pm_module.scrape_pubmed("99999")
    # Second scrape: ELink should not be called again because the cache is populated.
    cache_file = tmp_path / "citations_99999.json"
    assert cache_file.exists()


def test_pubmed_authors_cached(monkeypatch, isolated_cache, tmp_path):
    _fake_entrez(monkeypatch, article=_full_article(), citation_count=1, prior_count=7)
    pm_module.scrape_pubmed("12345")
    cache_file = tmp_path / "pubmed_authors.json"
    assert cache_file.exists()
    import json
    cache = json.loads(cache_file.read_text())
    assert "doe|j" in cache
    assert cache["doe|j"] == 7
