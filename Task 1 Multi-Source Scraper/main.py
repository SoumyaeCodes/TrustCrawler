"""CLI entrypoint — "Run All" backend (Phase 6 / CLAUDE.md §13).

Scrapes every default source in `src.defaults`, runs the trust-score
pipeline, and writes four JSON files into `Task 1 Multi-Source Scraper/output/`:

    blogs.json         — list[ScrapedSource] for the 3 default blogs
    youtube.json       — list[ScrapedSource] for the 2 default YouTube videos
    pubmed.json        — list[ScrapedSource] for the 1 default PubMed article
    scraped_data.json  — concatenation of the above (the submission artifact)

Two import paths run side-by-side, on purpose:

1. **Path-loaded shims.** The spec asks for "blog posts extractor/api.py",
   "YouTube videos extractor/api.py", and "PubMed article extractor/api.py"
   — folder names with spaces are not legal Python identifiers, so we load
   each shim by file path with `importlib.util`. Loading them here
   satisfies the literal reading of the spec and exercises the same code
   path that `src/api.py` uses to mount routers, so a regression in either
   the shim or the loader is caught early.

2. **Direct `src.*` imports** do the actual work. Running through the
   FastAPI routers from a CLI would require booting uvicorn or hitting
   ourselves over HTTP — pointless overhead. The `scrape_*` functions and
   `compute_trust_score` are pure-Python, so we call them directly.

Run from the project root:

    python "Task 1 Multi-Source Scraper/main.py"
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

# Make `src.*` importable regardless of the cwd the user invoked from.
_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load `.env` before importing anything that reads env vars at module load,
# so PUBMED_EMAIL / USER_AGENT / LOG_LEVEL flow into the scrapers when run
# via `python "Task 1 Multi-Source Scraper/main.py"` (the FastAPI/uvicorn
# entry point handles this via uvicorn --env-file).
try:
    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

from src.defaults import DEFAULT_BLOGS, DEFAULT_PUBMED, DEFAULT_YOUTUBE  # noqa: E402
from src.logging_config import get_logger  # noqa: E402
from src.schema import ScrapedSource  # noqa: E402
from src.scrapers import blog as blog_module  # noqa: E402
from src.scrapers import pubmed as pubmed_module  # noqa: E402
from src.scrapers import youtube as youtube_module  # noqa: E402
from src.trust_score.abuse_prevention import DuplicateTracker  # noqa: E402
from src.trust_score.compute import compute_trust_score  # noqa: E402

log = get_logger(__name__)

_SHIM_DIR = _THIS_FILE.parent
_SHIM_PATHS: dict[str, Path] = {
    "blog": _SHIM_DIR / "blog posts extractor" / "api.py",
    "youtube": _SHIM_DIR / "YouTube videos extractor" / "api.py",
    "pubmed": _SHIM_DIR / "PubMed article extractor" / "api.py",
}

_OUTPUT_DIR = _SHIM_DIR / "output"


def _path_load_shims() -> dict[str, ModuleType]:
    """Path-load each extractor's api.py. Returned modules are not used
    by the CLI's scraping logic — see the module docstring — but loading
    them validates that the shim files import cleanly.
    """
    loaded: dict[str, ModuleType] = {}
    for name, path in _SHIM_PATHS.items():
        spec = importlib.util.spec_from_file_location(f"_extractor_shim_{name}", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"could not load extractor shim {name} from {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "router"):
            raise ImportError(f"shim at {path} does not expose `router`")
        loaded[name] = module
    return loaded


def _score_or_skip(
    raw, meta, *, dedup: DuplicateTracker, source_label: str
) -> ScrapedSource | None:
    """Apply the run-scoped duplicate check (CLAUDE.md §6.4 step 5 of the
    abuse-prevention list) before scoring. Returns None when the source is
    a duplicate of one already processed in this run.
    """
    body = meta.get("body_text") or ""
    if dedup.is_duplicate(body):
        log.warning("skipping duplicate: %s", source_label)
        return None
    return compute_trust_score(raw, meta)


def _scrape_blogs(dedup: DuplicateTracker) -> list[ScrapedSource]:
    out: list[ScrapedSource] = []
    for url in DEFAULT_BLOGS:
        log.info("blog: %s", url)
        raw, meta = blog_module.scrape_blog(url)
        scored = _score_or_skip(raw, meta, dedup=dedup, source_label=url)
        if scored is not None:
            out.append(scored)
    return out


def _scrape_youtube(dedup: DuplicateTracker) -> list[ScrapedSource]:
    out: list[ScrapedSource] = []
    for vid in DEFAULT_YOUTUBE:
        log.info("youtube: %s", vid)
        raw, meta = youtube_module.scrape_youtube(vid)
        scored = _score_or_skip(raw, meta, dedup=dedup, source_label=vid)
        if scored is not None:
            out.append(scored)
    return out


def _scrape_pubmed(dedup: DuplicateTracker) -> list[ScrapedSource]:
    out: list[ScrapedSource] = []
    log.info("pubmed: %s", DEFAULT_PUBMED)
    raw, meta = pubmed_module.scrape_pubmed(DEFAULT_PUBMED)
    scored = _score_or_skip(raw, meta, dedup=dedup, source_label=DEFAULT_PUBMED)
    if scored is not None:
        out.append(scored)
    return out


def _serialize(records: list[ScrapedSource]) -> list[dict[str, Any]]:
    # `mode="json"` ensures HttpUrl, date, etc. become JSON-native types.
    return [r.model_dump(mode="json") for r in records]


def _write_json(path: Path, records: list[ScrapedSource]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialize(records)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    log.info("wrote %d record(s) to %s", len(records), path)


def run() -> int:
    _path_load_shims()  # raises if any shim is broken; fast-fail is the goal
    dedup = DuplicateTracker()

    blogs = _scrape_blogs(dedup)
    youtube = _scrape_youtube(dedup)
    pubmed = _scrape_pubmed(dedup)

    _write_json(_OUTPUT_DIR / "blogs.json", blogs)
    _write_json(_OUTPUT_DIR / "youtube.json", youtube)
    _write_json(_OUTPUT_DIR / "pubmed.json", pubmed)
    _write_json(_OUTPUT_DIR / "scraped_data.json", blogs + youtube + pubmed)

    total = len(blogs) + len(youtube) + len(pubmed)
    log.info("done — %d records in scraped_data.json", total)
    return 0


if __name__ == "__main__":
    sys.exit(run())
