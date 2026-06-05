"""Stage 9: generate short titles for long paper titles via DeepSeek."""
from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.progress import Progress

from ...core.config import Config, resolve_topic
from ...core.console import console
from ...core.db import DB
from ...analysis.stats import write_stage_stats
from .core import _batch_titles, _pdf_snippet, _resolve_duplicates


def run(
    cfg: Config,
    *,
    force: bool = False,
    batch_size: int = 20,
    scope: str = "core",
    workers: int = 5,
    use_pdf: bool = True,
    topic_name: str = "",
) -> dict:
    topic_name = resolve_topic(topic_name, cfg)
    db = DB(cfg.abs_path("db"))
    try:
        # Query paper_topics for scope
        rel_list = ["core"] if scope == "core" else (
            ["core", "related", "adjacent"] if scope in ("all", "classified") else [scope]
        )
        rows = []
        for pt in db.iter_paper_topics(
            topic_name,
            f"relevance IN ({','.join('?' * len(rel_list))})",
            rel_list,
        ):
            if not force and pt.get("short_title"):
                continue
            rows.append(pt)
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
                task = prog.add_task("reading PDFs (papers)", total=len(pdf_rows))

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
            db.upsert_paper_topic(pid, topic_name, {"short_title": short})
            db.mark_stage(pid, "short_titles", topic_name=topic_name)
            processed += 1

        for r in short_rows:
            db.upsert_paper_topic(r["paper_id"], topic_name, {"short_title": r["title"]})
            db.mark_stage(r["paper_id"], "short_titles", topic_name=topic_name)

        # Final duplicate check across topic+scope
        all_shorts = []
        for pt in db.iter_paper_topics(
            topic_name,
            f"relevance IN ({','.join('?' * len(rel_list))})",
            rel_list,
        ):
            if pt.get("short_title"):
                all_shorts.append(pt["short_title"])
        dup_count = sum(c - 1 for c in Counter(all_shorts).values() if c > 1)
        if dup_count:
            console.print(f"[yellow]Warning: {dup_count} duplicate short titles remain in DB[/yellow]")

        stats = {"processed": processed, "skipped": len(short_rows), "duplicates_remaining": dup_count}
        out = write_stage_stats(cfg, "short_titles", stats)
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
