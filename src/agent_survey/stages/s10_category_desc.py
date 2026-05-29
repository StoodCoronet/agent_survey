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

from ..analysis.stats import print_overview, write_stage_stats
from ..core.config import Config
from ..core.console import console
from ..core.db import DB
from ..services.llm import DeepSeekClient, cached_chat_json
from ..services.pdf_extract import build_prompt_body, extract_text

# ------------------------------------------------------------------
# Venue priority tiers (lower number = higher priority)
# ------------------------------------------------------------------
_TIER1 = {"ICSE", "FSE", "ASE", "ISSTA", "SP", "CCS", "USS", "NDSS"}
_TIER2 = {"TOSEM", "TSE"}
_TIER3 = {"ICLR", "NeurIPS", "ICML", "AAAI"}
_TIER4 = {"ACL", "EMNLP", "NAACL", "COLM"}
_TIER5 = {"CHI", "UIST"}

_VENUE_PRIORITY: dict[str, int] = {}
for v in _TIER1:
    _VENUE_PRIORITY[v] = 1
for v in _TIER2:
    _VENUE_PRIORITY[v] = 2
for v in _TIER3:
    _VENUE_PRIORITY[v] = 3
for v in _TIER4:
    _VENUE_PRIORITY[v] = 4
for v in _TIER5:
    _VENUE_PRIORITY[v] = 5

_MAX_ABSTRACTS_FOR_SELECTION = 9999
_TARGET_SELECTED_PAPERS = 20


def _venue_priority(venue: str | None) -> int:
    if not venue:
        return 99
    return _VENUE_PRIORITY.get(venue, 99)


def _collect_all_paths(tax_jsons: list[str]) -> dict[str, set[str]]:
    """Collect all unique paths per tree, including intermediate nodes."""
    tree_paths: dict[str, set[str]] = defaultdict(set)
    for raw in tax_jsons:
        if not raw:
            continue
        try:
            tax = json.loads(raw)
        except Exception:
            continue
        for tree_name, paths in tax.items():
            if not isinstance(paths, list):
                continue
            for p in paths:
                parts = p.split("/")
                for i in range(1, len(parts) + 1):
                    tree_paths[tree_name].add("/".join(parts[:i]))
    return tree_paths


def _get_direct_children(tree_paths: dict[str, set[str]], tree_name: str, path: str) -> list[str]:
    """Return direct children of a path within a tree."""
    prefix = path + "/" if path else ""
    children: set[str] = set()
    for p in tree_paths.get(tree_name, set()):
        if not p.startswith(prefix) or p == path:
            continue
        rest = p[len(prefix):]
        if "/" not in rest:
            children.add(rest)
    return sorted(children)


def _get_papers_for_path(
    db: DB, tree_name: str, path: str
) -> list[dict[str, Any]]:
    """Return ALL core papers whose taxonomy_json contains this path.
    Sorted by venue priority (tier 1 first) then year DESC.
    """
    like = f'%{tree_name}%{path}%'
    sql = """
    SELECT * FROM papers
    WHERE relevance = 'core'
      AND taxonomy_json LIKE ?
    ORDER BY year DESC
    """
    rows = list(db._conn.execute(sql, (like,)))
    papers = [dict(r) for r in rows]
    papers.sort(key=lambda p: (_venue_priority(p.get("venue")), -(p.get("year") or 0)))
    return papers


# ------------------------------------------------------------------
# Dimension root — no papers, describe WHY this dimension exists
# ------------------------------------------------------------------

def _build_dimension_prompt(tree_name: str, sub_categories: list[str]) -> list[dict]:
    system = (
        "You are a research taxonomy expert. "
        "Explain the rationale behind a taxonomy dimension in AI-agent research. "
        "Respond with strict JSON only."
    )
    cats_block = "\n".join(f"- {sc}" for sc in sub_categories)
    user = f"""Our survey taxonomy has a dimension called "{tree_name}". It is divided into the following sub-categories:
{cats_block}

Please write a concise bilingual description:
1. What this dimension captures in AI-agent research
2. Why these sub-categories are grouped under this dimension (what is the organising principle?)
3. What aspects of agent research this classification tries to organise

Requirements:
- 3-4 sentences in English (desc_en)
- 3-4 sentences in Chinese (desc_zh)
- Keep it accessible to someone unfamiliar with the field
- Do NOT mention individual papers; this is a meta-level description of the dimension itself

Return strict JSON:
{{
  "desc_en": "...",
  "desc_zh": "..."
}}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _process_dimension_root(
    tree_name: str,
    cfg: Config,
    tree_paths: dict[str, set[str]],
    db_path: Path,
    llm: DeepSeekClient | None = None,
) -> tuple[str, str, str, str, int, dict[str, Any], dict]:
    """Process a dimension root (tree_name with empty path).

    Returns (tree, path, desc_en, desc_zh, paper_count, metadata, meta).
    """
    worker_name = threading.current_thread().name
    own_llm = llm is None
    llm = llm or DeepSeekClient(cfg)
    db = DB(db_path)

    try:
        db.set_taxonomy_status(tree_name, "", "processing")
        sub_categories = _get_direct_children(tree_paths, tree_name, "")
        if not sub_categories:
            db.set_taxonomy_status(tree_name, "", "done")
            return tree_name, "", "", "", 0, {}, {
                "worker": worker_name,
                "cached": False,
                "errors": 0,
            }

        messages = _build_dimension_prompt(tree_name, sub_categories)
        stage_cfg = cfg.llm.stage10_category_desc or cfg.llm.stage3_classify

        out = cached_chat_json(
            llm,
            db,
            paper_id=f"catdesc_dim_{tree_name}",
            stage="category_desc_dim",
            model=stage_cfg.model,
            prompt_version="v1",
            messages=messages,
            temperature=0.3,
            max_tokens=512,
        )
        data = out.get("content", {})
        desc_en = data.get("desc_en", "").strip()
        desc_zh = data.get("desc_zh", "").strip()
        cached = out.get("cached", False)
        u = out.get("usage") or {}
        db.set_taxonomy_status(tree_name, "", "done")
        return tree_name, "", desc_en, desc_zh, 0, {}, {
            "worker": worker_name,
            "cached": cached,
            "errors": 0,
            "usage": dict(u) if u else {},
        }
    except Exception as exc:
        console.print(f"[red]Failed dimension root {tree_name}: {exc}[/red]")
        db.set_taxonomy_status(tree_name, "", "failed", last_error=str(exc)[:500])
        return tree_name, "", "", "", 0, {}, {
            "worker": worker_name,
            "cached": False,
            "errors": 1,
        }
    finally:
        db.close()
        if own_llm:
            pass


# ------------------------------------------------------------------
# Phase A — select representative papers from abstracts
# ------------------------------------------------------------------

def _build_stage_a_prompt(
    tree_name: str, path: str, papers: list[dict[str, Any]]
) -> list[dict]:
    parts = path.split("/")
    level = len(parts)

    abstracts_block = "\n\n---\n\n".join(
        f"[{i+1}] {p['paper_id']}\nTitle: {p.get('title', '')}\nVenue: {p.get('venue', '')} ({p.get('year', '')})\nAbstract: {p.get('abstract') or '(no abstract)'}"
        for i, p in enumerate(papers)
    )

    system = (
        "You are a research survey expert. Your task is to pick the most representative papers "
        "from a list of abstracts so that a later LLM can write a high-quality category description. "
        "Respond with strict JSON only."
    )

    user = f"""We need to write a description for taxonomy category: "{path}"
Tree: {tree_name}  |  Level: {level}

Below are {len(papers)} papers belonging to this category. Each has an ID, title, venue, year, and abstract.

Selection rules (in order of importance):
1. DIVERSITY — pick papers that cover *different* angles / methods within this category. Avoid abstracts that look like minor variants of the same idea.
2. RECENCY — prefer 2025/2024 over 2023. Only include 2023 if it is a foundational/unique work.
3. VENUE — top-tier venues (ICSE, FSE, ASE, ISSTA, S&P, CCS, USENIX Security, NDSS, TOSEM, TSE) are preferred.
4. DEPTH — prefer papers with richer abstracts (detailed method, evaluation, dataset) over shallow / teaser abstracts.

Please select exactly {_TARGET_SELECTED_PAPERS} paper IDs (use the `paper_id` field) that together give the best overview of this category. If fewer than {_TARGET_SELECTED_PAPERS} papers exist, return all of them.

{abstracts_block}

Return strict JSON:
{{
  "selected_paper_ids": ["paper_id_1", "paper_id_2", ...],
  "reasoning": "brief explanation of why these papers were chosen"
}}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _stage_a_select(
    db: DB,
    llm: DeepSeekClient,
    cfg: Config,
    tree_name: str,
    path: str,
    papers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run Phase A: return the subset of papers selected by DeepSeek."""
    if len(papers) <= _TARGET_SELECTED_PAPERS:
        return papers

    capped = papers[:_MAX_ABSTRACTS_FOR_SELECTION]
    messages = _build_stage_a_prompt(tree_name, path, capped)
    stage_cfg = cfg.llm.stage10_category_desc or cfg.llm.stage3_classify

    out = cached_chat_json(
        llm,
        db,
        paper_id=f"catdesc_a_{tree_name}_{path.replace('/', '_')}",
        stage="category_desc_a",
        model=stage_cfg.model,
        prompt_version="v2",
        messages=messages,
        temperature=0.3,
        max_tokens=512,
    )
    data = out.get("content", {})
    selected_ids = set(data.get("selected_paper_ids", []))
    selected = [p for p in papers if p["paper_id"] in selected_ids]

    # fallback: if DeepSeek returned none or invalid IDs, just take top N
    if not selected:
        selected = papers[:_TARGET_SELECTED_PAPERS]

    return selected


# ------------------------------------------------------------------
# Phase B — generate description from selected papers
# ------------------------------------------------------------------

def _extract_pdf_snippets(papers: list[dict]) -> list[tuple[str, str]]:
    """Extract (title, body) from up to 3 pages of each PDF."""
    out: list[tuple[str, str]] = []
    for p in papers:
        pdf_path = p.get("pdf_path")
        if not pdf_path:
            continue
        text = extract_text(Path(pdf_path), max_pages=3)
        if not text:
            continue
        body = build_prompt_body(text, max_chars=6000)
        out.append((p["title"], body))
    return out


def _build_stage_b_prompt(
    tree_name: str, path: str, level: int, snippets: list[tuple[str, str]]
) -> list[dict]:
    parts = path.split("/")
    parent = parts[-2] if level > 1 else "(root)"
    leaf = parts[-1]

    papers_text = "\n\n---\n\n".join(
        f"Paper: {title}\n{body[:2500]}" for title, body in snippets
    )

    if level == 1:
        emphasis = (
            "This is a SUB-CATEGORY (first level under the dimension). "
            "Use plain, accessible language to explain what this sub-field does. "
            "What is the typical goal? What kind of tasks or problems do researchers in this area tackle?"
        )
    else:
        emphasis = (
            "This is a LEAF category (concrete direction). Describe the specific techniques, core methods, and main challenges. "
            "What makes this direction distinct from sibling categories?"
        )

    system = (
        "You are a research taxonomy expert. Based on the provided paper excerpts, "
        "write a concise bilingual description of what this taxonomy category represents. "
        "Respond with strict JSON only."
    )

    user = f"""Category: "{path}"
Tree: {tree_name}
Level: {level} (parent = "{parent}")
Selected papers for analysis: {len(snippets)}

Emphasis: {emphasis}

Paper excerpts:
{papers_text}

Requirements:
- 3-4 sentences in English (desc_en)
- 3-4 sentences in Chinese (desc_zh)
- Focus on what kind of research this category covers
- Mention the typical tasks, methods, or goals
- Keep it accessible to someone unfamiliar with the field

Also provide structured metadata about this category:
- methods: list of 2-5 typical methods / techniques used in this category (strings)
- datasets: list of 0-5 commonly used datasets or benchmarks (strings)
- trends: one sentence describing the recent trend or evolution of this category

Return strict JSON:
{{
  "desc_en": "...",
  "desc_zh": "...",
  "metadata": {{
    "methods": ["..."],
    "datasets": ["..."],
    "trends": "..."
  }}
}}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _process_category(
    tree_name: str,
    path: str,
    cfg: Config,
    db_path: Path,
    llm: DeepSeekClient | None = None,
) -> tuple[str, str, str, str, int, dict[str, Any], dict]:
    """Process one sub-category through Phase A + Phase B.

    Returns (tree, path, desc_en, desc_zh, paper_count, metadata, meta).
    """
    worker_name = threading.current_thread().name
    own_llm = llm is None
    llm = llm or DeepSeekClient(cfg)
    db = DB(db_path)

    try:
        db.set_taxonomy_status(tree_name, path, "processing")
        # ---- Phase A: gather & select papers ----
        all_papers = _get_papers_for_path(db, tree_name, path)
        paper_count = len(all_papers)

        if not all_papers:
            db.set_taxonomy_status(tree_name, path, "done")
            return tree_name, path, "", "", 0, {}, {
                "worker": worker_name,
                "cached": False,
                "errors": 0,
            }

        selected = _stage_a_select(db, llm, cfg, tree_name, path, all_papers)
        if not selected:
            selected = all_papers[:_TARGET_SELECTED_PAPERS]

        # ---- Phase B: extract text & generate description ----
        snippets = _extract_pdf_snippets(selected)
        if not snippets:
            # fallback: use abstracts
            snippets = [
                (p["title"], p.get("abstract", "") or "")
                for p in selected
                if p.get("abstract")
            ]

        level = len(path.split("/"))
        messages = _build_stage_b_prompt(tree_name, path, level, snippets)
        stage_cfg = cfg.llm.stage10_category_desc or cfg.llm.stage3_classify

        out = cached_chat_json(
            llm,
            db,
            paper_id=f"catdesc_b_{tree_name}_{path.replace('/', '_')}",
            stage="category_desc_b",
            model=stage_cfg.model,
            prompt_version="v2",
            messages=messages,
            temperature=0.3,
            max_tokens=768,
        )
        data = out.get("content", {})
        desc_en = data.get("desc_en", "").strip()
        desc_zh = data.get("desc_zh", "").strip()
        metadata = data.get("metadata", {})
        cached = out.get("cached", False)
        u = out.get("usage") or {}
        db.set_taxonomy_status(tree_name, path, "done")
        return tree_name, path, desc_en, desc_zh, paper_count, metadata, {
            "worker": worker_name,
            "cached": cached,
            "errors": 0,
            "usage": dict(u) if u else {},
        }
    except Exception as exc:
        console.print(f"[red]Failed {tree_name}/{path}: {exc}[/red]")
        db.set_taxonomy_status(tree_name, path, "failed", last_error=str(exc)[:500])
        return tree_name, path, "", "", 0, {}, {
            "worker": worker_name,
            "cached": False,
            "errors": 1,
        }
    finally:
        db.close()
        if own_llm:
            pass  # no close needed


def run(
    cfg: Config,
    *,
    force: bool = False,
    limit: int | None = None,
    workers: int = 3,
) -> dict:
    db_path = cfg.abs_path("db")
    db = DB(db_path)
    try:
        # Collect all taxonomy_json values
        rows = list(db._conn.execute(
            "SELECT taxonomy_json FROM papers WHERE relevance='core' AND taxonomy_json IS NOT NULL AND taxonomy_json != '' AND taxonomy_json != '{}'"
        ))
        tax_jsons = [r[0] for r in rows]
        tree_paths = _collect_all_paths(tax_jsons)

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
            db.upsert_taxonomy_desc(tree, path, status=status)

        # Filter out already-done if not force (backward-compat: desc_en IS NOT NULL also counts as done)
        if not force:
            existing = {
                (r["tree_name"], r["path"])
                for r in db.iter_taxonomy_descs()
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

        with Live(Group(token_line, prog), console=console, refresh_per_second=4):
            task = prog.add_task(
                f"category-desc ({stage_cfg.model}) [{workers}w]",
                total=total,
                saved=0,
            )

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {}
                for tree, path in all_tasks:
                    if path == "":
                        f = executor.submit(_process_dimension_root, tree, cfg, tree_paths, db_path, llm)
                    else:
                        f = executor.submit(_process_category, tree, path, cfg, db_path, llm)
                    futures[f] = (tree, path)

                for future in as_completed(futures):
                    tree_name, path = futures[future]
                    try:
                        result = future.result()
                        tree_name, path, desc_en, desc_zh, paper_count, metadata, meta = result
                    except Exception as exc:
                        console.print(f"[red]Crashed {tree_name}/{path}: {exc}[/red]")
                        db.set_taxonomy_status(tree_name, path, "failed", last_error=str(exc)[:500])
                        with lock:
                            failed += 1
                        prog.advance(task)
                        continue

                    if meta.get("errors"):
                        with lock:
                            failed += 1
                    else:
                        db.upsert_taxonomy_desc(
                            tree_name, path,
                            desc_en=desc_en or None,
                            desc_zh=desc_zh or None,
                            paper_count=paper_count,
                            metadata=metadata or None,
                        )
                        with lock:
                            processed += 1

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
