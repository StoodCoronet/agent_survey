#!/usr/bin/env python3
"""Test Google Search fallback via Playwright for missing survey PDFs.

Usage:
    conda activate survey_agent
    PYTHONPATH=src python scripts/test_google_search_playwright.py
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from urllib.parse import quote_plus

from rich.console import Console
from rich.table import Table

from agent_survey.core.config import load_config

console = Console()

HTTP_PROXY = os.getenv("HTTP_PROXY", "http://192.168.1.106:7890")

ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)")
OR_RE = re.compile(r"openreview\.net/forum\?id=([A-Za-z0-9_-]+)")
ACL_RE = re.compile(r"aclanthology\.org/([^/]+\.pdf)")


def _launch_browser():
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(
        headless=True,
        proxy={"server": HTTP_PROXY} if HTTP_PROXY else None,
    )
    return p, browser


def google_search_playwright(browser, title: str) -> dict:
    """Search Google by title via Playwright, extract links from rendered results."""
    q = quote_plus(title)
    url = f"https://www.google.com/search?q={q}&hl=en"
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    try:
        page.goto(url, timeout=30000, wait_until="networkidle")
        time.sleep(1.5)  # allow JS to settle

        # Extract all hrefs from result links
        # Google uses <a> with hrefs like /url?q=https://arxiv.org/abs/...
        links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        text = page.content()

        # Check CAPTCHA
        if "captcha" in text.lower() or "unusual traffic" in text.lower():
            return {"status": "blocked", "arxiv_id": None, "openreview_id": None, "acl_id": None}

        arxiv_ids = ARXIV_RE.findall(" ".join(links))
        or_ids = OR_RE.findall(" ".join(links))
        acl_ids = ACL_RE.findall(" ".join(links))

        return {
            "status": "ok",
            "arxiv_id": arxiv_ids[0] if arxiv_ids else None,
            "openreview_id": or_ids[0] if or_ids else None,
            "acl_id": acl_ids[0] if acl_ids else None,
        }
    except Exception as e:
        return {"status": f"error: {e}", "arxiv_id": None, "openreview_id": None, "acl_id": None}
    finally:
        context.close()


def main():
    cfg = load_config()
    db_path = cfg.abs_path("db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        '''
        SELECT p.title, p.venue
        FROM papers p
        JOIN paper_topics pt ON p.paper_id = pt.paper_id
        WHERE pt.topic_name = 'llm-context-management'
          AND pt.survey_score IS NOT NULL
          AND (p.pdf_path IS NULL OR p.pdf_path = '')
          AND (p.pdf_url IS NULL OR p.pdf_url = '')
          AND (p.arxiv_id IS NULL OR p.arxiv_id = '')
        ORDER BY p.venue
        '''
    ).fetchall()

    console.print(f"[bold]Testing Playwright Google Search for {len(rows)} missing surveys...[/bold]")
    console.print(f"[dim]Proxy: {HTTP_PROXY}[/dim]\n")

    p, browser = _launch_browser()

    results = {
        "arxiv": 0,
        "openreview": 0,
        "acl": 0,
        "multiple": 0,
        "none": 0,
        "blocked": 0,
        "error": 0,
    }
    details: list[dict] = []

    start = time.time()
    for i, row in enumerate(rows, 1):
        title = row["title"]
        venue = row["venue"]
        console.print(f"[{i}/{len(rows)}] {venue:<8} {title[:55]}...", end=" ")

        res = google_search_playwright(browser, title)
        status = res["status"]

        if status == "blocked":
            results["blocked"] += 1
            console.print("[red]BLOCKED[/red]")
        elif status.startswith("error"):
            results["error"] += 1
            console.print(f"[red]{status[:30]}[/red]")
        else:
            found = []
            if res["arxiv_id"]:
                found.append(f"arxiv:{res['arxiv_id']}")
            if res["openreview_id"]:
                found.append(f"OR:{res['openreview_id']}")
            if res["acl_id"]:
                found.append(f"ACL:{res['acl_id']}")
            if len(found) > 1:
                results["multiple"] += 1
                console.print(f"[green]{' + '.join(found)}[/green]")
            elif found:
                key = "arxiv" if res["arxiv_id"] else ("openreview" if res["openreview_id"] else "acl")
                results[key] += 1
                console.print(f"[cyan]{found[0]}[/cyan]")
            else:
                results["none"] += 1
                console.print("[yellow]none[/yellow]")

        details.append({
            "title": title,
            "venue": venue,
            **res,
        })

        time.sleep(2)  # polite delay

    elapsed = time.time() - start
    browser.close()
    p.stop()

    console.print(f"\n[bold]Results ({len(rows)} papers, {elapsed:.1f}s)[/bold]")
    table = Table(show_header=True)
    table.add_column("Result")
    table.add_column("Count", justify="right")
    table.add_column("%", justify="right")
    for key, val in results.items():
        pct = val / len(rows) * 100 if rows else 0
        table.add_row(key, str(val), f"{pct:.1f}%")
    console.print(table)

    console.print("\n[bold]Sample successes:[/bold]")
    shown = 0
    for d in details:
        if d.get("arxiv_id") or d.get("openreview_id") or d.get("acl_id"):
            console.print(f"  {d['venue']:<8} {d['title'][:50]}... → arxiv:{d.get('arxiv_id')} OR:{d.get('openreview_id')} ACL:{d.get('acl_id')}")
            shown += 1
            if shown >= 10:
                break


if __name__ == "__main__":
    main()
