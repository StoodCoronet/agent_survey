#!/usr/bin/env python3
"""Test Bing international search fallback for missing survey PDFs.

Usage:
    conda activate survey_agent
    PYTHONPATH=src python scripts/test_bing_search.py
"""
from __future__ import annotations

import re
import sqlite3
import time
from urllib.parse import quote_plus

import httpx
from rich.console import Console
from rich.table import Table

from agent_survey.core.config import load_config

console = Console()

ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)")
OR_RE = re.compile(r"openreview\.net/forum\?id=([A-Za-z0-9_-]+)")
ACL_RE = re.compile(r"aclanthology\.org/([^/]+\.pdf)")
AAAI_RE = re.compile(r"aaai\.org/(?:ojs/)?index\.php/AAAI/article/view/(\d+)")


def bing_search(client: httpx.Client, title: str) -> dict:
    """Search Bing international by title, extract PDF links."""
    q = quote_plus(title)
    url = f"https://www.bing.com/search?q={q}&setmkt=en-US&setlang=en"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        r = client.get(url, headers=headers, timeout=15, follow_redirects=True)
        text = r.text

        if r.status_code != 200:
            return {"status": f"http_{r.status_code}", "arxiv_id": None, "openreview_id": None, "acl_id": None, "aaai_id": None}

        # Check for block
        lower = text.lower()
        if "captcha" in lower or "verify you are human" in lower or "unusual traffic" in lower:
            return {"status": "blocked", "arxiv_id": None, "openreview_id": None, "acl_id": None, "aaai_id": None}

        # Bing sometimes wraps links in redirects; extract from both raw hrefs and visible text
        arxiv_ids = ARXIV_RE.findall(text)
        or_ids = OR_RE.findall(text)
        acl_ids = ACL_RE.findall(text)
        aaai_ids = AAAI_RE.findall(text)

        return {
            "status": "ok",
            "arxiv_id": arxiv_ids[0] if arxiv_ids else None,
            "openreview_id": or_ids[0] if or_ids else None,
            "acl_id": acl_ids[0] if acl_ids else None,
            "aaai_id": aaai_ids[0] if aaai_ids else None,
        }
    except Exception as e:
        return {"status": f"error: {e}", "arxiv_id": None, "openreview_id": None, "acl_id": None, "aaai_id": None}


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

    console.print(f"[bold]Testing Bing Search for {len(rows)} missing surveys...[/bold]\n")

    client = httpx.Client(timeout=15, follow_redirects=True)

    results = {
        "arxiv": 0,
        "openreview": 0,
        "acl": 0,
        "aaai": 0,
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
        console.print(f"[{i:3d}/{len(rows)}] {venue:<8} {title[:50]}...", end=" ")

        res = bing_search(client, title)
        status = res["status"]

        if status == "blocked":
            results["blocked"] += 1
            console.print("[red]BLOCKED[/red]")
        elif status.startswith("error") or status.startswith("http_"):
            results["error"] += 1
            console.print(f"[red]{status[:25]}[/red]")
        else:
            found = []
            if res["arxiv_id"]:
                found.append(f"arxiv:{res['arxiv_id']}")
            if res["openreview_id"]:
                found.append(f"OR:{res['openreview_id']}")
            if res["acl_id"]:
                found.append(f"ACL:{res['acl_id']}")
            if res["aaai_id"]:
                found.append(f"AAAI:{res['aaai_id']}")
            if len(found) > 1:
                results["multiple"] += 1
                console.print(f"[green]{' + '.join(found)}[/green]")
            elif found:
                key = "arxiv" if res["arxiv_id"] else ("openreview" if res["openreview_id"] else ("acl" if res["acl_id"] else "aaai"))
                results[key] += 1
                console.print(f"[cyan]{found[0]}[/cyan]")
            else:
                results["none"] += 1
                console.print("[yellow]none[/yellow]")

        details.append({"title": title, "venue": venue, **res})
        time.sleep(1.5)  # polite delay

    elapsed = time.time() - start
    client.close()

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
        if d.get("arxiv_id") or d.get("openreview_id") or d.get("acl_id") or d.get("aaai_id"):
            parts = []
            if d.get("arxiv_id"): parts.append(f"arxiv:{d['arxiv_id']}")
            if d.get("openreview_id"): parts.append(f"OR:{d['openreview_id']}")
            if d.get("acl_id"): parts.append(f"ACL:{d['acl_id']}")
            if d.get("aaai_id"): parts.append(f"AAAI:{d['aaai_id']}")
            console.print(f"  {d['venue']:<8} {d['title'][:45]}... → {' '.join(parts)}")
            shown += 1
            if shown >= 15:
                break

    # Save full results
    import json
    out = cfg.abs_topic_dir("llm-context-management", "json") / "bing_search_results.json"
    out.write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"\n[dim]Full results saved to {out}[/dim]")


if __name__ == "__main__":
    main()
