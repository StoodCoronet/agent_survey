"""arXiv web search fallback using Playwright + rapidfuzz title matching.

This module is a port of reference/arxiv_api_crawler tailored for the
survey-mining download phase.  It is invoked ONLY when the arXiv API search
fails to find a paper by title.

Environment:
- Strips proxy env vars via launch(env=...) so Playwright connects directly
  to arXiv without polluting global os.environ.
- Uses headless Chromium with anti-detection measures.
- Persists cookies/storage_state across sessions to reduce detection risk.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

TITLE_MATCH_THRESHOLD = 0.85

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_COOKIES_DIR = Path(__file__).parent.parent.parent.parent / "cache" / "playwright"
_COOKIES_DIR.mkdir(parents=True, exist_ok=True)
_COOKIES_PATH = _COOKIES_DIR / "arxiv.json"

_VIEWPORT = {"width": 1440, "height": 900}
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Strip proxy env vars inside launch() via env= rather than global mutation.
_ALLOWED_ENV_KEYS = {
    k for k in os.environ.keys()
    if k.upper() not in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class ArxivWebResult:
    success: bool = False
    arxiv_id: str | None = None
    pdf_url: str | None = None
    landing_url: str | None = None
    title_matched: str = "none"  # exact | fuzzy | none
    title_score: float = 0.0
    confidence: str = "low"  # high | medium | low
    authors: list[str] = field(default_factory=list)
    error: str | None = None
    debug_log: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Title utilities
# ---------------------------------------------------------------------------
def _clean_title_for_search(title: str) -> str:
    """Replace all non-alphabetic chars with spaces so arXiv search doesn't choke."""
    cleaned = re.sub(r"[^a-zA-Z]", " ", title)
    return re.sub(r"\s+", " ", cleaned).strip()


def _generate_search_variants(title: str) -> list[str]:
    """Generate multiple cleaned title variants to try on arXiv."""
    variants: list[str] = [_clean_title_for_search(title)]
    if ":" in title:
        parts = title.split(":", 1)
        variants.append(_clean_title_for_search(parts[0].strip()))
        variants.append(_clean_title_for_search(parts[1].strip()))
    seen: set[str] = set()
    unique: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            unique.append(v)
    return unique


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def _match_title(query_title: str, extracted_title: str) -> tuple[float, str]:
    """Return (score, confidence)."""
    from rapidfuzz import fuzz

    score = fuzz.ratio(query_title.lower(), extracted_title.lower()) / 100.0
    if score >= 0.95:
        return score, "high"
    elif score >= TITLE_MATCH_THRESHOLD:
        return score, "medium"
    else:
        return score, "low"


# ---------------------------------------------------------------------------
# Browser helpers (with cookie persistence and isolated env)
# ---------------------------------------------------------------------------
def _launch_browser(headless: bool = True):
    """Launch Chromium with anti-detection, cookie restore, and isolated env."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=headless,
        args=[
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--disable-infobars",
        ],
        env={k: os.environ[k] for k in _ALLOWED_ENV_KEYS},
    )
    context_kwargs: dict = {"viewport": _VIEWPORT, "user_agent": _USER_AGENT}
    if _COOKIES_PATH.exists():
        context_kwargs["storage_state"] = str(_COOKIES_PATH)
    context = browser.new_context(**context_kwargs)
    page = context.new_page()
    page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    return pw, browser, context, page


def _close_browser(pw, browser, context):
    """Close browser and persist cookies for next session."""
    if context is not None:
        try:
            _COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(_COOKIES_PATH))
        except Exception:
            pass
        context.close()
    if browser is not None:
        browser.close()
    if pw is not None:
        pw.stop()


# ---------------------------------------------------------------------------
# Core search
# ---------------------------------------------------------------------------
def search_arxiv_web(
    title: str,
    headless: bool = True,
    timeout_ms: int = 30000,
) -> ArxivWebResult:
    """Search arXiv web interface by title with multi-variant fuzzy matching.

    Returns ArxivWebResult with arxiv_id / pdf_url when a confident match is found.
    """
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    except ImportError as exc:
        return ArxivWebResult(error=f"Playwright not installed: {exc}")

    result = ArxivWebResult()
    variants = _generate_search_variants(title)
    pw = browser = context = page = None

    try:
        pw, browser, context, page = _launch_browser(headless=headless)

        for variant_idx, search_title in enumerate(variants, 1):
            q = urllib.parse.quote(search_title)
            url = (
                f"https://arxiv.org/search/?query={q}"
                "&searchtype=title&source=header&order=-announced_date_first"
            )
            result.debug_log.append(f"[variant {variant_idx}/{len(variants)}] URL: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except PlaywrightTimeoutError:
                result.debug_log.append("  → timeout loading page")
                continue

            try:
                page.wait_for_selector(".arxiv-result, .no-results", timeout=15000)
            except PlaywrightTimeoutError:
                result.debug_log.append("  → timeout waiting for results")
                continue

            if page.query_selector(".no-results"):
                result.debug_log.append("  → no-results banner found")
                continue

            result_elems = page.query_selector_all(".arxiv-result")
            if not result_elems:
                result.debug_log.append("  → 0 result elements found")
                continue

            result.debug_log.append(f"  → {len(result_elems)} result element(s) found")

            best_elem = None
            best_score = 0.0
            candidates: list[tuple[str, float]] = []
            for elem in result_elems:
                title_elem = elem.query_selector("p.title")
                extracted = title_elem.inner_text().strip() if title_elem else ""
                score, _ = _match_title(title, extracted)
                candidates.append((extracted, score))
                if score > best_score:
                    best_score = score
                    best_elem = elem

            for ext, sc in candidates:
                result.debug_log.append(f"      candidate: score={sc:.2f} | {ext[:120]}")

            if best_elem is None:
                result.debug_log.append("  → no best element selected")
                continue

            extracted_title = best_elem.query_selector("p.title").inner_text().strip()
            score, confidence = _match_title(title, extracted_title)
            result.title_score = score
            result.confidence = confidence
            result.title_matched = (
                "exact" if score >= 0.95 else ("fuzzy" if score >= TITLE_MATCH_THRESHOLD else "none")
            )
            result.debug_log.append(
                f"  → best match: score={score:.2f} confidence={confidence} | {extracted_title[:120]}"
            )

            if confidence == "low":
                result.debug_log.append("  → rejected: confidence too low")
                continue

            # Extract landing URL
            abs_link = best_elem.query_selector('a[href*="/abs/"]')
            if abs_link:
                href = abs_link.get_attribute("href")
                if href:
                    result.landing_url = (
                        "https://arxiv.org" + href if href.startswith("/abs/") else href
                    )
                    result.arxiv_id = href.split("/abs/")[-1].split("v")[0]

            # Extract PDF URL (prefer link; fall back to inference from landing_url)
            pdf_link = best_elem.query_selector('a[href*="/pdf/"]')
            if pdf_link:
                href = pdf_link.get_attribute("href")
                if href:
                    result.pdf_url = (
                        "https://arxiv.org" + href if href.startswith("/pdf/") else href
                    )
            if not result.pdf_url and result.landing_url:
                abs_id = result.landing_url.split("/abs/")[-1].split("v")[0]
                result.pdf_url = f"https://arxiv.org/pdf/{abs_id}.pdf"
                result.debug_log.append(f"  → inferred PDF URL from landing page")

            # Extract authors (best-effort)
            authors_elem = best_elem.query_selector(".authors")
            if authors_elem:
                authors_text = authors_elem.inner_text()
                result.authors = [
                    a.strip()
                    for a in authors_text.replace("Authors:", "").split(",")
                    if a.strip()
                ]

            result.success = True
            break

        if not result.success:
            result.error = f"All {len(variants)} variants exhausted without confident match"

    except Exception as exc:
        result.error = str(exc)
    finally:
        _close_browser(pw, browser, context)

    return result
