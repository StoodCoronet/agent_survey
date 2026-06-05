"""Venue-specific abstract fetchers.

Simple HTTP-based fetchers (USENIX, NDSS, Crossref) are registered in
VENUE_FETCHERS or used directly by the main enrich stage.

Playwright-based fetchers (ACM, IEEE) require a shared Browser
instance and are called directly from the `enrich-web` fallback
stage to avoid launching a browser per worker.
"""
from __future__ import annotations

from .acm import fetch_acm_abstract
from .crossref import fetch_crossref_abstract
from .ieee import fetch_ieee_abstract
from .ndss import fetch_ndss_abstract
from .usenix import fetch_usenix_abstract

VENUE_FETCHERS: dict[str, callable] = {
    "USS": fetch_usenix_abstract,
    "NDSS": fetch_ndss_abstract,
}
