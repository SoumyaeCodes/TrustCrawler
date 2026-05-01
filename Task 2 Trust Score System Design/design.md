# Trust Score — Design Notes

This document explains the trust-score algorithm implemented in
`src/trust_score/`. It complements `CLAUDE.md` §6 with concrete
formulas, the 6-step application order, the determinism contract, and
two worked examples.

---

## 1. Inputs

`compute_trust_score(raw: ScrapedRaw, meta: RawMetadata) -> ScrapedSource`

- **`raw`** — the structured fields the scraper produced (URL, source
  type, author, date, language, region, topic tags, content chunks).
- **`meta`** — auxiliary signals the scraper produced alongside `raw`:
  citations, subscriber count, channel verification, outbound links,
  transcript availability, body text, medical-content flag,
  affiliations, etc. Defined as a `TypedDict(total=False)` in
  `src/schema.py` so each scraper only fills what it can.

---

## 2. Components

Each component returns a float in `[0, 1]`. Symbols below match the
constants in `src/trust_score/components/*.py`.

| Component | Formula |
|---|---|
| `author_credibility` | **PubMed**: per author, 1.0 if `prior_articles ≥ 3` else 0.7; arithmetic mean across `meta["author_prior_articles"]`. **Blog**: 0.6 baseline + 0.2 if `meta["author_bio_on_domain"]`. **YouTube**: 0.5 + 0.5 · `min(subs / 1_000_000, 1.0)`. **Missing author** → 0.3. **Fake author** (any of `is_fake_author`) → multiplied by 0.3 *here*, not after the weighted sum. |
| `citation_count` | **PubMed**: `min(log10(1 + meta["citations"]) / 3, 1.0)` (so 1k citations ≈ 1.0). **Blog/YouTube**: count outbound links to `.gov`, `.edu`, `pubmed.ncbi.nlm.nih.gov`, `ncbi.nlm.nih.gov`, `doi.org`, then `min(count / 10, 1.0)`. |
| `domain_authority` | Static lookup against `data/domain_tiers.json` (loaded once at import). Tier 1 = 1.0, Tier 2 = 0.7, Tier 3 = 0.4 (default), Tier 4 = 0.1 (forced by `spam_domains.txt` match). Spam wins over explicit tier; explicit tier wins over suffix; suffix wins over default. **YouTube**: derived from `channel_verified` + `subs` (verified ≥100K → 1.0; verified small → 0.7; unverified ≥1M → 0.7; otherwise 0.4). |
| `recency` | `exp(-age_days / τ)`. τ = 730 days (general) or 1825 (medical, when `meta["is_medical"]`). Implied half-lives are `ln(2)·τ` ≈ 506 days (general) and ≈ 1265 days (medical). Future dates clamp to `age = 0`. **Missing date** → 0.3. |
| `medical_disclaimer_presence` | Only meaningful when `meta["is_medical"]`. Regex bank in `src/trust_score/components/medical_disclaimer.py` matches "not medical advice", "consult [your] doctor", "for informational purposes", "diagnose, treat, cure", "seek medical advice". Match → 1.0; medical with no match → 0.4 (softened from the original 0.2 floor). For **non-medical** content the orchestrator drops this component and rescales the remaining 4 weights to sum to 1.0 — otherwise the neutral 1.0 would grant every non-medical article a free `weights[disclaimer]` floor. **Tier-1 sources are exempt** from the absent-disclaimer penalty (PubMed always; tier-1 hosts via `is_tier_1_source`) — peer review / institutional authority is the implicit caveat. |

The medical-keyword set used to compute `meta["is_medical"]` is exported
from `medical_disclaimer.py` and consumed by scrapers — there is one
canonical definition of "medical content" in the codebase.

---

## 3. Weights

Defined in `src/trust_score/weights.py`:

```python
WEIGHTS = {
    "author_credibility":          0.25,
    "citation_count":              0.20,
    "domain_authority":            0.20,
    "recency":                     0.20,
    "medical_disclaimer_presence": 0.15,
}
```

These sum to 1.000. `validate_weights()` enforces:
- exactly the canonical key set,
- every value numeric and in `[0, 1]`,
- `|sum − 1.0| ≤ 1e-6`.

UI overrides go through `validate_weights()` before reaching
`compute_trust_score`; out-of-range or wrong-sum overrides raise
`WeightValidationError` which the API maps to HTTP 400.

The weights are reasoned defaults, not empirically tuned — see
`README.md` §14 limitations. Author and citation weight more than the
others because (a) author credibility is the hardest single signal to
fake and (b) citations are the most directly checkable evidence of a
claim's standing.

---

## 4. Application order (§6.4)

The orchestrator in `src/trust_score/compute.py` follows this exact sequence:

1. **Compute each component score.**
2. **Component-level multipliers.** Currently: the 0.3× fake-author
   penalty applied inside `author_credibility.score()`. Each component
   owns its own pre-aggregation multipliers.
3. **Resolve effective weights.** If `meta["is_medical"]` is true,
   weights pass through unchanged. Otherwise the orchestrator drops
   the `medical_disclaimer_presence` component (sets its weight to 0)
   and rescales the remaining 4 weights by `1 / (1 − w_disclaimer)` so
   they sum to 1.0 again. Without this, the disclaimer's neutral 1.0
   for non-medical content would grant a free `w_disclaimer` floor on
   every non-medical score.
4. **Weighted sum.** `aggregated = Σ effective_weight[k] · component[k]`.
5. **Post-aggregation multipliers.** Two:
   - keyword stuffing (>4% non-stopword density, only on bodies ≥350 words to avoid false-tripping on short transcripts) → ×0.7
   - old-medical content (`is_medical` and `age > 3650 days`, non-tier-1 source) → scaled `max(0.6, 1 - (age_days - 3650) / 12000)`. Tier-1 hosts (PubMed, `nih.gov`, `who.int`, `nature.com`, …) are exempt so canonical references aren't double-penalized.
   Multiple multipliers compound multiplicatively.
6. **Clamp** to `[0, 1]`.
7. **Round** to 3 decimals.

The order matters: applying the keyword-stuffing multiplier *before*
component-level multipliers would let the fake-author flag and the
spam-domain forcing both ride on top, double-counting them through
post-aggregation. The 7-step ordering keeps each penalty in exactly one
place.

---

## 5. Determinism contract (§6.5)

Data files (`domain_tiers.json`, `spam_domains.txt`, `known_orgs.txt`)
load **once** at module import in `abuse_prevention.py`. The runtime
helpers (`domain_to_score`, `is_fake_author`, `has_keyword_stuffing`,
`DuplicateTracker.is_duplicate`) are pure given the loaded constants —
no I/O, no network calls. Tests monkeypatch the constants
(`tests/trust_score/test_abuse_prevention.py`) rather than touching the
filesystem.

`compute_trust_score` is pure given `(raw, meta, weights, today)`. The
optional `today` parameter is the only "wall-clock" input; passing it
explicitly makes the function fully deterministic for tests.

---

## 6. Edge cases (§6.3)

Each is covered by a unit test in `tests/trust_score/`:

- Missing author → `author_credibility = 0.3`.
- Missing date → `recency = 0.3`.
- Multi-author PubMed → arithmetic mean per author.
- Future-dated content → `age` clamped to 0; `recency ≤ 1.0`.
- Non-English content → no score penalty.
- No transcript on YouTube → `meta["transcript_available"] = False`,
  pipeline continues.
- Very long articles → chunker truncates at 10k tokens before reaching
  `compute_trust_score` (covered in `tests/utils/test_chunking.py`).

---

## 7. Worked examples

### 7.1 High-trust .gov medical article

Input:
- URL: `https://nih.gov/treatment-guide`
- author: "Jane Researcher", `author_bio_on_domain = True`
- published: 180 days ago, `is_medical = True`
- body contains "for informational purposes" + "consult your doctor"
- outbound links: `[nih.gov, doi.org]`

Components:
- `author_credibility` = 0.6 + 0.2 = **0.8**
- `citation_count` = `min(2 / 10, 1.0)` = **0.2**
- `domain_authority` = nih.gov → tier 1 → **1.0**
- `recency` = `exp(-180/1825)` ≈ **0.906**
- `medical_disclaimer_presence` = match → **1.0**

Aggregated: `0.25·0.8 + 0.20·0.2 + 0.20·1.0 + 0.20·0.906 + 0.15·1.0 = 0.781`.
No post-aggregation multipliers fire. Final: **0.781** → rounded **0.781**.

### 7.2 Low-trust SEO blog

Input:
- URL: `https://ehow.com/get-rich`
- author: "SEO Bot"
- published: 2000 days ago
- body: `"click here " × 200`, `is_medical = False`

Components:
- `author_credibility` = 0.6 (baseline blog) — author isn't flagged as
  fake by the heuristic ("SEO Bot" has no honorifics)
- `citation_count` = 0 (no authoritative outbound links)
- `domain_authority` = `spam_domains.txt` match → tier 4 → **0.1**
- `recency` = `exp(-2000/730)` ≈ **0.064**
- `medical_disclaimer_presence` = 1.0 (non-medical, neutral)

Aggregated: `0.25·0.6 + 0.20·0 + 0.20·0.1 + 0.20·0.064 + 0.15·1.0 = 0.333`.

Post-aggregation multipliers:
- keyword stuffing (max non-stopword density ≈ 50%) → ×0.7

Final: `0.333 · 0.7 = 0.233` → rounded **0.233**.

The two examples differ by ~0.55 on the same 0–1 scale, which is the
intended dynamic range. A "neutral" blog with average everything lands
near 0.5.

---

## 8. Limitations

- Weights are reasoned, not learned — there is no labelled training set
  here, so the 0.25/0.20/0.20/0.20/0.15 split is editorial.
- Domain authority is a static tier list, not a live Moz/Ahrefs lookup.
  Re-tiering means editing JSON.
- Author credibility for blogs depends on a "bio page exists on domain"
  signal that the scraper produces heuristically; false negatives are
  common for personal-site author pages with non-standard URL patterns.
- The fake-author heuristic catches obvious red flags (excessive
  honorifics, all-caps gibberish) but is intentionally permissive — a
  real author should never be flagged.
- `data/spam_domains.txt` is a stand-in for a reputation feed; in
  production you would replace it with a live source.
