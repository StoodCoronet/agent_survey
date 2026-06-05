#!/usr/bin/env python3
"""Debug Google Search blocking with visible browser."""
from __future__ import annotations

import os
import re
import time
from urllib.parse import quote_plus

from rich.console import Console

console = Console()

HTTP_PROXY = os.getenv("HTTP_PROXY", "http://192.168.1.106:7890")

def _launch_browser():
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(
        headless=False,
        proxy={"server": HTTP_PROXY} if HTTP_PROXY else None,
    )
    return p, browser


def search_one(browser, title: str) -> dict:
    q = quote_plus(title)
    url = f"https://www.google.com/search?q={q}&hl=en"
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1920, "height": 1080},
    )
    page = context.new_page()
    try:
        console.print(f"\n[cyan]Opening:[/cyan] {url}")
        page.goto(url, timeout=60000, wait_until="networkidle")
        console.print("[green]Page loaded. Waiting 10s so you can see it...[/green]")
        time.sleep(10)

        text = page.content()
        if "captcha" in text.lower():
            console.print("[red]CAPTCHA detected in HTML[/red]")
        if "unusual traffic" in text.lower():
            console.print("[red]Unusual traffic detected[/red]")

        # Extract links
        links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        arxiv_ids = re.findall(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)", " ".join(links))
        or_ids = re.findall(r"openreview\.net/forum\?id=([A-Za-z0-9_-]+)", " ".join(links))

        console.print(f"[dim]Found {len(arxiv_ids)} arxiv, {len(or_ids)} OR links[/dim]")
        if arxiv_ids:
            console.print(f"[green]arxiv:[/green] {arxiv_ids[0]}")
        if or_ids:
            console.print(f"[green]OR:[/green] {or_ids[0]}")

        return {"arxiv_id": arxiv_ids[0] if arxiv_ids else None, "openreview_id": or_ids[0] if or_ids else None}
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return {}
    finally:
        context.close()


def main():
    p, browser = _launch_browser()
    try:
        # Test 2 representative titles
        titles = [
            "A Survey on Context-Aware Multi-Turn Reasoning in Large Language Models",
            "Advances and Challenges in Contextual Learning for Large Language Models",
        ]
        for t in titles:
            console.print(f"\n[bold]Searching:[/bold] {t}")
            search_one(browser, t)
            time.sleep(2)
    finally:
        browser.close()
        p.stop()


if __name__ == "__main__":
    main()
