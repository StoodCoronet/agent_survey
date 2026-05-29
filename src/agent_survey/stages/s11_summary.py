"""Stage 11: generate 3-4 sentence bilingual summaries for every paper."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

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
from threading import Lock

from ..analysis.stats import write_stage_stats
from ..core.config import Config
from ..core.console import console
from ..core.db import DB
from ..services.llm import DeepSeekClient, cached_chat_json

_SYSTEM = """You are an academic paper summarizer.
Read the title and abstract, then write a concise summary in 3-4 sentences.
Return strict JSON only."""

_USER_TEMPLATE = """Title: {title}

Abstract:
{abstract}

Write a 3-4 sentence summary of this paper's core contribution in BOTH English and Chinese.

- English: clear, accessible to someone familiar with CS/AI but not the exact sub-field
- Chinese: natural academic Chinese, same length and level of detail as the English version

Return strict JSON:
{{"summary_en": "...", "summary_zh": "..."}}"""


def _build_prompt(title: str, abstract: str) -> list[dict]:
    # Truncate abstract to keep prompt size reasonable
    abstract = abstract.strip()[:4000]
    user = _USER_TEMPLATE.format(title=title, abstract=abstract)
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]


def _process_paper(
    paper_id: str,
    cfg: Config,
    db_path: Path,
    llm: DeepSeekClient,
) -> dict[str, Any]:
    """Process a single paper. Returns result dict."""
    db = DB(db_path)
    try:
        paper = db.get_paper(paper_id)
        if not paper:
            return {"paper_id": paper_id, "success": False, "error": "not found"}

        title = paper.get("title", "")
        abstract = paper.get("abstract", "") or ""

        if not abstract.strip():
            # No abstract — mark as done with empty summary so we don't retry forever
            db.update_paper(paper_id, {"summary_en": "", "summary_zh": ""})
            db.mark_stage(paper_id, "summary")
            return {"paper_id": paper_id, "success": True, "cached": False, "no_abstract": True}

        messages = _build_prompt(title, abstract)
        stage_cfg = cfg.llm.stage11_summary or cfg.llm.stage3_classify

        out = cached_chat_json(
            llm,
            db,
            paper_id=paper_id,
            stage="summary",
            model=stage_cfg.model,
            prompt_version=stage_cfg.prompt_version,
            messages=messages,
            temperature=stage_cfg.temperature,
            max_tokens=stage_cfg.max_tokens,
        )
        data = out.get("content", {})
        summary_en = data.get("summary_en", "").strip()
        summary_zh = data.get("summary_zh", "").strip()

        db.update_paper(paper_id, {"summary_en": summary_en, "summary_zh": summary_zh})
        db.mark_stage(paper_id, "summary")

        return {
            "paper_id": paper_id,
            "success": True,
            "cached": out.get("cached", False),
            "usage": out.get("usage") or {},
        }
    except Exception as exc:
        return {"paper_id": paper_id, "success": False, "error": str(exc)}
    finally:
        db.close()


def run(
    cfg: Config,
    *,
    force: bool = False,
    workers: int = 20,
) -> dict:
    db_path = cfg.abs_path("db")
    db = DB(db_path)

    where = "relevance = 'core'"
    if not force:
        where += " AND (summary_en IS NULL OR summary_en = '')"

    paper_ids = [r["paper_id"] for r in db.iter_papers(where)]
    total = len(paper_ids)
    if not total:
        console.print("[yellow]no papers left to summarize[/yellow]")
        return {"processed": 0}

    console.print(
        Panel(
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

    with Live(Group(token_line, prog), console=console, refresh_per_second=4):
        task = prog.add_task(
            f"summary ({stage_cfg.model}) [{workers}w]",
            total=total,
            saved=0,
        )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_process_paper, pid, cfg, db_path, llm): pid
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
                else:
                    with lock:
                        failed += 1

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
