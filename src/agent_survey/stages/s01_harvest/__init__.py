"""Stage 0: DBLP harvest for every (venue, year).

Single-threaded sequential fetch to respect DBLP rate limits and avoid
background threads that outlive their timeout. DB writes go to a dedicated
writer thread via a queue.
"""
from __future__ import annotations

import queue
import time
from collections import Counter
from threading import Event, Thread

from rich.console import Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from ...analysis.stats import print_overview, write_stage_stats
from ...core.config import Config
from ...core.console import console
from ...core.db import DB
from .core import fetch_venue_year, format_error

_SENTINEL = object()  # queue termination signal
_BATCH_SIZE = 200     # papers per DB commit


def _db_writer(db_path, paper_queue: queue.Queue, stop: Event, progress_cb):
    """Drain paper_queue and batch-insert into SQLite on a single thread.

    Creates its own DB connection since SQLite connections are thread-affine.
    Catches and logs flush errors so one bad batch does not kill the thread
    and lose the rest of the queue.
    """
    from ...core.db import DB
    from ...core.console import console

    db = DB(db_path)
    batch: list[dict] = []
    try:
        while True:
            try:
                item = paper_queue.get(timeout=0.3)
            except queue.Empty:
                if stop.is_set() and paper_queue.empty():
                    break
                continue

            if item is _SENTINEL:
                break

            batch.append(item)
            if len(batch) >= _BATCH_SIZE:
                try:
                    _flush_batch(db, batch)
                    if progress_cb:
                        progress_cb(len(batch))
                except Exception as e:
                    console.print(f"[red]batch writer error ({len(batch)} rows): {e}[/red]")
                batch = []

        if batch:
            try:
                _flush_batch(db, batch)
                if progress_cb:
                    progress_cb(len(batch))
            except Exception as e:
                console.print(f"[red]batch writer final error ({len(batch)} rows): {e}[/red]")
    finally:
        db.close()


def _flush_batch(db: DB, batch: list[dict]) -> None:
    """Insert a batch of papers in a single transaction.

    Avoids upsert_paper() because it commits after each row.
    """
    import json as _json
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).isoformat()
    cols = [
        "paper_id", "dblp_key", "title", "year", "authors_json",
        "doi", "url", "venue", "venue_area", "venue_type",
        "stage_status_json", "created_at", "updated_at",
    ]
    placeholders = ",".join(["?"] * len(cols))
    update = ",".join(
        f"{c}=excluded.{c}" for c in cols
        if c not in ("paper_id", "created_at")
    )
    sql = (
        f"INSERT INTO papers ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(paper_id) DO UPDATE SET {update}"
    )

    rows = []
    for p in batch:
        authors = p.get("authors")
        if authors is not None and not isinstance(authors, str):
            authors = _json.dumps(authors, ensure_ascii=False)
        status_json = _json.dumps({"harvest": "done"}, ensure_ascii=False)
        rows.append((
            p["paper_id"], p.get("dblp_key"), p["title"], p.get("year"),
            authors, p.get("doi"), p.get("url"), p.get("venue"),
            p.get("venue_area"), p.get("venue_type"),
            status_json, ts, ts,
        ))

    db._conn.execute("BEGIN IMMEDIATE")
    db._conn.executemany(sql, rows)
    db._conn.commit()


def _flush_writer_remaining(db: DB, q: queue.Queue) -> None:
    """Drain any remaining items from the queue into the DB."""
    batch: list[dict] = []
    while True:
        try:
            item = q.get_nowait()
        except queue.Empty:
            break
        if item is _SENTINEL:
            continue
        batch.append(item)
    if batch:
        _flush_batch(db, batch)


def run(
    cfg: Config,
    *,
    force: bool = False,
    fetch_abstracts: bool = False,
    openreview: bool = True,
    publisher: bool = True,
) -> dict:
    years = list(range(cfg.years.start, cfg.years.end + 1))
    all_venues = [("conf", v) for v in cfg.venues.conferences] + [
        ("journal", v) for v in cfg.venues.journals
    ]

    db_path = cfg.abs_path("db")
    skipped = 0
    by_venue: Counter = Counter()
    db = DB(db_path)
    try:
        # init papers counter from DB so a restart shows cumulative total
        initial_total = db.count()
        inserted = initial_total

        # ── Queue + writer thread for bulk DB writes ───────────────
        paper_queue: queue.Queue = queue.Queue()
        writer_stop = Event()
        writer_inserted = [0]  # mutable counter for callback

        def _on_flush(n: int) -> None:
            writer_inserted[0] += n

        writer_thread = Thread(
            target=_db_writer,
            args=(db_path, paper_queue, writer_stop, _on_flush),
            daemon=True,
        )
        writer_thread.start()

        # two stacked progress tasks (line 1 status, line 2 bar) for narrow terms
        status_progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            console=console,
        )
        bar_progress = Progress(
            TextColumn("[bold]{task.fields[stage]}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("•"),
            TextColumn("[green]papers:{task.fields[papers]}"),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("ETA"),
            TimeRemainingColumn(),
            console=console,
        )

        # one combination = one task in the pool — skip (venue, year)
        # combos already finished in a previous run unless --force
        all_combos = [
            (vtype, vc, year)
            for vtype, vc in all_venues
            for year in years
        ]
        tasks_args: list = []
        skipped_done = 0
        for vtype, vc, year in all_combos:
            st = db.get_harvest_status(vc.name, year)
            if not force and st in ("done", "empty"):
                skipped_done += 1
                continue
            tasks_args.append((vtype, vc, year))
        total_combos = len(all_combos)
        if skipped_done:
            console.print(
                f"[yellow]using cache:[/yellow] "
                f"[bold]{skipped_done}/{total_combos}[/bold] (venue, year) combos "
                f"already harvested; [dim]{len(tasks_args)} to crawl "
                f"(use --force to re-crawl all)[/dim]"
            )
        if not tasks_args and not fetch_abstracts:
            console.print("[green]nothing to harvest[/green]")
            writer_stop.set()
            paper_queue.put(_SENTINEL)
            writer_thread.join(timeout=5)
            print_overview(db, "harvest overview")
            return {
                "initial_total": initial_total,
                "final_total": initial_total,
                "newly_inserted": 0,
                "skipped_existing": 0,
                "skipped_done": skipped_done,
                "by_venue_year": {},
            }

        if tasks_args:
            group = Group(status_progress, bar_progress)
            with Live(group, console=console, refresh_per_second=8):
                status_tid = status_progress.add_task(
                    "[dim]idle[/dim]", start=True, total=None
                )
                stage_label = (
                    f"harvest (cache:{skipped_done})" if skipped_done else "harvest"
                )
                bar_task = bar_progress.add_task(
                    "bar",
                    total=total_combos,
                    completed=skipped_done,
                    papers=initial_total,
                    stage=stage_label,
                )

                for args in tasks_args:
                    vtype, vc, year = args
                    status_progress.update(
                        status_tid,
                        description=f"[cyan]{vc.name} {year}[/cyan] fetching…",
                    )

                    vc, year, papers, err = fetch_venue_year(args, cfg)

                    if err is not None:
                        short, detail = format_error(err)
                        console.print(
                            f"[red]error {vc.name} {year}[/red]: {short}"
                        )
                        console.print(f"[dim]{detail}[/dim]")
                        db.mark_harvest_failed(vc.name, year, detail)
                        bar_progress.advance(bar_task)
                        time.sleep(5)
                        continue

                    added = 0
                    for paper in papers:
                        existing = db.get_paper(paper["paper_id"])
                        if existing and not force:
                            skipped += 1
                            continue
                        row = {
                            "paper_id": paper["paper_id"],
                            "dblp_key": paper.get("dblp_key"),
                            "title": paper["title"],
                            "year": paper.get("year"),
                            "authors_json": paper.get("authors"),
                            "doi": paper.get("doi"),
                            "url": paper.get("url"),
                            "venue": paper.get("venue"),
                            "venue_area": paper.get("venue_area"),
                            "venue_type": paper.get("venue_type"),
                            "stage_status_json": {"harvest": "done"},
                        }
                        paper_queue.put(dict(row))
                        inserted += 1
                        by_venue[(vc.name, year)] += 1
                        added += 1

                    status_progress.update(
                        status_tid,
                        description=f"[green]{vc.name} {year}[/green]  +{added} (saved)",
                    )
                    inserted = initial_total + writer_inserted[0]
                    bar_progress.update(bar_task, papers=inserted)
                    bar_progress.advance(bar_task)
                    db.mark_harvest_done(vc.name, year, len(papers))
                    time.sleep(5)

            # ── Shutdown writer thread ─────────────────────────────
            writer_stop.set()
            paper_queue.put(_SENTINEL)
            writer_thread.join(timeout=30)
            # Final drain in case writer missed anything
            _flush_writer_remaining(db, paper_queue)
            inserted = initial_total + writer_inserted[0]

            stats = {
                "initial_total": initial_total,
                "final_total": inserted,
                "newly_inserted": inserted - initial_total,
                "skipped_existing": skipped,
                "skipped_done": skipped_done,
                "by_venue_year": {f"{v}/{y}": c for (v, y), c in by_venue.items()},
            }
            out_path = write_stage_stats(cfg, "harvest", stats)
            print_overview(db, "harvest overview")
            console.print(f"[green]wrote stats to {out_path}[/green]")
        else:
            stats = {
                "initial_total": initial_total,
                "final_total": inserted,
                "newly_inserted": 0,
                "skipped_existing": 0,
                "skipped_done": skipped_done,
                "by_venue_year": {},
            }

        # ------------------------------------------------------------------
        # Post-harvest abstract fetching (OpenReview + publishers)
        # ------------------------------------------------------------------
        if fetch_abstracts:
            from ...services.harvest_abstract import fetch_all_missing_abstracts

            console.rule("[bold cyan]fetching abstracts from sources")
            abs_stats = fetch_all_missing_abstracts(
                db, openreview=openreview, publisher=publisher
            )
            for source, src_stats in abs_stats.items():
                if src_stats.get("processed", 0) > 0:
                    console.print(
                        f"[green]{source}[/green]: filled {src_stats['filled']:,} / {src_stats['processed']:,}"
                    )
            stats["abstract_fetch"] = abs_stats

        return stats
    finally:
        db.close()
