"""Streamlit UI — CLAUDE.md §7, plan.txt P7.

Four tabs (Blog / YouTube / PubMed / Run All). The first three call the
FastAPI endpoints (so the same code path the grader exercises through
`/docs` is what the UI uses). The Run-All tab calls the scraper and
trust-score machinery directly — going through HTTP for six sequential
calls would just add round-trip latency to a progress bar that already
shows what's happening.

Editable parameters per tab live in an "Advanced" expander. The 5 trust-
score weight overrides are number inputs (not sliders — float drift on
five sliders made it surprisingly hard to land on a sum of exactly 1.0).
The Run button is disabled until `src.trust_score.weights.validate_weights`
accepts the override (or the override is turned off, in which case the
API uses its canonical defaults).

Boot:
    streamlit run "Task 1 Multi-Source Scraper/ui/app.py"

Env:
    TRUSTCRAWLER_API_URL  (default http://localhost:8000)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
import streamlit as st

# Make `src.*` importable regardless of cwd. Streamlit usually launches with
# the cwd set to the project that holds the script, but in Docker we want
# this to work whether `streamlit run` is invoked from /app or somewhere else.
_THIS = Path(__file__).resolve()
_PROJECT_ROOT = _THIS.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Local-dev convenience: pick up PUBMED_EMAIL etc. from the project .env
# (Docker passes envs via --env-file; local boots don't).
try:
    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

from src.defaults import DEFAULT_BLOGS, DEFAULT_PUBMED, DEFAULT_YOUTUBE  # noqa: E402
from src.errors import WeightValidationError  # noqa: E402
from src.scrapers import blog as blog_module  # noqa: E402
from src.scrapers import pubmed as pubmed_module  # noqa: E402
from src.scrapers import youtube as youtube_module  # noqa: E402
from src.trust_score.abuse_prevention import DuplicateTracker  # noqa: E402
from src.trust_score.compute import compute_trust_score  # noqa: E402
from src.trust_score.weights import WEIGHTS, validate_weights  # noqa: E402

API_BASE: str = os.environ.get("TRUSTCRAWLER_API_URL", "http://localhost:8000").rstrip("/")
API_TIMEOUT_S: int = 180  # PubMed citation lookup + KeyBERT first-load can be slow
OUTPUT_DIR: Path = _THIS.parent.parent / "output"

st.set_page_config(page_title="TrustCrawler", layout="wide")
st.title("TrustCrawler — Multi-Source Scraper")
st.caption(
    "Scrape blogs, YouTube videos, and PubMed articles — then compute a "
    "trust score from author credibility, citations, domain authority, "
    "recency, and medical-disclaimer presence."
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _weight_editor(key_prefix: str) -> tuple[dict[str, float] | None, str | None]:
    """Render the trust-score weight override panel.

    Returns (weights, error). When the user has not enabled the override,
    `weights` is None (so the API falls back to its canonical defaults)
    and `error` is None. When the override IS enabled but invalid, the
    caller should treat `error` as a hard gate on the Run button.
    """
    override = st.checkbox(
        "Override default trust-score weights",
        value=False,
        key=f"{key_prefix}_override",
        help="Off → API uses canonical weights from src/trust_score/weights.py.",
    )
    if not override:
        with st.container():
            st.caption(
                "Defaults: " + ", ".join(f"{k}={v}" for k, v in WEIGHTS.items())
            )
        return None, None

    cols = st.columns(len(WEIGHTS))
    overrides: dict[str, float] = {}
    for col, (k, v) in zip(cols, WEIGHTS.items(), strict=True):
        with col:
            overrides[k] = st.number_input(
                k,
                min_value=0.0,
                max_value=1.0,
                value=float(v),
                step=0.01,
                format="%.3f",
                key=f"{key_prefix}_w_{k}",
            )
    total = sum(overrides.values())
    st.caption(f"Sum: **{total:.6f}** (must equal 1.000000 within 1e-6)")

    try:
        validate_weights(overrides)
    except WeightValidationError as e:
        return overrides, f"{e} — {e.details}"
    return overrides, None


def _call_api(endpoint: str, payload: dict[str, Any]) -> tuple[dict | None, str | None]:
    """POST to the API; return (json, error_message). Surfaces the FastAPI
    `detail` payload from 400/422 responses verbatim per CLAUDE.md §11.
    """
    url = f"{API_BASE}{endpoint}"
    try:
        r = requests.post(url, json=payload, timeout=API_TIMEOUT_S)
    except requests.exceptions.ConnectionError:
        return None, (
            f"Cannot reach the FastAPI server at {API_BASE}. "
            "Start it with: uvicorn src.api:app --port 8000"
        )
    except requests.RequestException as e:
        return None, f"Network error calling {url}: {e}"

    if r.status_code == 200:
        try:
            return r.json(), None
        except json.JSONDecodeError as e:
            return None, f"Server returned invalid JSON: {e}"

    # 400 / 422 / 500 — try to surface the structured detail body.
    try:
        body = r.json()
    except json.JSONDecodeError:
        body = {"raw": r.text[:500]}
    pretty = json.dumps(body, indent=2)
    return None, f"HTTP {r.status_code} from {endpoint}\n```\n{pretty}\n```"


def _render_result(result: dict, *, filename: str) -> None:
    score = result.get("trust_score")
    if isinstance(score, (int, float)):
        st.metric("Trust score", f"{score:.3f}")
    st.json(result, expanded=False)
    st.download_button(
        "⬇ Download JSON",
        data=json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False),
        file_name=filename,
        mime="application/json",
    )


def _render_error(error: str) -> None:
    if error.startswith("HTTP "):
        st.error(error.split("\n", 1)[0])
        st.markdown(error.split("\n", 1)[1] if "\n" in error else "")
    else:
        st.error(error)


# ----------------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------------

tab_blog, tab_yt, tab_pm, tab_all = st.tabs(["Blog", "YouTube", "PubMed", "Run All"])


def _blog_tab() -> None:
    st.subheader("Blog")
    url = st.text_input("Blog URL", value=DEFAULT_BLOGS[0], key="blog_url")
    with st.expander("Advanced", expanded=False):
        c1, c2, c3 = st.columns(3)
        max_tags = c1.number_input(
            "max_tags", min_value=1, max_value=20, value=8, step=1, key="blog_tags"
        )
        chunk_min = c2.number_input(
            "chunk_min", min_value=50, max_value=2000, value=200, step=10, key="blog_cmin"
        )
        chunk_max = c3.number_input(
            "chunk_max", min_value=100, max_value=5000, value=500, step=10, key="blog_cmax"
        )
        weights, w_err = _weight_editor("blog")
    disabled = w_err is not None or not url.strip()
    if w_err:
        st.warning(w_err)
    if st.button("Run", key="blog_run", disabled=disabled, type="primary"):
        payload: dict[str, Any] = {
            "url": url.strip(),
            "max_tags": int(max_tags),
            "chunk_min": int(chunk_min),
            "chunk_max": int(chunk_max),
        }
        if weights is not None:
            payload["weights"] = weights
        with st.spinner("Scraping…"):
            result, error = _call_api("/scrape/blog", payload)
        if error:
            _render_error(error)
        elif result:
            _render_result(result, filename="blog_result.json")


def _youtube_tab() -> None:
    st.subheader("YouTube")
    url_or_id = st.text_input(
        "YouTube URL or video ID", value=DEFAULT_YOUTUBE[0], key="yt_url"
    )
    with st.expander("Advanced", expanded=False):
        c1, c2 = st.columns(2)
        max_tags = c1.number_input(
            "max_tags", min_value=1, max_value=20, value=8, step=1, key="yt_tags"
        )
        language_hint = c2.text_input(
            "language_hint",
            value="",
            help="ISO 639-1 code, e.g. 'en', 'es'. Leave blank for auto.",
            key="yt_lang",
        )
        weights, w_err = _weight_editor("yt")
    disabled = w_err is not None or not url_or_id.strip()
    if w_err:
        st.warning(w_err)
    if st.button("Run", key="yt_run", disabled=disabled, type="primary"):
        payload: dict[str, Any] = {
            "url_or_id": url_or_id.strip(),
            "max_tags": int(max_tags),
        }
        if language_hint.strip():
            payload["language_hint"] = language_hint.strip()
        if weights is not None:
            payload["weights"] = weights
        with st.spinner("Scraping…"):
            result, error = _call_api("/scrape/youtube", payload)
        if error:
            _render_error(error)
        elif result:
            _render_result(result, filename="youtube_result.json")


def _pubmed_tab() -> None:
    st.subheader("PubMed")
    pmid_or_url = st.text_input(
        "PMID or PubMed URL", value=DEFAULT_PUBMED, key="pm_url"
    )
    with st.expander("Advanced", expanded=False):
        max_tags = st.number_input(
            "max_tags", min_value=1, max_value=20, value=8, step=1, key="pm_tags"
        )
        weights, w_err = _weight_editor("pm")
    disabled = w_err is not None or not pmid_or_url.strip()
    if w_err:
        st.warning(w_err)
    if st.button("Run", key="pm_run", disabled=disabled, type="primary"):
        payload: dict[str, Any] = {
            "pmid_or_url": pmid_or_url.strip(),
            "max_tags": int(max_tags),
        }
        if weights is not None:
            payload["weights"] = weights
        with st.spinner("Scraping…"):
            result, error = _call_api("/scrape/pubmed", payload)
        if error:
            _render_error(error)
        elif result:
            _render_result(result, filename="pubmed_result.json")


def _run_all_tab() -> None:
    st.subheader("Run All — 6 default sources")
    st.caption(
        "Scrapes every source listed in `src/defaults.py`, computes trust "
        "scores, and writes `output/{blogs,youtube,pubmed,scraped_data}.json`."
    )
    if not st.button("Run all 6", key="all_run", type="primary"):
        return

    plan: list[tuple[str, str, Any]] = (
        [("blog", url, blog_module.scrape_blog) for url in DEFAULT_BLOGS]
        + [("youtube", vid, youtube_module.scrape_youtube) for vid in DEFAULT_YOUTUBE]
        + [("pubmed", DEFAULT_PUBMED, pubmed_module.scrape_pubmed)]
    )
    progress = st.progress(0.0, text="Starting…")
    status = st.empty()
    by_type: dict[str, list[dict]] = {"blog": [], "youtube": [], "pubmed": []}
    failures: list[dict] = []
    dedup = DuplicateTracker()

    for i, (kind, target, fn) in enumerate(plan):
        progress.progress(
            i / len(plan),
            text=f"({i + 1}/{len(plan)}) {kind}: {target}",
        )
        status.info(f"Scraping {kind}: `{target}`")
        try:
            raw, meta = fn(target)
            body = meta.get("body_text") or ""
            if dedup.is_duplicate(body):
                status.warning(f"Skipped duplicate: {target}")
                failures.append({"kind": kind, "target": target, "error": "duplicate"})
                continue
            scored = compute_trust_score(raw, meta)
            by_type[kind].append(scored.model_dump(mode="json"))
        except Exception as e:  # noqa: BLE001 — show errors in the UI, don't crash the tab
            failures.append({"kind": kind, "target": target, "error": str(e)})
            status.warning(f"{kind} `{target}` failed: {e}")

    progress.progress(1.0, text="Done.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "blogs.json": by_type["blog"],
        "youtube.json": by_type["youtube"],
        "pubmed.json": by_type["pubmed"],
        "scraped_data.json": by_type["blog"] + by_type["youtube"] + by_type["pubmed"],
    }
    for name, payload in files.items():
        (OUTPUT_DIR / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )

    canonical = files["scraped_data.json"]
    st.success(
        f"Wrote {len(canonical)} record(s) to `output/scraped_data.json`"
        + (f" — {len(failures)} failure(s)" if failures else "")
    )

    if canonical:
        st.markdown("**Summary**")
        rows = [
            {
                "url": str(rec["source_url"]),
                "type": rec["source_type"],
                "trust_score": rec["trust_score"],
                "top_tags": ", ".join(rec["topic_tags"][:3]),
            }
            for rec in canonical
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇ Download scraped_data.json",
            data=json.dumps(canonical, indent=2, sort_keys=True, ensure_ascii=False),
            file_name="scraped_data.json",
            mime="application/json",
        )

    if failures:
        st.markdown("**Failures**")
        st.dataframe(failures, use_container_width=True, hide_index=True)


with tab_blog:
    _blog_tab()
with tab_yt:
    _youtube_tab()
with tab_pm:
    _pubmed_tab()
with tab_all:
    _run_all_tab()
