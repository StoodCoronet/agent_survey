"""Stage 7: multi-dimensional taxonomy classification.

Maps each paper to leaf paths across 3 independent trees:
  1. application-domain
  2. technical-approach
  3. research-goal

Plus cross-cutting tags.
"""
from __future__ import annotations

import json
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
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

from ..analysis.stats import print_overview, write_stage_stats
from ..core.config import Config
from ..core.console import console
from ..core.db import DB
from ..services.llm import DeepSeekClient, cached_chat_json
from ..services.taxonomy import (
    TREES,
    build_messages,
    merge_into_taxonomy_json,
    parse_result,
)


def _process_batch(
    batch: list[dict],
    cfg: Config,
    stage_cfg: Any,
    db: DB | None = None,
    llm: DeepSeekClient | None = None,
) -> tuple[list[dict], list[dict], Exception | None, dict]:
    """Process one batch. Returns (batch, paper_results, error, meta)."""
    worker_name = threading.current_thread().name
    own_db = db is None
    own_llm = llm is None
    db = db or DB(cfg.abs_path("db"))
    llm = llm or DeepSeekClient(cfg)

    def _meta(u: dict | None = None, c: bool = False, err: bool = False) -> dict:
        return {
            "worker": worker_name,
            "usage": dict(u) if u else {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "cached": c,
            "errors": 1 if err else 0,
        }

    try:
        messages = build_messages(batch)
        out = cached_chat_json(
            llm,
            db,
            paper_id=f"batch_{batch[0]['paper_id']}",
            stage="taxonomy_classify",
            model=stage_cfg.model,
            prompt_version="v1",
            messages=messages,
            temperature=stage_cfg.temperature,
            max_tokens=1024 * len(batch),
        )
        u = out.get("usage") or {}
        cached = out.get("cached", False)
        raw = out.get("raw", json.dumps(out["content"]))
        data = json.loads(raw) if isinstance(out.get("content"), dict) else out["content"]
        if isinstance(data, dict) and "papers" in data:
            return batch, data["papers"], None, _meta(u, cached)
        return batch, [], None, _meta(u, cached)
    except Exception as e:
        return batch, [], e, _meta(err=True)
    finally:
        if own_db:
            db.close()


def run(
    cfg: Config,
    *,
    scope: str | None = "core",
    force: bool = False,
    limit: int | None = None,
    batch_size: int = 10,
    workers: int = 2,
) -> dict:
    db = DB(cfg.abs_path("db"))
    try:
        # scope filter
        rel_filter = scope or "core"
        where = f"relevance = '{rel_filter}' AND abstract IS NOT NULL AND abstract != ''"
        if not force:
            where += " AND (taxonomy_json IS NULL OR taxonomy_json = '' OR taxonomy_json = '{}')"

        rows = [r for r in db.iter_papers(where)]
        if limit:
            rows = rows[:limit]
        total = len(rows)
        if not total:
            console.print(f"[yellow]no papers left to taxonomy-classify for scope={scope}[/yellow]")
            return {"processed": 0}

        stage_cfg = cfg.llm.stage3_classify  # reuse classify model

        console.print(
            Panel(
                f"[bold]Scope[/bold]       : {scope}\n"
                f"[bold]Papers[/bold]      : {total:,}\n"
                f"[bold]Batch size[/bold] : {batch_size}\n"
                f"[bold]Workers[/bold]    : {workers}",
                title="Taxonomy Classification",
                border_style="cyan",
            )
        )

        batches = [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]

        processed = 0
        failed = 0
        new_leaves: list[str] = []
        tree_counters: dict[str, Counter] = {t: Counter() for t in TREES}
        cross_counter: Counter = Counter()
        lock = Lock()

        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_api_calls = 0
        total_cached_hits = 0

        progress_columns = [
            TextColumn("[progress.description]{task.description}"),
            MofNCompleteColumn(),
            TextColumn("[green]saved {task.fields[saved]}[/green]"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        ]

        token_line = Text("in0 out0 tot0", style="cyan")
        prog = Progress(*progress_columns, console=console, auto_refresh=False)

        with Live(Group(token_line, prog), console=console, refresh_per_second=4):
            task = prog.add_task(
                f"taxonomy-classify ({stage_cfg.model}) [{workers}w]",
                total=total,
                saved=0,
            )

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_process_batch, batch, cfg, stage_cfg): batch
                    for batch in batches
                }

                for future in as_completed(futures):
                    batch, results, err, meta = future.result()
                    if err:
                        console.print(f"[red]batch failed ({len(batch)} papers): {err}[/red]")
                        with lock:
                            failed += len(batch)
                            prog.advance(task, advance=len(batch))
                        continue

                    u = meta.get("usage") or {}
                    if meta.get("cached"):
                        total_cached_hits += 1
                    else:
                        total_prompt_tokens += u.get("prompt_tokens", 0) or 0
                        total_completion_tokens += u.get("completion_tokens", 0) or 0
                        total_api_calls += 1
                    token_line.plain = f"in{total_prompt_tokens:,} out{total_completion_tokens:,} tot{total_prompt_tokens + total_completion_tokens:,}"

                    with lock:
                        for pr in results:
                            idx = pr.get("paper_idx", 1) - 1
                            if idx < 0 or idx >= len(batch):
                                continue
                            paper = batch[idx]

                            # Build taxonomy_json
                            paths: dict[str, list[str]] = {}
                            for tree_key in ("application_domain", "technical_approach", "research_goal"):
                                vals = pr.get(tree_key, [])
                                if vals:
                                    paths[tree_key] = vals
                                    for v in vals:
                                        tree_counters[tree_key.replace("_", "-")][v] += 1

                            cross = pr.get("cross_cutting", [])
                            if cross:
                                paths["cross_cutting"] = cross
                                for c in cross:
                                    cross_counter[c] += 1

                            # Track new leaf proposals
                            for leaf in pr.get("new_leaves", []):
                                new_leaves.append(leaf)

                            existing = paper.get("taxonomy_json")
                            existing_dict = {}
                            if existing and existing not in ("", "{}"):
                                try:
                                    existing_dict = json.loads(existing)
                                except Exception:
                                    pass

                            merged = merge_into_taxonomy_json(existing_dict, paths)
                            db.update_paper(
                                paper["paper_id"],
                                {"taxonomy_json": merged},
                            )
                            db.mark_stage(paper["paper_id"], "taxonomy_classify", "done")
                            processed += 1

                        prog.advance(task, advance=len(batch))
                        prog.update(task, saved=processed)

        total_tokens = total_prompt_tokens + total_completion_tokens
        cost_input = total_prompt_tokens / 1_000_000 * 0.14
        cost_output = total_completion_tokens / 1_000_000 * 0.28
        cost_total = cost_input + cost_output

        # Print tree distributions
        for tree_name, counter in tree_counters.items():
            if counter:
                console.print(f"\n[bold]{tree_name}[/bold]")
                for path, c in counter.most_common():
                    console.print(f"  {path}: {c}")

        if cross_counter:
            console.print("\n[bold]cross-cutting[/bold]")
            for tag, c in cross_counter.most_common():
                console.print(f"  {tag}: {c}")

        if new_leaves:
            console.print(f"\n[yellow]{len(new_leaves)} new leaf proposals[/yellow]")
            for leaf in set(new_leaves):
                console.print(f"  - {leaf}")

        summary_lines = [
            f"[bold]Processed[/bold]        : {processed:,}",
            f"[bold]Failed[/bold]           : {failed:,}",
            f"[bold]API calls[/bold]        : {total_api_calls:,}",
            f"[bold]Cache hits[/bold]       : {total_cached_hits:,}",
            f"[bold]Total tokens[/bold]     : {total_tokens:,}",
            f"[bold]Est. cost (USD)[/bold] : ${cost_total:.2f}",
        ]
        console.print(
            Panel(
                "\n".join(summary_lines),
                title="Taxonomy Classification Summary",
                border_style="green",
            )
        )

        stats = {
            "scope": scope,
            "processed": processed,
            "failed": failed,
            "by_tree": {t: dict(c) for t, c in tree_counters.items()},
            "cross_cutting": dict(cross_counter),
            "new_leaves": list(set(new_leaves)),
            "tokens": {
                "prompt": total_prompt_tokens,
                "completion": total_completion_tokens,
                "total": total_tokens,
            },
            "api_calls": total_api_calls,
            "cached_hits": total_cached_hits,
            "estimated_cost_usd": round(cost_total, 2),
        }
        out = write_stage_stats(cfg, "taxonomy_classify", stats)
        print_overview(db, "after taxonomy classify")
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
