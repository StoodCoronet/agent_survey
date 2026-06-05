"""Harvest strategies for venues that need special handling."""
from __future__ import annotations

# Venue-specific Playwright URLs (last-resort fallback)
# These are only used when both DBLP XML TOC and Search API fail.
VENUE_PLAYWRIGHT_URLS: dict[str, dict[int, str]] = {
    "FSE": {
        2024: "https://2024.esec-fse.org/track/fse-2024-research-papers",
        2025: "https://conf.researchr.org/track/fse-2025/fse-2025-research-papers",
    },
    "ISSTA": {
        2025: "https://conf.researchr.org/track/issta-2025/issta-2025-papers",
    },
}
