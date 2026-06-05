"""Stage 3: venue-aware batch classification with DeepSeek (concurrent).

Two strategies:
- default (full): classify EVERY paper (slower, ~$6-7, but most thorough)
- --prefilter-only: only classify keyword hits (faster, ~$0.2)

Venue-aware prompts:
- Core venues (SE/Security Big-4): title + abstract (arXiv-enriched)
- All other venues: title-only (be more inclusive)

Batching: groups papers into batches (default 10) to reduce API calls.
Concurrency: multiple workers call DeepSeek API in parallel.
"""
from __future__ import annotations

import json
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from rich.console import Group, Text
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from pathlib import Path

import yaml

import queue

from ...core.config import Config, load_stage_config, load_topic_config, resolve_topic
from ...core.console import console
from ...core.db import DB, now_iso
from ...analysis.stats import print_overview, write_stage_stats
from .core import process_batch_worker


def _humanize(n: int) -> str:
    if n < 1_000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1_000:.1f}K"
    return f"{n / 1_000_000:.2f}M"


def _fmt_tokens(p: int, c: int) -> str:
    return f"in{_humanize(p)} out{_humanize(c)} tot{_humanize(p + c)}"


def _load_stage_config():
    return load_stage_config("classify")


def run(
    cfg: Config,
    *,
    only_prefilter_hits: bool = True,
    force: bool = False,
    limit: int | None = None,
    batch_size: int | None = None,
    workers: int | None = None,
    topic_name: str = "",
) -> dict:
    sconf = _load_stage_config()
    s_llm = sconf.get("llm", {})
    batch_size = batch_size or s_llm.get("batch_size", 10)
    workers = workers or s_llm.get("workers", 2)
    limit = limit or sconf.get("limit", 0) or None

    topic_name = resolve_topic(topic_name, cfg)
    tc = load_topic_config(topic_name)
    classify_cfg = tc.classify
    rev_levels = classify_cfg.relevance_levels
    pt_version = cfg.llm.stage3_classify.prompt_version
    if force:
        # Bump prompt version to bypass stale LLM cache on full re-run
        pt_version = pt_version + "_force"

    db = DB(cfg.abs_path("db"))
    try:
        # Checkpoint: count using paper_topics, prefilter is topic-scoped
        # Total papers in scope = papers with prefilter_hit for this topic
        total_in_scope = db.count()
        if only_prefilter_hits:
            # Count papers with non-empty prefilter_hit for this topic
            total_in_scope = 0
            for r in db.iter_papers():
                ph = r.get("prefilter_hit") or "{}"
                try:
                    phd = json.loads(ph) if isinstance(ph, str) else ph
                except Exception:
                    phd = {}
                if phd.get(topic_name):
                    total_in_scope += 1

        already_done = db.count_topic(topic_name, "relevance IS NOT NULL AND relevance != ''")

        where_parts: list[str] = []
        if not force:
            # Need to check per-paper: not done yet for this topic
            pass  # handled below
        rows = list(db.iter_papers())
        # Filter: papers that need classification for this topic
        todo = []
        for r in rows:
            if only_prefilter_hits:
                ph = r.get("prefilter_hit") or "{}"
                try:
                    phd = json.loads(ph) if isinstance(ph, str) else ph
                except Exception:
                    phd = {}
                if not phd.get(topic_name):
                    continue
            if not force:
                pt = db.get_paper_topic(r["paper_id"], topic_name)
                if pt and pt.get("relevance"):
                    continue  # already done
            todo.append(r)
        if limit:
            todo = todo[:limit]
        if not todo:
            console.print("[yellow]no papers left to classify[/yellow]")
            return {"classified": 0}

        remaining = len(todo)
        console.print(
            Panel(
                f"[bold]Topic[/bold]      : {topic_name}\n"
                f"[bold]Scope[/bold]      : {total_in_scope:,} papers\n"
                f"[bold]Done[/bold]       : {already_done:,}\n"
                f"[bold]Remaining[/bold]  : {remaining:,}\n"
                f"[bold]Workers[/bold]    : {workers}\n"
                f"[bold]Batch size[/bold] : {batch_size}",
                title="Checkpoint",
                border_style="cyan",
            )
        )

        stage_cfg = cfg.llm.stage3_classify
        rel_counter: Counter = Counter()
        domain_counter: Counter = Counter()
        method_counter: Counter = Counter()
        failed = 0
        processed = 0

        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_api_calls = 0
        total_cached_hits = 0
        worker_stats: dict[str, Any] = {}

        batches = []
        for i in range(0, len(todo), batch_size):
            batches.append(todo[i : i + batch_size])

        lock = Lock()
        token_line = Text("in0 out0 tot0", style="cyan")
        in_flight = 0          # futures currently running
        stalled_count = 0      # how many times we detected stall
        last_progress_ts = time.time()

        def _accumulate(meta: dict, paper_count: int, error: bool = False):
            nonlocal total_prompt_tokens, total_completion_tokens, total_api_calls, total_cached_hits, last_progress_ts
            w = meta.get("worker", "unknown")
            if w not in worker_stats:
                worker_stats[w] = {
                    "batches": 0, "papers": 0, "prompt_tokens": 0,
                    "completion_tokens": 0, "errors": 0, "cached_hits": 0,
                }
            ws = worker_stats[w]
            ws["batches"] += 1
            ws["papers"] += paper_count
            if error:
                ws["errors"] += 1
            if meta.get("cached"):
                ws["cached_hits"] += 1
                total_cached_hits += 1
            else:
                u = meta.get("usage") or {}
                ws["prompt_tokens"] += u.get("prompt_tokens", 0)
                ws["completion_tokens"] += u.get("completion_tokens", 0)
                total_prompt_tokens += u.get("prompt_tokens", 0)
                total_completion_tokens += u.get("completion_tokens", 0)
                total_api_calls += 1
            token_line.plain = _fmt_tokens(total_prompt_tokens, total_completion_tokens)
            last_progress_ts = time.time()

        progress_columns = [
            TextColumn("[progress.description]{task.description}"),
            MofNCompleteColumn(),
            TextColumn("[green]saved {task.fields[saved]}[/green]"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        ]

        interrupted = False
        prog = Progress(*progress_columns, console=console, auto_refresh=False)
        # ── Queue-based DB writer (single thread, batch commit) ──
        # Bounded queue prevents memory explosion when workers produce faster
        # than the writer can flush (e.g. all cache hits).
        write_queue: queue.Queue = queue.Queue(maxsize=500)
        writer_error: list[Exception] = []

        def _writer():
            dbw = DB(cfg.abs_path("db"))
            buf: list[tuple] = []
            batch_sz = 50
            ts = now_iso()
            try:
                while True:
                    try:
                        item = write_queue.get(timeout=2)
                    except queue.Empty:
                        # Periodic flush so small trailing batches don't sit idle
                        if buf:
                            _bulk_upsert(dbw, buf, ts)
                            buf = []
                        continue
                    if item is None:
                        if buf:
                            _bulk_upsert(dbw, buf, ts)
                        break
                    buf.append(item)
                    if len(buf) >= batch_sz:
                        _bulk_upsert(dbw, buf, ts)
                        buf = []
            except Exception as exc:
                writer_error.append(exc)
                console.print(f"[red]Writer thread crashed: {exc}[/red]")
            finally:
                dbw.close()

        def _bulk_upsert(dbw, buf, ts):
            dbw._conn.execute("BEGIN")
            for paper_id, topic_name, res in buf:
                rel = (res.get("relevance") or "").lower()
                if rel not in rev_levels:
                    rel = "irrelevant"
                dbw._conn.execute(
                    """
                    INSERT INTO paper_topics
                        (paper_id, topic_name, relevance, domain_primary,
                         domain_secondary_json, method_tags_json, tldr, rationale, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(paper_id, topic_name) DO UPDATE SET
                        relevance=excluded.relevance,
                        domain_primary=excluded.domain_primary,
                        domain_secondary_json=excluded.domain_secondary_json,
                        method_tags_json=excluded.method_tags_json,
                        tldr=excluded.tldr,
                        rationale=excluded.rationale,
                        updated_at=excluded.updated_at
                    """,
                    (
                        paper_id, topic_name, rel,
                        res.get("domain_primary"),
                        json.dumps(res.get("domain_secondary") or [], ensure_ascii=False),
                        json.dumps(res.get("method_tags") or [], ensure_ascii=False),
                        res.get("tldr"),
                        res.get("rationale"),
                        ts,
                    ),
                )
                dbw._conn.execute(
                    """
                    UPDATE papers SET stage_status_json = json_set(
                        COALESCE(stage_status_json, '{}'), ?, 'done'
                    ) WHERE paper_id = ?
                    """,
                    (f"$.{topic_name}.classify", paper_id),
                )
            dbw._conn.commit()

        writer = threading.Thread(target=_writer, daemon=True)
        writer.start()

        with Live(Group(token_line, prog), console=console, refresh_per_second=4):
            task = prog.add_task(
                f"classify ({stage_cfg.model}) [{workers}w][{topic_name}]",
                total=remaining,
                saved=0,
            )

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        process_batch_worker, batch, cfg, stage_cfg,
                        classify_cfg, pt_version, topic_name=topic_name
                    ): batch
                    for batch in batches
                }

                # ---- Heartbeat: log every 30s and detect stalls ----
                stop_heartbeat = threading.Event()
                def _heartbeat():
                    while not stop_heartbeat.is_set():
                        stop_heartbeat.wait(30)
                        if stop_heartbeat.is_set():
                            break
                        idle = time.time() - last_progress_ts
                        pending = len(futures)
                        done_count = processed + failed
                        in_flight_approx = min(workers, pending - done_count)
                        # Use plain print to avoid competing with Live for the console lock
                        print(
                            f"[heartbeat] done={done_count}/{pending} "
                            f"in_flight≈{in_flight_approx} idle={idle:.0f}s "
                            f"tokens={_fmt_tokens(total_prompt_tokens, total_completion_tokens)}"
                        )
                        if idle > 120:
                            console.print(
                                f"[yellow]STALL: no progress for {idle:.0f}s — "
                                f"likely API timeout/rate-limit. Consider reducing --workers.[/yellow]"
                            )

                hb = threading.Thread(target=_heartbeat, daemon=True)
                hb.start()

                try:
                    for future in as_completed(futures, timeout=None):
                        # Early abort if writer crashed
                        if writer_error:
                            console.print(
                                f"[red]Writer thread crashed: {writer_error[0]}. Aborting...[/red]"
                            )
                            break

                        batch, results, err, meta = future.result()
                        if err:
                            _accumulate(meta, len(batch), error=True)
                            console.print(
                                f"[red]batch failed ({len(batch)} papers): {err}[/red]"
                            )
                            with lock:
                                failed += len(batch)
                                prog.advance(task, advance=len(batch))
                                prog.update(task, saved=processed)
                            continue

                        _accumulate(meta, len(batch))
                        with lock:
                            for paper, res in zip(batch, results or []):
                                rel = (res.get("relevance") or "").lower()
                                if rel not in rev_levels:
                                    rel = "irrelevant"
                                rel_counter[rel] += 1
                                if res.get("domain_primary"):
                                    domain_counter[res["domain_primary"]] += 1
                                for t in res.get("method_tags") or []:
                                    method_counter[t] += 1
                                processed += 1
                                # Queue DB write instead of direct write
                                try:
                                    write_queue.put((paper["paper_id"], topic_name, res), timeout=1)
                                except queue.Full:
                                    # Writer likely stalled/crashed; skip queueing
                                    pass
                            prog.advance(task, advance=len(batch))
                            prog.update(task, saved=processed)
                except KeyboardInterrupt:
                    interrupted = True
                    console.print("\n[red]Interrupted by user. Shutting down workers...[/red]")
                    for fut in futures:
                        fut.cancel()
                finally:
                    stop_heartbeat.set()

        # Signal writer to flush remaining items
        try:
            write_queue.put(None, timeout=5)
        except queue.Full:
            console.print("[yellow]Writer queue full (writer may have crashed); skipping graceful shutdown[/yellow]")
        writer.join(timeout=120)
        if writer.is_alive():
            console.print("[yellow]Writer thread still alive after 120s timeout — data may be lost[/yellow]")
        if writer_error:
            console.print(f"[red]Writer error: {writer_error[0]}[/red]")

        # ---- Checkpoint summary ----
        if interrupted:
            console.print(
                Panel(
                    f"[bold]Saved[/bold]      : {processed:,}\n"
                    f"[bold]Failed[/bold]     : {failed:,}\n"
                    f"[bold]Remaining[/bold]  : {remaining - processed - failed:,}",
                    title="Checkpoint (interrupted)",
                    border_style="yellow",
                )
            )

        # ---- Visual summary ----
        table = Table(title="Worker Status", show_lines=True)
        table.add_column("Worker", style="cyan", no_wrap=True)
        table.add_column("Batches", justify="right")
        table.add_column("Papers", justify="right")
        table.add_column("Prompt Tokens", justify="right")
        table.add_column("Completion Tokens", justify="right")
        table.add_column("Errors", justify="right")
        table.add_column("Cache Hits", justify="right")
        for w, s in sorted(worker_stats.items()):
            table.add_row(
                w,
                str(s["batches"]),
                str(s["papers"]),
                f"{s['prompt_tokens']:,}",
                f"{s['completion_tokens']:,}",
                f"[red]{s['errors']}[/red]" if s["errors"] else "0",
                f"[green]{s['cached_hits']}[/green]" if s["cached_hits"] else "0",
            )
        console.print(table)

        total_tokens = total_prompt_tokens + total_completion_tokens
        cost_input = total_prompt_tokens / 1_000_000 * 0.14
        cost_output = total_completion_tokens / 1_000_000 * 0.28
        cost_total = cost_input + cost_output

        summary_lines = [
            f"[bold]API calls[/bold]       : {total_api_calls:,}",
            f"[bold]Cache hits[/bold]      : {total_cached_hits:,}",
            f"[bold]Prompt tokens[/bold]   : {total_prompt_tokens:,}",
            f"[bold]Completion tokens[/bold]: {total_completion_tokens:,}",
            f"[bold]Total tokens[/bold]    : {total_tokens:,}",
            f"[bold]Est. cost (USD)[/bold] : ${cost_total:.2f}  (in ${cost_input:.2f} / out ${cost_output:.2f})",
        ]
        console.print(
            Panel(
                "\n".join(summary_lines),
                title="Token & Cost Summary",
                border_style="green",
            )
        )

        stats = {
            "processed": processed,
            "failed": failed,
            "by_relevance": dict(rel_counter),
            "by_domain_primary": dict(domain_counter),
            "by_method_tag": dict(method_counter),
            "tokens": {
                "prompt": total_prompt_tokens,
                "completion": total_completion_tokens,
                "total": total_tokens,
            },
            "api_calls": total_api_calls,
            "cached_hits": total_cached_hits,
            "estimated_cost_usd": round(cost_total, 2),
            "worker_stats": worker_stats,
        }
        out = write_stage_stats(cfg, "classify", stats)
        print_overview(db, "after classify")
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
