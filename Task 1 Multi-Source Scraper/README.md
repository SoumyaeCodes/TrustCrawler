# Task 1 — Multi-Source Scraper

This folder is a **presentation-layer shim** required by the assignment spec.
It contains no Python packages — the real implementation lives under `src/`
at the project root.

The folder name has spaces in it on purpose (the spec is explicit). Python
cannot import from a folder whose name contains spaces, so:

- There is no `__init__.py` in this folder or in any of its subfolders.
- The entry-point files (`main.py`, each extractor's `api.py`, `ui/app.py`)
  import from `src.*` using normal import syntax.
- When the orchestrator (`main.py`) needs to reach into one of the spaced
  extractor folders, it loads the file by **path** via `importlib.util` —
  the folder name with spaces never appears in an `import` statement.

| Folder                       | Real implementation                          |
|------------------------------|----------------------------------------------|
| `blog posts extractor/`      | `src/scrapers/blog.py`                       |
| `YouTube videos extractor/`  | `src/scrapers/youtube.py`                    |
| `PubMed article extractor/`  | `src/scrapers/pubmed.py`                     |
| `ui/app.py`                  | imports from `src.*`                         |
| `output/scraped_data.json`   | canonical submission file (written by `main.py`) |

See `CLAUDE.md` §2 for the full layout rationale.
