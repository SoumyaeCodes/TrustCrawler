# TrustCrawler

A multi-source content scraper for the **Data Scraping Assignment**:
extracts structured data from blog posts, YouTube videos, and PubMed
articles, then assigns each source a trust score (0–1) based on author
credibility, citation density, domain authority, recency, and presence
of medical disclaimers.

Six default sources (3 blogs / 2 YouTube videos / 1 PubMed article) are
scraped on demand and written to `Task 1 Multi-Source Scraper/output/scraped_data.json`.

---

## 1. Quickstart — Docker (recommended)

The Docker image ships with the sentence-transformers backbone and the
tiktoken encoder pre-cached, so the first scrape works without reaching
out to Hugging Face. You only need Docker and a populated `.env`.

```bash
# 1. Clone and step into the project
git clone <repo-url> TrustCrawler
cd TrustCrawler

# 2. Create your .env (PUBMED_EMAIL is REQUIRED — NCBI rejects calls without it)
cp .env.example .env
$EDITOR .env                          # set PUBMED_EMAIL=you@example.com

# 3. Build the image (takes ~3 min on a warm cache; downloads ~1.6 GB of wheels)
docker compose build

# 4. Bring the stack up (FastAPI on :8000, Streamlit on :8501)
docker compose up -d

# 5. Wait for both services to report healthy
curl -fsS http://localhost:8000/health        # → {"status":"ok",...}
curl -fsS http://localhost:8501/_stcore/health  # → ok
```

Then open the UI in a browser:

| URL | What you'll see |
|---|---|
| **http://localhost:8501** | Streamlit UI — four tabs (Blog / YouTube / PubMed / Run All) |
| http://localhost:8000/docs | FastAPI Swagger UI — try each scraper endpoint with editable request bodies |
| http://localhost:8000/openapi.json | Raw OpenAPI schema |

**Driving the UI**

1. Pick a tab (the URL/ID input is pre-filled with one of the default sources).
2. Open the **Advanced** expander to override `max_tags`, chunk size, language hint, or trust-score weights.
3. Hit **Run**. The Run button is disabled until the weight overrides validate (sum = 1.000 ± 1e-6, each in [0, 1]).
4. The result renders as JSON with a **Download JSON** button.
5. The **Run All** tab scrapes every default source sequentially with a progress bar, writes `output/scraped_data.json`, and shows a summary table (URL / type / score / top tags).

**Stopping the stack**

```bash
docker compose down                   # graceful — `docker stop` returns in <1 s
```

---

## 2. Quickstart — local Python (no Docker)

For development or grading without Docker:

```bash
# 1. Python 3.11 venv
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install deps + the package itself in editable mode
pip install -r requirements.txt
pip install -e .

# 3. Populate .env
cp .env.example .env
$EDITOR .env

# 4. Two processes, two terminals
# Terminal A — FastAPI:
uvicorn src.api:app --host 127.0.0.1 --port 8000 --env-file ./.env

# Terminal B — Streamlit:
streamlit run "Task 1 Multi-Source Scraper/ui/app.py" \
    --server.address 127.0.0.1 --server.port 8501

# 5. Open http://localhost:8501
```

To run the CLI ("Run All" without launching the UI):

```bash
python "Task 1 Multi-Source Scraper/main.py"
# → writes output/{blogs,youtube,pubmed,scraped_data}.json
```

To verify the six default sources are still reachable (helpful before
demoing — runs HEAD/GET on each blog, lists transcripts for each video,
calls Entrez summary for the PMID):

```bash
python scripts/verify_defaults.py
```

To run the test suite:

```bash
pytest -v                             # 184 tests, fully offline
```

---

## 3. What's actually in the box

### 3.1 Tools

| Layer | Library | Why |
|---|---|---|
| Blog | `requests` + `trafilatura` (primary), `BeautifulSoup4` selectors fallback | Trafilatura gives clean main text; BS4 catches edge cases via `article`, `main`, `[role=main]`, `.post-content`, `.entry-content`. Newspaper3k considered and rejected (unmaintained on Python 3.11). |
| YouTube | `yt-dlp` for metadata, `youtube-transcript-api>=1.2.4,<2.0` for transcripts | No API key needed for transcripts. The 1.x API is instance-based — `YouTubeTranscriptApi().fetch(video_id)`. The pinned range avoids 0.x breakage and a 2.x major-version change. |
| PubMed | `Bio.Entrez` (Biopython) | Official NCBI E-utilities client; returns parsed XML. |
| Topic tagging | `KeyBERT` with `all-MiniLM-L6-v2`; `yake` fallback | KeyBERT gives semantically meaningful tags via MMR; YAKE keeps the offline build alive when the model can't load. |
| Tokenization | `tiktoken` (`cl100k_base`) | Same encoder for paragraph chunker (200–500 tokens) and transcript chunker (250-token windows, 30-token overlap). |
| Language detection | `langdetect` | Cheap, works on ≥50-word inputs. |
| API | `FastAPI` + `uvicorn` | Auto-generated `/docs` doubles as a manual test affordance. |
| UI | `Streamlit` | Fastest path to a 4-tab UI with editable parameters. |
| Validation | `Pydantic v2` | `ScrapedRaw` and `ScrapedSource` are the single source of truth for the output schema. |

### 3.2 Trust score (0–1, 3 decimals)

```
trust_score = round(
    0.25 · author_credibility
  + 0.20 · citation_count
  + 0.20 · domain_authority
  + 0.20 · recency
  + 0.15 · medical_disclaimer_presence
, 3)
```

then post-aggregation multipliers (keyword stuffing 0.7×, old-medical
0.5×) clamped to [0, 1]. Full algorithm — including the explicit 6-step
application order — is in [`Task 2 Trust Score System Design/design.md`](./Task%202%20Trust%20Score%20System%20Design/design.md).
A condensed version is in [`REPORT.md`](./REPORT.md).

### 3.3 Output

Every scraped record is a `ScrapedSource` (Pydantic v2):

```jsonc
{
  "source_url":      "https://...",
  "source_type":     "blog" | "youtube" | "pubmed",
  "author":          "string" | ["multiple"] | null,
  "published_date":  "YYYY-MM-DD" | null,
  "language":        "en",                    // ISO 639-1
  "region":          "GB" | null,             // ISO 3166-1 alpha-2 if known
  "topic_tags":      ["...", "..."],
  "content_chunks":  ["...", "..."],
  "trust_score":     0.580,
  "trust_score_calculation": {                // explainability — how the score was reached
    "components":        { "author_credibility": 0.6, "citation_count": 1.0, ... },
    "weights":           { "author_credibility": 0.25, "citation_count": 0.20, ... },
    "contributions":     { "author_credibility": 0.15, "citation_count": 0.20, ... },
    "aggregated":        0.580001,            // sum(contributions)
    "post_multipliers":  { "keyword_stuffing": 0.7 },  // empty {} when none apply
    "final":             0.580                // clamp+round of aggregated × Π multipliers
  }
}
```

`output/scraped_data.json` is the canonical submission artifact. Every
record — across `blogs.json`, `youtube.json`, `pubmed.json`, and the
canonical `scraped_data.json` — carries `trust_score_calculation` so a
grader can audit the score without re-running the pipeline.

---

## 4. Project layout

```
TrustCrawler/
├── src/                                       # All real Python code lives here.
│   ├── schema.py                              # ScrapedRaw, ScrapedSource, TrustScoreCalculation, RawMetadata
│   ├── api.py                                 # FastAPI app — path-loads the three router shims
│   ├── defaults.py                            # DefaultSource(kind, target, label, rationale) × 6
│   ├── errors.py                              # ScrapingError, MetadataMissingError, TrustScoreError, WeightValidationError
│   ├── logging_config.py                      # get_logger(name) — reads LOG_LEVEL from env
│   ├── scrapers/
│   │   ├── blog.py                            # trafilatura + BS4 fallback + Wayback retry on 403
│   │   ├── youtube.py                         # yt-dlp + youtube-transcript-api 1.x
│   │   └── pubmed.py                          # Bio.Entrez + on-disk citation/author caches
│   ├── trust_score/
│   │   ├── compute.py                         # 6-step orchestration → TrustScoreCalculation
│   │   ├── weights.py                         # WEIGHTS + validate_weights (1.0 ± 1e-6)
│   │   ├── abuse_prevention.py                # data files loaded ONCE at import (pure runtime)
│   │   └── components/
│   │       ├── author_credibility.py
│   │       ├── citation_count.py
│   │       ├── domain_authority.py
│   │       ├── recency.py
│   │       └── medical_disclaimer.py
│   └── utils/
│       ├── tagging.py                         # KeyBERT (primary) + YAKE (offline fallback)
│       ├── chunking.py                        # paragraph chunker + transcript window chunker (tiktoken)
│       └── language.py                        # langdetect wrapper with confidence threshold
│
├── tests/                                     # 184 tests, fully offline (no network)
│   ├── test_api.py                            # FastAPI route + exception-handler tests
│   ├── test_errors.py                         # custom-exception payload tests
│   ├── test_schema.py                         # Pydantic round-trip + validator tests
│   ├── scrapers/
│   │   ├── conftest.py                        # autouse fixtures (KeyBERT stub, sleep no-op)
│   │   ├── test_blog.py                       # incl. wayback-fallback + 403-no-fallback tests
│   │   ├── test_youtube.py                    # incl. mandatory TranscriptsDisabled test
│   │   └── test_pubmed.py                     # incl. missing-affiliation + missing-email tests
│   ├── trust_score/
│   │   ├── test_compute.py                    # §6.3 edge cases + §6.4 application order
│   │   ├── test_abuse_prevention.py           # fake-author / keyword-stuffing / dedup
│   │   ├── test_weights.py                    # validator boundary cases
│   │   └── components/                        # one test file per component
│   └── utils/                                 # chunking / language / tagging
│
├── scripts/verify_defaults.py                 # pre-submission gate — every URL 200, every PMID resolves
│
├── Task 1 Multi-Source Scraper/               # Spec-mandated spaced folders (presentation layer).
│   ├── README.md                              # points at src/ for the real code
│   ├── main.py                                # CLI "Run All" — path-loads each shim, writes 4 JSONs
│   ├── ui/app.py                              # Streamlit UI: 4 tabs + editable Run-All plan + advanced params
│   ├── blog posts extractor/
│   │   ├── README.md
│   │   └── api.py                             # FastAPI router shim → src.scrapers.blog
│   ├── YouTube videos extractor/
│   │   ├── README.md
│   │   └── api.py                             # ditto for src.scrapers.youtube
│   ├── PubMed article extractor/
│   │   ├── README.md
│   │   └── api.py                             # ditto for src.scrapers.pubmed
│   └── output/
│       ├── blogs.json                         # per-type debugging files
│       ├── youtube.json
│       ├── pubmed.json
│       └── scraped_data.json                  # canonical submission artifact (concat of the three)
│
├── Task 2 Trust Score System Design/
│   ├── README.md                              # points at src/trust_score/
│   ├── design.md                              # full trust-score writeup with worked examples
│   └── data/                                  # loaded ONCE at module import in abuse_prevention.py
│       ├── README.md                          # provenance + criteria for each list
│       ├── domain_tiers.json                  # 4-tier authority map
│       ├── spam_domains.txt                   # forces tier 4 + post-aggregation 0.7×
│       └── known_orgs.txt                     # whitelist for the fake-author detector
│
├── sample-results/                            # Manually curated screenshots + sample JSONs.
├── Dockerfile                                 # CPU-only torch (~2.2 GB) + sentence-transformers + tiktoken pre-cache
├── docker-compose.yml                         # init: true, stop_grace_period: 5s, env_file: .env
├── run.sh                                     # trap SIGTERM/INT + wait -n → docker stop in <1 s
├── .dockerignore                              # keeps .env / output cache / .git out of the image
├── .env.example                               # PUBMED_EMAIL=..., USER_AGENT=..., LOG_LEVEL=...
├── pyproject.toml                             # ruff + pytest config; src as the package
├── requirements.txt                           # pinned dependency surface
├── README.md
└── REPORT.md                                  # 1–2 page short report
```

The folders with spaces are presentation-layer shims with no
`__init__.py`. Their entry-point files (`api.py`, `main.py`) are loaded
by file path via `importlib.util` — Python won't import them by module
name because the names contain spaces. All real code is under `src/`.

---

## 5. Project root name (spec drift)

The assignment spec asks for `Data Scraping Assignment/` as the on-disk
root. This project keeps `TrustCrawler/` — the existing repo name — to
avoid re-initing the working tree for a name-only change. The deviation
is **cosmetic**:

- The Dockerfile's `WORKDIR` is `/app` (arbitrary, not `/Data Scraping Assignment`).
- `docker-compose.yml` mounts the project root by relative path (`.:/app`).
- No Python module, shell script, or config file references either string literally.
- All Python imports go through `src.*`; the spec-mandated spaced folders are presentation-layer shims only.

A grader can rename `TrustCrawler/` to `Data Scraping Assignment/` after
unzipping with no functional impact.

---

## 6. Known limitations

- **Heavy-JS blogs** — `trafilatura` does not execute JavaScript. A Playwright fallback could be added but is out of scope.
- **Anti-bot hosts (Medium, X, LinkedIn, …)** — these fingerprint TLS handshakes and data-center IPs and 403 regardless of User-Agent. The scraper transparently retries through the Wayback Machine (`https://web.archive.org/web/2025/<url>`) for these hosts; the returned record's `source_url` is the original URL. If the Wayback snapshot is missing, the original 403 + the Wayback status code are both surfaced in the error payload.
- **YouTube transcripts** depend on creator-uploaded or auto-generated captions; some videos have neither. The scraper falls back to the description and sets `meta["transcript_available"] = False`.
- **`youtube-transcript-api` fragility** — depends on undocumented YouTube internals and has broken before. The pinned version range (`>=1.2.4,<2.0`) is known-working as of submission; the description fallback covers the case where YouTube changes break it.
- **PubMed citation count** via ELink can be slow; results are cached in `output/.cache/citations_<pmid>.json` and per-author ESearch counts in `output/.cache/pubmed_authors.json`. The first `docker run` is the only slow one.
- **Domain authority** is heuristic (static tier list in `Task 2 Trust Score System Design/data/domain_tiers.json`), not a live Moz/Ahrefs lookup.
- **Topic tagging** quality depends on the KeyBERT model. The Docker image pre-caches it (~90 MB); offline builds without Docker fall back to YAKE, which is noisier.
- **Trust-score weights** are reasoned defaults, not empirically tuned.
- **PubMed author credibility** lookups scale O(authors × articles) and are cached. Large author lists make the first run slow.
- **Image size** — the Docker image is ~2.2 GB. CPU-only torch keeps it well below the 6 GB the default CUDA wheels would have produced, but torch + transformers is still the bulk of the image.

---

## 7. Running tests

```bash
pytest -v                                  # 184 tests, all offline
ruff check src/ tests/ scripts/ "Task 1 Multi-Source Scraper"  # lint clean
```

Scraper tests use monkeypatched fakes for `requests`, `Bio.Entrez`,
`yt_dlp`, and `youtube_transcript_api` — they never touch the network.
The full suite runs in about 1.2 seconds.

---

## 8. Help / docs

- [`REPORT.md`](./REPORT.md) — 1–2 page short report (scraping, tagging, trust score, edge cases).
- [`Task 2 Trust Score System Design/design.md`](./Task%202%20Trust%20Score%20System%20Design/design.md) — full trust-score writeup with worked examples.
- [`CLAUDE.md`](./CLAUDE.md) — project specification (tech stack, schemas, edge-case behavior).
- [`plan.txt`](./plan.txt) — phased implementation plan (sequencing rationale).
