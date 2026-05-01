"""Default sources for the 6 submission entries.

Both the UI (Streamlit) and the CLI (`Task 1 Multi-Source Scraper/main.py`)
read from this module, so there is exactly one place to update if a default
goes stale. Re-run `scripts/verify_defaults.py` after any edit.

Two views of the same data:

- `DEFAULTS` — the rich tuple, with a `label` and `rationale` per entry,
  used by the Streamlit "Run All" tab to render an explanatory table.
- `DEFAULT_BLOGS` / `DEFAULT_YOUTUBE` / `DEFAULT_PUBMED` — flat lists
  derived from `DEFAULTS`, kept for backward compat with the CLI and
  `scripts/verify_defaults.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DefaultSource:
    kind: Literal["blog", "youtube", "pubmed"]
    target: str       # URL for blog/youtube; PMID for pubmed
    label: str        # short human-readable name shown in the UI
    rationale: str    # why this entry was picked — what it exercises


DEFAULTS: tuple[DefaultSource, ...] = (
    DefaultSource(
        kind="blog",
        target="https://en.wikipedia.org/wiki/Artificial_intelligence",
        label="Wikipedia — Artificial Intelligence",
        rationale=(
            "Non-medical AI/tech reference. Exercises the long-body chunker "
            "(>10k tokens), JSON-LD author extraction, and the .org → tier 3 "
            "domain-authority path."
        ),
    ),
    DefaultSource(
        kind="blog",
        target="https://www.cdc.gov/diabetes/about/index.html",
        label="CDC — Diabetes overview",
        rationale=(
            "Medical .gov source. Exercises the suffix → tier 1 domain "
            "lookup and the medical-disclaimer regex bank."
        ),
    ),
    DefaultSource(
        kind="blog",
        target="https://en.wikipedia.org/wiki/Photosynthesis",
        label="Wikipedia — Photosynthesis",
        rationale=(
            "Non-medical biology reference. Second Wikipedia article so the "
            "duplicate-detection hash has something to compare against on "
            "successive runs."
        ),
    ),
    DefaultSource(
        kind="youtube",
        target="aircAruvnKk",
        label="3Blue1Brown — But what is a neural network?",
        rationale=(
            "Mid-channel (~5M subs), both auto and manual captions present. "
            "Exercises the transcript chunker and yt-dlp metadata path."
        ),
    ),
    DefaultSource(
        kind="youtube",
        target="8jPQjjsBbIc",
        label="TED — Sir Ken Robinson — Do schools kill creativity?",
        rationale=(
            "Very high subscriber count (TED), captions in many languages. "
            "Exercises the language-cascade fallback in the transcript fetch."
        ),
    ),
    DefaultSource(
        kind="pubmed",
        target="34813764",
        label="PubMed — Arabidopsis embryos cuticle germination",
        rationale=(
            "Stable PMID with an abstract, citations, and author affiliations. "
            "Exercises the citation-cache + per-author ESearch cache."
        ),
    ),
)


# Flat-list views (preserved for the CLI + verify_defaults.py).
DEFAULT_BLOGS: list[str] = [d.target for d in DEFAULTS if d.kind == "blog"]
DEFAULT_YOUTUBE: list[str] = [d.target for d in DEFAULTS if d.kind == "youtube"]
DEFAULT_PUBMED: str = next(d.target for d in DEFAULTS if d.kind == "pubmed")
