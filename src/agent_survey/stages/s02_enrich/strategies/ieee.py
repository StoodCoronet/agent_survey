"""IEEE Xplore abstract fetcher via Playwright.

IEEE Xplore pages are JavaScript-rendered and protected by Cloudflare.
Simple HTTP requests return challenge pages, so this fetcher requires a
Playwright Browser instance.

It is designed to be called from the `enrich-web` fallback stage where a
single shared browser is reused across workers.
"""
from __future__ import annotations

from playwright.sync_api import Browser


def fetch_ieee_abstract(browser: Browser, url: str) -> str | None:
    """Fetch abstract from IEEE Xplore via Playwright.

    Args:
        browser: Shared Playwright browser (usually launched in headless=False
            mode with --disable-blink-features=AutomationControlled to reduce
            Cloudflare detection).
        url: IEEE document page, e.g. https://ieeexplore.ieee.org/document/...

    Returns:
        Abstract text, or None if blocked / not found.
    """
    page = None
    try:
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(3000)

        # Cloudflare / bot detection
        content = page.content()
        if "Unable to Load Page" in content or "chk_captcha" in content:
            return None

        selectors = [
            "div.abstract-text",
            "div.abstract div",
            "section#abstract p",
            "xpl-document-abstract p",
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

        # Fallback: look for "Abstract" heading
        try:
            text = page.evaluate(
                """
                () => {
                    const h = Array.from(document.querySelectorAll('h2, h3, h4, .document-title'))
                        .find(e => e.innerText.toLowerCase().includes('abstract'));
                    if (!h) return '';
                    let n = h.nextElementSibling;
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
