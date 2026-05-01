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

from src.defaults import (  # noqa: E402
    DEFAULT_BLOGS,
    DEFAULT_PUBMED,
    DEFAULT_YOUTUBE,
    DEFAULTS,
)
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


_SCRAPER_FOR_KIND = {
    "blog": blog_module.scrape_blog,
    "youtube": youtube_module.scrape_youtube,
    "pubmed": pubmed_module.scrape_pubmed,
}


def _kwargs_for(kind: str, *, max_tags: int, chunk_min: int, chunk_max: int,
                language_hint: str | None) -> dict[str, Any]:
    """Project the global Run-All settings onto each scraper's signature.

    All three scrapers accept `max_tags`. Only `blog` accepts chunk knobs;
    only `youtube` accepts a language hint. Sending unknown kwargs would
    crash the call, so we filter per kind.
    """
    if kind == "blog":
        return {"max_tags": max_tags, "chunk_min": chunk_min, "chunk_max": chunk_max}
    if kind == "youtube":
        kw: dict[str, Any] = {"max_tags": max_tags}
        if language_hint:
            kw["language_hint"] = language_hint
        return kw
    if kind == "pubmed":
        return {"max_tags": max_tags}
    return {}


def _run_all_tab() -> None:
    st.subheader("Run All — 6 default sources")
    st.caption(
        "Scrapes every source below, computes trust scores, and writes "
        "`output/{blogs,youtube,pubmed,scraped_data}.json`. Edit any "
        "**target** cell to scrape a different URL/PMID — the kind, label, "
        "and rationale columns are read-only."
    )

    # Pre-run editable plan ---------------------------------------------------
    initial_rows = [
        {
            "kind": d.kind,
            "label": d.label,
            "target": d.target,
            "rationale": d.rationale,
        }
        for d in DEFAULTS
    ]
    edited = st.data_editor(
        initial_rows,
        key="all_plan",
        num_rows="fixed",
        width="stretch",
        hide_index=True,
        column_config={
            "kind": st.column_config.TextColumn(
                "Kind",
                help="Which scraper handles this entry. Read-only.",
                disabled=True,
                width="small",
            ),
            "label": st.column_config.TextColumn(
                "Label",
                help="Human-readable name shown for this source.",
                disabled=True,
                width="medium",
            ),
            "target": st.column_config.TextColumn(
                "Target (URL or PMID)",
                help="What to scrape. Editable — change to point at a different source.",
                width="large",
                required=True,
            ),
            "rationale": st.column_config.TextColumn(
                "Why this entry was picked",
                help="Explains what code paths this entry exercises.",
                disabled=True,
                width="large",
            ),
        },
    )

    # Per-run settings — applied uniformly across all 6 sources. Each
    # scraper only consumes the kwargs in its signature; `_kwargs_for`
    # filters on `kind` so YouTube doesn't get `chunk_min` etc.
    with st.expander("Advanced — parameters & trust-score weights", expanded=False):
        st.caption(
            "These settings apply to every source in the table above. "
            "`chunk_min`/`chunk_max` only affect blogs; `language_hint` "
            "only affects YouTube; `max_tags` applies to all three."
        )
        c1, c2, c3, c4 = st.columns(4)
        all_max_tags = c1.number_input(
            "max_tags", min_value=1, max_value=20, value=8, step=1, key="all_tags"
        )
        all_chunk_min = c2.number_input(
            "chunk_min (blog)", min_value=50, max_value=2000, value=200, step=10,
            key="all_cmin",
        )
        all_chunk_max = c3.number_input(
            "chunk_max (blog)", min_value=100, max_value=5000, value=500, step=10,
            key="all_cmax",
        )
        all_language_hint = c4.text_input(
            "language_hint (youtube)", value="",
            help="ISO 639-1 code, e.g. 'en', 'es'. Leave blank for auto.",
            key="all_lang",
        )
        st.markdown("**Trust-score weights**")
        all_weights, all_w_err = _weight_editor("all")

    if all_w_err:
        st.warning(all_w_err)

    if not st.button(
        "Run all",
        key="all_run",
        type="primary",
        disabled=all_w_err is not None,
    ):
        return

    # Execute the (possibly edited) plan -------------------------------------
    plan: list[tuple[str, str, str]] = []
    for row in edited:
        kind = (row.get("kind") or "").strip()
        target = (row.get("target") or "").strip()
        label = (row.get("label") or "").strip()
        if not target:
            continue  # silently skip blank rows; data_editor doesn't add any with num_rows="fixed"
        plan.append((kind, target, label))

    progress = st.progress(0.0, text="Starting…")
    status = st.empty()
    live_rows: list[dict] = [
        {"#": i + 1, "kind": k, "label": lbl, "target": t, "status": "queued", "trust_score": ""}
        for i, (k, t, lbl) in enumerate(plan)
    ]
    live_table = st.empty()
    live_table.dataframe(live_rows, width="stretch", hide_index=True)

    by_type: dict[str, list[dict]] = {"blog": [], "youtube": [], "pubmed": []}
    failures: list[dict] = []
    dedup = DuplicateTracker()

    for i, (kind, target, label) in enumerate(plan):
        live_rows[i]["status"] = "scraping…"
        live_table.dataframe(live_rows, width="stretch", hide_index=True)
        progress.progress(i / len(plan), text=f"({i + 1}/{len(plan)}) {kind}: {label}")
        status.info(f"**{label}** — `{target}`")

        fn = _SCRAPER_FOR_KIND.get(kind)
        if fn is None:
            failures.append({"kind": kind, "target": target, "error": f"unknown kind: {kind!r}"})
            live_rows[i]["status"] = "✗ unknown kind"
            continue

        try:
            kwargs = _kwargs_for(
                kind,
                max_tags=int(all_max_tags),
                chunk_min=int(all_chunk_min),
                chunk_max=int(all_chunk_max),
                language_hint=(all_language_hint.strip() or None),
            )
            raw, meta = fn(target, **kwargs)
            body = meta.get("body_text") or ""
            if dedup.is_duplicate(body):
                live_rows[i]["status"] = "⊘ duplicate"
                failures.append({"kind": kind, "target": target, "error": "duplicate"})
                continue
            scored = compute_trust_score(raw, meta, weights=all_weights)
            by_type[kind].append(scored.model_dump(mode="json"))
            live_rows[i]["status"] = "✓ done"
            live_rows[i]["trust_score"] = round(scored.trust_score, 3)
        except Exception as e:  # noqa: BLE001 — surface in UI, don't crash the tab
            live_rows[i]["status"] = "✗ failed"
            failures.append({"kind": kind, "target": target, "error": str(e)})

        live_table.dataframe(live_rows, width="stretch", hide_index=True)

    progress.progress(1.0, text="Done.")

    # Persist outputs ---------------------------------------------------------
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
        st.dataframe(rows, width="stretch", hide_index=True)
        st.download_button(
            "⬇ Download scraped_data.json",
            data=json.dumps(canonical, indent=2, sort_keys=True, ensure_ascii=False),
            file_name="scraped_data.json",
            mime="application/json",
        )

    if failures:
        st.markdown("**Failures**")
        st.dataframe(failures, width="stretch", hide_index=True)


with tab_blog:
    _blog_tab()
with tab_yt:
    _youtube_tab()
with tab_pm:
    _pubmed_tab()
with tab_all:
    _run_all_tab()
