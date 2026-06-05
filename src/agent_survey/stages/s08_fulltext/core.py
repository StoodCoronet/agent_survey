"""Core PDF download worker for fulltext stage."""
from __future__ import annotations

from pathlib import Path

import httpx

from ...core.config import Config
from ...core.db import DB
from ...services import arxiv as arxiv_src


def download_one(
    r: dict,
    cfg: Config,
    pdf_dir: Path,
    force: bool,
    db_path: Path,
    topic_name: str = "",
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
                db.mark_stage(paper_id, "fulltext", "done", topic_name=topic_name)
            finally:
                db.close()
            return {"status": "ok", "arxiv_id": arxiv_id, "paper_id": paper_id}
        else:
            return {"status": "failed", "arxiv_id": arxiv_id, "paper_id": paper_id}
    finally:
        http.close()
