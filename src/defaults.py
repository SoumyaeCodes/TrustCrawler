"""Default sources for the 6 submission entries.

Both the UI (Streamlit) and the CLI (`Task 1 Multi-Source Scraper/main.py`)
read from this module, so there is exactly one place to update if a default
goes stale. Re-run `scripts/verify_defaults.py` after any edit.
"""

from __future__ import annotations

# 3 blogs — at least one .gov or .edu, mix of medical and non-medical.
# OpenAI's blog (the original default in CLAUDE.md §7) returns 403 to
# unauthenticated requests; swapped for a stable AI-topic article.
DEFAULT_BLOGS: list[str] = [
    # Non-medical, AI/tech — Wikipedia article on Artificial Intelligence.
    "https://en.wikipedia.org/wiki/Artificial_intelligence",
    # Medical, .gov source — CDC's overview of diabetes.
    "https://www.cdc.gov/diabetes/about/index.html",
    # Non-medical, biology — Wikipedia article on Photosynthesis.
    "https://en.wikipedia.org/wiki/Photosynthesis",
]

# 2 YouTube videos with confirmed English transcripts.
DEFAULT_YOUTUBE: list[str] = [
    # 3Blue1Brown — "But what is a neural network?" (mid-channel size,
    # auto + manual captions present).
    "aircAruvnKk",
    # Sir Ken Robinson — "Do schools kill creativity?" (TED, very high
    # subs, captions in many languages).
    "8jPQjjsBbIc",
]

# 1 PubMed PMID (default value from CLAUDE.md §7).
DEFAULT_PUBMED: str = "34813764"
