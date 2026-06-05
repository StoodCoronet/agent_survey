"""Stage 10: generate bilingual descriptions for taxonomy categories (two-phase).

Dimension root (tree_name itself, e.g. application-domain):
  No papers are read. Based on the sub-categories under this dimension,
  generate a description of WHY this dimension exists and WHAT it organises.

Sub-categories (level 1+ paths, e.g. GUI Agent / Desktop GUI):
  Phase A — Abstract Selection:
    Collect ALL core papers in that category, sorted by venue tier.
    Feed abstracts to DeepSeek; it picks 5 most representative
    (diverse, non-redundant, prefer newer & top-venue).
  Phase B — Full-text Summarisation:
    Read PDF excerpts of the selected papers and generate:
      - desc_en / desc_zh   (3-4 sentences each)
      - metadata_json       {methods, datasets, trends}
    Level-aware emphasis:
      - level 1 (sub-category)    → plain-language overview of the sub-field
      - level 2+ (leaf)           → concrete techniques & challenges
"""
from __future__ import annotations

import json
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

from ...analysis.stats import print_overview, write_stage_stats
from ...core.config import Config, resolve_topic
from ...core.console import console
from ...core.db import DB
from ...services.llm import DeepSeekClient
from .core import collect_all_paths, process_category, process_dimension_root


def run(
    cfg: Config,
    *,
    force: bool = False,
    limit: int | None = None,
    workers: int = 3,
    topic_name: str = "",
) -> dict:
    topic_name = resolve_topic(topic_name, cfg)
    db_path = cfg.abs_path("db")
    db = DB(db_path)
    try:
        # Collect all taxonomy_json values from paper_topics
        tax_jsons = []
        for pt in db.iter_paper_topics(
            topic_name,
            "relevance = 'core' AND taxonomy_json IS NOT NULL AND taxonomy_json != '' AND taxonomy_json != '{}'",
        ):
            tax_jsons.append(json.dumps(pt["taxonomy_json"]) if isinstance(pt["taxonomy_json"], dict) else pt["taxonomy_json"])
        tree_paths = collect_all_paths(tax_jsons)

        # Build task list: dimension roots + sub-categories
        all_tasks: list[tuple[str, str]] = []
        for tree_name in sorted(tree_paths):
            # Dimension root (path="") — describes WHY this dimension exists
            all_tasks.append((tree_name, ""))
            # Sub-categories under this dimension
            for p in sorted(tree_paths[tree_name]):
                all_tasks.append((tree_name, p))

        if limit:
            all_tasks = all_tasks[:limit]

        # Pre-register all tasks and set / reset status
        for tree, path in all_tasks:
            status = "pending" if force else None
            db.upsert_taxonomy_desc(tree, path, status=status, topic_name=topic_name)

        # Filter out already-done if not force
        if not force:
            existing = {
                (r["tree_name"], r["path"])
                for r in db.iter_taxonomy_descs(topic_name)
                if r.get("status") == "done" or r.get("desc_en")
            }
            all_tasks = [t for t in all_tasks if t not in existing]

        total = len(all_tasks)
        if not total:
            console.print("[yellow]no categories left to describe[/yellow]")
            return {"processed": 0}

        dim_roots = sum(1 for _, p in all_tasks if p == "")
        sub_cats = total - dim_roots
        console.print(
            Panel(
                f"[bold]Dimension roots[/bold] : {dim_roots:,}\n"
                f"[bold]Sub-categories[/bold]  : {sub_cats:,}\n"
                f"[bold]Workers[/bold]         : {workers}",
                title="Category Description Generation",
                border_style="cyan",
            )
        )

        stage_cfg = cfg.llm.stage10_category_desc or cfg.llm.stage3_classify
        llm = DeepSeekClient(cfg)

        processed = 0
        failed = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_api_calls = 0
        total_cached_hits = 0
        lock = Lock()

        progress_columns = [
            TextColumn("[progress.description]{task.description}"),
            MofNCompleteColumn(),
            TextColumn("[green]saved {task.fields[saved]}[/green]"),
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
                if item.get("error"):
                    db.set_taxonomy_status(
                        item["tree_name"], item["path"], "failed",
                        last_error=item["last_error"], topic_name=topic_name, commit=False,
                    )
                else:
                    db.upsert_taxonomy_desc(
                        item["tree_name"], item["path"],
                        desc_en=item.get("desc_en") or None,
                        desc_zh=item.get("desc_zh") or None,
                        paper_count=item.get("paper_count"),
                        topic_name=topic_name,
                        metadata=item.get("metadata") or None,
                        commit=False,
                    )
                    db.set_taxonomy_status(
                        item["tree_name"], item["path"], "done",
                        topic_name=topic_name, commit=False,
                    )
            db._conn.commit()

        with Live(Group(token_line, prog), console=console, refresh_per_second=4):
            task = prog.add_task(
                f"category-desc (categories) ({stage_cfg.model}) [{workers}w]",
                total=total,
                saved=0,
            )

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {}
                for tree, path in all_tasks:
                    db.set_taxonomy_status(tree, path, "processing", topic_name=topic_name, commit=False)
                    if path == "":
                        f = executor.submit(process_dimension_root, tree, cfg, tree_paths, db_path, llm, topic_name)
                    else:
                        f = executor.submit(process_category, tree, path, cfg, db_path, llm, topic_name)
                    futures[f] = (tree, path)

                db._conn.commit()

                for future in as_completed(futures):
                    tree_name, path = futures[future]
                    try:
                        result = future.result()
                        tree_name, path, desc_en, desc_zh, paper_count, metadata, meta = result
                    except Exception as exc:
                        console.print(f"[red]Crashed {tree_name}/{path}: {exc}[/red]")
                        with lock:
                            failed += 1
                        pending_writes.append({
                            "tree_name": tree_name, "path": path,
                            "error": True, "last_error": str(exc)[:500],
                        })
                        prog.advance(task)
                        continue

                    if meta.get("errors"):
                        with lock:
                            failed += 1
                        pending_writes.append({
                            "tree_name": tree_name, "path": path,
                            "error": True, "last_error": meta.get("last_error", ""),
                        })
                    else:
                        with lock:
                            processed += 1
                        pending_writes.append({
                            "tree_name": tree_name, "path": path,
                            "error": False,
                            "desc_en": desc_en, "desc_zh": desc_zh,
                            "paper_count": paper_count, "metadata": metadata,
                        })

                    if len(pending_writes) >= FLUSH_EVERY:
                        _flush(pending_writes)
                        pending_writes = []

                    u = meta.get("usage") or {}
                    if meta.get("cached"):
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
            f"[bold]API calls[/bold]        : {total_api_calls:,}",
            f"[bold]Cache hits[/bold]       : {total_cached_hits:,}",
            f"[bold]Total tokens[/bold]     : {total_tokens:,}",
            f"[bold]Est. cost (USD)[/bold] : ${cost_total:.2f}",
        ]
        console.print(
            Panel(
                "\n".join(summary_lines),
                title="Category Description Summary",
                border_style="green",
            )
        )

        stats = {
            "processed": processed,
            "failed": failed,
            "total_categories": total,
            "tokens": {
                "prompt": total_prompt_tokens,
                "completion": total_completion_tokens,
                "total": total_tokens,
            },
            "api_calls": total_api_calls,
            "cached_hits": total_cached_hits,
            "estimated_cost_usd": round(cost_total, 2),
        }
        out = write_stage_stats(cfg, "category_desc", stats)
        print_overview(db, "after category desc")
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
