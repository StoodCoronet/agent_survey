#!/usr/bin/env python3
"""Test Google Search fallback for missing survey PDFs.

Usage:
    conda activate survey_agent
    PYTHONPATH=src python scripts/test_google_search.py
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from urllib.parse import quote_plus

import httpx
from rich.console import Console
from rich.table import Table

from agent_survey.core.config import load_config

console = Console()

# Proxy from .env
HTTP_PROXY = os.getenv("HTTP_PROXY", "http://192.168.1.106:7890")

# Regex patterns
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)")
OR_RE = re.compile(r"openreview\.net/forum\?id=([A-Za-z0-9_-]+)")


def google_search(client: httpx.Client, title: str) -> dict:
    """Search Google by title, extract arxiv_id and openreview_id from first page."""
    q = quote_plus(title)
    url = f"https://www.google.com/search?q={q}&hl=en"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    try:
        r = client.get(url, headers=headers, timeout=15, follow_redirects=True)
        text = r.text

        # Check for CAPTCHA / block
        if "captcha" in text.lower() or r.status_code != 200:
            return {"status": "blocked", "arxiv_id": None, "openreview_id": None}

        arxiv_ids = ARXIV_RE.findall(text)
        or_ids = OR_RE.findall(text)

        return {
            "status": "ok",
            "arxiv_id": arxiv_ids[0] if arxiv_ids else None,
            "openreview_id": or_ids[0] if or_ids else None,
        }
    except Exception as e:
        return {"status": f"error: {e}", "arxiv_id": None, "openreview_id": None}


def main():
    cfg = load_config()
    db_path = cfg.abs_path("db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Find survey candidates without pdf_url
    rows = conn.execute(
        '''
        SELECT p.title, p.venue
        FROM papers p
        JOIN paper_topics pt ON p.paper_id = pt.paper_id
        WHERE pt.topic_name = 'llm-context-management'
          AND pt.survey_score IS NOT NULL
          AND (p.pdf_url IS NULL OR p.pdf_url = '')
          AND (p.arxiv_id IS NULL OR p.arxiv_id = '')
        ORDER BY p.venue
        '''
    ).fetchall()

    console.print(f"[bold]Testing Google Search for {len(rows)} missing surveys...[/bold]")
    console.print(f"[dim]Proxy: {HTTP_PROXY}[/dim]\n")

    client = httpx.Client(
        timeout=15,
        follow_redirects=True,
        proxy=HTTP_PROXY,
    )

    results = {
        "arxiv": 0,
        "openreview": 0,
        "both": 0,
        "none": 0,
        "blocked": 0,
        "error": 0,
    }
    details: list[dict] = []

    start = time.time()
    for i, row in enumerate(rows, 1):
        title = row["title"]
        venue = row["venue"]
        console.print(f"[{i}/{len(rows)}] {title[:60]}...", end=" ")

        res = google_search(client, title)
        status = res["status"]

        if status == "blocked":
            results["blocked"] += 1
            console.print("[red]BLOCKED/CAPTCHA[/red]")
        elif status.startswith("error"):
            results["error"] += 1
            console.print(f"[red]{status}[/red]")
        elif res["arxiv_id"] and res["openreview_id"]:
            results["both"] += 1
            console.print(f"[green]both[/green] arxiv:{res['arxiv_id']} OR:{res['openreview_id']}")
        elif res["arxiv_id"]:
            results["arxiv"] += 1
            console.print(f"[green]arxiv[/green] {res['arxiv_id']}")
        elif res["openreview_id"]:
            results["openreview"] += 1
            console.print(f"[cyan]OR[/cyan] {res['openreview_id']}")
        else:
            results["none"] += 1
            console.print("[yellow]none[/yellow]")

        details.append({
            "title": title,
            "venue": venue,
            "arxiv_id": res.get("arxiv_id"),
            "openreview_id": res.get("openreview_id"),
            "status": status,
        })

        time.sleep(2)  # polite delay between searches

    elapsed = time.time() - start
    client.close()

    # Summary
    console.print(f"\n[bold]Results ({len(rows)} papers, {elapsed:.1f}s)[/bold]")
    table = Table(show_header=True)
    table.add_column("Result")
    table.add_column("Count", justify="right")
    table.add_column("%", justify="right")
    for key, val in results.items():
        pct = val / len(rows) * 100 if rows else 0
        table.add_row(key, str(val), f"{pct:.1f}%")
    console.print(table)

    # Show samples
    console.print("\n[bold]Sample successes:[/bold]")
    for d in details:
        if d["arxiv_id"] or d["openreview_id"]:
            console.print(f"  {d['venue']:<10} {d['title'][:50]}... → arxiv:{d['arxiv_id']} OR:{d['openreview_id']}")
            if sum(1 for x in details if x['arxiv_id'] or x['openreview_id']) >= 5:
                break


if __name__ == "__main__":
    main()
