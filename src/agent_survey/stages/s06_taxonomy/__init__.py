"""Stage 7: unified taxonomy classification (absorbs former s06 classify-topics).

Maps each paper to leaf paths across dynamically-defined trees (from topic config).
Also outputs flat topic labels (topics_json) by mapping tree paths via flat_labels.
Supports incremental discovery of new leaves / trees via new_leaves proposals.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any

import yaml
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
from ...core.config import Config, LLMStageCfg, load_stage_config, load_topic_config, resolve_topic
from ...core.console import console
from ...core.db import DB
from ...services.taxonomy import (
    apply_new_leaves,
    apply_new_leaves_v2,
    merge_into_taxonomy_json,
    paths_to_flat_labels,
)
from .core import process_batch


def _load_stage_config():
    return load_stage_config("taxonomy")


def run(
    cfg: Config,
    *,
    force: bool = False,
    limit: int | None = None,
    batch_size: int | None = None,
    workers: int | None = None,
    topic_name: str = "",
    relevance_levels: list[str] | None = None,
) -> dict:
    sconf = _load_stage_config()
    s_llm = sconf.get("llm", {})
    batch_size = batch_size or s_llm.get("batch_size", 10)
    workers = workers or s_llm.get("workers", 2)
    limit = limit or sconf.get("limit", 0) or None
    batch_timeout = s_llm.get("batch_timeout", 120)
    flush_every = sconf.get("flush_every", 200)

    topic_name = resolve_topic(topic_name, cfg)
    tc = load_topic_config(topic_name)
    tax_cfg = tc.taxonomy
    trees = tax_cfg.trees

    db = DB(cfg.abs_path("db"))
    relevance_levels = relevance_levels or ["core", "related", "adjacent"]
    rel_list = ", ".join(f"'{r}'" for r in relevance_levels)
    try:
        # Process papers matching relevance_levels
        rows = []
        for pt in db.iter_paper_topics(
            topic_name,
            f"relevance IN ({rel_list}) AND abstract IS NOT NULL AND abstract != ''",
        ):
            if not force:
                if pt.get("taxonomy_json") and pt["taxonomy_json"] not in ("", "{}", "[]"):
                    continue
            rows.append(pt)
        if limit:
            rows = rows[:limit]
        total = len(rows)
        if not total:
            console.print(f"[yellow]no papers left to taxonomy-classify for {topic_name}[/yellow]")
            return {"processed": 0}

        # Build stage_cfg from stage config (overrides global classify config)
        base_cfg = cfg.llm.stage3_classify
        stage_cfg = base_cfg.model_copy(update={
            "model": s_llm.get("model", base_cfg.model),
            "temperature": s_llm.get("temperature", base_cfg.temperature),
            "timeout": s_llm.get("timeout", base_cfg.timeout),
        })
        max_tokens_per_paper = s_llm.get("max_tokens_per_paper", 1024)

        console.print(
            Panel(
                f"[bold]Topic[/bold]       : {topic_name}\n"
                f"[bold]Papers[/bold]      : {total:,}\n"
                f"[bold]Trees[/bold]       : {list(trees.keys())}\n"
                f"[bold]Batch size[/bold] : {batch_size}\n"
                f"[bold]Workers[/bold]    : {workers}",
                title="Taxonomy Classification",
                border_style="cyan",
            )
        )

        batches = [rows[i : i + batch_size] for i in range(0, len(rows), batch_size)]

        processed = 0
        failed = 0
        new_leaves_proposals: list[str] = []
        proposals_with_papers: dict[str, list[dict]] = {}
        tree_counters: dict[str, Counter] = {t: Counter() for t in trees}
        cross_counter: Counter = Counter()
        flat_label_counter: Counter = Counter()

        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_api_calls = 0

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
                f"taxonomy-classify ({stage_cfg.model}) [{workers}w][{topic_name}]",
                total=total,
                saved=0,
            )

            # Pre-build shared LLM client (passed to each worker)
            from ...services.llm import DeepSeekClient
            shared_llm = DeepSeekClient(cfg)

            with ThreadPoolExecutor(max_workers=workers) as executor:
                batch_starts: dict = {}
                futures = {}
                for i, batch in enumerate(batches):
                    batch_id = f"B{i:04d}"
                    batch_starts[batch_id] = time.monotonic()
                    fut = executor.submit(
                        process_batch, batch, cfg, stage_cfg, tax_cfg, shared_llm,
                        topic_name=topic_name, max_tokens_per_paper=max_tokens_per_paper
                    )
                    futures[fut] = (batch_id, batch)
                console.print(f"[dim]submitted {len(futures)} batches, batch_timeout={batch_timeout}s[/dim]")

                # Accumulate DB writes in main thread, flush every N papers
                _pending_writes: list[tuple[str, dict, list[str]]] = []  # (paper_id, taxonomy_json, topics_json)
                FLUSH_EVERY = flush_every

                def _flush_db(force: bool = False):
                    if not _pending_writes and not force:
                        return
                    n = len(_pending_writes)
                    t0 = time.monotonic()
                    for paper_id, tax_json, topics_json in _pending_writes:
                        db.upsert_paper_topic(
                            paper_id, topic_name,
                            {"taxonomy_json": tax_json, "topics_json": topics_json},
                            commit=False,
                        )
                        db.mark_stage(paper_id, "taxonomy_classify", "done", topic_name=topic_name, commit=False)
                    db._conn.commit()
                    t1 = time.monotonic()
                    console.print(f"[dim]flushed {n} papers to DB in {(t1-t0)*1000:.0f}ms[/dim]")
                    _pending_writes.clear()

                def _build_result(pr: dict, paper: dict) -> tuple[dict, list[str]]:
                    """Build (taxonomy_json, topics_json) for a single paper."""
                    paths: dict[str, list[str]] = {}
                    for raw_key in pr:
                        if raw_key in ("paper_idx", "cross_cutting", "new_leaves"):
                            continue
                        vals = pr.get(raw_key, [])
                        if vals:
                            # Filter out single-char garbage from malformed LLM JSON
                            vals = [v for v in vals if isinstance(v, str) and len(v) > 2 and "/" in v]
                            if not vals:
                                continue
                            tree_key = raw_key.replace("_", "-")
                            paths[tree_key] = vals
                            for v in vals:
                                tree_counters[tree_key][v] += 1

                    cross = pr.get("cross_cutting", [])
                    if cross:
                        paths["cross_cutting"] = cross
                        for c in cross:
                            cross_counter[c] += 1

                    for leaf in pr.get("new_leaves", []):
                        new_leaves_proposals.append(leaf)
                        leaf_clean = leaf.strip().strip("/")
                        if leaf_clean:
                            proposals_with_papers.setdefault(leaf_clean, []).append({
                                "paper_id": paper["paper_id"],
                                "title": paper.get("title", ""),
                                "abstract": paper.get("abstract", ""),
                                "venue": paper.get("venue", ""),
                                "year": paper.get("year", ""),
                            })

                    existing = paper.get("taxonomy_json")
                    existing_dict = {}
                    if existing and existing not in ("", "{}", "[]"):
                        try:
                            existing_dict = json.loads(existing)
                        except Exception:
                            pass

                    merged = dict(existing_dict)
                    for tree_name, new_paths in paths.items():
                        existing_set = set(merged.get(tree_name, []))
                        existing_set.update(new_paths)
                        merged[tree_name] = sorted(existing_set)

                    flat_labels = paths_to_flat_labels(merged, tax_cfg.flat_labels)
                    for fl in flat_labels:
                        flat_label_counter[fl] += 1

                    return merged, flat_labels

                for future in as_completed(futures):
                    batch_id, batch = futures[future]
                    elapsed = time.monotonic() - batch_starts.get(batch_id, 0)
                    try:
                        batch, results, err, meta = future.result(timeout=batch_timeout)
                    except Exception as e:
                        future.cancel()
                        paper_ids = ",".join(p["paper_id"] for p in batch)
                        console.print(
                            f"[red][{batch_id}] TIMEOUT/CRASH after {elapsed:.1f}s | "
                            f"papers={len(batch)} ids={paper_ids} | err={e}[/red]"
                        )
                        failed += len(batch)
                        prog.advance(task, advance=len(batch))
                        continue

                    if err:
                        paper_ids = ",".join(p["paper_id"] for p in batch)
                        console.print(
                            f"[yellow][{batch_id}] BATCH_FAIL after {elapsed:.1f}s | "
                            f"papers={len(batch)} ids={paper_ids} | err={err}[/yellow]"
                        )
                        failed += len(batch)
                        prog.advance(task, advance=len(batch))
                        continue

                    # Success path
                    u = meta.get("usage") or {}
                    paper_ids = ",".join(p["paper_id"] for p in batch)
                    console.print(
                        f"[dim][{batch_id}] OK after {elapsed:.1f}s | "
                        f"papers={len(batch)} ids={paper_ids} | "
                        f"p={u.get('prompt_tokens',0)} c={u.get('completion_tokens',0)} | "
                        f"results={len(results)}[/dim]"
                    )
                    total_prompt_tokens += u.get("prompt_tokens", 0) or 0
                    total_completion_tokens += u.get("completion_tokens", 0) or 0
                    total_api_calls += 1
                    token_line.plain = f"in{total_prompt_tokens:,} out{total_completion_tokens:,} tot{total_prompt_tokens + total_completion_tokens:,}"

                    for pr in results:
                        idx = pr.get("paper_idx", 1) - 1
                        if idx < 0 or idx >= len(batch):
                            console.print(
                                f"[yellow][{batch_id}] bad paper_idx={pr.get('paper_idx')} "
                                f"batch_len={len(batch)}[/yellow]"
                            )
                            continue
                        paper = batch[idx]
                        merged, flat_labels = _build_result(pr, paper)
                        _pending_writes.append((paper["paper_id"], merged, flat_labels))
                        processed += 1

                        if len(_pending_writes) >= FLUSH_EVERY:
                            _flush_db()

                    prog.advance(task, advance=len(batch))
                    prog.update(task, saved=processed)

                # Final flush
                _flush_db(force=True)

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

        # Process new-leaf proposals (fully-automatic maintenance with LLM judge)
        auto_created = 0
        pending_leaves: list[dict] = []
        judge_meta: dict = {}
        reclassified_count = 0
        if new_leaves_proposals:
            if tax_cfg.auto_create_leaves:
                # New v2: reasoner judge + YAML write + fallback reclassification
                maint_result = apply_new_leaves_v2(
                    proposals_with_papers=proposals_with_papers,
                    trees=trees,
                    flat_labels=dict(tax_cfg.flat_labels),
                    cfg=cfg,
                    topic_name=topic_name,
                    auto_create=tax_cfg.auto_create_leaves,
                    min_papers=tax_cfg.auto_create_min_papers,
                    judge_model=tax_cfg.auto_create_judge_model,
                    write_yaml=tax_cfg.auto_create_write_yaml,
                    enable_fallback=tax_cfg.auto_create_fallback,
                    db=db,
                )
                auto_created = maint_result["auto_created"]
                reclassified_count = maint_result.get("reclassified", 0)
                pending_leaves = maint_result.get("pending", [])
                judge_meta = maint_result.get("meta", {})

                if auto_created:
                    yaml_added = maint_result.get("yaml_added", 0)
                    console.print(f"\n[green]Auto-created {auto_created} new leaves[/green]")
                    if yaml_added:
                        console.print(f"[green]({yaml_added} written to topics/{topic_name}.yaml)[/green]")
                if reclassified_count:
                    console.print(
                        f"[yellow]Reclassified {reclassified_count} papers to fallback leaves[/yellow]"
                    )
                rejected = maint_result.get("rejected", 0)
                if rejected:
                    console.print(f"[yellow]{rejected} proposals rejected by judge[/yellow]")
                if pending_leaves:
                    console.print(
                        f"[yellow]{len(pending_leaves)} proposals below min-paper threshold[/yellow]"
                    )
                # Write pending + rejected for reference
                pending_path = cfg.project_root / "output" / topic_name / "pending_leaves.json"
                pending_path.write_text(
                    json.dumps(
                        {
                            "pending": pending_leaves,
                            "rejected_paths": maint_result.get("rejected_paths", []),
                            "approved_paths": maint_result.get("approved_paths", []),
                            "reclassified": reclassified_count,
                        },
                        ensure_ascii=False, indent=2,
                    ),
                    encoding="utf-8",
                )
                console.print(f"[dim]wrote maintenance report to {pending_path}[/dim]")
            else:
                # Legacy mode: simple threshold-based
                auto_created, pending_leaves = apply_new_leaves(
                    proposals=new_leaves_proposals,
                    trees=trees,
                    flat_labels=dict(tax_cfg.flat_labels),
                    auto_create=tax_cfg.auto_create_leaves,
                    threshold=tax_cfg.auto_create_threshold,
                    project_root=cfg.project_root,
                    topic_name=topic_name,
                )
                if auto_created:
                    console.print(f"\n[green]Auto-created {auto_created} new leaves[/green]")
                if pending_leaves:
                    console.print(f"[yellow]{len(pending_leaves)} pending leaf proposals for review[/yellow]")
                    pending_path = cfg.project_root / "output" / topic_name / "pending_leaves.json"
                    pending_path.write_text(
                        json.dumps(pending_leaves, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    console.print(f"[dim]wrote pending leaves to {pending_path}[/dim]")

        # Compute judge tokens (after maintenance)
        judge_tokens = 0
        judge_cost = 0.0
        if judge_meta and judge_meta.get("usage"):
            ju = judge_meta["usage"]
            j_prompt = ju.get("prompt_tokens", 0) or 0
            j_comp = ju.get("completion_tokens", 0) or 0
            judge_tokens = j_prompt + j_comp
            # deepseek-v4-pro pricing: input ~$0.14/M, output ~$2.19/M (reasoner)
            judge_cost = (j_prompt / 1_000_000 * 0.14) + (j_comp / 1_000_000 * 2.19)

        # Flat label distribution
        if flat_label_counter:
            console.print("\n[bold]flat labels[/bold]")
            for label, c in flat_label_counter.most_common():
                console.print(f"  {label}: {c}")

        summary_lines = [
            f"[bold]Processed[/bold]        : {processed:,}",
            f"[bold]Failed[/bold]           : {failed:,}",
            f"[bold]API calls[/bold]        : {total_api_calls:,}",
            f"[bold]Total tokens[/bold]     : {total_tokens:,}",
            f"[bold]Est. cost (USD)[/bold] : ${cost_total:.2f}",
        ]
        if judge_meta:
            j_calls = judge_meta.get("api_calls", 0)
            j_cached = judge_meta.get("cached_hits", 0)
            if j_calls or j_cached:
                summary_lines.append(
                    f"[bold]Judge calls[/bold]      : {j_calls} (cached {j_cached})"
                )
                summary_lines.append(
                    f"[bold]Judge tokens[/bold]     : {judge_tokens:,} (${judge_cost:.3f})"
                )
        console.print(
            Panel(
                "\n".join(summary_lines),
                title="Taxonomy Classification Summary",
                border_style="green",
            )
        )

        stats = {
            "topic": topic_name,
            "processed": processed,
            "failed": failed,
            "by_tree": {t: dict(c) for t, c in tree_counters.items()},
            "cross_cutting": dict(cross_counter),
            "flat_labels": dict(flat_label_counter),
            "new_leaves_auto": auto_created,
            "new_leaves_pending": len(pending_leaves),
            "reclassified": reclassified_count,
            "tokens": {
                "prompt": total_prompt_tokens,
                "completion": total_completion_tokens,
                "total": total_tokens,
            },
            "api_calls": total_api_calls,
            "estimated_cost_usd": round(cost_total, 2),
            "judge": {
                "api_calls": judge_meta.get("api_calls", 0) if judge_meta else 0,
                "tokens": judge_tokens,
                "estimated_cost_usd": round(judge_cost, 3),
            },
        }
        out = write_stage_stats(cfg, "taxonomy_classify", stats)
        print_overview(db, f"after taxonomy classify [{topic_name}]")
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
