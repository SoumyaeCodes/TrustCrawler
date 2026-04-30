#!/usr/bin/env python3
"""Verify every default source still resolves before submission.

Exits 0 if all checks pass; non-zero otherwise. Run after editing
`src/defaults.py` and as a pre-submission gate (CLAUDE.md §13).

Checks:
- Each blog URL returns HTTP 200 (GET with realistic User-Agent).
- Each YouTube video ID has at least one transcript track listed.
- The PubMed PMID resolves via Entrez.esummary and has a non-empty title.
"""

from __future__ import annotations

import os
import sys

import requests
from dotenv import load_dotenv

from src.defaults import DEFAULT_BLOGS, DEFAULT_PUBMED, DEFAULT_YOUTUBE
from src.logging_config import get_logger

load_dotenv()
log = get_logger("verify_defaults")

USER_AGENT = os.environ.get("USER_AGENT", "DataScrapingAssignment/1.0")
TIMEOUT_S = 10


def check_blog(url: str) -> bool:
    try:
        r = requests.get(
            url,
            timeout=TIMEOUT_S,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
    except requests.RequestException as e:
        log.error("blog %s — request failed: %s", url, e)
        return False
    ok = r.status_code == 200
    log.info("blog %s -> %s", url, r.status_code)
    return ok


def check_youtube(video_id: str) -> bool:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as e:
        log.error("youtube-transcript-api not installed: %s", e)
        return False
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        any_track = any(True for _ in transcript_list)
    except Exception as e:
        log.error("youtube %s — transcript list failed: %s", video_id, e)
        return False
    log.info("youtube %s -> transcripts=%s", video_id, any_track)
    return any_track


def check_pubmed(pmid: str) -> bool:
    email = os.environ.get("PUBMED_EMAIL", "")
    if not email:
        log.error("PUBMED_EMAIL is not set")
        return False
    try:
        from Bio import Entrez
    except ImportError as e:
        log.error("biopython not installed: %s", e)
        return False
    Entrez.email = email
    if os.environ.get("PUBMED_API_KEY"):
        Entrez.api_key = os.environ["PUBMED_API_KEY"]
    try:
        handle = Entrez.esummary(db="pubmed", id=pmid)
        summaries = Entrez.read(handle)
        handle.close()
    except Exception as e:
        log.error("pubmed %s — esummary failed: %s", pmid, e)
        return False
    if not summaries:
        log.error("pubmed %s — empty summaries", pmid)
        return False
    title = (summaries[0].get("Title") or "").strip()
    log.info("pubmed %s -> %s", pmid, title[:80])
    return bool(title)


def main() -> int:
    fails = 0
    for url in DEFAULT_BLOGS:
        if not check_blog(url):
            fails += 1
    for vid in DEFAULT_YOUTUBE:
        if not check_youtube(vid):
            fails += 1
    if not check_pubmed(DEFAULT_PUBMED):
        fails += 1
    if fails:
        log.error("%d default(s) failed verification", fails)
        return 1
    log.info("all %d defaults verified", len(DEFAULT_BLOGS) + len(DEFAULT_YOUTUBE) + 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
