"""FastAPI application root.

Mounts three POST endpoints — `/scrape/blog`, `/scrape/youtube`,
`/scrape/pubmed` — each defined in a router living inside the spec-mandated
*spaced* folder under `Task 1 Multi-Source Scraper/`. The folder names
contain spaces, which is illegal in `import` syntax, so we load each shim
by file path with `importlib.util.spec_from_file_location` and call
`app.include_router(shim.router)`.

Exception handler map (CLAUDE.md §11):
    ScrapingError / MetadataMissingError → 422
    WeightValidationError                → 400
    TrustScoreError (other subclasses)   → 500 (sanitized)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.errors import (
    MetadataMissingError,
    ScrapingError,
    TrustScoreError,
    WeightValidationError,
)
from src.logging_config import get_logger

log = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SHIM_DIR = _PROJECT_ROOT / "Task 1 Multi-Source Scraper"
_SHIMS: dict[str, Path] = {
    "blog": _SHIM_DIR / "blog posts extractor" / "api.py",
    "youtube": _SHIM_DIR / "YouTube videos extractor" / "api.py",
    "pubmed": _SHIM_DIR / "PubMed article extractor" / "api.py",
}


def _load_shim(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_extractor_shim_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load extractor shim {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "router"):
        raise ImportError(f"shim at {path} does not expose `router`")
    return module


def create_app() -> FastAPI:
    app = FastAPI(
        title="TrustCrawler — Data Scraping Assignment",
        description=(
            "Multi-source content scraper (blogs, YouTube, PubMed) with a "
            "credibility-scoring algorithm. Each route returns a `ScrapedSource`."
        ),
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    for name, path in _SHIMS.items():
        shim = _load_shim(name, path)
        app.include_router(shim.router)
        log.info("mounted %s router from %s", name, path)

    @app.exception_handler(MetadataMissingError)
    def _h_meta(request: Request, exc: MetadataMissingError) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(
            status_code=422,
            content={"error": "metadata_missing", "message": str(exc), "details": exc.details},
        )

    @app.exception_handler(ScrapingError)
    def _h_scrape(request: Request, exc: ScrapingError) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(
            status_code=422,
            content={"error": "scraping_failed", "message": str(exc), "details": exc.details},
        )

    @app.exception_handler(WeightValidationError)
    def _h_weights(request: Request, exc: WeightValidationError) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_weights", "message": str(exc), "details": exc.details},
        )

    @app.exception_handler(TrustScoreError)
    def _h_trust(request: Request, exc: TrustScoreError) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(
            status_code=500,
            content={"error": "trust_score_failed", "message": "internal error during scoring"},
        )

    @app.get("/health")
    def _health() -> dict[str, Any]:
        return {"status": "ok", "routes": sorted(_SHIMS)}

    return app


app = create_app()
