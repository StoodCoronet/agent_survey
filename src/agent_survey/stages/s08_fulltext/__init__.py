"""Stage 4: download arXiv PDFs (only for classified non-irrelevant papers)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import json

from rich.progress import Progress

from ...analysis.stats import print_overview, write_stage_stats
from ...core.config import Config, resolve_topic
from ...core.console import console
from ...core.db import DB
from .core import download_one


def run(
    cfg: Config,
    *,
    relevance_in: list[str] | None = None,
    force: bool = False,
    limit: int | None = None,
    scope: str | None = None,
    workers: int = 1,
    topic_name: str = "",
) -> dict:
    topic_name = resolve_topic(topic_name, cfg)
    relevance_in = relevance_in or ["core", "related", "adjacent"]
    db = DB(cfg.abs_path("db"))
    pdf_dir = cfg.abs_dir("pdfs")

    try:
        # Collect paper IDs from paper_topics
        candidate_ids = set()
        for pt in db.iter_paper_topics(
            topic_name,
            "arxiv_id IS NOT NULL AND arxiv_id != ''",
        ):
            if scope:
                if pt["relevance"] != scope:
                    continue
                dk = pt.get("dedup_keep_json")
                if dk:
                    try:
                        dkd = json.loads(dk) if isinstance(dk, str) else dk
                    except Exception:
                        dkd = {}
                    if not dkd.get(scope):
                        continue
            elif pt["relevance"] not in relevance_in:
                continue
            candidate_ids.add(pt["paper_id"])

        rows = [db.get_paper(pid) for pid in candidate_ids if db.get_paper(pid)]
        if limit:
            rows = rows[:limit]
        if not rows:
            console.print("[yellow]no candidates with arxiv_id to download[/yellow]")
            return {"downloaded": 0}

        console.print(
            f"[bold]PDF candidates:[/bold] {len(rows)} "
            f"(topic={topic_name}, scope={scope or 'all'}, workers={workers})"
        )

        ok = 0
        skipped = 0
        failed = 0
        db_path = cfg.abs_path("db")

        with Progress(console=console) as prog:
            task = prog.add_task("download pdfs", total=len(rows))

            if workers > 1:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(
                            download_one, r, cfg, pdf_dir, force, db_path, topic_name
                        ): r
                        for r in rows
                    }
                    for future in as_completed(futures):
                        res = future.result()
                        prog.update(task, description=f"[cyan]{res['arxiv_id']}[/cyan]")
                        if res["status"] == "ok":
                            ok += 1
                        elif res["status"] == "skipped":
                            skipped += 1
                        else:
                            failed += 1
                        prog.advance(task)
            else:
                for r in rows:
                    res = download_one(r, cfg, pdf_dir, force, db_path, topic_name)
                    prog.update(task, description=f"[cyan]{res['arxiv_id']}[/cyan]")
                    if res["status"] == "ok":
                        ok += 1
                    elif res["status"] == "skipped":
                        skipped += 1
                    else:
                        failed += 1
                    prog.advance(task)

        stats = {
            "downloaded": ok,
            "skipped_existing": skipped,
            "failed": failed,
            "total_candidates": len(rows),
            "scope": scope,
            "workers": workers,
        }
        out = write_stage_stats(cfg, "fulltext", stats)
        print_overview(db, "after fulltext")
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
