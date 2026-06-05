#!/usr/bin/env python3
"""Click Bing '国际版' tab via Playwright to get international results."""
from __future__ import annotations

import re
import time
from urllib.parse import quote_plus

from rich.console import Console

console = Console()


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


def bing_intl_search(title: str) -> dict:
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
        page.goto(url, timeout=30000, wait_until="networkidle")
        time.sleep(1)

        # Check if international tab exists and click it
        intl_tab = page.query_selector("#est_en")
        if intl_tab:
            console.print("[dim]Clicking 国际版 tab...[/dim]")
            intl_tab.click()
            page.wait_for_load_state("networkidle")
            time.sleep(2)
        else:
            console.print("[yellow]No 国际版 tab found[/yellow]")

        html = page.content()
        query_norm = _norm(title)
        candidates = []

        # Extract b_algo blocks
        algo_blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, re.DOTALL | re.IGNORECASE)
        for block in algo_blocks[:8]:
            m = re.search(r'<h2[^>]*>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>\s*</h2>', block, re.DOTALL | re.IGNORECASE)
            if m:
                raw_url = m.group(1)
                raw_title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                if len(raw_title) < 10:
                    continue
                result_norm = _norm(raw_title)
                match_type = _match(query_norm, result_norm)
                candidates.append({
                    "url": raw_url,
                    "raw_title": raw_title,
                    "result_norm": result_norm,
                    "match": match_type,
                })

        # Extract IDs
        arxiv_re = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)")
        or_re = re.compile(r"openreview\.net/(?:forum|pdf)\?id=([A-Za-z0-9_-]+)")
        acl_re = re.compile(r"aclanthology\.org/([^/]+\.pdf)")
        aaai_re = re.compile(r"aaai\.org/(?:ojs/)?index\.php/AAAI/article/view/(\d+)")
        pdf_re = re.compile(r"\.pdf$")

        matched = [c for c in candidates if c["match"]]
        best = None
        for c in matched:
            u = c["url"]
            c["arxiv_id"] = (arxiv_re.search(u).group(1) if arxiv_re.search(u) else None)
            c["openreview_id"] = (or_re.search(u).group(1) if or_re.search(u) else None)
            c["acl_id"] = (acl_re.search(u).group(1) if acl_re.search(u) else None)
            c["aaai_id"] = (aaai_re.search(u).group(1) if aaai_re.search(u) else None)
            c["is_pdf"] = bool(pdf_re.search(u))
            if not best:
                best = c

        return {
            "query_norm": query_norm,
            "candidates": candidates,
            "matched": matched,
            "best": best,
            "html_len": len(html),
            "algo_blocks": len(algo_blocks),
            "clicked_intl": intl_tab is not None,
        }
    finally:
        browser.close()
        p.stop()


def main():
    titles = [
        "Preserve Context Information for Extract-Generate Long-Input Summarization Framework",
        "Knowledge Graph Prompting for Multi-Document Question Answering",
        "Working Memory Capacity of ChatGPT: An Empirical Study",
    ]

    for i, title in enumerate(titles, 1):
        console.print(f"\n[bold cyan]=== [{i}] ===[/bold cyan]")
        console.print(f"[dim]Query:[/dim] {title}")

        res = bing_intl_search(title)
        console.print(f"[dim]HTML: {res['html_len']}, blocks: {res['algo_blocks']}, clicked_intl: {res['clicked_intl']}[/dim]")

        if res["candidates"]:
            console.print("[dim]Top candidates:[/dim]")
            for c in res["candidates"][:5]:
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
            console.print(f"[bold green]MATCH → {' '.join(ids) if ids else 'URL only'}[/bold green]")
        else:
            console.print("[bold yellow]NO MATCH[/bold yellow]")


if __name__ == "__main__":
    main()
