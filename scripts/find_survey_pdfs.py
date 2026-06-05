#!/usr/bin/env python3
"""Find PDF sources for missing survey papers via multi-platform search.

Usage:
    python scripts/find_survey_pdfs.py --topic llm-context-management

Search order:
    1. arXiv API (fast)
    2. arXiv Playwright (fallback)
    3. ACM DL Playwright (for CHI/ICSE/TOSEM)
    4. IEEE Xplore Playwright (for ICSE/USS)
    5. Author homepage (hardcoded mappings)
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import time
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table

console = Console()

# Hardcoded author-homepage PDFs for known papers
_AUTHOR_PDFS: dict[str, str] = {
    "Demystifying Exploitable Bugs in Smart Contracts": "https://www.cs.purdue.edu/homes/zhan3299/res/ICSE23.pdf",
    "Evaluating and Improving Hybrid Fuzzing": "https://shadowmydx.github.io/papers/icse23main-p966.pdf",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _arxiv_api_search(title: str) -> dict | None:
    """Search arXiv by title via API."""
    q = title.replace('"', "").strip()
    params = {
        "search_query": f'ti:"{q}"',
        "max_results": 3,
        "sortBy": "relevance",
    }
    try:
        r = httpx.get(
            "https://export.arxiv.org/api/query",
            params=params,
            timeout=15,
            follow_redirects=True,
        )
        r.raise_for_status()
        import xml.etree.ElementTree as ET

        NS = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(r.text)
        for entry in root.findall("a:entry", NS):
            arxiv_url = entry.findtext("a:id", default="", namespaces=NS)
            m = re.search(r"arxiv\.org/abs/([^v\s]+)", arxiv_url)
            aid = m.group(1) if m else None
            etitle = (entry.findtext("a:title", default="", namespaces=NS) or "").strip()
            if aid and _norm(etitle) == _norm(title):
                pdf_url = f"https://arxiv.org/pdf/{aid}.pdf"
                return {"source": "arxiv_api", "arxiv_id": aid, "pdf_url": pdf_url}
            # fuzzy prefix match
            if aid and len(etitle) > 30 and len(title) > 30:
                if _norm(etitle)[:40] == _norm(title)[:40]:
                    pdf_url = f"https://arxiv.org/pdf/{aid}.pdf"
                    return {"source": "arxiv_api", "arxiv_id": aid, "pdf_url": pdf_url}
    except Exception:
        pass
    return None


def _playwright_search(title: str, venue: str, proxy: str = "") -> dict | None:
    """Use Playwright to search arXiv / ACM / IEEE."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        console.print("[yellow]playwright not installed, skip[/yellow]")
        return None

    result = None

    with sync_playwright() as p:
        args = ["--disable-blink-features=AutomationControlled"]
        if proxy:
            args.append(f"--proxy-server={proxy}")
        browser = p.chromium.launch(headless=True, args=args)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        # 1. arXiv search
        try:
            q = title.replace(" ", "+").replace('"', "")
            url = f"https://arxiv.org/search/?query={q}&searchtype=title"
            page.goto(url, timeout=20000)
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(random.uniform(1, 2))

            # Extract first result link
            link = page.query_selector("li.arxiv-result a[href^='/abs/']")
            if link:
                href = link.get_attribute("href") or ""
                m = re.search(r"/abs/([^v\s]+)", href)
                if m:
                    aid = m.group(1)
                    result = {
                        "source": "arxiv_pw",
                        "arxiv_id": aid,
                        "pdf_url": f"https://arxiv.org/pdf/{aid}.pdf",
                    }
        except Exception:
            pass

        if result:
            browser.close()
            return result

        # 2. ACM DL (for CHI/ICSE/TOSEM)
        if venue in {"CHI", "ICSE", "TOSEM"}:
            try:
                q = title.replace(" ", "+").replace('"', "")
                url = f"https://dl.acm.org/action/doSearch?AllField={q}"
                page.goto(url, timeout=20000)
                page.wait_for_load_state("networkidle", timeout=15000)
                time.sleep(random.uniform(2, 4))

                # Try to find PDF link
                pdf_link = page.query_selector("a[href*='doi/pdf']")
                if pdf_link:
                    href = pdf_link.get_attribute("href") or ""
                    if href.startswith("/"):
                        href = f"https://dl.acm.org{href}"
                    result = {"source": "acm", "pdf_url": href}
            except Exception:
                pass

        if result:
            browser.close()
            return result

        # 3. IEEE Xplore (for ICSE/USS)
        if venue in {"ICSE", "USS"}:
            try:
                q = title.replace(" ", "+").replace('"', "")
                url = f"https://ieeexplore.ieee.org/search/searchresult.jsp?queryText={q}"
                page.goto(url, timeout=20000)
                page.wait_for_load_state("networkidle", timeout=15000)
                time.sleep(random.uniform(2, 4))

                pdf_link = page.query_selector("a[href*='stamp.jsp']")
                if pdf_link:
                    href = pdf_link.get_attribute("href") or ""
                    if href.startswith("/"):
                        href = f"https://ieeexplore.ieee.org{href}"
                    result = {"source": "ieee", "pdf_url": href}
            except Exception:
                pass

        browser.close()
        return result


def _author_homepage(title: str) -> dict | None:
    """Check hardcoded author homepage PDFs."""
    for key, url in _AUTHOR_PDFS.items():
        if _norm(key) == _norm(title) or key.lower() in title.lower():
            return {"source": "author", "pdf_url": url}
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="llm-context-management")
    parser.add_argument("--proxy", default="", help="http proxy for Playwright")
    parser.add_argument("--non-headless", action="store_true", help="show browser window")
    args = parser.parse_args()

    from agent_survey.core.config import load_config

    cfg = load_config()
    manifest_path = cfg.abs_topic_dir(args.topic, "json") / "download_manifest.json"
    if not manifest_path.exists():
        console.print(f"[red]Manifest not found: {manifest_path}[/red]")
        return

    manifest = json.loads(manifest_path.read_text())
    candidates = manifest.get("candidates", [])

    # Filter missing ones
    missing = [c for c in candidates if not c.get("pdf_url")]
    console.print(f"[bold]Finding PDFs for {len(missing)} missing surveys...[/bold]")

    found = 0
    table = Table(show_header=True)
    table.add_column("Venue")
    table.add_column("Title")
    table.add_column("Found")
    table.add_column("Source")

    for c in missing:
        title = c.get("title", "")
        venue = c.get("venue", "")
        result = None

        # 1. Author homepage
        result = _author_homepage(title)

        # 2. arXiv API
        if not result:
            result = _arxiv_api_search(title)
            time.sleep(3)  # arXiv rate limit

        # 3. Playwright multi-platform
        if not result:
            result = _playwright_search(title, venue, proxy=args.proxy)

        if result:
            found += 1
            c["pdf_url"] = result["pdf_url"]
            c["source"] = result["source"]
            if result.get("arxiv_id"):
                c["arxiv_id"] = result["arxiv_id"]
            table.add_row(venue, title[:50] + "...", "✓", result["source"])
        else:
            table.add_row(venue, title[:50] + "...", "✗", "")

    console.print(table)
    console.print(f"[green]Found {found}/{len(missing)} new PDF sources[/green]")

    # Update DB
    db_path = cfg.abs_path("db")
    conn = sqlite3.connect(db_path)
    updated = 0
    for c in candidates:
        if c.get("pdf_url") and c.get("source") in {"arxiv_api", "arxiv_pw", "author"}:
            # Only update arxiv/author sources (ACM/IEEE may need cookie)
            conn.execute(
                "UPDATE papers SET pdf_url = ? WHERE title = ?",
                (c["pdf_url"], c["title"]),
            )
            updated += 1
    conn.commit()
    console.print(f"[dim]Updated {updated} entries in DB[/dim]")

    # Rewrite manifest
    manifest["with_source"] = sum(1 for c in candidates if c.get("pdf_url"))
    manifest["missing"] = sum(1 for c in candidates if not c.get("pdf_url"))
    manifest["candidates"] = candidates
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    console.print(f"[dim]Manifest updated: {manifest_path}[/dim]")


if __name__ == "__main__":
    main()
