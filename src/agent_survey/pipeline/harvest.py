"""Stage 0: DBLP harvest for every (venue, year).

Uses a ThreadPoolExecutor to fetch multiple (venue, year) combinations in
parallel. DB writes happen on the main thread to keep SQLite simple.
"""
from __future__ import annotations

import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import httpx
from tenacity import RetryError
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from ..config import Config
from ..console import console
from ..db import DB
from ..sources import dblp
from .stats import print_overview, write_stage_stats


def _unwrap(exc: BaseException) -> BaseException:
    """Peel tenacity.RetryError to get the actual underlying exception."""
    if isinstance(exc, RetryError) and exc.last_attempt is not None:
        try:
            return exc.last_attempt.exception() or exc
        except Exception:
            return exc
    return exc


def _format_err(err: BaseException) -> tuple[str, str]:
    """Return (short_one_liner, long_detail) for logging."""
    inner = _unwrap(err)
    short = f"{type(err).__name__} → {type(inner).__name__}: {inner}"

    lines: list[str] = [f"outer: {type(err).__name__}: {err!r}"]
    if inner is not err:
        lines.append(f"inner: {type(inner).__name__}: {inner!r}")

    # httpx-specific context (URL, method, status, body snippet)
    req = getattr(inner, "request", None)
    if req is not None:
        try:
            lines.append(f"url   : {req.method} {req.url}")
        except Exception:
            pass
    resp = getattr(inner, "response", None)
    if resp is not None:
        try:
            body = resp.text[:300].replace("\n", " ")
            lines.append(f"status: {resp.status_code}")
            lines.append(f"body  : {body}")
        except Exception:
            pass

    # traceback of the inner cause
    tb = "".join(
        traceback.format_exception(type(inner), inner, inner.__traceback__)
    ).rstrip()
    if tb and tb != f"{type(inner).__name__}: {inner}":
        lines.append("traceback:")
        lines.append(tb)

    return short, "\n".join(lines)


def run(cfg: Config, *, force: bool = False, workers: int | None = None) -> dict:
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
        from rich.console import Group
        from rich.live import Live

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
        if not tasks_args:
            console.print("[green]nothing to harvest[/green]")
            print_overview(db, "harvest overview")
            return {
                "initial_total": initial_total,
                "final_total": initial_total,
                "newly_inserted": 0,
                "skipped_existing": 0,
                "skipped_done": skipped_done,
                "by_venue_year": {},
            }

        workers = max(1, workers if workers is not None else cfg.network.max_concurrency)

        # slot state so status_progress can show multiple in-flight workers
        slots_lock = Lock()
        slots: list[int | None] = [None] * workers  # slot -> active task_id or None
        slot_task_ids: list[int] = []

        def acquire_slot(desc: str) -> int:
            with slots_lock:
                for i in range(workers):
                    if slots[i] is None:
                        slots[i] = 1
                        status_progress.update(
                            slot_task_ids[i], description=desc, visible=True
                        )
                        return i
            return -1

        def update_slot(i: int, desc: str) -> None:
            if i < 0:
                return
            status_progress.update(slot_task_ids[i], description=desc)

        def release_slot(i: int) -> None:
            if i < 0:
                return
            with slots_lock:
                slots[i] = None
                status_progress.update(
                    slot_task_ids[i], description="[dim]idle[/dim]"
                )

        def _worker(args):
            vtype, vc, year = args
            slot = acquire_slot(f"[cyan]{vc.name} {year}[/cyan] fetching…")
            ua = cfg.network.user_agent
            client = httpx.Client(
                timeout=cfg.network.request_timeout,
                headers={"User-Agent": ua, "Accept": "application/json"},
            )
            try:
                if year in vc.skip_years:
                    papers = []
                elif vc.json_source_url:
                    url = vc.json_source_url.format(year=year)
                    from agent_survey.sources import external

                    papers = list(
                        external.fetch_json_papers(
                            url,
                            year,
                            venue_name=vc.name,
                            venue_area=vc.area,
                            venue_type=vtype,
                            client=client,
                        )
                    )
                elif vc.journal_stream:
                    vols = vc.journal_volumes.get(year, [])
                    papers = list(
                        dblp.fetch_journal_volumes(
                            vc.journal_stream,
                            vols,
                            year,
                            venue_name=vc.name,
                            venue_area=vc.area,
                            venue_type=vtype,
                            client=client,
                        )
                    )
                elif vc.toc_stream:
                    papers = list(
                        dblp.fetch_toc_xml(
                            vc.toc_stream,
                            year,
                            venue_name=vc.name,
                            venue_area=vc.area,
                            venue_type=vtype,
                            client=client,
                        )
                    )
                else:
                    papers = list(
                        dblp.fetch_venue_year(
                            vc.name,
                            year,
                            venue_area=vc.area,
                            venue_type=vtype,
                            client=client,
                            aliases=vc.aliases,
                            key_prefixes=vc.key_prefixes,
                        )
                    )
                update_slot(slot, f"[cyan]{vc.name} {year}[/cyan] got {len(papers)}")
                return (vc, year, papers, None, slot)
            except Exception as e:
                return (vc, year, [], e, slot)
            finally:
                client.close()

        group = Group(status_progress, bar_progress)
        with Live(group, console=console, refresh_per_second=8):
            # one status task per worker slot
            for i in range(workers):
                tid = status_progress.add_task(
                    "[dim]idle[/dim]", start=True, total=None
                )
                slot_task_ids.append(tid)
            stage_label = (
                f"harvest (cache:{skipped_done})" if skipped_done else "harvest"
            )
            bar_task = bar_progress.add_task(
                "bar",
                total=total_combos,
                completed=skipped_done,            # ← cached combos count as already-done
                papers=initial_total,
                stage=stage_label,
            )
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {ex.submit(_worker, a): a for a in tasks_args}
                for fut in as_completed(futures):
                    vc, year, papers, err, slot = fut.result()
                    if err is not None:
                        short, detail = _format_err(err)
                        console.print(
                            f"[red]error {vc.name} {year}[/red]: {short}"
                        )
                        console.print(f"[dim]{detail}[/dim]")
                        db.mark_harvest_failed(vc.name, year, detail)
                        release_slot(slot)
                        bar_progress.advance(bar_task)
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
                        db.upsert_paper(row)
                        inserted += 1
                        by_venue[(vc.name, year)] += 1
                        added += 1
                    update_slot(
                        slot,
                        f"[green]{vc.name} {year}[/green]  +{added} (saved)",
                    )
                    bar_progress.update(bar_task, papers=inserted)
                    bar_progress.advance(bar_task)
                    db.mark_harvest_done(vc.name, year, len(papers))
                    release_slot(slot)
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
        return stats
    finally:
        db.close()
