# Trust Score — static lookup data

These files are loaded **once** at module import in
`src/trust_score/abuse_prevention.py`. Runtime functions do not touch the
filesystem (per the §6.5 determinism contract in `CLAUDE.md`).

| File                | Format        | Populated in | Provenance / criteria |
|---------------------|---------------|--------------|------------------------|
| `domain_tiers.json` | JSON          | Phase 2      | Tier 1: `.gov`/`.edu` suffixes + curated authoritative domains (`nih.gov`, `who.int`, `nature.com`, …). Tier 2: established mainstream news/blogs. Tier 3: default for unknown domains (assigned at runtime, not enumerated). Tier 4: SEO-spam matches via `spam_domains.txt`. |
| `spam_domains.txt`  | one per line  | Phase 2      | A handful of well-known SEO content farms. Illustrative, not exhaustive — a real deployment would replace this with a reputation-feed lookup. |
| `known_orgs.txt`    | one per line  | Phase 2      | Legitimate organisations that look unusual to the fake-author detector ("WHO Collaborating Centre on…"). Suppresses false positives only — does NOT grant a credibility bonus. |

There is intentionally no `known_authors.txt` allow-list. The original
spec referenced one as a `+0.2` bonus for blog authors, but the rule was
removed because a hand-curated list of 5–10 names reads as cherry-picking
in a small assignment. See plan.txt §A19 / CLAUDE.md §6.1 for the rationale.

## Conventions

- **`spam_domains.txt`** — one domain per line, lowercase, no protocol
  prefix, no comments. Sort alphabetically.
- **`known_orgs.txt`** — one org name per line in its canonical
  human-readable casing (matching is case-insensitive at runtime). Sort
  alphabetically (case-insensitive). No comments.
- **`domain_tiers.json`** — the loader reads only `scores`, `suffix_to_tier`,
  and `domains`. Any key beginning with `_` is documentation and ignored
  at runtime, so `_notes` is the safe place to leave editorial comments
  (JSON has no native comment syntax).
