"""Stage 6: incremental topic classification with multi-label support.

For each batch of papers, LLM outputs:
- matched topic IDs (multi-label, with scores)
- suggested new topics (with parent, confidence, reason)

New topics are collected into a queue and processed AFTER all batches finish,
to avoid race conditions and duplicate creation under concurrency.
"""
from __future__ import annotations

import json
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
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
from rich.table import Table

from ..analysis.stats import print_overview, write_stage_stats
from ..core.config import Config
from ..core.console import console
from ..core.db import DB
from ..services.llm import DeepSeekClient, cached_chat_json
from ..services.taxonomy import TaxonomyManager

# ------------------------------------------------------------------
# Prompts
# ------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert research assistant classifying AI-agent papers into a topic taxonomy.

Your task: for each paper, decide which existing topics it belongs to (multi-label), and suggest new topics if none fit well.

Rules:
- A paper CAN match multiple topics.
- Only suggest a NEW topic if the paper clearly does NOT fit any existing topic.
- New topic confidence must reflect how clearly the paper defines a distinct theme.
- Focus on agent testing, agent security, and dataset/benchmark generation. General agent applications are lower priority.

Output strict JSON with two keys: "papers" and "new_topics".
"""


def _build_batch_messages(papers: list[dict], topics: list[dict]) -> list[dict]:
    paper_blocks = []
    for i, p in enumerate(papers, 1):
        abs_text = p.get("abstract") or ""
        if abs_text:
            block = f"""[{i}] Title: {p['title']}
Venue: {p.get('venue', '')} ({p.get('year', '')})
Abstract: {abs_text}"""
        else:
            block = f"""[{i}] Title: {p['title']}
Venue: {p.get('venue', '')} ({p.get('year', '')})
⚠️ Only title available."""
        paper_blocks.append(block)

    topic_lines = "\n".join(
        f"- {t['id']}: {t['name']} / {t['name_zh']} — {t['desc']}"
        for t in topics
    )

    user = f"""Existing topics (match papers to these IDs):
{topic_lines}

Papers to classify ({len(papers)}):
---
{"\n---\n".join(paper_blocks)}
---

Return JSON with exactly these keys:
{{
  "papers": [
    {{
      "paper_idx": 1,
      "topic_ids": ["sec_attack", "test_redteam"],
      "topic_scores": {{"sec_attack": 0.92, "test_redteam": 0.75}},
      "rationale": "short sentence explaining why"
    }}
  ],
  "new_topics": [
    {{
      "parent_id": "sec_attack",
      "name": "Prompt Injection",
      "name_zh": "提示注入",
      "desc": "specific description",
      "confidence": 0.95,
      "paper_idx": 1,
      "reason": "why this new topic is needed"
    }}
  ]
}}

If no new topics needed, return "new_topics": [].
If a paper matches no existing topic and no new topic is warranted, set "topic_ids": []."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


# ------------------------------------------------------------------
# Batch worker
# ------------------------------------------------------------------

def _process_batch(
    batch: list[dict],
    cfg: Config,
    stage_cfg: Any,
    taxonomy: TaxonomyManager,
    db: DB | None = None,
    llm: DeepSeekClient | None = None,
) -> tuple[list[dict], dict, Exception | None, dict]:
    """Process one batch. Returns (batch, results_dict, error, meta)."""
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
        messages = _build_batch_messages(batch, taxonomy.list_for_prompt())
        out = cached_chat_json(
            llm,
            db,
            paper_id=f"batch_{batch[0]['paper_id']}",
            stage="topic_classify",
            model=stage_cfg.model,
            prompt_version=stage_cfg.prompt_version,
            messages=messages,
            temperature=stage_cfg.temperature,
            max_tokens=stage_cfg.max_tokens * len(batch),
        )
        u = out.get("usage") or {}
        cached = out.get("cached", False)
        raw = out.get("raw", json.dumps(out["content"]))
        data = json.loads(raw) if isinstance(out.get("content"), dict) else out["content"]
        if isinstance(data, dict):
            return batch, data, None, _meta(u, cached)
        # wrapped in extra dict sometimes
        for key in ("results", "data"):
            if key in data and isinstance(data[key], dict):
                return batch, data[key], None, _meta(u, cached)
        return batch, {"papers": [], "new_topics": []}, None, _meta(u, cached)
    except Exception as e:
        return batch, {}, e, _meta(err=True)
    finally:
        if own_db:
            db.close()


# ------------------------------------------------------------------
# Queue-based topic creation (post-batch, single-threaded)
# ------------------------------------------------------------------

def _drain_new_topic_queue(
    taxonomy: TaxonomyManager,
    queue: list[dict],
    auto_create_threshold: float,
) -> tuple[int, list[dict]]:
    """Deduplicate and create new topics from collected suggestions.

    Returns (auto_created_count, pending_list).
    """
    # Deduplicate by normalized (name, name_zh) key
    seen: set[str] = set()
    unique: list[dict] = []
    for nt in queue:
        key = f"{nt.get('name', '').lower().strip()}|{nt.get('name_zh', '').lower().strip()}"
        if key in seen:
            continue
        # also skip if already exists in taxonomy
        exists = False
        for t in taxonomy.topics.values():
            if t.name.lower() == nt.get("name", "").lower().strip():
                exists = True
                break
            if t.name_zh.lower() == nt.get("name_zh", "").lower().strip():
                exists = True
                break
        if exists:
            continue
        seen.add(key)
        unique.append(nt)

    auto_created = 0
    pending: list[dict] = []
    for nt in unique:
        conf = nt.get("confidence", 0.0)
        if conf >= auto_create_threshold:
            taxonomy.add_topic(
                parent_id=nt.get("parent_id"),
                name=nt["name"],
                name_zh=nt["name_zh"],
                desc=nt["desc"],
                source="auto",
            )
            auto_created += 1
        else:
            pending.append(nt)

    return auto_created, pending


# ------------------------------------------------------------------
# Main run
# ------------------------------------------------------------------

def run(
    cfg: Config,
    *,
    force: bool = False,
    limit: int | None = None,
    batch_size: int = 10,
    workers: int = 2,
    auto_create_threshold: float = 0.8,
) -> dict:
    db = DB(cfg.abs_path("db"))
    try:
        # scope: relevant papers with abstracts
        where = "relevance IN ('core', 'related', 'adjacent') AND abstract IS NOT NULL AND abstract != ''"
        if not force:
            where += " AND (topics_json IS NULL OR topics_json = '' OR topics_json = '[]')"

        rows = [r for r in db.iter_papers(where)]
        if limit:
            rows = rows[:limit]
        total = len(rows)
        if not total:
            console.print("[yellow]no papers left to topic-classify[/yellow]")
            return {"processed": 0}

        taxonomy_path = cfg.project_root / "output" / "taxonomy" / "taxonomy.json"
        taxonomy = TaxonomyManager(taxonomy_path)

        stage_cfg = cfg.llm.stage3_classify  # reuse same model config

        console.print(
            Panel(
                f"[bold]Papers[/bold]      : {total:,}\n"
                f"[bold]Topics[/bold]      : {len(taxonomy.topics)}\n"
                f"[bold]Batch size[/bold] : {batch_size}\n"
                f"[bold]Workers[/bold]    : {workers}\n"
                f"[bold]Auto-create[/bold]: confidence >= {auto_create_threshold}",
                title="Topic Classification",
                border_style="cyan",
            )
        )

        batches = [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]

        processed = 0
        failed = 0
        topic_counter: Counter = Counter()
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

        # Queue for new topic suggestions (thread-safe list via lock)
        new_topic_queue: list[dict] = []
        queue_lock = Lock()

        with Live(Group(token_line, prog), console=console, refresh_per_second=4):
            task = prog.add_task(
                f"topic-classify ({stage_cfg.model}) [{workers}w]",
                total=total,
                saved=0,
            )

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_process_batch, batch, cfg, stage_cfg, taxonomy): batch
                    for batch in batches
                }

                for future in as_completed(futures):
                    batch, result, err, meta = future.result()
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

                    paper_results = result.get("papers", [])
                    new_topics = result.get("new_topics", [])

                    # persist paper tags (DB is thread-safe via connection locking)
                    with lock:
                        for pr in paper_results:
                            idx = pr.get("paper_idx", 1) - 1
                            if idx < 0 or idx >= len(batch):
                                continue
                            paper = batch[idx]
                            topic_ids = pr.get("topic_ids", [])
                            db.update_paper(
                                paper["paper_id"],
                                {
                                    "topics_json": topic_ids,
                                },
                            )
                            db.mark_stage(paper["paper_id"], "topic_classify", "done")
                            for tid in topic_ids:
                                topic_counter[tid] += 1
                            processed += 1

                        # enqueue new topic suggestions (do NOT create yet)
                        with queue_lock:
                            new_topic_queue.extend(new_topics)

                        taxonomy.bump_count(
                            [tid for pr in paper_results for tid in pr.get("topic_ids", [])]
                        )
                        prog.advance(task, advance=len(batch))
                        prog.update(task, saved=processed)

        # ------------------------------------------------------------------
        # AFTER all batches: drain the queue once, single-threaded
        # ------------------------------------------------------------------
        with queue_lock:
            queue_snapshot = list(new_topic_queue)

        new_topics_auto, new_topics_pending = _drain_new_topic_queue(
            taxonomy, queue_snapshot, auto_create_threshold
        )

        # summary
        table = Table(title="Topic Distribution", show_header=True, box=None)
        table.add_column("Topic ID", style="cyan")
        table.add_column("Name", style="white")
        table.add_column("Count", justify="right", style="magenta")
        for tid, c in sorted(topic_counter.items(), key=lambda x: -x[1]):
            t = taxonomy.topics.get(tid)
            name = t.name if t else tid
            table.add_row(tid, name, str(c))
        console.print(table)

        if new_topics_auto:
            console.print(f"[green]Auto-created {new_topics_auto} new topics[/green]")
        if new_topics_pending:
            console.print(f"[yellow]{len(new_topics_pending)} pending new topics for review[/yellow]")
            pending_path = cfg.project_root / "output" / "taxonomy" / "pending_topics.json"
            pending_path.write_text(
                json.dumps(new_topics_pending, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            console.print(f"[dim]wrote pending topics to {pending_path}[/dim]")

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
                title="Topic Classification Summary",
                border_style="green",
            )
        )

        stats = {
            "processed": processed,
            "failed": failed,
            "by_topic": dict(topic_counter),
            "new_topics_auto": new_topics_auto,
            "new_topics_pending": len(new_topics_pending),
            "tokens": {
                "prompt": total_prompt_tokens,
                "completion": total_completion_tokens,
                "total": total_tokens,
            },
            "api_calls": total_api_calls,
            "cached_hits": total_cached_hits,
            "estimated_cost_usd": round(cost_total, 2),
        }
        out = write_stage_stats(cfg, "topic_classify", stats)
        print_overview(db, "after topic classify")
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
