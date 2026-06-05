"""Stage 6b: sub-topic discovery + dedup within topic, before deepdive.

Two-stage LLM pipeline:
1. Discover sub-topics per topic (batch of 20-25 papers)
2. Dedup within each (topic, sub-topic) group (batch of 20-25 papers)

Venue bias:
- SE/Security venues (ICSE, ASE, CCS, USS, SP, NDSS, FSE, TSE, TOSEM, ISSTA)
  are treated as higher-quality; dedup is conservative.
- AI/NLP/HCI venues are treated as more incremental; dedup is stricter.

Retention priority:
  SE/Security core > SE/Security related > AI core > AI related
"""
from __future__ import annotations

import json
from collections import defaultdict

from rich.panel import Panel

from ...analysis.stats import write_stage_stats
from ...core.config import Config, resolve_topic
from ...core.console import console
from ...core.db import DB
from .core import run_stage_a, run_stage_b, write_report


def run(
    cfg: Config,
    *,
    scope: str = "core_related",
    force: bool = False,
    limit: int | None = None,
    batch_size: int = 20,
    workers: int = 2,
    dry_run: bool = False,
    topic_name: str = "",
) -> dict:
    """Run sub-topic dedup for a given scope.

    scope options (run all 3 to compare):
      - core     : only core papers (~635) — most conservative dedup
      - related  : only related papers (~3,249) — moderate dedup
      - adjacent : only adjacent papers (~7,576) — most aggressive dedup

    Results are merged into dedup_keep_json column.
    """
    topic_name = resolve_topic(topic_name, cfg)
    db = DB(cfg.abs_path("db"))
    try:
        # ------------------------------------------------------------------
        # Determine relevance filter based on scope
        # ------------------------------------------------------------------
        if scope == "core":
            rel_filter = "('core')"
        elif scope == "related":
            rel_filter = "('related')"
        elif scope == "adjacent":
            rel_filter = "('adjacent')"
        else:
            console.print(f"[red]invalid scope: {scope}. Use core | related | adjacent[/red]")
            return {"processed": 0}

        # ------------------------------------------------------------------
        # Load papers for Stage A: ALL papers with abstracts get sub-topics
        # Stage B only processes papers matching scope
        # ------------------------------------------------------------------
        where_a = "pt.relevance IN ('core', 'related', 'adjacent') AND p.abstract IS NOT NULL AND p.abstract != ''"
        if not force:
            where_a += " AND (pt.sub_topics_json IS NULL OR pt.sub_topics_json = '' OR pt.sub_topics_json = '[]')"

        rows_a = [r for r in db.iter_paper_topics(topic_name, where_a)]

        where_b = f"pt.relevance IN {rel_filter} AND p.abstract IS NOT NULL AND p.abstract != ''"
        rows_b = [r for r in db.iter_paper_topics(topic_name, where_b)]

        if limit:
            rows_a = rows_a[:limit]
            rows_b = rows_b[:limit]

        if not rows_b:
            console.print(f"[yellow]no papers in scope {scope} to dedup[/yellow]")
            return {"processed": 0}

        stage_cfg = cfg.llm.stage3_classify

        # ------------------------------------------------------------------
        # Group ALL papers by topic for Stage A
        # ------------------------------------------------------------------
        topic_groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows_a:
            topics = r.get("topics_json")
            if not topics or topics in ("", "[]"):
                continue
            try:
                tids = json.loads(topics) if isinstance(topics, str) else topics
                if not isinstance(tids, list):
                    continue
                for tid in tids:
                    if tid:
                        topic_groups[tid].append(r)
            except Exception:
                continue

        # Scope-filtered topic_groups for Stage B
        scope_ids = {r["paper_id"] for r in rows_b}
        topic_groups_b: dict[str, list[dict]] = defaultdict(list)
        for tid, papers in topic_groups.items():
            for p in papers:
                if p["paper_id"] in scope_ids:
                    topic_groups_b[tid].append(p)

        # Fallback: if topic_groups_b is empty (sub-topics already discovered for most papers),
        # build topic_groups_b from rows_b directly using existing sub_topics_json
        paper_subtopics: dict[str, list[str]] = {}
        if not topic_groups_b and rows_b:
            console.print("[dim]sub-topics already discovered; loading from DB for Stage B[/dim]")
            for r in rows_b:
                pid = r["paper_id"]
                st = r.get("sub_topics_json")
                if st and st not in ("", "[]"):
                    try:
                        paper_subtopics[pid] = json.loads(st) if isinstance(st, str) else st
                    except Exception:
                        paper_subtopics[pid] = ["uncategorized"]
                else:
                    paper_subtopics[pid] = ["uncategorized"]
                # also build topic_groups_b from rows_b directly
                topics = r.get("topics_json")
                if topics and topics not in ("", "[]"):
                    try:
                        tids = json.loads(topics) if isinstance(topics, str) else topics
                        for tid in tids:
                            if tid:
                                topic_groups_b[tid].append(r)
                    except Exception:
                        pass

        console.print(
            Panel(
                f"[bold]Scope[/bold]       : {scope}\n"
                f"[bold]Stage A[/bold]     : {len(rows_a):,} papers (all with abstract)\n"
                f"[bold]Stage B[/bold]     : {len(rows_b):,} papers (scope-filtered)\n"
                f"[bold]Topics[/bold]      : {len(topic_groups_b)}\n"
                f"[bold]Batch size[/bold] : {batch_size}\n"
                f"[bold]Workers[/bold]    : {workers}\n"
                f"[bold]Dry run[/bold]    : {dry_run}",
                title="Sub-topic Dedup",
                border_style="cyan",
            )
        )

        # ------------------------------------------------------------------
        # Stage A: discover sub-topics per topic (on ALL papers)
        # ------------------------------------------------------------------
        if rows_a:
            stage_a_stats = run_stage_a(db, cfg, stage_cfg, topic_groups, batch_size, workers, dry_run, topic_name)
        else:
            # fake stage_a_stats when skipping
            stage_a_stats = {
                "api_calls": 0, "cached_hits": 0,
                "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0,
                "subtopic_map": {}, "paper_subtopics": paper_subtopics,
            }

        if dry_run:
            console.print("[yellow]Dry run finished after Stage A. Review sub-topics above.[/yellow]")
            return stage_a_stats

        if rows_a:
            stage_a_subs = stage_a_stats.get("paper_subtopics", {})
            # Only overwrite fallback if Stage A actually produced results
            if stage_a_subs:
                paper_subtopics = stage_a_subs
            # Persist sub-topics to DB (only for papers that don't have it yet)
            for paper_id, subs in (stage_a_subs or {}).items():
                if subs:
                    existing = db.get_paper_topic(paper_id, topic_name)
                    if existing and not existing.get("sub_topics_json"):
                        db.upsert_paper_topic(paper_id, topic_name, {"sub_topics_json": subs})

        # ------------------------------------------------------------------
        # Stage B: dedup within each (topic, sub-topic) group (scope-filtered)
        # ------------------------------------------------------------------
        stage_b_stats = run_stage_b(
            db, cfg, stage_cfg, topic_groups_b, paper_subtopics, batch_size, workers, scope, topic_name
        )

        # ------------------------------------------------------------------
        # Summary report
        # ------------------------------------------------------------------
        write_report(
            cfg, topic_groups_b, paper_subtopics, stage_b_stats.get("kept_paper_ids", set()), scope
        )

        total_tokens = (
            stage_a_stats.get("prompt_tokens", 0)
            + stage_a_stats.get("completion_tokens", 0)
            + stage_b_stats.get("prompt_tokens", 0)
            + stage_b_stats.get("completion_tokens", 0)
        )
        summary_lines = [
            f"[bold]Scope[/bold]        : {scope}",
            f"[bold]Stage A calls[/bold] : {stage_a_stats.get('api_calls', 0):,}",
            f"[bold]Stage B calls[/bold] : {stage_b_stats.get('api_calls', 0):,}",
            f"[bold]Total tokens[/bold] : {total_tokens:,}",
            f"[bold]Est. cost[/bold]    : ${stage_a_stats.get('cost', 0) + stage_b_stats.get('cost', 0):.2f}",
            f"[bold]Papers kept[/bold]  : {len(stage_b_stats.get('kept_paper_ids', set())):,} / {len(rows_b):,}",
        ]
        console.print(
            Panel(
                "\n".join(summary_lines),
                title="Dedup Summary",
                border_style="green",
            )
        )

        stats = {
            "scope": scope,
            "processed": len(rows_b),
            "kept": len(stage_b_stats.get("kept_paper_ids", set())),
            "stage_a": {k: v for k, v in stage_a_stats.items() if k not in ("subtopic_map", "paper_subtopics")},
            "stage_b": {k: v for k, v in stage_b_stats.items() if k != "kept_paper_ids"},
        }
        out = write_stage_stats(cfg, f"subtopic_dedup_{scope}", stats)
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats

    finally:
        db.close()
