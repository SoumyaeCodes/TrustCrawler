"""Content chunking utilities.

Two chunkers, both using tiktoken's `cl100k_base` encoding for token sizing:

- `chunk_paragraphs(text, ...)` — paragraph-based, merging short paragraphs
  and splitting long ones to keep each chunk in the 200–500 token band.
- `chunk_transcript(segments, ...)` — token-window-based with overlap, since
  paragraphs don't exist in transcripts.

Both cap the total at `TOTAL_TOKEN_CAP` (10 000 tokens) and emit a warning
when truncating, per CLAUDE.md §6.3 ("very long articles must not OOM").
Output is always `list[str]` with no empty strings.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import tiktoken

from src.logging_config import get_logger

_logger = get_logger(__name__)

_ENCODING = tiktoken.get_encoding("cl100k_base")
TOTAL_TOKEN_CAP = 10_000


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _split_paragraphs(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    # Prefer blank-line splits; fall back to single newlines.
    parts = text.split("\n\n") if "\n\n" in text else text.split("\n")
    return [p.strip() for p in parts if p.strip()]


def _token_window_split(text: str, target_max: int) -> list[str]:
    tokens = _ENCODING.encode(text)
    out: list[str] = []
    for start in range(0, len(tokens), target_max):
        decoded = _ENCODING.decode(tokens[start : start + target_max]).strip()
        if decoded:
            out.append(decoded)
    return out


def _split_long_paragraph(para: str, target_max: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", para)
    out: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        sent_tokens = _count_tokens(sent)
        if sent_tokens > target_max:
            # Sentence exceeds target_max (or sentence detection failed
            # entirely on a punctuation-free block). Flush the buffer and
            # token-window-split this fragment so no chunk exceeds the cap.
            if buf:
                out.append(" ".join(buf))
                buf, buf_tokens = [], 0
            out.extend(_token_window_split(sent, target_max))
            continue
        if buf_tokens + sent_tokens > target_max:
            out.append(" ".join(buf))
            buf, buf_tokens = [sent], sent_tokens
        else:
            buf.append(sent)
            buf_tokens += sent_tokens
    if buf:
        out.append(" ".join(buf))
    return out


def chunk_paragraphs(
    text: str,
    target_min: int = 200,
    target_max: int = 500,
) -> list[str]:
    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    expanded: list[str] = []
    for p in paragraphs:
        if _count_tokens(p) > target_max:
            expanded.extend(_split_long_paragraph(p, target_max))
        else:
            expanded.append(p)

    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for p in expanded:
        p_tokens = _count_tokens(p)
        if buf_tokens + p_tokens <= target_max:
            buf.append(p)
            buf_tokens += p_tokens
        else:
            if buf:
                chunks.append("\n\n".join(buf))
            buf, buf_tokens = [p], p_tokens
    if buf:
        chunks.append("\n\n".join(buf))

    capped: list[str] = []
    running = 0
    for c in chunks:
        c_tokens = _count_tokens(c)
        if running + c_tokens > TOTAL_TOKEN_CAP:
            _logger.warning(
                "paragraph chunker hit %d-token cap; dropping %d chunks",
                TOTAL_TOKEN_CAP, len(chunks) - len(capped),
            )
            break
        capped.append(c)
        running += c_tokens

    return [c for c in capped if c]


def chunk_transcript(
    segments: Iterable[dict | str],
    window: int = 250,
    overlap: int = 30,
) -> list[str]:
    if overlap >= window:
        raise ValueError("overlap must be less than window")

    parts: list[str] = []
    for seg in segments:
        if isinstance(seg, str):
            parts.append(seg)
        elif isinstance(seg, dict) and "text" in seg:
            parts.append(str(seg["text"]))
    text = " ".join(p.strip() for p in parts if p and p.strip())
    if not text:
        return []

    tokens = _ENCODING.encode(text)
    if len(tokens) > TOTAL_TOKEN_CAP:
        _logger.warning(
            "transcript chunker truncating %d tokens to %d",
            len(tokens), TOTAL_TOKEN_CAP,
        )
        tokens = tokens[:TOTAL_TOKEN_CAP]

    chunks: list[str] = []
    step = window - overlap
    start = 0
    while start < len(tokens):
        end = start + window
        slice_ = tokens[start:end]
        if not slice_:
            break
        chunk = _ENCODING.decode(slice_).strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(tokens):
            break
        start += step
    return chunks
