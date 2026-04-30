"""Tagging tests — exercise the YAKE fallback path explicitly to keep
tests fast and hermetic. The KeyBERT path needs a 90 MB model download
on first use; it gets implicit coverage when phase 4 scrapers run.
"""

from src.utils import tagging


def _force_yake(monkeypatch):
    monkeypatch.setattr(tagging, "_KEYBERT", None, raising=False)
    monkeypatch.setattr(tagging, "_KEYBERT_LOAD_FAILED", True, raising=False)


def test_extract_tags_yake_path(monkeypatch):
    _force_yake(monkeypatch)
    title = "Quantum Computing Breakthrough"
    body = (
        "Researchers at MIT announced a new approach to quantum computing "
        "that uses photonic qubits. The technique reduces decoherence and "
        "improves gate fidelity. Quantum supremacy may be closer than "
        "previously thought. The team published the results in Nature."
    ) * 4
    tags = tagging.extract_tags(title, body, top_n=5)
    assert isinstance(tags, list)
    assert 0 < len(tags) <= 5
    assert all(t == t.lower() for t in tags)
    assert len(tags) == len(set(tags))


def test_extract_tags_empty_input(monkeypatch):
    _force_yake(monkeypatch)
    assert tagging.extract_tags("", "") == []
    assert tagging.extract_tags("   ", "   ") == []


def test_normalize_drops_stopword_only():
    out = tagging._normalize(["the", "the and", "machine learning", "  THE  "])
    assert "machine learning" in out
    assert "the" not in out
    assert "the and" not in out


def test_normalize_dedupes_case_insensitive():
    out = tagging._normalize(["Machine Learning", "machine learning", "MACHINE LEARNING"])
    assert out == ["machine learning"]


def test_normalize_lowercases():
    out = tagging._normalize(["Quantum Computing", "PHOTONIC QUBITS"])
    assert out == ["quantum computing", "photonic qubits"]
