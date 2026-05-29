"""Stage 4: download arXiv PDFs (only for classified non-irrelevant papers)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from rich.progress import Progress

from ..analysis.stats import print_overview, write_stage_stats
from ..core.config import Config
from ..core.console import console
from ..core.db import DB
from ..services import arxiv as arxiv_src


def _download_one(
    r: dict,
    cfg,
    pdf_dir: Path,
    force: bool,
    db_path: Path,
) -> dict:
    """Download a single PDF. Returns result dict."""
    arxiv_id = r["arxiv_id"]
    paper_id = r["paper_id"]
    safe = arxiv_id.replace("/", "_")
    dest = pdf_dir / f"{safe}.pdf"

    if dest.exists() and dest.stat().st_size > 1024 and not force:
        db = DB(db_path)
        try:
            existing = db.get_paper(paper_id)
            if existing and not existing.get("pdf_path"):
                db.update_paper(paper_id, {"pdf_path": str(dest)})
        finally:
            db.close()
        return {"status": "skipped", "arxiv_id": arxiv_id, "paper_id": paper_id}

    http = httpx.Client(
        timeout=60, headers={"User-Agent": cfg.network.user_agent}
    )
    try:
        if arxiv_src.download_pdf(http, arxiv_id, dest):
            db = DB(db_path)
            try:
                db.update_paper(paper_id, {"pdf_path": str(dest)})
                db.mark_stage(paper_id, "fulltext", "done")
            finally:
                db.close()
            return {"status": "ok", "arxiv_id": arxiv_id, "paper_id": paper_id}
        else:
            return {"status": "failed", "arxiv_id": arxiv_id, "paper_id": paper_id}
    finally:
        http.close()


def run(
    cfg: Config,
    *,
    relevance_in: list[str] | None = None,
    force: bool = False,
    limit: int | None = None,
    scope: str | None = None,
    workers: int = 1,
) -> dict:
    relevance_in = relevance_in or ["core", "related", "adjacent"]
    db = DB(cfg.abs_path("db"))
    pdf_dir = cfg.abs_dir("pdfs")

    try:
        if scope:
            where = (
                f"relevance = '{scope}' "
                f"AND dedup_keep_json LIKE '%\"{scope}\": true%' "
                f"AND arxiv_id IS NOT NULL AND arxiv_id != ''"
            )
            params = []
        else:
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

        console.print(
            f"[bold]PDF candidates:[/bold] {len(rows)} "
            f"(scope={scope or 'all'}, workers={workers})"
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
                            _download_one, r, cfg, pdf_dir, force, db_path
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
                    res = _download_one(r, cfg, pdf_dir, force, db_path)
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
