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
from rich.table import Table

from ..core.config import Config
from ..core.console import console
from ..core.db import DB
from ..services.llm import DeepSeekClient, cached_chat_json
from ..services.llm import (
    DOMAIN_LABELS,
    METHOD_LABELS,
    RELEVANCE_LEVELS,
    STAGE3_SYSTEM,
    STAGE3_USER_TITLE_ONLY,
    build_classify_messages,
)
from ..analysis.stats import print_overview, write_stage_stats

CORE_VENUES = {"ICSE", "FSE", "ASE", "ISSTA", "SP", "CCS", "USS", "NDSS"}


def _humanize(n: int) -> str:
    if n < 1_000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1_000:.1f}K"
    return f"{n / 1_000_000:.2f}M"


def _fmt_tokens(p: int, c: int) -> str:
    return f"in{_humanize(p)} out{_humanize(c)} tot{_humanize(p + c)}"


def _paper_prompt_block(paper: dict, idx: int) -> str:
    is_core = paper.get("venue") in CORE_VENUES
    has_abs = bool(paper.get("abstract") and paper.get("abstract").strip())
    if is_core and has_abs:
        return f"""[{idx}] Title: {paper['title']}
Venue: {paper.get('venue', '')} ({paper.get('year', '')})
Abstract: {paper['abstract']}"""
    return f"""[{idx}] Title: {paper['title']}
Venue: {paper.get('venue', '')} ({paper.get('year', '')})
⚠️ Only title available."""


def _build_batch_messages(papers: list[dict]) -> list[dict]:
    blocks = [_paper_prompt_block(p, i + 1) for i, p in enumerate(papers)]
    user = f"""You are labeling {len(papers)} papers for an AI-agent survey focused on computer-use / GUI agents, with a secondary focus on software engineering and security/privacy.

For each paper, output ONE JSON object with these keys:
- "relevance": one of {RELEVANCE_LEVELS}
  - core: main topic is computer-use / GUI / Web / Mobile / OS / Desktop agent
  - related: LLM agent applied to SE (testing, debugging, code gen, program analysis, vuln discovery) OR security/privacy attack/defense involving agents
  - adjacent: general LLM agent work (framework, planning, tool use) not directly computer-use / SE / security
  - irrelevant: not an agent paper, or agent but unrelated to any of the above
- "domain_primary": one of {DOMAIN_LABELS}
- "domain_secondary": list of additional labels from {DOMAIN_LABELS} (omit if none)
- "method_tags": 1-3 labels from {METHOD_LABELS}
- "tldr": one sentence (<=30 words) plain English summary
- "rationale": one short sentence explaining relevance choice

Return a JSON array with exactly {len(papers)} objects, in the same order as the papers below (index 1..{len(papers)}). Do not skip any.

Papers:
---
{"\n---\n".join(blocks)}
---

Return strict JSON array only."""
    return [
        {"role": "system", "content": STAGE3_SYSTEM},
        {"role": "user", "content": user},
    ]


def _classify_single(
    llm: DeepSeekClient,
    db: DB,
    paper: dict,
    stage_cfg: Any,
) -> tuple[dict | None, dict, bool]:
    """Returns (parsed_content, usage_dict, cached_bool)."""
    is_core = paper.get("venue") in CORE_VENUES
    has_abs = bool(paper.get("abstract") and paper.get("abstract").strip())
    if is_core and has_abs:
        messages = build_classify_messages(
            title=paper.get("title") or "",
            abstract=paper.get("abstract") or "",
            venue=paper.get("venue") or "",
            year=paper.get("year"),
        )
    else:
        user = STAGE3_USER_TITLE_ONLY.format(
            title=paper.get("title") or "",
            venue=paper.get("venue") or "",
            year=paper.get("year") or "",
            relevance_levels=RELEVANCE_LEVELS,
            domain_labels=DOMAIN_LABELS,
            method_labels=METHOD_LABELS,
        )
        messages = [
            {"role": "system", "content": STAGE3_SYSTEM},
            {"role": "user", "content": user},
        ]

    out = cached_chat_json(
        llm,
        db,
        paper_id=paper["paper_id"],
        stage="classify",
        model=stage_cfg.model,
        prompt_version=stage_cfg.prompt_version,
        messages=messages,
        temperature=stage_cfg.temperature,
        max_tokens=stage_cfg.max_tokens,
    )
    return out["content"], out.get("usage") or {}, out.get("cached", False)


def _parse_batch_result(raw: str, expected_len: int) -> list[dict]:
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("results", "papers", "data", "items"):
            if key in data and isinstance(data[key], list):
                return data[key]
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        return json.loads(raw[start : end + 1])
    raise ValueError(f"Could not parse batch result: expected {expected_len} items")


def _process_batch_worker(
    batch: list[dict],
    cfg: Config,
    stage_cfg: Any,
    db: DB | None = None,
    llm: DeepSeekClient | None = None,
) -> tuple[list[dict], list[dict] | None, Exception | None, dict]:
    """Worker that runs in a thread.  Handles its own fallback (split-half → singles)."""
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

    def _merge_meta(left: dict, right: dict) -> dict:
        lu = left.get("usage") or {}
        ru = right.get("usage") or {}
        return {
            "worker": worker_name,
            "usage": {
                "prompt_tokens": (lu.get("prompt_tokens", 0) or 0) + (ru.get("prompt_tokens", 0) or 0),
                "completion_tokens": (lu.get("completion_tokens", 0) or 0) + (ru.get("completion_tokens", 0) or 0),
                "total_tokens": (lu.get("total_tokens", 0) or 0) + (ru.get("total_tokens", 0) or 0),
            },
            "cached": left.get("cached", False) or right.get("cached", False),
            "errors": (left.get("errors", 0) or 0) + (right.get("errors", 0) or 0),
        }

    try:
        # ---- Single paper: fast path ----
        if len(batch) == 1:
            data, u, c = _classify_single(llm, db, batch[0], stage_cfg)
            return batch, [data], None, _meta(u, c)

        # ---- Try batch call ----
        messages = _build_batch_messages(batch)
        out = cached_chat_json(
            llm,
            db,
            paper_id=f"batch_{batch[0]['paper_id']}",
            stage="classify_batch",
            model=stage_cfg.model,
            prompt_version=stage_cfg.prompt_version + "_batch",
            messages=messages,
            temperature=stage_cfg.temperature,
            max_tokens=stage_cfg.max_tokens * len(batch),
        )
        u = out.get("usage") or {}
        cached = out.get("cached", False)
        results = _parse_batch_result(out.get("raw", json.dumps(out["content"])), len(batch))
        if len(results) == len(batch):
            return batch, results, None, _meta(u, cached)

        # Partial / wrong count → fall through to split retry
        raise ValueError(f"Batch returned {len(results)} results, expected {len(batch)}")

    except Exception:
        # ---- Fallback: tiny batches go straight to singles ----
        if len(batch) <= 3:
            all_results: list[dict] = []
            total_u = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            any_cached = False
            any_err = False
            for paper in batch:
                try:
                    data, u, c = _classify_single(llm, db, paper, stage_cfg)
                    total_u["prompt_tokens"] += u.get("prompt_tokens", 0) or 0
                    total_u["completion_tokens"] += u.get("completion_tokens", 0) or 0
                    total_u["total_tokens"] += u.get("total_tokens", 0) or 0
                    if c:
                        any_cached = True
                    all_results.append(data)
                except Exception:
                    any_err = True
            if any_err:
                return batch, all_results or None, Exception("Some singles failed"), _meta(total_u, any_cached, err=True)
            return batch, all_results, None, _meta(total_u, any_cached)

        # ---- Split in half and recurse (same thread, same db/llm) ----
        mid = len(batch) // 2
        left_b, left_r, left_e, left_m = _process_batch_worker(
            batch[:mid], cfg, stage_cfg, db=db, llm=llm
        )
        right_b, right_r, right_e, right_m = _process_batch_worker(
            batch[mid:], cfg, stage_cfg, db=db, llm=llm
        )

        combined = _merge_meta(left_m, right_m)
        if left_e and right_e:
            return batch, None, ValueError("Both halves failed"), combined
        all_results = (left_r or []) + (right_r or [])
        return batch, all_results, None, combined

    finally:
        if own_db:
            db.close()


def run(
    cfg: Config,
    *,
    only_prefilter_hits: bool = True,
    force: bool = False,
    limit: int | None = None,
    batch_size: int = 10,
    workers: int = 2,
) -> dict:
    db = DB(cfg.abs_path("db"))
    try:
        # ---- Checkpoint: scope & resume count ----
        prefilter_clause = (
            "prefilter_hit IS NOT NULL AND prefilter_hit != '[]' AND prefilter_hit != '{}'"
        )
        if only_prefilter_hits:
            total_in_scope = db.count(prefilter_clause)
            already_done = db.count(
                f"{prefilter_clause} AND relevance IS NOT NULL AND relevance != ''"
            )
        else:
            total_in_scope = db.count()
            already_done = db.count("relevance IS NOT NULL AND relevance != ''")

        where_parts: list[str] = []
        if only_prefilter_hits:
            where_parts.append(prefilter_clause)
        if not force:
            where_parts.append("(relevance IS NULL OR relevance = '')")
        where = " AND ".join(where_parts) if where_parts else ""
        rows = [r for r in db.iter_papers(where)]
        if limit:
            rows = rows[:limit]
        if not rows:
            console.print("[yellow]no papers left to classify[/yellow]")
            return {"classified": 0}

        remaining = len(rows)
        console.print(
            Panel(
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
        for i in range(0, len(rows), batch_size):
            batches.append(rows[i : i + batch_size])

        lock = Lock()

        token_line = Text("in0 out0 tot0", style="cyan")

        def _accumulate(meta: dict, paper_count: int, error: bool = False):
            nonlocal total_prompt_tokens, total_completion_tokens, total_api_calls, total_cached_hits
            w = meta.get("worker", "unknown")
            if w not in worker_stats:
                worker_stats[w] = {
                    "batches": 0,
                    "papers": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "errors": 0,
                    "cached_hits": 0,
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

        progress_columns = [
            TextColumn("[progress.description]{task.description}"),
            MofNCompleteColumn(),
            TextColumn("[green]saved {task.fields[saved]}[/green]"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
        ]

        interrupted = False
        prog = Progress(*progress_columns, console=console, auto_refresh=False)
        with Live(Group(token_line, prog), console=console, refresh_per_second=4):
            task = prog.add_task(
                f"classify ({stage_cfg.model}) [{workers}w]",
                total=remaining,
                saved=0,
            )

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_process_batch_worker, batch, cfg, stage_cfg): batch
                    for batch in batches
                }

                try:
                    for future in as_completed(futures):
                        batch, results, err, meta = future.result()
                        if err:
                            _accumulate(meta, len(batch), error=True)
                            console.print(
                                f"[red]batch completely failed ({len(batch)} papers) after split retry: {err}[/red]"
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
                                if rel not in RELEVANCE_LEVELS:
                                    rel = "irrelevant"
                                db.update_paper(
                                    paper["paper_id"],
                                    {
                                        "relevance": rel,
                                        "domain_primary": res.get("domain_primary"),
                                        "domain_secondary_json": res.get("domain_secondary") or [],
                                        "method_tags_json": res.get("method_tags") or [],
                                        "tldr": res.get("tldr"),
                                    },
                                )
                                db.mark_stage(paper["paper_id"], "classify", "done")
                                rel_counter[rel] += 1
                                if res.get("domain_primary"):
                                    domain_counter[res["domain_primary"]] += 1
                                for t in res.get("method_tags") or []:
                                    method_counter[t] += 1
                                processed += 1
                            prog.advance(task, advance=len(batch))
                            prog.update(task, saved=processed)
                except KeyboardInterrupt:
                    interrupted = True
                    console.print("\n[red]Interrupted by user. Shutting down workers...[/red]")
                    for fut in futures:
                        fut.cancel()

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
