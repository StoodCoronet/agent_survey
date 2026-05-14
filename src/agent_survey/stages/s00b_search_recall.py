"""Search-recall branch.

For each target query (e.g. "GUI agent"), search S2 + arXiv, then match the
returned papers back to DBLP entries in our DB. If matched, flip the
prefilter_hit flag so those papers enter the classify stage even if keyword
prefilter missed them.

This does NOT create new DB rows — only augments existing DBLP entries.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Iterable

import httpx
from rich.progress import Progress

from ..core.config import Config
from ..core.console import console
from ..core.db import DB
from ..services import arxiv as arxiv_src
from ..services.s2 import S2Client
from ..analysis.stats import print_overview, write_stage_stats

# queries tuned to widen recall for our themes
DEFAULT_QUERIES = [
    "GUI agent",
    "computer use agent",
    "mobile agent LLM",
    "web agent large language model",
    "screen agent",
    "LLM agent testing",
    "LLM agent security",
    "autonomous coding agent",
    "prompt injection agent",
    "agent benchmark GUI",
    "visual language model agent",
]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _build_title_index(db: DB) -> dict[str, str]:
    """norm(title) -> paper_id."""
    idx: dict[str, str] = {}
    for r in db.iter_papers():
        t = _norm(r.get("title") or "")
        if t:
            idx[t] = r["paper_id"]
    return idx


def _build_doi_index(db: DB) -> dict[str, str]:
    idx: dict[str, str] = {}
    for r in db.iter_papers("doi IS NOT NULL AND doi != ''"):
        idx[r["doi"].lower()] = r["paper_id"]
    return idx


def _build_dblp_index(db: DB) -> dict[str, str]:
    idx: dict[str, str] = {}
    for r in db.iter_papers("dblp_key IS NOT NULL AND dblp_key != ''"):
        idx[r["dblp_key"]] = r["paper_id"]
    return idx


def _match_paper(
    title: str,
    doi: str | None,
    dblp_key: str | None,
    arxiv_id: str | None,
    title_idx: dict[str, str],
    doi_idx: dict[str, str],
    dblp_idx: dict[str, str],
) -> str | None:
    if dblp_key and dblp_key in dblp_idx:
        return dblp_idx[dblp_key]
    if doi and doi.lower() in doi_idx:
        return doi_idx[doi.lower()]
    if title:
        n = _norm(title)
        if n in title_idx:
            return title_idx[n]
    return None


def _merge_hit(db: DB, paper_id: str, key: str, matches: list[str]) -> None:
    paper = db.get_paper(paper_id)
    if not paper:
        return
    existing_raw = paper.get("prefilter_hit") or "[]"
    try:
        existing = json.loads(existing_raw) if isinstance(existing_raw, str) else existing_raw
    except Exception:
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    if key not in existing:
        existing[key] = []
    for m in matches:
        if m not in existing[key]:
            existing[key].append(m)
    db.update_paper(paper_id, {"prefilter_hit": existing})


def run(
    cfg: Config,
    queries: list[str] | None = None,
    *,
    per_query: int = 200,
    enable_arxiv: bool = True,
) -> dict:
    queries = queries or DEFAULT_QUERIES
    db = DB(cfg.abs_path("db"))
    try:
        title_idx = _build_title_index(db)
        doi_idx = _build_doi_index(db)
        dblp_idx = _build_dblp_index(db)
        if not title_idx:
            console.print("[yellow]DB is empty — run harvest first[/yellow]")
            return {"matched": 0}

        s2 = S2Client(api_key=cfg.semantic_scholar_api_key)
        http_ax = httpx.Client(
            timeout=cfg.network.request_timeout,
            headers={"User-Agent": cfg.network.user_agent},
        )

        per_query_counts: Counter = Counter()
        matched_ids: dict[str, list[str]] = defaultdict(list)
        total_s2_hits = 0
        total_arxiv_hits = 0
        unmatched_examples: dict[str, list[str]] = defaultdict(list)

        with Progress(console=console) as prog:
            task = prog.add_task("recall", total=len(queries))
            for q in queries:
                prog.update(task, description=f"[cyan]S2: {q}[/cyan]")
                # ----- S2 search -----
                try:
                    for item in s2.search_relevance(
                        q,
                        year_start=cfg.years.start,
                        year_end=cfg.years.end,
                        max_results=per_query,
                    ):
                        total_s2_hits += 1
                        title = item.get("title") or ""
                        ext = item.get("externalIds") or {}
                        pid = _match_paper(
                            title,
                            ext.get("DOI"),
                            ext.get("DBLP"),
                            ext.get("ArXiv"),
                            title_idx,
                            doi_idx,
                            dblp_idx,
                        )
                        if pid:
                            matched_ids[pid].append(f"s2:{q}")
                            per_query_counts[q] += 1
                        elif len(unmatched_examples[q]) < 5:
                            unmatched_examples[q].append(title)
                except Exception as e:
                    console.print(f"[red]S2 search {q} failed: {e}[/red]")

                # ----- arXiv search -----
                if enable_arxiv:
                    prog.update(task, description=f"[cyan]arXiv: {q}[/cyan]")
                    try:
                        ax_query = f'all:"{q}"'
                        for ax in arxiv_src.search_query(
                            http_ax,
                            ax_query,
                            max_results=per_query,
                            year_start=cfg.years.start,
                            year_end=cfg.years.end,
                        ):
                            total_arxiv_hits += 1
                            pid = _match_paper(
                                ax.get("title") or "",
                                ax.get("doi"),
                                None,
                                ax.get("arxiv_id"),
                                title_idx,
                                doi_idx,
                                dblp_idx,
                            )
                            if pid:
                                matched_ids[pid].append(f"arxiv:{q}")
                                per_query_counts[q] += 1
                    except Exception as e:
                        console.print(f"[red]arXiv search {q} failed: {e}[/red]")
                prog.advance(task)

        # apply to DB
        for pid, sources in matched_ids.items():
            _merge_hit(db, pid, "search_recall", sources)

        stats = {
            "queries": queries,
            "total_s2_hits": total_s2_hits,
            "total_arxiv_hits": total_arxiv_hits,
            "matched_unique": len(matched_ids),
            "matches_per_query": dict(per_query_counts),
            "unmatched_examples_per_query": dict(unmatched_examples),
        }
        out = write_stage_stats(cfg, "search_recall", stats)
        print_overview(db, "after search-recall")
        console.print(f"[green]recall matched {len(matched_ids)} unique papers[/green]")
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        try:
            s2.close()
        except Exception:
            pass
        try:
            http_ax.close()
        except Exception:
            pass
        db.close()
