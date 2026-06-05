"""Core workers for sub-topic dedup stage."""
from __future__ import annotations

import json
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any

from rich.live import Live
from rich.progress import (
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from ...core.config import Config
from ...core.console import console
from ...core.db import DB
from ...services.llm import DeepSeekClient, cached_chat_json
from .prompts import build_dedup_messages, build_subtopic_messages, venue_tier


def process_subtopic_batch(
    batch: list[dict],
    cfg: Config,
    stage_cfg: Any,
    existing_subtopics: list[str],
    db: DB | None = None,
    llm: DeepSeekClient | None = None,
    topic_name: str = "",
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
        messages = build_subtopic_messages(batch, existing_subtopics)
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
            topic_name=topic_name,
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


def process_dedup_batch(
    batch: list[dict],
    cfg: Config,
    stage_cfg: Any,
    scope: str,
    db: DB | None = None,
    llm: DeepSeekClient | None = None,
    topic_name: str = "",
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
        messages = build_dedup_messages(batch, scope)
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
            topic_name=topic_name,
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


def run_stage_a(
    db: DB,
    cfg: Config,
    stage_cfg: Any,
    topic_groups: dict[str, list[dict]],
    batch_size: int,
    workers: int,
    dry_run: bool,
    topic_name: str,
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
        papers.sort(key=lambda p: (venue_tier(p.get("venue")) != "se_sec", -(p.get("year") or 0)))
        for i in range(0, len(papers), batch_size):
            all_batches.append((tid, papers[i : i + batch_size]))

    with Live(prog, console=console, refresh_per_second=4):
        task = prog.add_task("Stage A: discover sub-topics (batches)", total=len(all_batches))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    process_subtopic_batch, batch, cfg, stage_cfg, list(all_subtopics.get(tid, set())), topic_name=topic_name
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


def run_stage_b(
    db: DB,
    cfg: Config,
    stage_cfg: Any,
    topic_groups: dict[str, list[dict]],
    paper_subtopics: dict[str, list[str]],
    batch_size: int,
    workers: int,
    scope: str,
    topic_name: str,
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
                0 if venue_tier(p.get("venue")) == "se_sec" else 1,
                -(p.get("year") or 0),
            )
        )
        for i in range(0, len(papers), batch_size):
            all_batches.append(papers[i : i + batch_size])

    with Live(prog, console=console, refresh_per_second=4):
        task = prog.add_task("Stage B: dedup within sub-topics (batches)", total=len(all_batches))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(process_dedup_batch, batch, cfg, stage_cfg, scope, topic_name=topic_name): batch
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
                            existing = db.get_paper_topic(pid, topic_name)
                            keep_map = {}
                            if existing and existing.get("dedup_keep_json"):
                                try:
                                    keep_map = json.loads(existing["dedup_keep_json"])
                                except Exception:
                                    keep_map = {}
                            keep_map[scope] = True
                            db.upsert_paper_topic(pid, topic_name, {"dedup_keep_json": keep_map})
                            db.mark_stage(pid, "subtopic_dedup", "done", topic_name=topic_name)
                        else:
                            existing = db.get_paper_topic(pid, topic_name)
                            keep_map = {}
                            if existing and existing.get("dedup_keep_json"):
                                try:
                                    keep_map = json.loads(existing["dedup_keep_json"])
                                except Exception:
                                    keep_map = {}
                            keep_map[scope] = False
                            db.upsert_paper_topic(pid, topic_name, {"dedup_keep_json": keep_map})
                            db.mark_stage(pid, "subtopic_dedup", "done", topic_name=topic_name)

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


def write_report(
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
            tier = venue_tier(p.get("venue"))
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
