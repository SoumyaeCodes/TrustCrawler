"""Custom exceptions for the scraping/trust-score pipeline.

Each exception accepts an optional `details: dict` payload that the API
exception handlers serialize into the HTTP response body (CLAUDE.md §11).
"""

from __future__ import annotations


class ScrapingError(Exception):
    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details: dict = details or {}


class MetadataMissingError(ScrapingError):
    pass


class TrustScoreError(Exception):
    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details: dict = details or {}


class WeightValidationError(TrustScoreError):
    pass
