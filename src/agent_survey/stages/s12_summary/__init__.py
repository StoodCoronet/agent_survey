"""Stage 11: generate 3-4 sentence bilingual summaries for every paper."""
from __future__ import annotations

import threading
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

from ...analysis.stats import write_stage_stats
from ...core.config import Config, resolve_topic
from ...core.console import console
from ...core.db import DB
from ...services.llm import DeepSeekClient
from .core import process_paper


def run(
    cfg: Config,
    *,
    force: bool = False,
    workers: int = 20,
    topic_name: str = "",
) -> dict:
    topic_name = resolve_topic(topic_name, cfg)
    db_path = cfg.abs_path("db")
    db = DB(db_path)

    # Query paper_topics for core relevance
    paper_ids = []
    for pt in db.iter_paper_topics(topic_name, "relevance = ?", ["core"]):
        if not force and pt.get("summary_en"):
            continue
        paper_ids.append(pt["paper_id"])
    total = len(paper_ids)
    if not total:
        console.print("[yellow]no papers left to summarize[/yellow]")
        return {"processed": 0}

    console.print(
        Panel(
            f"[bold]Topic[/bold]              : {topic_name}\n"
            f"[bold]Papers to summarize[/bold] : {total:,}\n"
            f"[bold]Workers[/bold]            : {workers}",
            title="Paper Summary Generation",
            border_style="cyan",
        )
    )

    stage_cfg = cfg.llm.stage11_summary or cfg.llm.stage3_classify
    llm = DeepSeekClient(cfg)

    processed = 0
    failed = 0
    skipped = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_api_calls = 0
    total_cached_hits = 0
    lock = Lock()

    progress_columns = [
        TextColumn("[progress.description]{task.description}"),
        MofNCompleteColumn(),
        TextColumn("[green]ok {task.fields[saved]}[/green]"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    ]
    token_line = Text("in0 out0 tot0", style="cyan")
    prog = Progress(*progress_columns, console=console, auto_refresh=False)

    pending_writes: list[dict] = []
    FLUSH_EVERY = 20

    def _flush(buf: list[dict]) -> None:
        if not buf:
            return
        for item in buf:
            if item.get("no_abstract"):
                db.upsert_paper_topic(
                    item["paper_id"], topic_name,
                    {"summary_en": "", "summary_zh": ""},
                    commit=False,
                )
            else:
                db.upsert_paper_topic(
                    item["paper_id"], topic_name,
                    {"summary_en": item["summary_en"], "summary_zh": item["summary_zh"]},
                    commit=False,
                )
            db.mark_stage(item["paper_id"], "summary", topic_name=topic_name, commit=False)
        db._conn.commit()

    with Live(Group(token_line, prog), console=console, refresh_per_second=4):
        task = prog.add_task(
            f"summary ({stage_cfg.model}) [{workers}w]",
            total=total,
            saved=0,
        )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(process_paper, pid, cfg, db_path, llm, topic_name): pid
                for pid in paper_ids
            }

            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:
                    with lock:
                        failed += 1
                    prog.advance(task)
                    continue

                if result.get("success"):
                    with lock:
                        processed += 1
                        if result.get("no_abstract"):
                            skipped += 1
                    pending_writes.append(result)
                else:
                    with lock:
                        failed += 1

                if len(pending_writes) >= FLUSH_EVERY:
                    _flush(pending_writes)
                    pending_writes = []

                u = result.get("usage") or {}
                if result.get("no_abstract"):
                    pass  # no actual API call happened
                elif result.get("cached"):
                    total_cached_hits += 1
                else:
                    total_prompt_tokens += u.get("prompt_tokens", 0) or 0
                    total_completion_tokens += u.get("completion_tokens", 0) or 0
                    total_api_calls += 1

                token_line.plain = (
                    f"in{total_prompt_tokens:,} out{total_completion_tokens:,} "
                    f"tot{total_prompt_tokens + total_completion_tokens:,}"
                )
                prog.advance(task)
                prog.update(task, saved=processed)

        # Final flush
        _flush(pending_writes)

    total_tokens = total_prompt_tokens + total_completion_tokens
    cost_input = total_prompt_tokens / 1_000_000 * 0.14
    cost_output = total_completion_tokens / 1_000_000 * 0.28
    cost_total = cost_input + cost_output

    summary_lines = [
        f"[bold]Processed[/bold]        : {processed:,}",
        f"[bold]Failed[/bold]           : {failed:,}",
        f"[bold]Skipped (no abstract)[/bold] : {skipped:,}",
        f"[bold]API calls[/bold]        : {total_api_calls:,}",
        f"[bold]Cache hits[/bold]       : {total_cached_hits:,}",
        f"[bold]Tokens[/bold]           : {total_tokens:,} ({total_prompt_tokens:,} in + {total_completion_tokens:,} out)",
        f"[bold]Est. cost[/bold]        : ${cost_total:.2f}",
    ]
    console.print(Panel("\n".join(summary_lines), title="Summary Done", border_style="green"))

    stats = {
        "stage": "summary",
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
        "api_calls": total_api_calls,
        "cached_hits": total_cached_hits,
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens,
        "est_cost_usd": round(cost_total, 4),
    }
    write_stage_stats(cfg, "summary", stats)
    return stats
