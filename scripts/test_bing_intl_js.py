#!/usr/bin/env python3
"""Click Bing '国际版' via JS evaluation in Playwright."""
from __future__ import annotations

import re
import time
from urllib.parse import quote_plus

from rich.console import Console

console = Console()


def bing_intl_click(title: str) -> dict:
    from playwright.sync_api import sync_playwright

    q = quote_plus(title)
    url = f"https://cn.bing.com/search?q={q}"

    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="en-US",
    )
    page = context.new_page()

    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(2)

        # Try multiple selectors for international tab
        selectors = ["#est_en", "[aria-label='国际版']", "div:has-text('国际版')"]
        clicked = False
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    text = el.inner_text() if hasattr(el, 'inner_text') else ''
                    console.print(f"[dim]Found tab via '{sel}': {text[:20]}[/dim]")
                    el.click()
                    page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    clicked = True
                    break
            except Exception as e:
                console.print(f"[dim]Selector '{sel}' failed: {e}[/dim]")

        if not clicked:
            # Fallback: evaluate JS to find and click element containing '国际版'
            result = page.evaluate("""
                () => {
                    const els = document.querySelectorAll('*');
                    for (const el of els) {
                        if (el.innerText && el.innerText.trim() === '国际版') {
                            el.click();
                            return 'clicked: ' + el.tagName + '#' + el.id;
                        }
                    }
                    return 'not found';
                }
            """)
            console.print(f"[dim]JS fallback: {result}[/dim]")
            time.sleep(3)

        html = page.content()
        # Check if results look international (has arxiv/aaai/acl)
        has_academic = bool(re.search(r'(arxiv\.org|aaai\.org|aclanthology\.org|openreview\.net)', html))
        # Show first few result titles
        blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, re.DOTALL | re.I)
        titles = []
        for b in blocks[:5]:
            m = re.search(r'<h2[^>]*>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>\s*</h2>', b, re.DOTALL | re.I)
            if m:
                raw_title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                titles.append(raw_title[:50])

        return {
            "clicked": clicked,
            "has_academic": has_academic,
            "titles": titles,
            "html_len": len(html),
        }
    finally:
        browser.close()
        p.stop()


def main():
    title = "Knowledge Graph Prompting for Multi-Document Question Answering"
    console.print(f"[bold]Testing:[/bold] {title}")
    res = bing_intl_click(title)
    console.print(f"\n[dim]HTML size:[/dim] {res['html_len']}")
    console.print(f"[dim]Has academic links:[/dim] {res['has_academic']}")
    console.print(f"[dim]Clicked tab:[/dim] {res['clicked']}")
    console.print("[dim]Top result titles:[/dim]")
    for t in res["titles"]:
        console.print(f"  • {t}")


if __name__ == "__main__":
    main()
