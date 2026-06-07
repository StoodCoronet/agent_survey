"""arXiv web search fallback using Playwright + rapidfuzz title matching.

This module is a port of reference/arxiv_search_crawler tailored for the
survey-mining download phase.  It is invoked ONLY when the arXiv API search
fails to find a paper by title.

Environment:
- Strips proxy env vars before starting Playwright (arXiv should be direct).
- Uses headless Chromium with anti-detection measures.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from dataclasses import dataclass

# Strip proxy env vars so Playwright connects directly to arXiv.
for _proxy_var in (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
):
    os.environ.pop(_proxy_var, None)


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


@dataclass
class ArxivWebResult:
    success: bool = False
    arxiv_id: str | None = None
    pdf_url: str | None = None
    landing_url: str | None = None
    title_matched: str = "none"  # exact | fuzzy | none
    title_score: float = 0.0
    confidence: str = "low"  # high | medium | low
    error: str | None = None


TITLE_MATCH_THRESHOLD = 0.85


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
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return ArxivWebResult(error=f"Playwright not installed: {exc}")

    result = ArxivWebResult()
    variants = _generate_search_variants(title)

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=headless,
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-session-crashed-bubble",
                "--disable-infobars",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        for variant_idx, search_title in enumerate(variants, 1):
            q = urllib.parse.quote(search_title)
            url = (
                f"https://arxiv.org/search/?query={q}"
                "&searchtype=title&source=header&order=-announced_date_first"
            )
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except PlaywrightTimeoutError:
                continue

            try:
                page.wait_for_selector(".arxiv-result, .no-results", timeout=15000)
            except PlaywrightTimeoutError:
                continue

            no_results = page.query_selector(".no-results")
            if no_results:
                continue

            result_elems = page.query_selector_all(".arxiv-result")
            if not result_elems:
                continue

            best_elem = None
            best_score = 0.0
            for elem in result_elems:
                title_elem = elem.query_selector("p.title")
                extracted = title_elem.inner_text().strip() if title_elem else ""
                score, _ = _match_title(title, extracted)
                if score > best_score:
                    best_score = score
                    best_elem = elem

            if best_elem is None:
                continue

            extracted_title = best_elem.query_selector("p.title").inner_text().strip()
            score, confidence = _match_title(title, extracted_title)
            result.title_score = score
            result.confidence = confidence
            result.title_matched = (
                "exact" if score >= 0.95 else ("fuzzy" if score >= TITLE_MATCH_THRESHOLD else "none")
            )

            if confidence == "low":
                continue

            # Extract landing URL
            abs_link = best_elem.query_selector('a[href*="/abs/"]')
            if abs_link:
                href = abs_link.get_attribute("href")
                if href:
                    result.landing_url = (
                        "https://arxiv.org" + href if href.startswith("/abs/") else href
                    )
                    # Derive arxiv_id from landing URL
                    result.arxiv_id = href.split("/abs/")[-1].split("v")[0]

            # Extract PDF URL
            pdf_link = best_elem.query_selector('a[href*="/pdf/"]')
            if pdf_link:
                href = pdf_link.get_attribute("href")
                if href:
                    result.pdf_url = (
                        "https://arxiv.org" + href if href.startswith("/pdf/") else href
                    )
            elif result.arxiv_id:
                result.pdf_url = f"https://arxiv.org/pdf/{result.arxiv_id}.pdf"

            result.success = True
            break

        if not result.success:
            result.error = f"All {len(variants)} variants exhausted without confident match"

    except Exception as exc:
        result.error = str(exc)
    finally:
        try:
            context.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass

    return result
