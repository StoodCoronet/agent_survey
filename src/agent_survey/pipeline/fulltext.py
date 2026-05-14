"""Stage 4: download arXiv PDFs (only for classified non-irrelevant papers)."""
from __future__ import annotations

from pathlib import Path

import httpx
from rich.progress import Progress

from ..config import Config
from ..console import console
from ..db import DB
from ..sources import arxiv as arxiv_src
from .stats import print_overview, write_stage_stats


def run(
    cfg: Config,
    *,
    relevance_in: list[str] | None = None,
    force: bool = False,
    limit: int | None = None,
) -> dict:
    relevance_in = relevance_in or ["core", "related", "adjacent"]
    db = DB(cfg.abs_path("db"))
    pdf_dir = cfg.abs_dir("pdfs")
    http = httpx.Client(
        timeout=60, headers={"User-Agent": cfg.network.user_agent}
    )
    try:
        rel_list = ",".join("?" * len(relevance_in))
        where = (
            f"relevance IN ({rel_list}) AND arxiv_id IS NOT NULL AND arxiv_id != ''"
        )
        params = relevance_in
        rows = list(db.iter_papers(where, params))
        if limit:
            rows = rows[:limit]
        if not rows:
            console.print("[yellow]no candidates with arxiv_id to download[/yellow]")
            return {"downloaded": 0}
        ok = 0
        skipped = 0
        failed = 0
        with Progress(console=console) as prog:
            task = prog.add_task("download pdfs", total=len(rows))
            for r in rows:
                arxiv_id = r["arxiv_id"]
                safe = arxiv_id.replace("/", "_")
                dest = pdf_dir / f"{safe}.pdf"
                prog.update(task, description=f"[cyan]{arxiv_id}[/cyan]")
                if dest.exists() and dest.stat().st_size > 1024 and not force:
                    if not r.get("pdf_path"):
                        db.update_paper(r["paper_id"], {"pdf_path": str(dest)})
                    skipped += 1
                elif arxiv_src.download_pdf(http, arxiv_id, dest):
                    db.update_paper(r["paper_id"], {"pdf_path": str(dest)})
                    db.mark_stage(r["paper_id"], "fulltext", "done")
                    ok += 1
                else:
                    failed += 1
                prog.advance(task)
        stats = {"downloaded": ok, "skipped_existing": skipped, "failed": failed, "total_candidates": len(rows)}
        out = write_stage_stats(cfg, "fulltext", stats)
        print_overview(db, "after fulltext")
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        http.close()
        db.close()
