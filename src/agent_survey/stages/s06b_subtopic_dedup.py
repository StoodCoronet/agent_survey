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
import threading
from collections import defaultdict
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

from ..analysis.stats import write_stage_stats
from ..core.config import Config
from ..core.console import console
from ..core.db import DB
from ..services.llm import DeepSeekClient, cached_chat_json

# ------------------------------------------------------------------
# Venue classification
# ------------------------------------------------------------------

SE_VENUES = {"ICSE", "ASE", "FSE", "TSE", "TOSEM", "ISSTA"}
SEC_VENUES = {"SP", "CCS", "USS", "NDSS"}
AI_VENUES = {"ICLR", "NeurIPS", "ICML", "AAAI"}
NLP_VENUES = {"ACL", "EMNLP", "NAACL", "COLM"}
HCI_VENUES = {"CHI", "UIST"}


def _venue_tier(venue: str | None) -> str:
    if not venue:
        return "other"
    v = venue.upper()
    if v in SE_VENUES or v in SEC_VENUES:
        return "se_sec"
    if v in AI_VENUES or v in NLP_VENUES or v in HCI_VENUES:
        return "ai_nlp_hci"
    return "other"


# ------------------------------------------------------------------
# Prompts
# ------------------------------------------------------------------

SUBTOPIC_SYSTEM_PROMPT = """You are an expert research assistant organizing AI-agent papers into fine-grained sub-topics.

Your task: read a batch of paper titles and abstracts, then assign each paper a concise sub-topic label.

Rules:
- Sub-topic names should be 2-5 words, in English, using kebab-case (e.g., "code-agent-benchmark", "prompt-injection-attack").
- Papers that share the same core method / problem should share the same sub-topic.
- Papers that tackle different challenges or use fundamentally different techniques should get different sub-topics.
- Re-use existing sub-topic names when appropriate; only create a new one if no existing label fits.
- Output strict JSON.
"""


def _build_subtopic_messages(papers: list[dict], existing_subtopics: list[str]) -> list[dict]:
    paper_blocks = []
    for i, p in enumerate(papers, 1):
        block = f"""[{i}] Title: {p['title']}
Venue: {p.get('venue', '')} ({p.get('year', '')})
Relevance: {p.get('relevance', '')}
Abstract: {p.get('abstract', '')}"""
        paper_blocks.append(block)

    subtopic_hint = "\n".join(f"- {s}" for s in existing_subtopics) if existing_subtopics else "(none yet)"

    user = f"""Existing sub-topics observed so far (re-use when possible):
{subtopic_hint}

Papers to label ({len(papers)}):
---
{"\n---\n".join(paper_blocks)}
---

Return JSON with exactly this key:
{{
  "papers": [
    {{
      "paper_idx": 1,
      "sub_topic": "code-agent-benchmark",
      "rationale": "one sentence explaining the label"
    }}
  ]
}}

Use concise, consistent sub-topic names across papers."""
    return [
        {"role": "system", "content": SUBTOPIC_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _dedup_system_prompt(scope: str) -> str:
    """Generate scope-specific dedup system prompt."""
    base = """You are an expert research surveyor deciding which papers in a batch should be kept for an in-depth survey.

Your task: identify groups of papers that represent the SAME line of work (same method, same problem, minor variations), and select which to KEEP.

CRITICAL venue bias (your user is a SE/Security researcher):
- SE venues (ICSE, ASE, FSE, TSE, TOSEM, ISSTA) and Security venues (CCS, USS, SP, NDSS) produce focused, high-quality work.
- AI/NLP/HCI venues (AAAI, ICLR, NeurIPS, ICML, ACL, EMNLP, NAACL, CHI, UIST) tend to have more incremental variations.

Retention priority (when choosing which paper to keep from a cluster):
  1. SE/Security venue > AI/NLP/HCI venue
  2. newer year > older year
  3. higher venue reputation (e.g., ICSE/CCS > workshop)

Also: if two papers tackle DIFFERENT challenges or research questions, KEEP BOTH even if methods overlap.
"""
    if scope == "core":
        strictness = """
DEDUP STRICTNESS: VERY CONSERVATIVE (core papers).
- ONLY remove papers that are clearly follow-ups, minor extensions, or near-identical reproductions.
- If a paper introduces even a small novel technique, new dataset, or new evaluation, KEEP it.
- Do NOT remove papers just because they use the same base method.
"""
    elif scope == "related":
        strictness = """
DEDUP STRICTNESS: MODERATE (related papers).
- Remove clear duplicates and minor extensions (same method, same problem, only benchmark/dataset differs slightly).
- Keep papers that introduce meaningful new techniques or tackle different research questions.
- Be willing to remove incremental work that does not add substantial new insights.
"""
    else:  # adjacent
        strictness = """
DEDUP STRICTNESS: AGGRESSIVE (adjacent papers).
- Remove papers that use the same method even on different datasets or benchmarks.
- Only keep the most representative or earliest paper for each line of work.
- Remove minor adaptations, ablation studies, and follow-up evaluations unless they introduce fundamentally new insights.
"""
    return base + strictness + "\nOutput strict JSON.\n"


def _build_dedup_messages(papers: list[dict], scope: str) -> list[dict]:
    paper_blocks = []
    for i, p in enumerate(papers, 1):
        block = f"""[{i}] Title: {p['title']}
Venue: {p.get('venue', '')} ({p.get('year', '')})
Relevance: {p.get('relevance', '')}
Abstract: {p.get('abstract', '')}"""
        paper_blocks.append(block)

    user = f"""Papers to review ({len(papers)}):
---
{"\n---\n".join(paper_blocks)}
---

Return JSON with exactly this key:
{{
  "decisions": [
    {{
      "paper_idx": 1,
      "keep": true,
      "reason": "representative work, first to propose X"
    }},
    {{
      "paper_idx": 2,
      "keep": false,
      "reason": "same method as [1], only dataset differs"
    }}
  ]
}}

For each paper, decide keep=true or keep=false.
If keep=false, explain which paper it duplicates or why it is incremental.
If a paper is the best/only representative of a distinct line of work, always keep it."""
    return [
        {"role": "system", "content": _dedup_system_prompt(scope)},
        {"role": "user", "content": user},
    ]


# ------------------------------------------------------------------
# Batch worker
# ------------------------------------------------------------------

def _process_subtopic_batch(
    batch: list[dict],
    cfg: Config,
    stage_cfg: Any,
    existing_subtopics: list[str],
    db: DB | None = None,
    llm: DeepSeekClient | None = None,
) -> tuple[list[dict], list[dict], Exception | None, dict]:
    """Returns (batch, paper_results, error, meta)."""
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
        messages = _build_subtopic_messages(batch, existing_subtopics)
        out = cached_chat_json(
            llm,
            db,
            paper_id=f"batch_{batch[0]['paper_id']}",
            stage="subtopic_discover",
            model=stage_cfg.model,
            prompt_version="v1",
            messages=messages,
            temperature=0.0,
            max_tokens=512 * len(batch),
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


def _process_dedup_batch(
    batch: list[dict],
    cfg: Config,
    stage_cfg: Any,
    scope: str,
    db: DB | None = None,
    llm: DeepSeekClient | None = None,
) -> tuple[list[dict], list[dict], Exception | None, dict]:
    """Returns (batch, decisions, error, meta)."""
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
        messages = _build_dedup_messages(batch, scope)
        out = cached_chat_json(
            llm,
            db,
            paper_id=f"batch_{batch[0]['paper_id']}",
            stage="subtopic_dedup",
            model=stage_cfg.model,
            prompt_version=f"v1_{scope}",
            messages=messages,
            temperature=0.0,
            max_tokens=256 * len(batch),
        )
        u = out.get("usage") or {}
        cached = out.get("cached", False)
        raw = out.get("raw", json.dumps(out["content"]))
        data = json.loads(raw) if isinstance(out.get("content"), dict) else out["content"]
        if isinstance(data, dict) and "decisions" in data:
            return batch, data["decisions"], None, _meta(u, cached)
        return batch, [], None, _meta(u, cached)
    except Exception as e:
        return batch, [], e, _meta(err=True)
    finally:
        if own_db:
            db.close()


# ------------------------------------------------------------------
# Main run
# ------------------------------------------------------------------

def run(
    cfg: Config,
    *,
    scope: str = "core_related",
    force: bool = False,
    limit: int | None = None,
    batch_size: int = 20,
    workers: int = 2,
    dry_run: bool = False,
) -> dict:
    """Run sub-topic dedup for a given scope.

    scope options (run all 3 to compare):
      - core     : only core papers (~635) — most conservative dedup
      - related  : only related papers (~3,249) — moderate dedup
      - adjacent : only adjacent papers (~7,576) — most aggressive dedup

    Results are merged into dedup_keep_json column.
    """
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
        where_a = "relevance IN ('core', 'related', 'adjacent') AND abstract IS NOT NULL AND abstract != ''"
        if not force:
            where_a += " AND (sub_topics_json IS NULL OR sub_topics_json = '' OR sub_topics_json = '[]')"

        rows_a = [r for r in db.iter_papers(where_a)]

        where_b = f"relevance IN {rel_filter} AND abstract IS NOT NULL AND abstract != ''"
        rows_b = [r for r in db.iter_papers(where_b)]

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
            stage_a_stats = _run_stage_a(db, cfg, stage_cfg, topic_groups, batch_size, workers, dry_run)
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
                    existing = db.get_paper(paper_id)
                    if existing and not existing.get("sub_topics_json"):
                        db.update_paper(paper_id, {"sub_topics_json": subs})

        # ------------------------------------------------------------------
        # Stage B: dedup within each (topic, sub-topic) group (scope-filtered)
        # ------------------------------------------------------------------
        stage_b_stats = _run_stage_b(
            db, cfg, stage_cfg, topic_groups_b, paper_subtopics, batch_size, workers, scope
        )

        # ------------------------------------------------------------------
        # Summary report
        # ------------------------------------------------------------------
        _write_report(
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


def _run_stage_a(
    db: DB,
    cfg: Config,
    stage_cfg: Any,
    topic_groups: dict[str, list[dict]],
    batch_size: int,
    workers: int,
    dry_run: bool,
) -> dict:
    """Discover sub-topics. Returns stats dict."""
    total_api_calls = 0
    total_cached_hits = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    paper_subtopics: dict[str, list[str]] = defaultdict(list)
    all_subtopics: dict[str, set[str]] = defaultdict(set)
    lock = Lock()

    progress_columns = [
        TextColumn("[progress.description]{task.description}"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    ]
    prog = Progress(*progress_columns, console=console, auto_refresh=False)

    # Flatten all batches with topic label
    all_batches: list[tuple[str, list[dict]]] = []
    for tid, papers in topic_groups.items():
        # sort by venue tier then year desc
        papers.sort(key=lambda p: (_venue_tier(p.get("venue")) != "se_sec", -(p.get("year") or 0)))
        for i in range(0, len(papers), batch_size):
            all_batches.append((tid, papers[i : i + batch_size]))

    with Live(prog, console=console, refresh_per_second=4):
        task = prog.add_task("Stage A: discover sub-topics", total=len(all_batches))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _process_subtopic_batch, batch, cfg, stage_cfg, list(all_subtopics.get(tid, set()))
                ): (tid, batch)
                for tid, batch in all_batches
            }

            for future in as_completed(futures):
                tid, batch = futures[future]
                _batch, results, err, meta = future.result()
                if err:
                    console.print(f"[red]batch failed ({len(batch)} papers): {err}[/red]")
                    prog.advance(task)
                    continue

                u = meta.get("usage") or {}
                if meta.get("cached"):
                    total_cached_hits += 1
                else:
                    total_prompt_tokens += u.get("prompt_tokens", 0) or 0
                    total_completion_tokens += u.get("completion_tokens", 0) or 0
                    total_api_calls += 1

                # collect sub-topics
                new_names: set[str] = set()
                with lock:
                    for pr in results:
                        idx = pr.get("paper_idx", 1) - 1
                        if idx < 0 or idx >= len(batch):
                            continue
                        paper = batch[idx]
                        sub = pr.get("sub_topic", "uncategorized").strip().lower().replace(" ", "-")
                        if sub:
                            paper_subtopics[paper["paper_id"]].append(sub)
                            new_names.add(sub)
                    all_subtopics[tid].update(new_names)

                prog.advance(task)

    # normalize sub-topic names globally (simple dedup by exact match after cleaning)
    for pid, subs in paper_subtopics.items():
        paper_subtopics[pid] = list(dict.fromkeys(subs))

    cost_input = total_prompt_tokens / 1_000_000 * 0.14
    cost_output = total_completion_tokens / 1_000_000 * 0.28

    if dry_run:
        console.print("\n[bold]Discovered sub-topics by topic:[/bold]")
        for tid, subs in sorted(all_subtopics.items()):
            console.print(f"  [cyan]{tid}[/cyan]: {', '.join(sorted(subs))}")

    return {
        "api_calls": total_api_calls,
        "cached_hits": total_cached_hits,
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "cost": cost_input + cost_output,
        "subtopic_map": dict(all_subtopics),
        "paper_subtopics": dict(paper_subtopics),
    }


def _run_stage_b(
    db: DB,
    cfg: Config,
    stage_cfg: Any,
    topic_groups: dict[str, list[dict]],
    paper_subtopics: dict[str, list[str]],
    batch_size: int,
    workers: int,
    scope: str,
) -> dict:
    """Dedup within each (topic, sub-topic) group. Returns stats dict with kept_paper_ids."""
    total_api_calls = 0
    total_cached_hits = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    kept_paper_ids: set[str] = set()
    lock = Lock()

    progress_columns = [
        TextColumn("[progress.description]{task.description}"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    ]
    prog = Progress(*progress_columns, console=console, auto_refresh=False)

    # Build (topic, sub-topic) -> papers mapping
    group_papers: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for tid, papers in topic_groups.items():
        for p in papers:
            subs = paper_subtopics.get(p["paper_id"], [])
            if not subs:
                subs = ["uncategorized"]
            for sub in subs:
                group_papers[(tid, sub)].append(p)

    # Flatten batches
    all_batches: list[list[dict]] = []
    for (tid, sub), papers in group_papers.items():
        # sort by relevance then venue tier then year desc
        papers.sort(
            key=lambda p: (
                0 if p.get("relevance") == "core" else 1,
                0 if _venue_tier(p.get("venue")) == "se_sec" else 1,
                -(p.get("year") or 0),
            )
        )
        for i in range(0, len(papers), batch_size):
            all_batches.append(papers[i : i + batch_size])

    with Live(prog, console=console, refresh_per_second=4):
        task = prog.add_task("Stage B: dedup within sub-topics", total=len(all_batches))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_process_dedup_batch, batch, cfg, stage_cfg, scope): batch
                for batch in all_batches
            }

            for future in as_completed(futures):
                batch = futures[future]
                _batch, decisions, err, meta = future.result()
                if err:
                    console.print(f"[red]dedup batch failed ({len(batch)} papers): {err}[/red]")
                    prog.advance(task)
                    continue

                u = meta.get("usage") or {}
                if meta.get("cached"):
                    total_cached_hits += 1
                else:
                    total_prompt_tokens += u.get("prompt_tokens", 0) or 0
                    total_completion_tokens += u.get("completion_tokens", 0) or 0
                    total_api_calls += 1

                with lock:
                    for d in decisions:
                        idx = d.get("paper_idx", 1) - 1
                        if idx < 0 or idx >= len(batch):
                            continue
                        paper = batch[idx]
                        pid = paper["paper_id"]
                        if d.get("keep", True):
                            kept_paper_ids.add(pid)
                            # Update dedup_keep_json in DB (merge with existing)
                            existing = db.get_paper(pid)
                            keep_map = {}
                            if existing and existing.get("dedup_keep_json"):
                                try:
                                    keep_map = json.loads(existing["dedup_keep_json"])
                                except Exception:
                                    keep_map = {}
                            keep_map[scope] = True
                            db.update_paper(pid, {"dedup_keep_json": keep_map})
                        else:
                            existing = db.get_paper(pid)
                            keep_map = {}
                            if existing and existing.get("dedup_keep_json"):
                                try:
                                    keep_map = json.loads(existing["dedup_keep_json"])
                                except Exception:
                                    keep_map = {}
                            keep_map[scope] = False
                            db.update_paper(pid, {"dedup_keep_json": keep_map})

                prog.advance(task)

    cost_input = total_prompt_tokens / 1_000_000 * 0.14
    cost_output = total_completion_tokens / 1_000_000 * 0.28

    return {
        "api_calls": total_api_calls,
        "cached_hits": total_cached_hits,
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "cost": cost_input + cost_output,
        "kept_paper_ids": kept_paper_ids,
    }


def _write_report(
    cfg: Config,
    topic_groups: dict[str, list[dict]],
    paper_subtopics: dict[str, list[str]],
    kept_paper_ids: set[str],
    scope: str,
) -> Path:
    """Write dedup report markdown."""
    lines = [f"# Sub-topic Dedup Report — Scope: `{scope}`\n"]

    # Per-topic summary
    lines.append("## Per-topic Summary\n")
    lines.append("| Topic | Original | Kept | Kept % |")
    lines.append("|-------|----------|------|--------|")

    for tid, papers in sorted(topic_groups.items()):
        original = len(papers)
        kept = sum(1 for p in papers if p["paper_id"] in kept_paper_ids)
        pct = round(kept / original * 100, 1) if original else 0
        lines.append(f"| {tid} | {original} | {kept} | {pct}% |")

    # Per sub-topic breakdown (top groups)
    lines.append("\n## Sub-topic Breakdown (Top 30 groups)\n")
    group_counts: dict[tuple[str, str], int] = defaultdict(int)
    group_kept: dict[tuple[str, str], int] = defaultdict(int)
    for tid, papers in topic_groups.items():
        for p in papers:
            subs = paper_subtopics.get(p["paper_id"], ["uncategorized"])
            for sub in subs:
                group_counts[(tid, sub)] += 1
                if p["paper_id"] in kept_paper_ids:
                    group_kept[(tid, sub)] += 1

    sorted_groups = sorted(group_counts.items(), key=lambda x: -x[1])[:30]
    lines.append("| Topic | Sub-topic | Total | Kept | Kept % |")
    lines.append("|-------|-----------|-------|------|--------|")
    for (tid, sub), total in sorted_groups:
        kept = group_kept.get((tid, sub), 0)
        pct = round(kept / total * 100, 1) if total else 0
        lines.append(f"| {tid} | {sub} | {total} | {kept} | {pct}% |")

    # Venue tier summary
    lines.append("\n## Kept Papers by Venue Tier\n")
    tier_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"original": 0, "kept": 0})
    for tid, papers in topic_groups.items():
        for p in papers:
            tier = _venue_tier(p.get("venue"))
            tier_counts[tier]["original"] += 1
            if p["paper_id"] in kept_paper_ids:
                tier_counts[tier]["kept"] += 1

    lines.append("| Tier | Original | Kept | Kept % |")
    lines.append("|------|----------|------|--------|")
    for tier in ["se_sec", "ai_nlp_hci", "other"]:
        d = tier_counts[tier]
        pct = round(d["kept"] / d["original"] * 100, 1) if d["original"] else 0
        lines.append(f"| {tier} | {d['original']} | {d['kept']} | {pct}% |")

    report_path = cfg.project_root / "output" / "dedup" / "dedup_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"[green]wrote dedup report to {report_path}[/green]")
    return report_path
