"""Stage 1: fill abstract + arxiv_id + pdf_url using S2 and arXiv."""
from __future__ import annotations

import json
from collections import Counter

import httpx
from rich.progress import Progress

from ..config import Config
from ..console import console
from ..db import DB
from ..sources import arxiv as arxiv_src
from ..sources.semantic_scholar import S2Client
from .stats import print_overview, write_stage_stats


def _batch_ids_for_s2(rows: list[dict]) -> tuple[list[str], list[int]]:
    """Build S2 batch ids + aligned row indices.

    Prefers DOI (DOI:...), then DBLP (DBLP:<key>), then ARXIV.
    """
    ids: list[str] = []
    idx: list[int] = []
    for i, r in enumerate(rows):
        if r.get("doi"):
            ids.append(f"DOI:{r['doi']}")
            idx.append(i)
        elif r.get("dblp_key"):
            ids.append(f"DBLP:{r['dblp_key']}")
            idx.append(i)
    return ids, idx


def run(cfg: Config, *, force: bool = False, limit: int | None = None) -> dict:
    db = DB(cfg.abs_path("db"))
    try:
        where = "(abstract IS NULL OR abstract = '')" if not force else "1=1"
        rows = [r for r in db.iter_papers(where)]
        if limit:
            rows = rows[:limit]
        if not rows:
            console.print("[yellow]nothing to enrich[/yellow]")
            return {"enriched": 0}

        s2 = S2Client(api_key=cfg.semantic_scholar_api_key)
        http_ax = httpx.Client(
            timeout=cfg.network.request_timeout,
            headers={"User-Agent": cfg.network.user_agent},
        )

        enriched = 0
        arxiv_added = 0
        failed = 0
        src_counter: Counter = Counter()

        # ---- phase 1: S2 batch lookup by DOI/DBLP ids
        batch_ids, row_idx = _batch_ids_for_s2(rows)
        s2_results: dict[int, dict] = {}
        if batch_ids:
            console.print(f"[cyan]S2 batch lookup {len(batch_ids)} ids...[/cyan]")
            try:
                res = s2.batch_lookup(batch_ids)
                for i, r in zip(row_idx, res):
                    if r:
                        s2_results[i] = r
            except Exception as e:
                console.print(f"[red]S2 batch failed: {e}[/red]")

        # ---- phase 2: per-paper fallback (title search via S2 + arXiv)
        with Progress(console=console) as prog:
            task = prog.add_task("enriching", total=len(rows))
            for i, row in enumerate(rows):
                paper_id = row["paper_id"]
                prog.update(task, description=f"[cyan]{row['title'][:60]}[/cyan]")
                abstract = row.get("abstract") or ""
                arxiv_id = row.get("arxiv_id")
                pdf_url = row.get("pdf_url")
                doi = row.get("doi")
                source = []

                s2_data = s2_results.get(i)
                if not s2_data:
                    try:
                        s2_data = s2.search_by_title(row["title"])
                    except Exception:
                        s2_data = None

                if s2_data:
                    if not abstract and s2_data.get("abstract"):
                        abstract = s2_data["abstract"]
                        source.append("s2")
                    ext = s2_data.get("externalIds") or {}
                    if not arxiv_id and ext.get("ArXiv"):
                        arxiv_id = ext["ArXiv"]
                    if not doi and ext.get("DOI"):
                        doi = ext["DOI"]
                    oa = s2_data.get("openAccessPdf") or {}
                    if not pdf_url and oa.get("url"):
                        pdf_url = oa["url"]

                # arXiv fallback (title search) — only if still missing abstract
                if not arxiv_id and not abstract:
                    try:
                        ax = arxiv_src.search_title(http_ax, row["title"])
                        if ax:
                            arxiv_id = ax.get("arxiv_id")
                            if ax.get("abstract"):
                                abstract = ax["abstract"]
                                source.append("arxiv")
                            if not pdf_url and ax.get("pdf_url"):
                                pdf_url = ax["pdf_url"]
                            arxiv_added += 1
                    except Exception:
                        pass

                if abstract or arxiv_id or pdf_url:
                    db.update_paper(
                        paper_id,
                        {
                            "abstract": abstract or None,
                            "arxiv_id": arxiv_id,
                            "doi": doi,
                            "pdf_url": pdf_url,
                        },
                    )
                    db.mark_stage(paper_id, "enrich", "done")
                    enriched += 1
                    for s in source:
                        src_counter[s] += 1
                else:
                    failed += 1
                    db.mark_stage(paper_id, "enrich", "no_abstract")

                prog.advance(task)

        s2.close()
        http_ax.close()
        stats = {
            "processed": len(rows),
            "enriched": enriched,
            "arxiv_matched": arxiv_added,
            "failed": failed,
            "sources": dict(src_counter),
        }
        out = write_stage_stats(cfg, "enrich", stats)
        print_overview(db, "after enrich")
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
