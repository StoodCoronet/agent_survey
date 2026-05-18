"""Stage 1: fill abstract using arXiv → S2 → OpenReview fallback."""
from __future__ import annotations

import concurrent.futures
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table

from ..analysis.stats import write_stage_stats
from ..core.config import Config
from ..core.console import console
from ..core.db import DB
from ..services import arxiv as arxiv_src
from ..services.openreview import search_title as or_search_title
from ..services.s2 import S2Client

# Thread-local S2 clients so rate-limit sleeps stay per-thread
_thread_local = threading.local()

# Track what each worker thread is currently doing (venue/year/title/source)
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


def _build_worker_table() -> Table:
    with _worker_lock:
        items = list(_worker_jobs.items())
    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("Worker", style="dim", width=7)
    table.add_column("Source", style="cyan", width=9)
    table.add_column("Venue", width=9)
    table.add_column("Year", width=5)
    table.add_column("Title")
    for tid, job in sorted(items):
        table.add_row(
            f"W{tid % 1000:03d}",
            job.get("source", "?"),
            str(job.get("venue", "?"))[:9] if job.get("venue") else "?",
            str(job.get("year", "?")) if job.get("year") else "?",
            (job.get("title", "?") or "?")[:50],
        )
    if not items:
        table.add_row("—", "idle", "—", "—", "waiting for tasks...")
    return table


def _clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def _get_s2(api_key: str) -> S2Client:
    if not hasattr(_thread_local, "s2"):
        _thread_local.s2 = S2Client(api_key=api_key)
    return _thread_local.s2


# Venue-level skip logic — if a venue fails too much, skip remaining papers
_VENUE_SKIP_MIN = 10          # min attempts before evaluating skip
_VENUE_SKIP_THRESHOLD = 0.5   # fail rate >= 50% -> skip venue

# Venues dominated by conference proceedings (S2 coverage >> arXiv)
_S2_FIRST_VENUES = {
    "icml", "neurips", "nips",
    "acl", "emnlp", "naacl", "eacl", "coling", "findings",
    "aaai", "ijcai", "aistats",
    "cvpr", "iccv", "eccv", "wacv",
    "icra", "iros", "rss",
    "kdd", "www", "sigir", "recsys", "cikm",
    "ubicomp", "chi", "cscw", "uist", "assets",
    "ase", "fse", "issta", "oopsla", "pldi", "popl", "icse", "msr",
    "usenix security", "ieee s&p", "ccs", "ndss", "raid",
}


def _is_s2_first(venue: str | None) -> bool:
    v = (venue or "").lower().replace(" proceedings", "").replace(" workshop", "").strip()
    return v in _S2_FIRST_VENUES


def _try_sources(
    http: httpx.Client,
    api_key: str,
    row: dict,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (abstract, arxiv_id, pdf_url, source) or all Nones.

    Launches S2 / arXiv / OpenReview queries concurrently in a single worker
    thread. Returns the first successful response; the remaining threads are
    left to finish or time-out on their own.
    """
    title = row.get("title") or ""
    _set_worker_job(row, "querying")

    result_event = threading.Event()
    result_box: dict = {}
    result_lock = threading.Lock()

    def _query_one(name: str, fn):
        if result_event.is_set():
            return
        try:
            res = fn()
            if res:
                with result_lock:
                    if not result_event.is_set():
                        result_box["result"] = res
                        result_box["source"] = name
                        result_event.set()
        except Exception:
            pass

    def _valid_abstract(text: str | None) -> bool:
        return bool(text) and len(text.strip()) >= 30

    def _s2_fn():
        s2 = _get_s2(api_key)
        data = s2.search_by_title(title)
        if data and _valid_abstract(data.get("abstract")):
            ext = data.get("externalIds") or {}
            oa = data.get("openAccessPdf") or {}
            return data["abstract"], ext.get("ArXiv"), oa.get("url")
        return None

    def _arxiv_fn():
        ax = arxiv_src.search_title(http, title)
        if ax and _valid_abstract(ax.get("abstract")):
            return ax["abstract"], ax.get("arxiv_id"), ax.get("pdf_url")
        return None

    def _or_fn():
        or_data = or_search_title(http, title)
        if or_data and _valid_abstract(or_data.get("abstract")):
            return or_data["abstract"], None, or_data.get("url")
        return None

    threads = [
        threading.Thread(target=_query_one, args=("s2", _s2_fn), daemon=True),
        threading.Thread(target=_query_one, args=("arxiv", _arxiv_fn), daemon=True),
        threading.Thread(target=_query_one, args=("openreview", _or_fn), daemon=True),
    ]
    for t in threads:
        t.start()

    # Wait up to 30 s for the first hit
    result_event.wait(timeout=30)

    _clear_worker_job()
    if result_box:
        r = result_box["result"]
        return r[0], r[1], r[2], result_box["source"]
    return None, None, None, None


def run(
    cfg: Config,
    *,
    all_papers: bool = False,
    force: bool = False,
    patch: bool = False,
    limit: int | None = None,
    workers: int = 5,
) -> dict:
    db = DB(cfg.abs_path("db"))
    try:
        # Build WHERE clause — push relevance filter into SQL so we don't load 70k+ rows
        conditions = []
        if patch:
            # Re-process papers with suspiciously short / garbage abstracts
            conditions.append(
                "enrich_source IN ('s2','arxiv','openreview','failed','skipped_venue','failed_web','skipped_venue_web')"
            )
            conditions.append(
                "(abstract IS NULL OR abstract = '' OR LENGTH(abstract) < 30 OR abstract IN ('.', ',', '...', 'null'))"
            )
        elif not force:
            conditions.append("(abstract IS NULL OR abstract = '')")
            conditions.append("(enrich_source IS NULL OR enrich_source = '')")

        classified_any = db.count("relevance IS NOT NULL AND relevance != ''") > 0
        if not all_papers and classified_any and not patch:
            conditions.append("relevance IN ('core', 'related', 'adjacent')")

        where = " AND ".join(conditions) if conditions else "1=1"

        console.print("[dim]loading papers from database...[/dim]")
        rows = [r for r in db.iter_papers(where)]
        console.print(f"[dim]loaded {len(rows):,} papers[/dim]")

        if not all_papers and classified_any:
            console.print(
                f"[cyan]classification detected; targeting core/related/adjacent only ({len(rows):,})[/cyan]"
            )
        elif not classified_any:
            console.print(
                f"[cyan]no classification yet; enriching all papers needing abstracts ({len(rows):,})[/cyan]"
            )

        if limit:
            rows = rows[:limit]

        total = len(rows)
        if not total:
            console.print("[yellow]nothing to enrich[/yellow]")
            return {"processed": 0, "filled": 0}

        all_total = db.count()
        before_with_abs = db.count("abstract IS NOT NULL AND abstract != ''")

        http = httpx.Client(
            timeout=cfg.network.request_timeout,
            headers={"User-Agent": cfg.network.user_agent},
        )

        filled = 0
        failed = 0
        processed = 0
        skipped_count = 0
        by_source: Counter = Counter()
        by_venue: Counter = Counter()
        venue_attempts: Counter = Counter()
        venue_fails: Counter = Counter()
        skipped_venues: set[str] = set()

        def _maybe_skip_venue(venue: str) -> bool:
            if venue in skipped_venues:
                return True
            attempts = venue_attempts[venue]
            if attempts >= _VENUE_SKIP_MIN:
                fail_rate = venue_fails[venue] / attempts
                if fail_rate >= _VENUE_SKIP_THRESHOLD:
                    skipped_venues.add(venue)
                    console.print(
                        f"[bold yellow]⏹ 跳过 venue '{venue}' "
                        f"(失败率 {venue_fails[venue]}/{attempts} = {fail_rate:.0%})[/bold yellow]"
                    )
                    return True
            return False

        def _submit_or_skip(pool, http, api_key, row):
            venue = row.get("venue") or "?"
            if _maybe_skip_venue(venue):
                nonlocal skipped_count
                db.update_paper(
                    row["paper_id"],
                    {
                        "enrich_source": "skipped_venue",
                        "enrich_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                skipped_count += 1
                by_source["skipped_venue"] += 1
                return None
            f = pool.submit(_try_sources, http, api_key, row)
            return f

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
        task = progress.add_task("enrich", total=total, rate=0.0)

        def _refresh():
            _clear_screen()
            console.print(_build_worker_table())
            console.print(progress)

        def _top_up():
            """Keep submitting from it until pending is full or it is exhausted."""
            nonlocal processed
            while len(pending) < workers * 2:
                try:
                    r = next(it)
                    f = _submit_or_skip(pool, http, cfg.semantic_scholar_api_key, r)
                    if f:
                        pending[f] = r
                    else:
                        processed += 1
                except StopIteration:
                    break

        with ThreadPoolExecutor(max_workers=workers) as pool:
            _top_up()
            _refresh()

            while pending or processed < total:
                done, _ = concurrent.futures.wait(
                    pending,
                    timeout=0.3,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                for future in done:
                    row = pending.pop(future)
                    paper_id = row["paper_id"]
                    venue = row.get("venue") or "?"

                    try:
                        abstract, arxiv_id, pdf_url, source = future.result()
                    except Exception as e:
                        console.print(f"[red]error {paper_id}: {e}[/red]")
                        abstract = None
                        source = None

                    processed += 1
                    venue_attempts[venue] += 1

                    if abstract:
                        db.update_paper(
                            paper_id,
                            {
                                "abstract": abstract,
                                "arxiv_id": arxiv_id or row.get("arxiv_id"),
                                "pdf_url": pdf_url or row.get("pdf_url"),
                                "enrich_source": source,
                                "enrich_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                        filled += 1
                        by_source[source] += 1
                        by_venue[venue] += 1
                    else:
                        venue_fails[venue] += 1
                        db.update_paper(
                            paper_id,
                            {
                                "enrich_source": "failed",
                                "enrich_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                        failed += 1

                    if processed % 100 == 0:
                        db._conn.commit()

                _top_up()

                elapsed = time.perf_counter() - start_time
                rate = processed / elapsed if elapsed > 0 else 0.0
                progress.update(
                    task,
                    completed=processed,
                    rate=rate,
                    description=f"enrich  filled:{filled} failed:{failed} skip:{skipped_count}",
                )
                _refresh()

        db._conn.commit()
        http.close()

        after_with_abs = db.count("abstract IS NOT NULL AND abstract != ''")
        stats = {
            "processed": processed,
            "filled": filled,
            "failed": failed,
            "skipped": skipped_count,
            "skipped_venues": sorted(skipped_venues),
            "by_source": dict(by_source),
            "by_venue": dict(by_venue),
            "abstract_coverage_before_pct": (
                round(before_with_abs / all_total * 100, 1) if all_total else 0
            ),
            "abstract_coverage_after_pct": (
                round(after_with_abs / all_total * 100, 1) if all_total else 0
            ),
        }
        out = write_stage_stats(cfg, "enrich", stats)

        # ── enrich-specific summary ──────────────────────────
        console.rule("[bold cyan]enrich summary")
        from rich.table import Table

        t = Table(show_header=False, box=None)
        t.add_column(style="cyan", width=22)
        t.add_column(style="magenta", justify="right")
        t.add_row("processed", f"{processed:,}")
        t.add_row("filled", f"{filled:,}")
        t.add_row("failed", f"{failed:,}")
        t.add_row("skipped venues", f"{skipped_count:,}")
        t.add_row("fill rate", f"{round(filled/processed*100,1)}%" if processed else "--")
        t.add_row("coverage before", f"{stats['abstract_coverage_before_pct']}%")
        t.add_row("coverage after", f"{stats['abstract_coverage_after_pct']}%")
        console.print(t)

        if skipped_venues:
            skip_t = Table(title="skipped venues (fail rate ≥50% after ≥10 attempts)", show_header=True, box=None)
            skip_t.add_column("venue", style="yellow")
            skip_t.add_column("attempts", justify="right", style="magenta")
            skip_t.add_column("fails", justify="right", style="magenta")
            for v in sorted(skipped_venues):
                skip_t.add_row(v, str(venue_attempts[v]), str(venue_fails[v]))
            console.print(skip_t)

        if by_source:
            src_t = Table(title="by source", show_header=True, box=None)
            src_t.add_column("source", style="cyan")
            src_t.add_column("count", justify="right", style="magenta")
            for s, c in sorted(by_source.items(), key=lambda x: -x[1]):
                src_t.add_row(s, str(c))
            console.print(src_t)

        if by_venue:
            v_t = Table(title="by venue", show_header=True, box=None)
            v_t.add_column("venue", style="cyan")
            v_t.add_column("count", justify="right", style="magenta")
            for v, c in sorted(by_venue.items(), key=lambda x: -x[1])[:15]:
                v_t.add_row(v, str(c))
            if len(by_venue) > 15:
                v_t.add_row("...", f"({len(by_venue)-15} more)")
            console.print(v_t)

        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()


# backward-compat shim for old CLI enrich-arxiv command
def run_arxiv(cfg: Config, workers: int = 2) -> dict:
    console.print(
        "[yellow]enrich-arxiv is deprecated; use `agent-survey enrich` instead[/yellow]"
    )
    return run(cfg, workers=workers)
