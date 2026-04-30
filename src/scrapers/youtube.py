"""YouTube scraper. Per CLAUDE.md §5.2.

- yt-dlp for metadata (title, channel, upload_date, description, language,
  channel_follower_count, channel_is_verified).
- youtube-transcript-api 1.x — instance-based: `YouTubeTranscriptApi().fetch(...)`.
- Cascading language fallback: hint → "en" → auto-generated.
- If no transcript exists, set `meta["transcript_available"]=False` and
  fall back to the description for `content_chunks`.
- Transcript chunks: 250-token windows with 30-token overlap.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from src.errors import ScrapingError
from src.logging_config import get_logger
from src.schema import RawMetadata, ScrapedRaw
from src.trust_score.components.medical_disclaimer import is_medical_topic
from src.utils.chunking import chunk_transcript
from src.utils.language import detect_language
from src.utils.tagging import extract_tags

log = get_logger(__name__)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[?&]v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/embed/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})"),
)


def _resolve_video_id(value: str) -> str:
    v = (value or "").strip()
    if _VIDEO_ID_RE.match(v):
        return v
    for pat in _URL_ID_PATTERNS:
        m = pat.search(v)
        if m:
            return m.group(1)
    raise ScrapingError("could not resolve YouTube video id", details={"input": value})


def _fetch_metadata(video_id: str) -> dict[str, Any]:
    try:
        import yt_dlp
    except ImportError as e:
        raise ScrapingError("yt_dlp not available", details={"error": str(e)}) from e
    opts = {
        "skip_download": True,
        "extract_flat": False,
        "quiet": True,
        "noplaylist": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False
            )
    except Exception as e:  # noqa: BLE001 - yt-dlp throws many flavors
        raise ScrapingError(
            f"yt-dlp failed for {video_id}", details={"error": str(e)}
        ) from e
    return info or {}


def _fetch_transcript(
    video_id: str, language_hint: str | None
) -> tuple[list[dict[str, str]], bool]:
    """Return (segments, transcript_available). segments is a list of
    {"text": ...} dicts; empty when transcript_available is False.
    """
    try:
        from youtube_transcript_api import (
            NoTranscriptFound,
            TranscriptsDisabled,
            YouTubeTranscriptApi,
        )
    except ImportError as e:
        raise ScrapingError(
            "youtube_transcript_api not available", details={"error": str(e)}
        ) from e
    api = YouTubeTranscriptApi()
    languages: list[str] = []
    if language_hint:
        languages.append(language_hint)
    if "en" not in languages:
        languages.append("en")
    try:
        fetched = api.fetch(video_id, languages=languages)
    except (TranscriptsDisabled, NoTranscriptFound):
        return [], False
    except Exception as e:  # noqa: BLE001 - fall back to description on any failure
        log.warning("transcript fetch failed for %s: %s", video_id, e)
        return [], False
    segments: list[dict[str, str]] = []
    for snip in fetched:
        text = getattr(snip, "text", None) or (snip.get("text") if isinstance(snip, dict) else "")
        if text:
            segments.append({"text": str(text)})
    return segments, bool(segments)


def _yt_upload_date(date_str: str | None) -> date | None:
    if not date_str or len(date_str) != 8 or not date_str.isdigit():
        return None
    try:
        return date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
    except ValueError:
        return None


def scrape_youtube(
    url_or_id: str,
    *,
    language_hint: str | None = None,
    max_tags: int = 8,
) -> tuple[ScrapedRaw, RawMetadata]:
    video_id = _resolve_video_id(url_or_id)
    log.info("youtube: scraping %s", video_id)

    info = _fetch_metadata(video_id)
    title = (info.get("title") or "").strip()
    channel = (info.get("uploader") or info.get("channel") or "").strip() or None
    description = (info.get("description") or "").strip()
    upload_date = _yt_upload_date(info.get("upload_date"))
    yt_lang = info.get("language") or None

    segments, transcript_available = _fetch_transcript(
        video_id, language_hint or yt_lang
    )

    if transcript_available and segments:
        chunks = chunk_transcript(segments, window=250, overlap=30)
        body_for_tags = " ".join(s["text"] for s in segments)
    else:
        chunks = [description] if description else [title or video_id]
        body_for_tags = description or title or video_id

    if not chunks:
        chunks = [title or "(no content)"]

    body_for_lang = " ".join(c for c in chunks if c)
    language = detect_language(body_for_lang) if body_for_lang else "en"
    tags = extract_tags(title, body_for_tags, top_n=max_tags)
    is_med = is_medical_topic(tags, body_for_tags)

    raw = ScrapedRaw(
        source_url=f"https://www.youtube.com/watch?v={video_id}",
        source_type="youtube",
        author=channel,
        published_date=upload_date,
        language=language,
        region=None,
        topic_tags=tags,
        content_chunks=chunks,
    )
    meta: RawMetadata = {
        "subscriber_count": int(info.get("channel_follower_count") or 0),
        "channel_verified": bool(info.get("channel_is_verified", False)),
        "transcript_available": transcript_available,
        "word_count": len(body_for_tags.split()),
        "is_medical": is_med,
        "body_text": body_for_tags,
        "outbound_links": [],
    }
    return raw, meta
