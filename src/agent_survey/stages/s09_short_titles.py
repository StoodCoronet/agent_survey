"""Stage 9: generate short titles for long paper titles via DeepSeek."""
from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.progress import Progress

from ..core.config import Config
from ..core.console import console
from ..core.db import DB
from ..services.llm import DeepSeekClient
from ..services.pdf_extract import extract_text
from ..analysis.stats import write_stage_stats


_SYSTEM = """You are a research assistant creating concise abbreviations for academic paper titles.
Respond with strict JSON only."""

_USER_TEMPLATE = """Below are {n} academic papers. For each, provide a short abbreviation (≤35 chars) of the TITLE that preserves the key concept.

The EXCERPT from the paper's PDF is provided to help you understand the actual contribution so the abbreviation is accurate and distinctive.

CRITICAL: The final collection contains thousands of papers. Every abbreviation MUST be UNIQUE and easily distinguishable from others. Do NOT produce generic abbreviations.

Rules:
- Keep well-known acronyms (e.g., LLM, GUI, OSWorld, WebArena)
- Remove filler words like "A Survey of", "Towards", "Exploring", "Investigating" when possible
- Prefer "Method: Task" format when applicable
- Preserve DISTINCTIVE keywords (method name, dataset name, domain, or specific technique) to avoid duplicates
- If two titles would naturally abbreviate to the same thing, add a distinguishing word to make them unique
- If title is already ≤50 chars, keep it as-is

Papers:
{papers}

Return JSON: {{"mapping": {{"<full_title>": "<short_title>", ...}}}}
"""

_RETRY_TEMPLATE = """Some abbreviations you generated are DUPLICATE or too generic. Below are the problematic titles and the conflicting abbreviations already in use.

Please regenerate UNIQUE abbreviations for these titles only. Make sure each new abbreviation is clearly different from the existing ones listed below.

Existing abbreviations (do NOT reuse):
{existing}

Titles to fix (one per line):
{titles}

Return JSON: {{"mapping": {{"<full_title>": "<short_title>", ...}}}}
"""


def _pdf_snippet(pdf_path: str | None, max_chars: int = 1200) -> str:
    """Extract first ~2 pages of PDF text, truncated."""
    if not pdf_path:
        return ""
    p = Path(pdf_path)
    if not p.exists():
        return ""
    try:
        text = extract_text(p, max_pages=2)
        return text[:max_chars].strip()
    except Exception:
        return ""


def _batch_titles(
    items: list[tuple[str, str, str]],
    batch_size: int = 20,
    existing: list[str] | None = None,
    workers: int = 5,
) -> dict[str, str]:
    """Call DeepSeek in batches with parallel workers.

    items: list of (paper_id, title, pdf_snippet)
    """
    from ..core.config import load_config

    cfg = load_config()
    client = DeepSeekClient(cfg)
    mapping: dict[str, str] = {}

    batches = [items[i : i + batch_size] for i in range(0, len(items), batch_size)]

    with Progress(console=console) as prog:
        task = prog.add_task(
            "retrying duplicates" if existing else "generating short titles",
            total=len(batches),
        )

        def worker(batch):
            if existing:
                lines = "\n".join(f"{i+1}. {t}" for i, (_, t, _) in enumerate(batch))
                existing_str = "\n".join(f"- {s}" for s in existing)
                content = _RETRY_TEMPLATE.format(
                    n=len(batch), titles=lines, existing=existing_str
                )
            else:
                blocks = []
                for idx, (_, title, snippet) in enumerate(batch, 1):
                    snippet_line = f"Excerpt: {snippet[:800]}" if snippet else ""
                    blocks.append(f"{idx}. Title: {title}\n   {snippet_line}")
                content = _USER_TEMPLATE.format(n=len(batch), papers="\n\n".join(blocks))

            messages = [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": content},
            ]
            try:
                result = client.chat_json(
                    model="deepseek-chat",
                    messages=messages,
                    temperature=0.0,
                    max_tokens=4096,
                )
            except Exception as exc:
                console.print(f"[red]Batch failed: {exc}[/red]")
                return {}
            data = result.get("content", {})
            batch_map = data.get("mapping", {})
            return batch_map

        with ThreadPoolExecutor(max_workers=workers) as exe:
            futures = {exe.submit(worker, b): b for b in batches}
            for fut in as_completed(futures):
                try:
                    batch_map = fut.result()
                except Exception as exc:
                    console.print(f"[red]Worker crashed: {exc}[/red]")
                    batch_map = {}
                mapping.update(batch_map)
                prog.advance(task)

    return mapping


def _resolve_duplicates(
    items: list[tuple[str, str, str]],
    mapping: dict[str, str],
    batch_size: int,
    workers: int = 5,
) -> dict[str, str]:
    """Detect duplicate short titles and retry once."""
    all_shorts = [mapping.get(t, "") for _, t, _ in items]
    counts = Counter(all_shorts)
    dups = {s for s, c in counts.items() if c > 1 and s}

    if not dups:
        return mapping

    console.print(f"[yellow]Found {len(dups)} duplicate short titles, retrying...[/yellow]")
    dup_items = [(pid, t, s) for pid, t, s in items if mapping.get(t) in dups]
    existing = list(set(all_shorts))
    retry_map = _batch_titles(dup_items, batch_size=batch_size, existing=existing, workers=workers)
    mapping.update(retry_map)

    # Final check — fallback with numbered suffix for any remaining dups
    all_shorts2 = [mapping.get(t, "") for _, t, _ in items]
    counts2 = Counter(all_shorts2)
    remaining_dups = {s for s, c in counts2.items() if c > 1 and s}
    if remaining_dups:
        console.print(f"[yellow]{len(remaining_dups)} duplicates remain after retry, appending suffix...[/yellow]")
        for dup_short in remaining_dups:
            dup_pids = [pid for pid, t, _ in items if mapping.get(t) == dup_short]
            for idx, pid in enumerate(dup_pids[1:], start=1):
                title = next(t for p, t, _ in items if p == pid)
                base = mapping.get(title, title)
                if len(base) > 30:
                    base = base[:28]
                mapping[title] = f"{base} ({idx})"

    return mapping


def run(
    cfg: Config,
    *,
    force: bool = False,
    batch_size: int = 20,
    scope: str = "core",
    workers: int = 5,
    use_pdf: bool = True,
) -> dict:
    db = DB(cfg.abs_path("db"))
    try:
        scope_where = {
            "core": "relevance = 'core'",
            "related": "relevance = 'related'",
            "adjacent": "relevance = 'adjacent'",
            "all": "relevance IN ('core', 'related', 'adjacent')",
            "classified": "relevance IN ('core', 'related', 'adjacent')",
        }.get(scope, "relevance = 'core'")

        # Clear cache if force
        if force:
            console.print(f"[yellow]Clearing existing short titles for {scope}...[/yellow]")
            db._conn.execute(f"UPDATE papers SET short_title = NULL WHERE {scope_where}")
            db._conn.commit()

        where = scope_where + " AND (short_title IS NULL OR short_title = '')"

        rows = [r for r in db.iter_papers(where)]
        long_rows = [r for r in rows if len(r["title"]) > 50]
        short_rows = [r for r in rows if len(r["title"]) <= 50]

        if not long_rows:
            console.print("[yellow]no long titles need abbreviation[/yellow]")
            for r in short_rows:
                db.update_paper(r["paper_id"], {"short_title": r["title"]})
            return {"processed": 0, "skipped": len(short_rows)}

        # Extract PDF snippets in parallel
        snippets: dict[str, str] = {}
        if use_pdf:
            console.print("[bold]Extracting PDF snippets...[/bold]")
            pdf_rows = [r for r in long_rows if r.get("pdf_path")]
            with Progress(console=console) as prog:
                task = prog.add_task("reading PDFs", total=len(pdf_rows))

                def _read_one(r):
                    return r["paper_id"], _pdf_snippet(r.get("pdf_path"))

                with ThreadPoolExecutor(max_workers=8) as exe:
                    futures = [exe.submit(_read_one, r) for r in pdf_rows]
                    for fut in as_completed(futures):
                        pid, snippet = fut.result()
                        snippets[pid] = snippet
                        prog.advance(task)

        items = [(r["paper_id"], r["title"], snippets.get(r["paper_id"], "")) for r in long_rows]

        # With PDF context, shrink batch size to avoid overly long prompts
        effective_batch = min(batch_size, 5) if use_pdf else batch_size

        console.print(
            f"[bold]Generating short titles for {len(items)} papers (scope={scope}, batch={effective_batch}, workers={workers})...[/bold]"
        )

        mapping = _batch_titles(items, batch_size=effective_batch, workers=workers)
        mapping = _resolve_duplicates(items, mapping, batch_size=effective_batch, workers=workers)

        processed = 0
        for pid, title, _ in items:
            short = mapping.get(title)
            if not short:
                short = title[:38] + "..." if len(title) > 40 else title
            db.update_paper(pid, {"short_title": short})
            db.mark_stage(pid, "short_titles")
            processed += 1

        for r in short_rows:
            db.update_paper(r["paper_id"], {"short_title": r["title"]})
            db.mark_stage(r["paper_id"], "short_titles")

        # Final duplicate check across the whole DB for this scope
        all_rows = [r for r in db.iter_papers(scope_where)]
        all_shorts = [r.get("short_title", "") for r in all_rows if r.get("short_title")]
        dup_count = sum(c - 1 for c in Counter(all_shorts).values() if c > 1)
        if dup_count:
            console.print(f"[yellow]Warning: {dup_count} duplicate short titles remain in DB[/yellow]")

        stats = {"processed": processed, "skipped": len(short_rows), "duplicates_remaining": dup_count}
        out = write_stage_stats(cfg, "short_titles", stats)
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
