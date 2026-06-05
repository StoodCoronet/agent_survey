"""Generic Playwright abstract extractor — works for most academic paper pages.

Loads the page, waits for "Abstract" text, extracts text between "Abstract"
and the next section header (References, Introduction, Keywords, etc.).
"""
from __future__ import annotations

import asyncio
import threading
from typing import Iterator

# Shared browser (one per process), per-thread pages
_browser = None
_browser_lock = threading.Lock()
_thread_local = threading.local()

_CUTOFFS = [
    "References", "REFERENCES", "Bibliography",
    "1. ", "1  ", "Introduction",
    "Keywords", "KEYWORDS", "Cite", "BibTeX",
    "Submission Guidelines", "Code Of Ethics",
    "Supplementary Material", "Anonymous URL",
]


async def _maybe_start_browser(proxy: str = ""):
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
    if not hasattr(_thread_local, "loop"):
        _thread_local.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_thread_local.loop)
    return _thread_local.loop


async def _extract_async(url: str, timeout: int = 20) -> str | None:
    await _maybe_start_browser()
    if _browser is None:
        return None
    page = await _browser.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        try:
            await page.wait_for_selector("text=Abstract", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(0.3)
        text = await page.inner_text("body")
    except Exception:
        return None
    finally:
        await page.close()

    for keyword in ["Abstract", "ABSTRACT"]:
        if keyword in text:
            parts = text.split(keyword, 1)
            if len(parts) >= 2:
                abstract = parts[1].strip()[:5000]
                for cutoff in _CUTOFFS:
                    idx = abstract.find(cutoff)
                    if idx > 0:
                        abstract = abstract[:idx].strip()
                if len(abstract) >= 50:
                    return abstract
    return None


def fetch_playwright_generic(url: str, proxy: str = "", timeout: int = 20) -> str | None:
    """Synchronous: extract abstract from any academic paper page via Playwright.

    Thread-safe — each thread has its own event loop and browser page.
    """
    if not url:
        return None
    loop = _get_loop()
    return loop.run_until_complete(_extract_async(url, timeout))
