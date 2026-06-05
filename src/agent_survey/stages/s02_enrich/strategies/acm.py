"""ACM DL abstract fetcher via Playwright.

ACM Digital Library pages are heavily JavaScript-rendered and protected
by Cloudflare bot detection.  Simple HTTP requests (httpx/requests) return
challenge pages, so this fetcher requires a Playwright Browser instance.

It is designed to be called from the `enrich-web` fallback stage where a
single shared browser is reused across workers.
"""
from __future__ import annotations

from playwright.sync_api import Browser


def fetch_acm_abstract(browser: Browser, url: str) -> str | None:
    """Fetch abstract from ACM DL via Playwright.

    Args:
        browser: Shared Playwright browser (usually launched in headless=False
            mode with --disable-blink-features=AutomationControlled to reduce
            Cloudflare detection).
        url: ACM DOI page, e.g. https://dl.acm.org/doi/10.1145/...

    Returns:
        Abstract text, or None if blocked / not found.
    """
    page = None
    try:
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(3000)

        # Cloudflare challenge detection
        title = page.title()
        content = page.content()
        if "Just a moment" in title or "chk_captcha" in content:
            return None

        # Try several known ACM abstract selectors
        selectors = [
            "div.abstractInFull",
            "section#abstract p",
            "div.abstractSection p",
            "div[role='region'] p",
        ]
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    text = el.inner_text().strip()
                    if len(text) >= 30:
                        return text
            except Exception:
                continue

        # Fallback: grab first paragraph after an "Abstract" heading
        try:
            text = page.evaluate(
                """
                () => {
                    const h = Array.from(document.querySelectorAll('h2, h3, h4, strong, div.section__title'))
                        .find(e => e.innerText.toLowerCase().includes('abstract'));
                    if (!h) return '';
                    let n = h.nextElementSibling || h.parentElement.nextElementSibling;
                    while (n && n.tagName.match(/^H/i)) n = n.nextElementSibling;
                    return n ? n.innerText.trim() : '';
                }
                """
            )
            if text and len(text) >= 30:
                return text
        except Exception:
            pass
    except Exception:
        pass
    finally:
        if page:
            page.close()
    return None
