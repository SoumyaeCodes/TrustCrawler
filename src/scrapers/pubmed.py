"""PubMed scraper using Bio.Entrez. Per CLAUDE.md §5.3.

Caches:
- `output/.cache/citations_<pmid>.json` — citation count from ELink.
- `output/.cache/pubmed_authors.json`   — per-author prior-article count
  (keyed by `last_name|first_initial` per CLAUDE.md §5.3).

Both caches keep the trust-score module pure (it reads counts from
`meta`), and let repeated runs avoid hammering NCBI rate limits.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

from src.errors import MetadataMissingError, ScrapingError
from src.logging_config import get_logger
from src.schema import RawMetadata, ScrapedRaw
from src.utils.language import detect_language
from src.utils.tagging import extract_tags

log = get_logger(__name__)

_CACHE_DIR: Path = (
    Path(__file__).resolve().parents[2]
    / "Task 1 Multi-Source Scraper"
    / "output"
    / ".cache"
)
_AUTHORS_CACHE_FILE: Path = _CACHE_DIR / "pubmed_authors.json"

# Rate limit: 3 req/s without API key, 10 with. We add a small inter-call
# sleep before each ESearch/ELink — efetch only fires once per scrape.
_AUTHOR_SEARCH_SLEEP_S: float = 0.35


def _resolve_pmid(value: str) -> str:
    v = (value or "").strip()
    if v.isdigit():
        return v
    m = re.search(r"\d+", v)
    if m:
        return m.group(0)
    raise ScrapingError("could not resolve PMID", details={"input": value})


def _entrez_setup() -> None:
    from Bio import Entrez
    email = os.environ.get("PUBMED_EMAIL", "").strip()
    if not email:
        raise MetadataMissingError(
            "PUBMED_EMAIL env var is required by NCBI E-utilities",
            details={"field": "PUBMED_EMAIL"},
        )
    Entrez.email = email
    api_key = os.environ.get("PUBMED_API_KEY", "").strip()
    if api_key:
        Entrez.api_key = api_key


def _fetch_xml(pmid: str) -> dict:
    from Bio import Entrez
    _entrez_setup()
    try:
        handle = Entrez.efetch(db="pubmed", id=pmid, rettype="xml")
        records = Entrez.read(handle)
        handle.close()
    except Exception as e:  # noqa: BLE001
        raise ScrapingError(
            f"NCBI efetch failed for PMID {pmid}", details={"error": str(e)}
        ) from e
    if not records:
        raise ScrapingError(f"PMID {pmid} returned no records")
    arts = records.get("PubmedArticle", [])
    if not arts:
        raise ScrapingError(f"PMID {pmid} has no PubmedArticle entry")
    return arts[0]


def _stringy(v: Any) -> str:
    if isinstance(v, list):
        return " ".join(str(x) for x in v)
    return str(v) if v is not None else ""


def _extract_title(art: dict) -> str:
    article = art.get("MedlineCitation", {}).get("Article", {})
    return _stringy(article.get("ArticleTitle", "")).strip()


def _extract_authors(art: dict) -> tuple[list[str], list[str]]:
    article = art.get("MedlineCitation", {}).get("Article", {})
    authors: list[str] = []
    affiliations: list[str] = []
    for a in article.get("AuthorList", []):
        last = a.get("LastName", "")
        first = a.get("ForeName") or a.get("Initials") or ""
        if last or first:
            authors.append(f"{first} {last}".strip())
        for affil in a.get("AffiliationInfo", []) or []:
            text = affil.get("Affiliation")
            if text:
                affiliations.append(str(text))
    return authors, affiliations


def _extract_abstract(art: dict) -> tuple[str, list[str]]:
    article = art.get("MedlineCitation", {}).get("Article", {})
    sections = article.get("Abstract", {}).get("AbstractText", [])
    if not sections:
        return "", []
    chunks: list[str] = []
    body_parts: list[str] = []
    for sec in sections:
        text = str(sec).strip()
        if not text:
            continue
        label = ""
        if hasattr(sec, "attributes"):
            label = sec.attributes.get("Label", "") or ""
        piece = f"{label}: {text}" if label else text
        chunks.append(piece)
        body_parts.append(piece)
    if not chunks and not body_parts:
        return "", []
    return "\n\n".join(body_parts), chunks


_MONTH_MAP: dict[str, int] = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}


def _extract_date(art: dict) -> date | None:
    pub = (
        art.get("MedlineCitation", {})
        .get("Article", {})
        .get("Journal", {})
        .get("JournalIssue", {})
        .get("PubDate", {})
    )
    year = pub.get("Year")
    month = pub.get("Month") or "1"
    day = pub.get("Day") or "1"
    if not year:
        return None
    try:
        m_int = int(month) if str(month).isdigit() else _MONTH_MAP.get(str(month).lower()[:3], 1)
        return date(int(year), m_int, int(day))
    except (ValueError, TypeError):
        return None


def _fetch_citations(pmid: str) -> int:
    cache_file = _CACHE_DIR / f"citations_{pmid}.json"
    if cache_file.exists():
        try:
            return int(json.loads(cache_file.read_text())["count"])
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    from Bio import Entrez
    _entrez_setup()
    try:
        handle = Entrez.elink(dbfrom="pubmed", id=pmid, linkname="pubmed_pubmed_citedin")
        records = Entrez.read(handle)
        handle.close()
    except Exception as e:  # noqa: BLE001
        log.warning("ELink citation fetch failed for %s: %s", pmid, e)
        return 0
    count = 0
    for r in records:
        for ls in r.get("LinkSetDb", []):
            count += len(ls.get("Link", []))
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"count": count}))
    return count


def _author_cache_key(author: str) -> str:
    parts = author.strip().split()
    if not parts:
        return author.lower()
    last = parts[-1].lower()
    first_initial = parts[0][0].lower() if parts[0] else ""
    return f"{last}|{first_initial}"


def _load_authors_cache() -> dict[str, int]:
    if not _AUTHORS_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(_AUTHORS_CACHE_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def _save_authors_cache(cache: dict[str, int]) -> None:
    _AUTHORS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _AUTHORS_CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))


def _author_prior_count(author: str) -> int:
    if not author.strip():
        return 0
    key = _author_cache_key(author)
    cache = _load_authors_cache()
    if key in cache:
        return cache[key]
    from Bio import Entrez
    _entrez_setup()
    try:
        time.sleep(_AUTHOR_SEARCH_SLEEP_S)
        handle = Entrez.esearch(db="pubmed", term=f"{author}[Author]", retmax=0)
        result = Entrez.read(handle)
        handle.close()
        count = int(result.get("Count", 0))
    except Exception as e:  # noqa: BLE001
        log.warning("author prior count failed for %s: %s", author, e)
        count = 0
    cache[key] = count
    _save_authors_cache(cache)
    return count


def _affiliation_country(affiliations: list[str]) -> str | None:
    if not affiliations:
        return None
    try:
        import pycountry
    except ImportError:
        return None
    text = affiliations[0]
    candidates = [p.strip() for p in text.split(",") if p.strip()]
    for cand in reversed(candidates[:5]):
        try:
            results = pycountry.countries.search_fuzzy(cand)
        except LookupError:
            continue
        if len(results) == 1:
            return results[0].alpha_2
    return None


def scrape_pubmed(pmid_or_url: str, *, max_tags: int = 8) -> tuple[ScrapedRaw, RawMetadata]:
    pmid = _resolve_pmid(pmid_or_url)
    log.info("pubmed: scraping %s", pmid)
    art = _fetch_xml(pmid)
    title = _extract_title(art)
    authors, affiliations = _extract_authors(art)
    body, abstract_chunks = _extract_abstract(art)
    pub_date = _extract_date(art)

    if not body:
        body = title
        abstract_chunks = [title] if title else ["(no abstract available)"]

    language = detect_language(body) if body else "en"
    tags = extract_tags(title, body, top_n=max_tags)
    chunks = abstract_chunks if abstract_chunks else [body or title or "(empty)"]
    region = _affiliation_country(affiliations)

    citations = _fetch_citations(pmid)
    priors = [_author_prior_count(a) for a in authors] if authors else []

    if not authors:
        author_field: str | list[str] | None = None
    elif len(authors) == 1:
        author_field = authors[0]
    else:
        author_field = authors

    raw = ScrapedRaw(
        source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        source_type="pubmed",
        author=author_field,
        published_date=pub_date,
        language=language,
        region=region,
        topic_tags=tags,
        content_chunks=chunks,
    )
    meta: RawMetadata = {
        "citations": citations,
        "author_prior_articles": priors,
        "affiliations": affiliations,
        "outbound_links": [],
        "word_count": len(body.split()),
        "is_medical": True,
        "body_text": body,
    }
    return raw, meta
