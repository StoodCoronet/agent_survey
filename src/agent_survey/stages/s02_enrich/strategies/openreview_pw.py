"""OpenReview forum page abstract extractor via Playwright.

For ICLR and other OpenReview-hosted venues.  The abstract is rendered as
plain text after "Abstract:" on the forum page.  No CSS class wraps it,
so we use text-based extraction.

Thread-safe: each thread gets its own event loop + browser page.
One shared browser across threads.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Iterator

import httpx

# Shared HTTP client for fast path (no need to create per call)
_http_client = None
_http_lock = threading.Lock()

# Shared browser (one per process), per-thread pages
_browser = None
_browser_lock = threading.Lock()
_thread_local = threading.local()


async def _maybe_start_browser(proxy: str = ""):
    """Thread-safe browser init."""
    global _browser
    from playwright.async_api import async_playwright

    with _browser_lock:
        if _browser is not None:
            return
        pw = await async_playwright().start()
        proxy_setting = {"server": proxy} if proxy else None
        _browser = await pw.chromium.launch(
            headless=True,
            proxy=proxy_setting,  # type: ignore[arg-type]
            args=["--no-sandbox"],
        )


def _get_loop():
    """Get or create a per-thread event loop."""
    if not hasattr(_thread_local, "loop"):
        _thread_local.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_thread_local.loop)
    return _thread_local.loop


async def _extract_abstract_async(fid: str, timeout: int = 15) -> str | None:
    """Extract abstract from one OpenReview forum page."""
    global _browser
    await _maybe_start_browser()
    # Each thread gets its own page for true concurrency
    page = await _browser.new_page()
    try:
        await page.goto(
            f"https://openreview.net/forum?id={fid}",
            wait_until="domcontentloaded",
            timeout=timeout * 1000,
        )
        await page.wait_for_selector("text=Abstract:", timeout=8000)
        await asyncio.sleep(0.3)
        full_text = await page.inner_text("body")
    except Exception:
        return None
    finally:
        await page.close()

    parts = full_text.split("Abstract:", 1)
    if len(parts) < 2:
        return None
    abstract = parts[1].strip()
    for cutoff in [
        "Anonymous URL:", "Supplementary Material:", "Code Of Ethics:",
        "Submission Guidelines:", "Reply Type:", "Author:", "Visible To:",
    ]:
        idx = abstract.find(cutoff)
        if idx >= 0:
            abstract = abstract[:idx].strip()
    if len(abstract) >= 50:
        return abstract
    return None


def _get_http():
    """Lazy-init shared httpx client (thread-safe)."""
    global _http_client
    if _http_client is None:
        with _http_lock:
            if _http_client is None:
                import httpx as _httpx
                _http_client = _httpx.Client(timeout=10)
    return _http_client


def fetch_openreview_pw(url: str, proxy: str = "", timeout: int = 15) -> str | None:
    """Synchronous: extract abstract from OpenReview forum URL."""
    import re

    if not url or "openreview.net/forum" not in url:
        return None
    m = re.search(r'forum\?id=([\w_-]+)', url)
    if not m:
        return None
    fid = m.group(1)

    # Fast path: <meta name="citation_abstract"> in SSR HTML
    http = _get_http()
    try:
        r = http.get(f"https://openreview.net/forum?id={fid}")
        mm = re.search(r'<meta\s+name="citation_abstract"\s+content="([^"]+)"', r.text)
        if mm:
            text = mm.group(1).replace("&#x27;", "'").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            if len(text) >= 50:
                return text
        # Also try og:description
        mm2 = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', r.text)
        if mm2 and len(mm2.group(1)) >= 50:
            return mm2.group(1)
    except Exception:
        pass

    # Fast-fail: let next source (s2) handle it instead of slow Playwright
    return None
