#!/usr/bin/env python3
"""Debug DuckDuckGo HTML search — title matching on first 10 missing surveys."""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote_plus

import httpx
from rich.console import Console

console = Console()

OUT_DIR = Path("/tmp/ddg_debug")
OUT_DIR.mkdir(exist_ok=True)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _match(query_norm: str, result_norm: str) -> str:
    if query_norm == result_norm:
        return "exact"
    if len(query_norm) >= 20 and (query_norm in result_norm or result_norm in query_norm):
        return "substring"
    if len(query_norm) > 30 and len(result_norm) > 30 and query_norm[:40] == result_norm[:40]:
        return "prefix"
    return ""


def ddg_search_debug(client: httpx.Client, title: str, idx: int) -> dict:
    q = quote_plus(title)
    url = f"https://html.duckduckgo.com/html/?q={q}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    r = client.get(url, headers=headers, timeout=15, follow_redirects=True)
    html = r.text
    (OUT_DIR / f"{idx:02d}_ddg.html").write_text(html, encoding="utf-8")

    query_norm = _norm(title)
    candidates = []

    # DuckDuckGo HTML: results in <div class="result"> blocks
    # Title is: <a class="result__a" href="URL">TITLE</a>
    result_blocks = re.findall(
        r'<div class="result[^"]*"[^>]*>(.*?)</div>\s*(?=<div class="result|<div id="links")',
        html, re.DOTALL | re.IGNORECASE
    )
    # Fallback: simpler pattern
    if not result_blocks:
        result_blocks = re.findall(r'<div class="result[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL | re.IGNORECASE)

    for block in result_blocks[:10]:
        m = re.search(r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL | re.IGNORECASE)
        if not m:
            m = re.search(r'<a[^>]+href="([^"]*)"[^>]*>([^<]{10,200})</a>', block, re.DOTALL | re.IGNORECASE)
        if m:
            raw_url = m.group(1)
            raw_title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if len(raw_title) < 10:
                continue
            result_norm = _norm(raw_title)
            match_type = _match(query_norm, result_norm)
            candidates.append({
                "source": "ddg",
                "url": raw_url,
                "raw_title": raw_title,
                "result_norm": result_norm,
                "match": match_type,
            })

    # ID extraction
    arxiv_re = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)")
    or_re = re.compile(r"openreview\.net/(?:forum|pdf)\?id=([A-Za-z0-9_-]+)")
    acl_re = re.compile(r"aclanthology\.org/([^/]+\.pdf)")
    aaai_re = re.compile(r"aaai\.org/(?:ojs/)?index\.php/AAAI/article/view/(\d+)")
    pdf_re = re.compile(r"\.pdf$")

    matched = [c for c in candidates if c["match"]]
    best = None
    for c in matched:
        u = c["url"]
        am = arxiv_re.search(u)
        om = or_re.search(u)
        acm = acl_re.search(u)
        aam = aaai_re.search(u)
        c["arxiv_id"] = am.group(1) if am else None
        c["openreview_id"] = om.group(1) if om else None
        c["acl_id"] = acm.group(1) if acm else None
        c["aaai_id"] = aam.group(1) if aam else None
        c["is_pdf"] = bool(pdf_re.search(u))
        if not best:
            best = c

    return {
        "query_norm": query_norm,
        "candidates": candidates,
        "matched": matched,
        "best": best,
        "html_len": len(html),
        "result_blocks": len(result_blocks),
    }


def main():
    from agent_survey.core.config import load_config
    cfg = load_config()
    db_path = cfg.abs_path("db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute('''
        SELECT p.title, p.venue
        FROM papers p
        JOIN paper_topics pt ON p.paper_id = pt.paper_id
        WHERE pt.topic_name = 'llm-context-management'
          AND pt.survey_score IS NOT NULL
          AND (p.pdf_path IS NULL OR p.pdf_path = '')
          AND (p.pdf_url IS NULL OR p.pdf_url = '')
          AND (p.arxiv_id IS NULL OR p.arxiv_id = '')
        ORDER BY p.venue
        LIMIT 10
    ''').fetchall()

    client = httpx.Client(timeout=15, follow_redirects=True)
    summary = []

    for i, row in enumerate(rows, 1):
        title = row["title"]
        venue = row["venue"]
        console.print(f"\n[bold cyan]=== [{i}] {venue} ===[/bold cyan]")
        console.print(f"[dim]Query:[/dim] {title}")
        console.print(f"[dim]Norm :[/dim] {_norm(title)}")

        res = ddg_search_debug(client, title, i)
        console.print(f"[dim]HTML size: {res['html_len']}, result blocks: {res['result_blocks']}[/dim]")

        if res["candidates"]:
            console.print("[dim]Top candidates:[/dim]")
            for c in res["candidates"][:6]:
                icon = "[green]✓[/green]" if c["match"] else "[red]✗[/red]"
                console.print(f"  {icon} {c['match']:<10} | {c['raw_title'][:60]}...")
                console.print(f"       → {c['url'][:80]}")

        best = res["best"]
        if best:
            ids = []
            if best.get("arxiv_id"): ids.append(f"arxiv:{best['arxiv_id']}")
            if best.get("openreview_id"): ids.append(f"OR:{best['openreview_id']}")
            if best.get("acl_id"): ids.append(f"ACL:{best['acl_id']}")
            if best.get("aaai_id"): ids.append(f"AAAI:{best['aaai_id']}")
            if best.get("is_pdf"): ids.append("[PDF]")
            console.print(f"[bold green]MATCH → {' '.join(ids) if ids else 'URL only'}[/bold green]")
            summary.append({"idx": i, "venue": venue, "title": title, "found": True, "ids": ids, "url": best["url"]})
        else:
            console.print("[bold yellow]NO MATCH[/bold yellow]")
            summary.append({"idx": i, "venue": venue, "title": title, "found": False, "ids": [], "url": None})

        time.sleep(1.5)

    client.close()

    console.print("\n" + "=" * 60)
    console.print("[bold]SUMMARY[/bold]")
    found = sum(1 for s in summary if s["found"])
    console.print(f"Matched: {found}/{len(summary)}")
    for s in summary:
        status = "[green]✓[/green]" if s["found"] else "[red]✗[/red]"
        ids = " ".join(s["ids"]) if s["ids"] else "-"
        console.print(f"  {status} [{s['venue']:<6}] {s['title'][:45]}... → {ids}")

    sources = {}
    for s in summary:
        for id_str in s["ids"]:
            src = id_str.split(":")[0] if ":" in id_str else id_str
            sources[src] = sources.get(src, 0) + 1
    console.print("\n[bold]Pattern analysis:[/bold]")
    for src, cnt in sorted(sources.items(), key=lambda x: -x[1]):
        console.print(f"  {src}: {cnt}")


if __name__ == "__main__":
    main()
