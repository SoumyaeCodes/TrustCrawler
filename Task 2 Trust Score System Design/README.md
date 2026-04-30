# Task 2 — Trust Score System Design

This folder is a **presentation-layer shim** required by the assignment spec.
It contains no Python packages — the real implementation lives under
[`src/trust_score/`](../src/trust_score/) at the project root.

| Item                | Real location                                    |
|---------------------|--------------------------------------------------|
| Scoring orchestrator | `src/trust_score/compute.py`                    |
| Component scores    | `src/trust_score/components/*.py`                |
| Abuse prevention    | `src/trust_score/abuse_prevention.py`            |
| Weights + validator | `src/trust_score/weights.py`                     |

The `data/` subfolder holds the static lookup tables that
`abuse_prevention.py` loads **once** at module import (per the §6.5
determinism contract in `CLAUDE.md`):

- `domain_tiers.json` — tier 1–4 domain authority map
- `spam_domains.txt` — known SEO-spam domains (forces tier 4)
- `known_orgs.txt` — legitimate orgs that look unusual; suppress fake-author flag

`design.md` is the written explanation of the scoring algorithm,
component formulas, application order, and worked examples.
