#!/usr/bin/env python3
"""Debug Google Search blocking — screenshot + HTML dump."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

from rich.console import Console

console = Console()

HTTP_PROXY = os.getenv("HTTP_PROXY", "http://192.168.1.106:7890")
OUT_DIR = Path("/tmp/gsearch_debug")
OUT_DIR.mkdir(exist_ok=True)


def _launch_browser():
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(
        headless=True,
        proxy={"server": HTTP_PROXY} if HTTP_PROXY else None,
    )
    return p, browser


def search_and_dump(browser, title: str, idx: int) -> dict:
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
        time.sleep(2)

        # Screenshot + HTML
        screenshot = OUT_DIR / f"{idx:02d}_screenshot.png"
        htmlfile = OUT_DIR / f"{idx:02d}_page.html"
        page.screenshot(path=str(screenshot), full_page=True)
        htmlfile.write_text(page.content(), encoding="utf-8")
        console.print(f"[dim]Saved: {screenshot}, {htmlfile}[/dim]")

        text = page.content()
        lower = text.lower()
        issues = []
        if "captcha" in lower:
            issues.append("CAPTCHA")
        if "unusual traffic" in lower:
            issues.append("UNUSUAL_TRAFFIC")
        if "before you continue" in lower:
            issues.append("CONSENT_BANNER")
        if "verify you are human" in lower:
            issues.append("HUMAN_VERIFY")
        if issues:
            console.print(f"[red]Detected: {', '.join(issues)}[/red]")
        else:
            console.print("[green]No obvious block detected in HTML[/green]")

        # Extract visible text snippets
        snippets = page.eval_on_selector_all(
            "h3, span[data-st], div[data-sokoban]",
            "els => els.slice(0, 5).map(e => e.innerText)",
        )
        console.print(f"[dim]Top snippets:[/dim]")
        for s in snippets[:3]:
            console.print(f"  • {s[:80]}...")

        links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        arxiv_ids = re.findall(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)", " ".join(links))
        or_ids = re.findall(r"openreview\.net/forum\?id=([A-Za-z0-9_-]+)", " ".join(links))

        console.print(f"[dim]Links: {len(links)} total, {len(arxiv_ids)} arxiv, {len(or_ids)} OR[/dim]")
        return {"arxiv_id": arxiv_ids[0] if arxiv_ids else None, "openreview_id": or_ids[0] if or_ids else None, "issues": issues}
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return {"issues": [str(e)]}
    finally:
        context.close()


def main():
    p, browser = _launch_browser()
    try:
        titles = [
            "A Survey on Context-Aware Multi-Turn Reasoning in Large Language Models",
            "Advances and Challenges in Contextual Learning for Large Language Models",
            "Survey of Efficient Context Extension Methods for Large Language Models",
        ]
        for i, t in enumerate(titles, 1):
            console.print(f"\n[bold]=== [{i}] {t} ===[/bold]")
            search_and_dump(browser, t, i)
            time.sleep(3)
    finally:
        browser.close()
        p.stop()
    console.print(f"\n[green]All debug files saved to {OUT_DIR}[/green]")


if __name__ == "__main__":
    main()
