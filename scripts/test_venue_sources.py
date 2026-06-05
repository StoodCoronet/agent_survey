#!/usr/bin/env python3
"""Batch query venue-specific sources for missing survey PDFs."""
from __future__ import annotations

import os
import re
import sqlite3
import time
from urllib.parse import quote_plus

import httpx
from rich.console import Console
from rich.table import Table

console = Console()

HTTP_PROXY = os.getenv("HTTP_PROXY", "http://192.168.1.106:7890")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _match(query_norm: str, result_norm: str) -> bool:
    if query_norm == result_norm:
        return True
    if len(query_norm) >= 20 and (query_norm in result_norm or result_norm in query_norm):
        return True
    if len(query_norm) > 30 and len(result_norm) > 30 and query_norm[:40] == result_norm[:40]:
        return True
    return False


def search_acl_anthology(client: httpx.Client, title: str) -> dict | None:
    """Search ACL Anthology by title, return PDF URL on match."""
    q = quote_plus(title)
    url = f"https://aclanthology.org/search/?q={q}"
    try:
        r = client.get(url, timeout=15, follow_redirects=True)
        html = r.text
        # Results are in <div class="col">
        blocks = re.findall(r'<div class="col[^"]*"[^>]*>(.*?)</div>\s*(?=<div class="col|<nav)',
                          html, re.DOTALL | re.I)
        if not blocks:
            blocks = re.findall(r'<div class="col[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL | re.I)
        query_norm = _norm(title)
        for block in blocks[:10]:
            m = re.search(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>([^<]+)</a>', block, re.I)
            if m:
                pdf_url = m.group(1)
                link_title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                if _match(query_norm, _norm(link_title)):
                    return {"source": "acl_anthology", "pdf_url": pdf_url, "title": link_title}
            # Also match non-pdf links to anthology pages
            m = re.search(r'<a[^>]+href="(/[^"]+/)"[^>]*>([^<]+)</a>', block, re.I)
            if m:
                page_url = "https://aclanthology.org" + m.group(1)
                link_title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                if _match(query_norm, _norm(link_title)):
                    # Derive PDF URL from page URL
                    pdf_url = page_url.rstrip('/') + '.pdf'
                    return {"source": "acl_anthology", "pdf_url": pdf_url, "title": link_title}
        return None
    except Exception as e:
        return {"source": "error", "error": str(e)}


def search_openreview(client: httpx.Client, title: str) -> dict | None:
    """Search OpenReview by title, return PDF URL on match."""
    from agent_survey.services.openreview import search_title_pdf
    try:
        result = search_title_pdf(client, title)
        if result and result.get("pdf_url"):
            return {"source": "openreview", "pdf_url": result["pdf_url"], "forum_id": result.get("forum_id")}
        return None
    except Exception as e:
        return {"source": "error", "error": str(e)}


def search_aaai_ojs(client: httpx.Client, title: str) -> dict | None:
    """Search AAAI OJS by title, return PDF URL on match."""
    q = quote_plus(title)
    # Correct OJS search URL (NOT /search/search/)
    url = f"https://ojs.aaai.org/index.php/AAAI/search?query={q}"
    try:
        r = client.get(url, timeout=15, follow_redirects=True)
        html = r.text
        # OJS search results: <a href=".../article/view/ID">Title</a>
        blocks = re.findall(
            r'<a[^>]+href="([^"]+/article/view/\d+)"[^>]*>([^<]+)</a>',
            html, re.I)
        query_norm = _norm(title)
        for article_url, link_title in blocks[:5]:
            link_title = link_title.strip()
            if _match(query_norm, _norm(link_title)):
                if article_url.startswith('/'):
                    article_url = f"https://ojs.aaai.org{article_url}"
                # Fetch article page to extract citation_pdf_url
                ar = client.get(article_url, timeout=15, follow_redirects=True)
                pdf_match = re.search(
                    r'<meta[^>]+name="citation_pdf_url"[^>]+content="([^"]+)"',
                    ar.text, re.I)
                if pdf_match:
                    pdf_url = pdf_match.group(1)
                    return {"source": "aaai_ojs", "pdf_url": pdf_url, "article_url": article_url, "title": link_title}
                return {"source": "aaai_ojs", "article_url": article_url, "title": link_title}
        return None
    except Exception as e:
        return {"source": "error", "error": str(e)}


def search_neurips(client: httpx.Client, title: str) -> dict | None:
    """Search NeurIPS proceedings by title via Bing/Google fallback is hard;
    try NeurIPS official search."""
    q = quote_plus(title)
    url = f"https://papers.nips.cc/cgi-bin/search.py?search={q}"
    try:
        r = client.get(url, timeout=15, follow_redirects=True)
        html = r.text
        # Results are typically <li> with <a href="/paper/...">Title</a>
        blocks = re.findall(r'<li[^>]*>\s*<a[^>]+href="(/paper/[^"]+)"[^>]*>([^<]+)</a>\s*</li>',
                          html, re.DOTALL | re.I)
        query_norm = _norm(title)
        for paper_path, link_title in blocks[:5]:
            link_title = link_title.strip()
            if _match(query_norm, _norm(link_title)):
                page_url = f"https://papers.nips.cc{paper_path}"
                # NeurIPS paper page usually has PDF link
                return {"source": "neurips", "page_url": page_url, "title": link_title}
        return None
    except Exception as e:
        return {"source": "error", "error": str(e)}


def main():
    from agent_survey.core.config import load_config
    cfg = load_config()
    db_path = cfg.abs_path("db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    all_rows = conn.execute('''
        SELECT p.title, p.venue
        FROM papers p
        JOIN paper_topics pt ON p.paper_id = pt.paper_id
        WHERE pt.topic_name = 'llm-context-management'
          AND pt.survey_score IS NOT NULL
          AND (p.pdf_path IS NULL OR p.pdf_path = '')
          AND (p.pdf_url IS NULL OR p.pdf_url = '')
          AND (p.arxiv_id IS NULL OR p.arxiv_id = '')
        ORDER BY p.venue, p.title
    ''').fetchall()

    # Pick 10 representative: 1-2 per venue group
    seen_venues = set()
    rows = []
    for r in all_rows:
        v = r["venue"]
        if v not in seen_venues or sum(1 for x in rows if x["venue"] == v) < 2:
            rows.append(r)
            seen_venues.add(v)
        if len(rows) >= 10:
            break

    console.print(f"[bold]Batch querying venue-specific sources for {len(rows)} missing surveys...[/bold]\n")

    client = httpx.Client(timeout=15, follow_redirects=True)
    or_client = httpx.Client(timeout=30, follow_redirects=True)

    results = []
    stats = {"ok": 0, "fail": 0, "skip": 0}
    source_counts = {}

    for i, row in enumerate(rows, 1):
        title = row["title"]
        venue = row["venue"]
        console.print(f"[{i:3d}/{len(rows)}] {venue:<8} {title[:50]}...", end=" ")

        res = None
        if venue in {"ACL", "EMNLP", "NAACL"}:
            res = search_acl_anthology(client, title)
            time.sleep(1.5)
        elif venue in {"ICLR", "ICML", "NeurIPS", "COLM"}:
            if venue == "NeurIPS":
                res = search_neurips(client, title)
                if not res:
                    res = search_openreview(or_client, title)
            else:
                res = search_openreview(or_client, title)
            time.sleep(1.0)
        elif venue == "AAAI":
            res = search_aaai_ojs(client, title)
            time.sleep(1.5)
        else:
            console.print("[dim]skip[/dim]")
            stats["skip"] += 1
            results.append({"title": title, "venue": venue, "found": False, "source": None})
            continue

        if res and res.get("source") not in ("error", None):
            stats["ok"] += 1
            src = res["source"]
            source_counts[src] = source_counts.get(src, 0) + 1
            console.print(f"[green]✓ {src}[/green]")
            results.append({"title": title, "venue": venue, "found": True, "source": src, **res})
        else:
            stats["fail"] += 1
            err = res.get("error", "") if res else ""
            console.print(f"[yellow]✗ {err[:30]}[/yellow]")
            results.append({"title": title, "venue": venue, "found": False, "source": None})

    client.close()
    or_client.close()

    console.print(f"\n[bold]Results ({len(rows)} papers)[/bold]")
    table = Table(show_header=True)
    table.add_column("Status")
    table.add_column("Count", justify="right")
    table.add_column("%", justify="right")
    for key, val in stats.items():
        pct = val / len(rows) * 100 if rows else 0
        table.add_row(key, str(val), f"{pct:.1f}%")
    console.print(table)

    console.print("\n[bold]By source:[/bold]")
    for src, cnt in sorted(source_counts.items(), key=lambda x: -x[1]):
        console.print(f"  {src}: {cnt}")

    # Save
    import json
    out = cfg.abs_topic_dir("llm-context-management", "json") / "venue_source_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"\n[dim]Saved to {out}[/dim]")

    # Show successes
    console.print("\n[bold]Sample successes:[/bold]")
    shown = 0
    for r in results:
        if r["found"]:
            url = r.get("pdf_url") or r.get("article_url") or r.get("page_url") or ""
            console.print(f"  [{r['venue']:<6}] {r['title'][:45]}... → {r['source']} | {url[:60]}")
            shown += 1
            if shown >= 15:
                break


if __name__ == "__main__":
    main()
