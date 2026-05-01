# Data Scraping Assignment — Short Report

**Author:** soumyae663@gmail.com  &nbsp;·&nbsp;  **Project root:** `TrustCrawler/`  &nbsp;·&nbsp;  **Submission date:** 2026-04-30

This is the 1–2 page companion to `README.md` and
`Task 2 Trust Score System Design/design.md`. It explains *why* the
project looks the way it does — the choices, their trade-offs, and the
edge cases each one has to survive.

---

## 1. Scraping strategy (per source type)

**Blogs — `src/scrapers/blog.py`.** Two-stage extraction. `trafilatura.extract`
runs first (`favor_recall=True`, `output_format="json"`), giving title,
author, date, and main text in one pass. When trafilatura returns
nothing — Wikipedia and a few CMS layouts trip it — the fallback walks
selectors `article`, `main`, `[role=main]`, `.post-content`,
`.entry-content` in order, and accepts the first node whose text is
≥200 words. Below that threshold the scraper raises `ScrapingError`
rather than emit a half-empty record. Author and date both have an
explicit priority order: JSON-LD → meta tags → `<time datetime>` → trafilatura.
Region is derived only from a country-code TLD (`.uk → GB`, `.de → DE`, …);
generic TLDs (`.com`, `.org`, `.io`) yield `None` rather than a guess.

**YouTube — `src/scrapers/youtube.py`.** Metadata via `yt-dlp` (no API key
required); transcripts via the `youtube-transcript-api` 1.x **instance-based**
client — `YouTubeTranscriptApi().fetch(video_id, languages=...)`. Languages
cascade: hint → `"en"` → first available. When `TranscriptsDisabled` or
`NoTranscriptFound` fires, the scraper falls back to the description and
records `meta["transcript_available"] = False` (a unit test asserts this
path produces a valid `ScrapedRaw`). Transcript segments are grouped
into 250-token windows with 30-token overlap, sized with the `cl100k_base`
tiktoken encoder.

**PubMed — `src/scrapers/pubmed.py`.** `Bio.Entrez.efetch` returns parsed
XML; we extract title, author list, abstract (preserving labels like
`BACKGROUND:` / `METHODS:` when present), and `Journal/JournalIssue/PubDate`.
Citation count comes from `Entrez.elink(linkname="pubmed_pubmed_citedin")`
and is cached to `output/.cache/citations_<pmid>.json`. Author
credibility uses a per-author `ESearch` count cached to
`output/.cache/pubmed_authors.json` keyed by `last_name|first_initial`,
so the second run of the same article is a no-op against NCBI. Region
comes from the first author's affiliation country, fuzzy-matched via
`pycountry.countries.search_fuzzy` — but only when the search returns
exactly one candidate, so ambiguous strings yield `None` rather than a
wrong country.

---

## 2. Topic tagging

`src/utils/tagging.py` concatenates the title with the first 2000
characters of the body and runs `KeyBERT` with `keyphrase_ngram_range=(1,3)`,
`top_n=8`, `use_mmr=True`, `diversity=0.5`. MMR gives diverse phrases
rather than five paraphrases of one keyword. Output is lowercased,
deduplicated, and stripped of stopword-only phrases. If KeyBERT can't
load the model (offline build, missing wheel), the scraper falls back
to `yake.KeywordExtractor(n=3, top=8)` — noisier but always available.
The Docker image pre-caches the `all-MiniLM-L6-v2` backbone at build
time so the first scrape is offline-clean.

---

## 3. Trust-score algorithm

The score is a weighted sum of five components in [0, 1], with two
post-aggregation multipliers:

| Component | Default weight | Logic |
|---|---|---|
| `author_credibility` | 0.20 | PubMed: 1.0 if any author has ≥3 prior PubMed hits, else 0.7; Blog: 0.6 baseline + 0.2 if an author bio page exists on the same domain; YouTube: 0.5 + 0.5·min(subscribers / 1 M, 1.0). Multi-author → arithmetic mean. Missing author → 0.3. |
| `citation_count` | 0.15 | PubMed: `min(log10(1 + citations) / 3, 1.0)`. Blog/YouTube: count of outbound links to `.gov` / `.edu` / PubMed / DOI domains, normalized via `min(count / 10, 1.0)`. |
| `domain_authority` | 0.30 | Static tier map in `data/domain_tiers.json`: tier 1 (`.gov`, `.edu`, `nih.gov`, `nature.com`, …) = 1.0; tier 2 (NYT, BBC, Reuters, …) = 0.7; tier 3 (unknown) = 0.4; tier 4 (`spam_domains.txt`) = 0.1. YouTube: derived from `channel_verified` + subscribers. |
| `recency` | 0.10 | `exp(−age_days / τ)` where τ = 730 days (general) or 1825 days (medical). Implied half-lives are `ln(2)·τ` ≈ 506 days general, ≈ 1265 days medical. Missing date → 0.3. Future dates → clamped to `age_days = 0`. |
| `medical_disclaimer_presence` | 0.25 | Only weighted when `meta["is_medical"]` is true (i.e., `topic_tags` ∩ medical-keyword set is non-empty). Regex bank for "consult … doctor", "not medical advice", etc. Present → 1.0; absent on medical → 0.2; non-medical → 1.0 (neutral). |

**Why these weights** (vs. the original equal-ish 0.25/0.20×4/0.15 split): observation against the 6 default sources showed `domain_authority` was the cleanest cross-source signal and `recency` was the noisiest (Wikipedia exposes the article's *first*-revision date in JSON-LD — a useless freshness signal for living content). `medical_disclaimer_presence` was bumped because non-medical content already gets a neutral 1.0, so a higher weight only changes scoring on medical content where it's most relevant. `citation_count` was reduced because half the batch (YouTube + the default PMID with no ELink data) can't earn the signal at all.

**Application order** (the rule that surprised me when I worked through
worked examples — multipliers must apply in this exact sequence to keep
results stable):

1. Compute every component score.
2. Apply **component-level** multipliers — the 0.3× fake-author penalty modifies `author_credibility` before aggregation.
3. Compute the weighted sum.
4. Apply **post-aggregation** multipliers — keyword stuffing (0.7×) and old-medical (0.5×) chain multiplicatively.
5. Clamp to [0, 1].
6. Round to 3 decimals.

Weights live in `src/trust_score/weights.py` as a `WEIGHTS` constant.
`validate_weights(w)` raises `WeightValidationError` if any weight is
outside [0, 1] or the values do not sum to 1.0 within 1e-6. The
Streamlit UI calls this on every keystroke; the API calls it on
receipt. The Run button is disabled when the override fails.

---

## 4. Region heuristic

A separate concern from authority. Defaults to `None`, populated only
on unambiguous signals:

- **PubMed**: first-author affiliation country via `pycountry.countries.search_fuzzy`. Multiple matches → discarded.
- **Blog**: ccTLD only. `.uk → GB`, `.de → DE`, `.fr → FR`, `.jp → JP`, `.in → IN`, etc. Generic TLDs (`.com`, `.org`, `.net`, `.io`) yield `None`.
- **YouTube**: channel `country` field via the YouTube Data API, only when `YOUTUBE_DATA_API_KEY` is set; otherwise `None`.

The point is to avoid plausible-but-wrong country guesses. A `.com`
domain run by a German author is `region = None`, not `region = US`.

---

## 5. Edge cases (each has a unit test)

| Case | Expected behavior |
|---|---|
| Missing author | `author_credibility = 0.3` (penalty, not crash). |
| Missing date | `recency = 0.3`. |
| Future-dated content | `age_days` clamped to 0 (no >1.0 recency). |
| No transcript on YouTube | Falls back to description; `transcript_available = False`. |
| Multiple authors | Mean of per-author credibility. |
| Non-English content | No score penalty; `language` set correctly. |
| Very long articles | Chunker hard-caps at 10 k tokens with a logged truncation warning — no OOM. |
| Missing PubMed `AffiliationInfo` | `region = None`, `meta["affiliations"] = []`. |
| PubMed without `PUBMED_EMAIL` | Raises `MetadataMissingError` → API returns HTTP 422 with the missing-field name. |
| Duplicate run-scoped content | First-1000-char SHA-1 hash; subsequent matches are skipped, not re-scored. |
| Bad weights from the UI/API | `WeightValidationError` → HTTP 400 with offending dict. |

---

## 6. Abuse prevention

`src/trust_score/abuse_prevention.py` loads three data files **once** at
module import (`domain_tiers.json`, `spam_domains.txt`,
`known_orgs.txt`) so the runtime functions are pure and tests can
monkeypatch the constants without touching the filesystem. Four rules:

- **Fake authors**: red-flag detection (all-caps gibberish; >5 honorifics; ≥2 honorifics + ≤1 name token). Triggers a 0.3× component multiplier on `author_credibility`. `known_orgs.txt` whitelists legitimate weird-looking names ("Bill & Melinda Gates Foundation", "WHO Collaborating Centre …") so the heuristic doesn't false-positive them.
- **SEO spam**: `spam_domains.txt` forces `domain_authority = 0.1`. Keyword density >4 % of body text triggers the 0.7× post-aggregation multiplier.
- **Misleading medical**: medical topic without disclaimer → `medical_disclaimer_presence = 0.2` (handled component-side, no separate multiplier).
- **Outdated medical**: `age_days > 3650` (10 years) on medical content → 0.5× post-aggregation multiplier on top of the recency decay.

---

## 7. With more time

- Add a Playwright fallback for heavy-JS blogs.
- Tune the trust-score weights against a labelled set rather than reasoned defaults.
- Replace the static `domain_tiers.json` with a live reputation feed (Moz / Ahrefs / NewsGuard).
- Build a side-by-side explainer view in the UI showing each component and multiplier in the score breakdown, instead of just the final number.
- Cache the YouTube channel-info result per-channel (currently only PubMed citation/author counts are cached).
