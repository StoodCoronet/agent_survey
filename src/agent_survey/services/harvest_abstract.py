"""Post-harvest abstract fetching from OpenReview and publisher sites.

This is designed to run *after* the basic DBLP harvest is complete.  It
looks at papers whose `url` field points to a source we can crawl
(OpenReview API, PMLR, IEEE, NeurIPS, etc.) and tries to fill the
`abstract` column directly, reducing the load on the later S2/arXiv
enrichment stage.
"""
from __future__ import annotations

import os
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx
from rich.progress import Progress, TextColumn, BarColumn, TimeElapsedColumn, TimeRemainingColumn, MofNCompleteColumn

from ..core.console import console
from ..core.db import DB
from .openreview import fetch_forum_abstract
from .publisher_abstract import fetch_abstract as fetch_publisher_abstract


def _extract_forum_id(url: str) -> str | None:
    """Extract OpenReview forum ID from a URL."""
    m = re.search(r"openreview\.net/forum\?id=([A-Za-z0-9_-]+)", url)
    return m.group(1) if m else None


def _batch_update_abstracts(db: DB, items: list[tuple[str, str]], source: str) -> None:
    """Bulk-update abstract + enrich_source for many papers in one transaction."""
    if not items:
        return
    ts = _now_iso()
    db._conn.executemany(
        "UPDATE papers SET abstract=?, enrich_source=?, enrich_at=?, updated_at=? WHERE paper_id=?",
        [(ab, source, ts, ts, pid) for pid, ab in items],
    )
    db._conn.commit()


def fetch_openreview_abstracts(
    db: DB,
    client: httpx.Client | None = None,
    *,
    delay: float = 1.1,
    limit: int | None = None,
) -> dict[str, Any]:
    """Fetch abstracts for all papers with OpenReview URLs.

    Rate-limited to ~1 req/sec to stay within OpenReview's 60 req/min cap.
    """
    rows = [
        dict(r)
        for r in db._conn.execute(
            "SELECT paper_id, url FROM papers "
            "WHERE (abstract IS NULL OR abstract = '') "
            "AND url LIKE '%openreview.net/forum?id=%'"
        ).fetchall()
    ]
    if limit:
        rows = rows[:limit]
    total = len(rows)
    if not total:
        console.print("[dim]no OpenReview papers need abstract fetching[/dim]")
        return {"processed": 0, "filled": 0}

    if client is None:
        client = httpx.Client(
            timeout=30,
            proxy=os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or None,
        )

    filled = 0
    failed = 0
    skipped = 0
    batch: list[tuple[str, str]] = []
    _BATCH_SIZE = 50

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        auto_refresh=False,
    ) as prog:
        task = prog.add_task("openreview: 0 filled, 0 failed", total=total)
        for row in rows:
            forum_id = _extract_forum_id(row["url"] or "")
            if not forum_id:
                skipped += 1
                prog.advance(task)
                prog.refresh()
                continue
            try:
                res = fetch_forum_abstract(client, forum_id)
                if res and res.get("abstract"):
                    batch.append((row["paper_id"], res["abstract"]))
                    if len(batch) >= _BATCH_SIZE:
                        _batch_update_abstracts(db, batch, "harvest_openreview")
                        batch = []
                    filled += 1
                else:
                    failed += 1
                    console.log(f"[dim]openreview miss: {row['paper_id'].split('/')[-1][:30]}[/dim]")
            except Exception:
                failed += 1
            prog.update(task, description=f"openreview: {filled} filled, {failed} failed")
            prog.advance(task)
            prog.refresh()
            time.sleep(delay)

        if batch:
            _batch_update_abstracts(db, batch, "harvest_openreview")

    return {
        "source": "openreview",
        "processed": total,
        "filled": filled,
        "failed": failed,
        "skipped": skipped,
    }


def fetch_publisher_abstracts(
    db: DB,
    client: httpx.Client | None = None,
    *,
    workers: int = 3,
    delay: float = 0.5,
    timeout: int = 15,
    limit: int | None = None,
) -> dict[str, Any]:
    """Fetch abstracts for papers with publisher (DOI) URLs.

    Uses limited concurrency and per-domain extractors defined in
    `publisher_abstract.py`.
    """
    # Only target doi.org links (exclude arxiv/openreview already handled)
    rows = [
        dict(r)
        for r in db._conn.execute(
            "SELECT paper_id, url FROM papers "
            "WHERE (abstract IS NULL OR abstract = '') "
            "AND url LIKE '%doi.org%'"
        ).fetchall()
    ]
    if limit:
        rows = rows[:limit]
    total = len(rows)
    if not total:
        console.print("[dim]no DOI papers need abstract fetching[/dim]")
        return {"processed": 0, "filled": 0}

    if client is None:
        client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
            proxy=os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or None,
        )

    filled = 0
    failed = 0
    by_domain: Counter = Counter()

    batch: list[tuple[str, str]] = []
    _BATCH_SIZE = 50

    with Progress(
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        auto_refresh=False,
    ) as prog:
        task = prog.add_task("publisher: 0 filled, 0 failed", total=total)

        def _task(row: dict) -> tuple[str, str | None, str]:
            pid = row["paper_id"]
            url = row["url"] or ""
            domain = "unknown"
            try:
                abstract = fetch_publisher_abstract(client, url, timeout=timeout)
                if "doi.org" in url:
                    try:
                        r = client.head(url, follow_redirects=True, timeout=timeout)
                        domain = str(r.url.host).lower()
                    except Exception:
                        domain = url.split("/")[2].lower()
                else:
                    domain = url.split("/")[2].lower()
                return pid, abstract, domain
            except Exception:
                return pid, None, domain

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_task, row): (row["paper_id"], row.get("venue", "?"))
                for row in rows
            }

            for future in as_completed(futures):
                pid, venue = futures[future]
                try:
                    pid2, abstract, domain = future.result()
                except Exception:
                    abstract, domain = None, "err"

                if abstract:
                    batch.append((pid, abstract))
                    if len(batch) >= _BATCH_SIZE:
                        _batch_update_abstracts(db, batch, "harvest_publisher")
                        batch = []
                    filled += 1
                    by_domain[domain] += 1
                else:
                    failed += 1
                    console.log(f"[dim]publisher miss: [{venue}] {pid.split('/')[-1][:30]} -> {domain}[/dim]")
                prog.update(task, description=f"publisher: {filled} filled, {failed} failed")
                prog.advance(task)
                prog.refresh()

        if batch:
            _batch_update_abstracts(db, batch, "harvest_publisher")

    return {
        "source": "publisher",
        "processed": total,
        "filled": filled,
        "failed": failed,
        "by_domain": dict(by_domain),
    }


def fetch_all_missing_abstracts(
    db: DB,
    cfg: Any | None = None,
    *,
    openreview: bool = True,
    publisher: bool = True,
    or_delay: float = 1.1,
    pub_workers: int = 3,
    pub_delay: float = 0.5,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run both OpenReview and publisher abstract fetchers.

    Returns combined stats.
    """
    client = httpx.Client(
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        proxy=os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or None,
    )
    try:
        stats: dict[str, Any] = {}
        if openreview:
            or_stats = fetch_openreview_abstracts(
                db, client, delay=or_delay, limit=limit
            )
            stats["openreview"] = or_stats
        if publisher:
            pub_stats = fetch_publisher_abstracts(
                db, client, workers=pub_workers, delay=pub_delay, limit=limit
            )
            stats["publisher"] = pub_stats
        return stats
    finally:
        client.close()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
