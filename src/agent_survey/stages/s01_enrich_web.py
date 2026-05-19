"""Stage 1b: fill abstracts for failed papers using Playwright + arXiv only.

OpenReview was dropped because its rate-limit (5 req) is too strict
and papers not on arXiv are considered low-priority for this survey.
"""
from __future__ import annotations

import concurrent.futures
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from playwright.sync_api import Browser, sync_playwright
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from ..analysis.stats import write_stage_stats
from ..core.config import Config
from ..core.console import console
from ..core.db import DB


def _title_overlap(a: str, b: str) -> float:
    """Return word-overlap ratio between two titles."""
    aw = set(a.lower().split())
    bw = set(b.lower().split())
    if not aw:
        return 0.0
    return len(aw & bw) / len(aw)


def _search_arxiv(browser: Browser, expected_title: str) -> str | None:
    """Search arxiv.org by title and return abstract text.

    Validates that the first search-result title overlaps the
    expected title (>= 60 %) before trusting the abstract.
    """
    q = expected_title.replace('"', "").strip()
    url = f"https://arxiv.org/search/?query={q.replace(' ', '+')}&searchtype=all"
    page = None
    try:
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)

        body = page.inner_text("body")
        if "Rate exceeded" in body:
            return None

        result = page.query_selector(".arxiv-result")
        if result:
            title_el = result.query_selector("p.title")
            if title_el:
                found_title = title_el.inner_text().strip()
                if _title_overlap(expected_title, found_title) < 0.6:
                    return None

            abs_el = result.query_selector("p.abstract")
            if abs_el:
                full_el = abs_el.query_selector(".abstract-full")
                text = (
                    full_el.inner_text().strip()
                    if full_el
                    else abs_el.inner_text().strip()
                )
                if text.startswith("Abstract:"):
                    text = text[len("Abstract:"):].strip()
                if "\u25b3" in text:
                    text = text.split("\u25b3")[0].strip()
                if len(text) >= 30:
                    return text
    except Exception:
        pass
    finally:
        if page:
            page.close()
    return None


# Worker status tracking
_worker_jobs: dict[int, dict] = {}
_worker_lock = threading.Lock()


def _set_worker_job(row: dict, source: str = "?") -> None:
    with _worker_lock:
        _worker_jobs[threading.get_ident()] = {
            "title": row.get("title", "?"),
            "venue": row.get("venue", "?"),
            "year": row.get("year", "?"),
            "source": source,
        }


def _clear_worker_job() -> None:
    with _worker_lock:
        _worker_jobs.pop(threading.get_ident(), None)


def _build_worker_table():
    from rich.table import Table

    with _worker_lock:
        items = list(_worker_jobs.items())
    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("Worker", style="dim", width=7)
    table.add_column("Venue", width=9)
    table.add_column("Year", width=5)
    table.add_column("Title")
    for tid, job in sorted(items):
        table.add_row(
            f"W{tid % 1000:03d}",
            str(job.get("venue", "?"))[:9] if job.get("venue") else "?",
            str(job.get("year", "?")) if job.get("year") else "?",
            (job.get("title", "?") or "?")[:50],
        )
    if not items:
        table.add_row("—", "—", "—", "waiting for tasks...")
    return table


def _clear_screen() -> None:
    import sys

    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def run(
    cfg: Config,
    *,
    limit: int | None = None,
    workers: int = 1,
) -> dict:
    db = DB(cfg.abs_path("db"))
    try:
        conditions = [
            "relevance IN ('core', 'related', 'adjacent')",
            "AND ((abstract IS NULL OR abstract = '')",
            "  OR (LENGTH(abstract) < 30 AND enrich_source != 'web')",
            "  OR (abstract IN ('.', ',', '...', 'null', '[]', '{}')))",
        ]
        where = " ".join(conditions)

        console.print("[dim]loading papers from database...[/dim]")
        rows = [r for r in db.iter_papers(where)]
        console.print(f"[dim]loaded {len(rows):,} papers needing web enrichment[/dim]")

        if limit:
            rows = rows[:limit]

        total = len(rows)
        if not total:
            console.print("[yellow]nothing to enrich via web[/yellow]")
            return {"processed": 0, "filled": 0}

        # Launch shared browser once
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            headless=False,
            args=["--no-startup-window", "--window-position=2000,0"],
        )

        filled = 0
        failed = 0
        processed = 0
        skipped_count = 0
        by_venue: Counter = Counter()
        venue_attempts: Counter = Counter()
        venue_fails: Counter = Counter()
        skipped_venues: set[str] = set()

        _VENUE_SKIP_MIN = 10
        _VENUE_SKIP_THRESHOLD = 0.5

        def _maybe_skip_venue(venue: str) -> bool:
            if venue in skipped_venues:
                return True
            attempts = venue_attempts[venue]
            if attempts >= _VENUE_SKIP_MIN:
                fail_rate = venue_fails[venue] / attempts
                if fail_rate >= _VENUE_SKIP_THRESHOLD:
                    skipped_venues.add(venue)
                    console.print(
                        f"[bold yellow]\u23f9 \u8df3\u8fc7 venue '{venue}' "
                        f"(\u5931\u8d25\u7387 {venue_fails[venue]}/{attempts} = {fail_rate:.0%})[/bold yellow]"
                    )
                    return True
            return False

        def _submit_or_skip(pool, row):
            venue = row.get("venue") or "?"
            if _maybe_skip_venue(venue):
                nonlocal skipped_count
                db.update_paper(
                    row["paper_id"],
                    {
                        "enrich_source": "skipped_venue_web",
                        "enrich_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                skipped_count += 1
                return None
            f = pool.submit(_try_web_enrich, row)
            return f

        def _try_web_enrich(row: dict) -> str | None:
            _set_worker_job(row, "arxiv")
            abstract = _search_arxiv(browser, row.get("title", ""))
            _clear_worker_job()
            time.sleep(3.0)  # respect arXiv crawl-delay
            return abstract

        it = iter(rows)
        pending: dict[concurrent.futures.Future, dict] = {}

        start_time = time.perf_counter()

        progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=20),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("[{task.completed}/{task.total}]"),
            TextColumn("[green]{task.fields[rate]:.1f}/s"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            auto_refresh=False,
        )
        task = progress.add_task("enrich-web", total=total, rate=0.0)

        def _refresh():
            _clear_screen()
            console.print(_build_worker_table())
            console.print(progress)

        def _top_up(pool):
            nonlocal processed
            while len(pending) < workers * 2:
                try:
                    r = next(it)
                    f = _submit_or_skip(pool, r)
                    if f:
                        pending[f] = r
                    else:
                        processed += 1
                except StopIteration:
                    break

        with ThreadPoolExecutor(max_workers=workers) as pool:
            _top_up(pool)
            _refresh()

            while pending or processed < total:
                done, _ = concurrent.futures.wait(
                    pending,
                    timeout=0.5,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                for future in done:
                    row = pending.pop(future)
                    paper_id = row["paper_id"]
                    venue = row.get("venue") or "?"

                    try:
                        abstract = future.result()
                    except Exception as e:
                        console.print(f"[red]error {paper_id}: {e}[/red]")
                        abstract = None

                    processed += 1
                    venue_attempts[venue] += 1

                    if abstract:
                        db.update_paper(
                            paper_id,
                            {
                                "abstract": abstract,
                                "enrich_source": "web",
                                "enrich_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                        filled += 1
                        by_venue[venue] += 1
                    else:
                        venue_fails[venue] += 1
                        if not row.get("enrich_source") or row.get("enrich_source") == "":
                            db.update_paper(
                                paper_id,
                                {
                                    "enrich_source": "failed_web",
                                    "enrich_at": datetime.now(timezone.utc).isoformat(),
                                },
                            )
                        failed += 1

                    if processed % 50 == 0:
                        db._conn.commit()

                _top_up(pool)

                elapsed = time.perf_counter() - start_time
                rate = processed / elapsed if elapsed > 0 else 0.0
                progress.update(
                    task,
                    completed=processed,
                    rate=rate,
                    description=f"enrich-web  filled:{filled} failed:{failed} skip:{skipped_count}",
                )
                _refresh()

        db._conn.commit()
        browser.close()
        playwright.stop()

        stats = {
            "processed": processed,
            "filled": filled,
            "failed": failed,
            "skipped": skipped_count,
            "skipped_venues": sorted(skipped_venues),
            "by_venue": dict(by_venue),
        }
        out = write_stage_stats(cfg, "enrich_web", stats)

        console.rule("[bold cyan]enrich-web summary")
        from rich.table import Table

        t = Table(show_header=False, box=None)
        t.add_column(style="cyan", width=22)
        t.add_column(style="magenta", justify="right")
        t.add_row("processed", f"{processed:,}")
        t.add_row("filled", f"{filled:,}")
        t.add_row("failed", f"{failed:,}")
        t.add_row("skipped venues", f"{skipped_count:,}")
        t.add_row("fill rate", f"{round(filled/processed*100,1)}%" if processed else "--")
        console.print(t)

        if skipped_venues:
            skip_t = Table(title="skipped venues", show_header=True, box=None)
            skip_t.add_column("venue", style="yellow")
            skip_t.add_column("attempts", justify="right", style="magenta")
            skip_t.add_column("fails", justify="right", style="magenta")
            for v in sorted(skipped_venues):
                skip_t.add_row(v, str(venue_attempts[v]), str(venue_fails[v]))
            console.print(skip_t)

        if by_venue:
            v_t = Table(title="by venue", show_header=True, box=None)
            v_t.add_column("venue", style="cyan")
            v_t.add_column("count", justify="right", style="magenta")
            for v, c in sorted(by_venue.items(), key=lambda x: -x[1])[:15]:
                v_t.add_row(v, str(c))
            console.print(v_t)

        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
