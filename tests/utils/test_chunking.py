import pytest
import tiktoken

from src.utils.chunking import TOTAL_TOKEN_CAP, chunk_paragraphs, chunk_transcript

_ENC = tiktoken.get_encoding("cl100k_base")


def _tok(s: str) -> int:
    return len(_ENC.encode(s))


def test_chunk_paragraphs_empty_text():
    assert chunk_paragraphs("") == []
    assert chunk_paragraphs("   \n\n  ") == []


def test_chunk_paragraphs_returns_no_empty_strings():
    text = "First.\n\nSecond.\n\nThird."
    chunks = chunk_paragraphs(text, target_min=10, target_max=30)
    assert chunks
    assert all(c.strip() for c in chunks)


def test_chunk_paragraphs_respects_target_max():
    para = "lorem ipsum dolor sit amet " * 200
    chunks = chunk_paragraphs(para, target_min=50, target_max=200)
    for c in chunks:
        assert _tok(c) <= 250  # small slack at sentence boundary


def test_chunk_paragraphs_merges_short_paragraphs():
    text = "\n\n".join(["short."] * 10)
    chunks = chunk_paragraphs(text, target_min=20, target_max=200)
    assert len(chunks) <= 2


def test_chunk_paragraphs_truncates_above_cap():
    huge = "lorem ipsum dolor sit amet. " * 5000
    chunks = chunk_paragraphs(huge, target_min=100, target_max=400)
    total = sum(_tok(c) for c in chunks)
    assert total <= TOTAL_TOKEN_CAP + 200  # join-token slack


def test_chunk_transcript_with_dict_segments():
    segments = [{"text": "hello world."} for _ in range(50)]
    chunks = chunk_transcript(segments, window=20, overlap=5)
    assert chunks
    assert all(c for c in chunks)


def test_chunk_transcript_with_string_segments():
    segments = ["one two three four five"] * 30
    chunks = chunk_transcript(segments, window=15, overlap=3)
    assert chunks
    assert all(c for c in chunks)


def test_chunk_transcript_empty_input():
    assert chunk_transcript([]) == []
    assert chunk_transcript([{"text": ""}, ""]) == []


def test_chunk_transcript_window_overlap_validation():
    with pytest.raises(ValueError):
        chunk_transcript(["whatever"], window=10, overlap=10)
    with pytest.raises(ValueError):
        chunk_transcript(["whatever"], window=10, overlap=15)


def test_chunk_transcript_truncates_above_cap():
    big = "lorem ipsum dolor " * 20_000
    chunks = chunk_transcript([big], window=500, overlap=50)
    # Source truncated to 10k tokens; with step=450 we expect ~23 chunks max.
    assert len(chunks) <= 25
    assert all(c for c in chunks)
