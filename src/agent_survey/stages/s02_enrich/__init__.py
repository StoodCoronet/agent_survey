"""Stage 1: fill abstract using S2 → arXiv → OpenReview → Crossref (DOI) → venue-specific fallback."""
from __future__ import annotations

import concurrent.futures
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table

from ...analysis.stats import write_stage_stats
from ...core.config import Config
from ...core.console import console
from ...core.db import DB
from .core import (
    _build_worker_table,
    _clear_screen,
    _clear_worker_job,
    _is_s2_first,
    _set_worker_job,
    _VENUE_SKIP_MIN,
    _VENUE_SKIP_THRESHOLD,
)
from .sources import _try_one_source, get_source_workers, get_venue_strategies, _DEFAULT_SOURCES


def run(
    cfg: Config,
    *,
    all_papers: bool = True,
    force: bool = False,
    patch: bool = False,
    limit: int | None = None,
    topic_name: str = "",
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

        # Determine classification scope: if topic_name given, check that topic only
        if topic_name:
            classified_count = db._conn.execute(
                "SELECT COUNT(*) FROM paper_topics WHERE topic_name = ? AND relevance IN ('core', 'related', 'adjacent')",
                (topic_name,),
            ).fetchone()[0]
        else:
            classified_count = db._conn.execute(
                "SELECT COUNT(*) FROM paper_topics WHERE relevance IN ('core', 'related', 'adjacent')"
            ).fetchone()[0]

        where = " AND ".join(conditions) if conditions else "1=1"

        console.print("[dim]loading papers from database...[/dim]")
        rows = [r for r in db.iter_papers(where)]

        console.print(f"[dim]loaded {len(rows):,} papers[/dim]")

        if classified_count > 0 and not all_papers:
            scope = f"topic '{topic_name}'" if topic_name else "any topic"
            console.print(
                f"[cyan]classification detected in {scope}; targeting core/related/adjacent only ({len(rows):,})[/cyan]"
            )
        else:
            console.print(
                f"[cyan]enriching all papers needing abstracts ({len(rows):,})[/cyan]"
            )

        if limit:
            rows = rows[:limit]

        total = len(rows)
        if not total:
            console.print("[yellow]nothing to enrich[/yellow]")
            return {"processed": 0, "filled": 0}

        # ── Show per-venue strategy overview ────────────────────
        _venue_set = sorted(set(r.get("venue") or "?" for r in rows))
        if _venue_set:
            strat_tbl = Table(title="enrich strategy by venue", show_header=True, box=None)
            strat_tbl.add_column("Venue", style="cyan", width=10)
            strat_tbl.add_column("Papers", justify="right", width=8)
            strat_tbl.add_column("Sources", style="green", width=40)
            for vn in _venue_set:
                cnt = sum(1 for r in rows if r.get("venue") == vn)
                strategies = get_venue_strategies()
                sources = strategies.get(vn, _DEFAULT_SOURCES)
                strat_tbl.add_row(vn, str(cnt), ", ".join(sources))
            console.print(strat_tbl)

        all_total = db.count()
        before_with_abs = db.count("abstract IS NOT NULL AND abstract != ''")

        http = httpx.Client(
            timeout=cfg.network.request_timeout,
            headers={"User-Agent": cfg.network.user_agent},
            proxy=cfg.http_proxy or None,
        )

        filled = 0
        failed = 0
        processed = 0
        skipped_count = 0
        by_source: Counter = Counter()
        by_venue: Counter = Counter()
        by_venue_source: Counter = Counter()  # (venue, source) → count
        venue_attempts: Counter = Counter()
        venue_fails: Counter = Counter()
        skipped_venues: set[str] = set()

        it = iter(rows)
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
        task = progress.add_task("enrich (papers)", total=total, rate=0.0)

        def _refresh():
            _clear_screen()
            console.print(_build_worker_table())
            console.print(progress)

        # ── Per-source worker pools ──────────────────────────
        src_workers = get_source_workers()
        source_pools: dict[str, ThreadPoolExecutor] = {}
        for src, n in src_workers.items():
            if n > 0:
                source_pools[src] = ThreadPoolExecutor(max_workers=n)

        strategies = get_venue_strategies()

        # (future, row, source_index) — source_index tracks which source in the
        # venue's strategy this future is executing.
        pending: dict[concurrent.futures.Future, tuple[dict, int]] = {}

        def _submit_one(row: dict, src_idx: int = 0):
            """Submit a paper to the source at src_idx in its venue strategy."""
            venue = row.get("venue") or "?"
            venue_srcs = strategies.get(venue, _DEFAULT_SOURCES)
            if src_idx >= len(venue_srcs):
                # All sources exhausted → mark failed
                nonlocal failed, processed
                processed += 1
                failed += 1
                venue_fails[venue] += 1
                db.update_paper(
                    row["paper_id"],
                    {"enrich_source": "failed", "enrich_at": datetime.now(timezone.utc).isoformat()},
                )
                return

            source_name = venue_srcs[src_idx]
            pool = source_pools.get(source_name)
            if pool is None:
                # Source disabled (workers=0) → skip to next
                _submit_one(row, src_idx + 1)
                return

            cache_path = str(cfg.abs_path("db").parent / "abstract_cache.sqlite")
            f = pool.submit(_try_one_source, http, cfg.semantic_scholar_api_key, row, source_name, cache_path)
            pending[f] = (row, src_idx)

        def _top_up():
            nonlocal processed
            while len(pending) < sum(src_workers.values()) * 2:
                try:
                    r = next(it)
                    _submit_one(r, 0)
                except StopIteration:
                    break

        _top_up()
        _refresh()

        while pending or processed < total:
            done, _ = concurrent.futures.wait(
                pending, timeout=0.3, return_when=concurrent.futures.FIRST_COMPLETED,
            )

            for future in done:
                row, src_idx = pending.pop(future)
                paper_id = row["paper_id"]
                venue = row.get("venue") or "?"

                try:
                    abstract, arxiv_id, pdf_url, source = future.result()
                except Exception as e:
                    console.print(f"[red]error {paper_id}: {e}[/red]")
                    abstract = None
                    source = None

                venue_attempts[venue] += 1
                processed += 1

                if abstract:
                    db.update_paper(
                        paper_id,
                        {"abstract": abstract, "arxiv_id": arxiv_id or row.get("arxiv_id"),
                         "pdf_url": pdf_url or row.get("pdf_url"),
                         "enrich_source": source, "enrich_at": datetime.now(timezone.utc).isoformat()},
                    )
                    filled += 1
                    by_source[source] += 1
                    by_venue[venue] += 1
                    by_venue_source[(venue, source)] += 1
                    if source != "cache":
                        from ...services.abstract_cache import store
                        cache_path = str(cfg.abs_path("db").parent / "abstract_cache.sqlite")
                        store(cache_path, venue, row.get("title") or "", abstract)
                else:
                    venue_fails[venue] += 1
                    # Try next source in strategy
                    _submit_one(row, src_idx + 1)

                if processed % 100 == 0:
                    db._conn.commit()

            _top_up()

            elapsed = time.perf_counter() - start_time
            rate = processed / elapsed if elapsed > 0 else 0.0
            top_src = ", ".join(f"{s}:{c}" for s, c in by_source.most_common(3))
            progress.update(task, completed=processed, rate=rate,
                          description=f"enrich  ✅{filled}  ❌{failed}  💾{skipped_count}  [{top_src}]")
            _refresh()

        # Shut down source pools
        for name, pool in source_pools.items():
            pool.shutdown(wait=True)

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
            "by_venue_source": {f"{v}/{s}": c for (v, s), c in by_venue_source.items()},
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

        if by_venue_source:
            # Show per-venue source breakdown (top venues)
            vs_t = Table(title="by venue × source", show_header=True, box=None)
            vs_t.add_column("venue", style="cyan", width=10)
            vs_t.add_column("source", style="green", width=14)
            vs_t.add_column("count", justify="right", style="magenta")
            top_venues = sorted(set(v for v, _ in by_venue_source), key=lambda v: -by_venue.get(v, 0))[:10]
            for vn in top_venues:
                first = True
                for s in sorted(set(src for (v, src), _ in by_venue_source if v == vn)):
                    vs_t.add_row(vn if first else "", s, str(by_venue_source[(vn, s)]))
                    first = False
            console.print(vs_t)

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
def run_arxiv(cfg: Config) -> dict:
    console.print(
        "[yellow]enrich-arxiv is deprecated; use `agent-survey enrich` instead[/yellow]"
    )
    return run(cfg)


# enrich-web fallback
from .web import run_web  # noqa: E402
