"""Blog scraper. Per CLAUDE.md §5.1.

Pipeline:
1. requests.get with custom UA, 10s timeout, follow redirects.
2. trafilatura.extract for main text + metadata; BS4 selector fallback.
3. Author priority: JSON-LD → <meta name="author"> → trafilatura.
4. Date priority:   JSON-LD datePublished → <meta property="article:published_time">
                    → <time datetime=...> → trafilatura.
5. Region from ccTLD only (CLAUDE.md §5.6); generic TLDs → None.
6. Outbound links list and is_medical flag go into RawMetadata for the
   trust-score module.

Returns tuple[ScrapedRaw, RawMetadata].
"""

from __future__ import annotations

import json as jsonlib
import os
import re
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup

from src.errors import ScrapingError
from src.logging_config import get_logger
from src.schema import RawMetadata, ScrapedRaw
from src.trust_score.components.medical_disclaimer import is_medical_topic
from src.utils.chunking import chunk_paragraphs
from src.utils.language import detect_language
from src.utils.tagging import extract_tags

log = get_logger(__name__)

DEFAULT_TIMEOUT_S: int = 10
DEFAULT_USER_AGENT: str = "DataScrapingAssignment/1.0 (+https://example.com)"

_FALLBACK_SELECTORS: tuple[str, ...] = (
    "article",
    "main",
    '[role="main"]',
    ".post-content",
    ".entry-content",
)
_MIN_FALLBACK_WORDS: int = 200

_CC_TO_REGION: dict[str, str] = {
    "uk": "GB", "de": "DE", "fr": "FR", "jp": "JP", "in": "IN",
    "cn": "CN", "br": "BR", "au": "AU", "ca": "CA", "mx": "MX",
    "es": "ES", "it": "IT", "nl": "NL", "ru": "RU", "se": "SE",
    "no": "NO", "ch": "CH", "kr": "KR", "pl": "PL", "tr": "TR",
}

# Hosts that fingerprint TLS / IP rep / cookies and 403 data-center IPs
# regardless of User-Agent. For these we transparently retry through the
# Wayback Machine — archive.org is permitted to serve these snapshots and
# the URL stays stable. CLAUDE.md §14 documents this as a known limit.
_ANTIBOT_HOSTS: frozenset[str] = frozenset({
    "medium.com",
    "x.com",
    "twitter.com",
    "linkedin.com",
})
_WAYBACK_PREFIX: str = "https://web.archive.org/web/2025/"


def _is_antibot_host(host: str | None) -> bool:
    h = (host or "").lower()
    return any(h == d or h.endswith("." + d) for d in _ANTIBOT_HOSTS)


def _http_get(url: str, ua: str):
    return requests.get(
        url,
        timeout=DEFAULT_TIMEOUT_S,
        headers={"User-Agent": ua},
        allow_redirects=True,
    )


def _fetch(url: str) -> str:
    ua = os.environ.get("USER_AGENT", DEFAULT_USER_AGENT)
    try:
        r = _http_get(url, ua)
    except requests.RequestException as e:
        raise ScrapingError(
            f"failed to fetch {url}", details={"url": url, "error": str(e)}
        ) from e
    if r.status_code == 200:
        return r.text

    host = (urlparse(url).hostname or "").lower()
    if r.status_code == 403 and _is_antibot_host(host):
        wb = f"{_WAYBACK_PREFIX}{url}"
        log.info("blog: %s 403'd; retrying via wayback %s", url, wb)
        try:
            r2 = _http_get(wb, ua)
        except requests.RequestException as e:
            raise ScrapingError(
                f"wayback fallback for {url} failed",
                details={"url": url, "wayback_url": wb, "error": str(e)},
            ) from e
        if r2.status_code == 200:
            return r2.text
        raise ScrapingError(
            f"non-200 from {url} (wayback fallback also failed)",
            details={
                "url": url, "status": r.status_code,
                "wayback_url": wb, "wayback_status": r2.status_code,
            },
        )

    raise ScrapingError(
        f"non-200 from {url}", details={"url": url, "status": r.status_code}
    )


def _trafilatura_extract(html: str) -> dict[str, Any]:
    try:
        raw = trafilatura.extract(
            html,
            include_comments=False,
            favor_recall=True,
            output_format="json",
            with_metadata=True,
        )
    except Exception as e:  # noqa: BLE001 - any extractor failure should fall back
        log.debug("trafilatura raised %s; falling through", e)
        return {}
    if not raw:
        return {}
    try:
        return jsonlib.loads(raw)
    except jsonlib.JSONDecodeError:
        return {}


def _bs4_fallback(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for sel in _FALLBACK_SELECTORS:
        node = soup.select_one(sel)
        if not node:
            continue
        text = node.get_text(separator="\n").strip()
        if len(re.findall(r"\S+", text)) >= _MIN_FALLBACK_WORDS:
            return text
    return ""


def _parse_jsonld(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = jsonlib.loads(script.string or "")
        except (jsonlib.JSONDecodeError, TypeError):
            continue
        if isinstance(data, list):
            out.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            out.append(data)
    return out


def _coerce_jsonld_author(value: Any) -> str | list[str] | None:
    if isinstance(value, dict):
        n = value.get("name")
        return n.strip() if isinstance(n, str) and n.strip() else None
    if isinstance(value, list) and value:
        names: list[str] = []
        for x in value:
            if isinstance(x, dict) and isinstance(x.get("name"), str):
                names.append(x["name"].strip())
            elif isinstance(x, str) and x.strip():
                names.append(x.strip())
        if not names:
            return None
        return names[0] if len(names) == 1 else names
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _extract_author(soup: BeautifulSoup, traf: dict[str, Any]) -> str | list[str] | None:
    for blob in _parse_jsonld(soup):
        a = blob.get("author")
        coerced = _coerce_jsonld_author(a)
        if coerced:
            return coerced
    m = soup.find("meta", attrs={"name": "author"})
    if m and m.get("content"):
        v = m["content"].strip()
        if v:
            return v
    if traf.get("author"):
        return str(traf["author"]).strip() or None
    return None


def _extract_date(soup: BeautifulSoup, traf: dict[str, Any]) -> date | None:
    for blob in _parse_jsonld(soup):
        d = blob.get("datePublished")
        if isinstance(d, str):
            parsed = _parse_iso_date_prefix(d)
            if parsed:
                return parsed
    m = soup.find("meta", attrs={"property": "article:published_time"})
    if m and m.get("content"):
        parsed = _parse_iso_date_prefix(m["content"])
        if parsed:
            return parsed
    t = soup.find("time")
    if t and t.get("datetime"):
        parsed = _parse_iso_date_prefix(t["datetime"])
        if parsed:
            return parsed
    if traf.get("date"):
        parsed = _parse_iso_date_prefix(str(traf["date"]))
        if parsed:
            return parsed
    return None


def _parse_iso_date_prefix(s: str) -> date | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _outbound_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    base_host = (urlparse(base_url).hostname or "").lower()
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = urljoin(base_url, href)
        host = (urlparse(absolute).hostname or "").lower()
        if host and host != base_host:
            out.append(absolute)
    return out


def _ccTLD_to_region(host: str) -> str | None:
    if not host:
        return None
    parts = host.lower().split(".")
    if len(parts) >= 2 and parts[-1] in _CC_TO_REGION:
        return _CC_TO_REGION[parts[-1]]
    return None


def _has_author_bio(soup: BeautifulSoup, base_url: str, author: str | list[str]) -> bool:
    base_host = (urlparse(base_url).hostname or "").lower()
    if not base_host:
        return False
    name = author if isinstance(author, str) else (author[0] if author else "")
    if not name:
        return False
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        return False
    for a in soup.find_all("a", href=True):
        absolute = urljoin(base_url, a["href"])
        if (urlparse(absolute).hostname or "").lower() != base_host:
            continue
        path = (urlparse(absolute).path or "").lower()
        if any(seg in path for seg in ("/author/", "/authors/", "/by/")) and slug in path:
            return True
    return False


def scrape_blog(
    url: str,
    *,
    max_tags: int = 8,
    chunk_min: int = 200,
    chunk_max: int = 500,
) -> tuple[ScrapedRaw, RawMetadata]:
    log.info("blog: scraping %s", url)
    html = _fetch(url)

    traf = _trafilatura_extract(html)
    body = (traf.get("text") or traf.get("raw_text") or "").strip()

    soup = BeautifulSoup(html, "lxml")
    if not body:
        body = _bs4_fallback(html)
    if not body:
        raise ScrapingError(
            "could not extract main text", details={"url": url}
        )

    title = (traf.get("title") or "").strip()
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    author = _extract_author(soup, traf)
    published = _extract_date(soup, traf)
    language = detect_language(body)
    region = _ccTLD_to_region(urlparse(url).hostname or "")
    tags = extract_tags(title, body, top_n=max_tags)
    chunks = chunk_paragraphs(body, target_min=chunk_min, target_max=chunk_max)
    if not chunks:
        chunks = [body[:500]]
    out_links = _outbound_links(soup, url)
    is_med = is_medical_topic(tags, body)

    raw = ScrapedRaw(
        source_url=url,
        source_type="blog",
        author=author,
        published_date=published,
        language=language,
        region=region,
        topic_tags=tags,
        content_chunks=chunks,
    )
    meta: RawMetadata = {
        "outbound_links": out_links,
        "word_count": len(body.split()),
        "is_medical": is_med,
        "body_text": body,
    }
    if author:
        meta["author_bio_on_domain"] = _has_author_bio(soup, url, author)
    return raw, meta
