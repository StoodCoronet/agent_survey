"""Core workers for category-desc stage."""
from __future__ import annotations

import json
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

from ...core.config import Config
from ...core.console import console
from ...core.db import DB
from ...services.llm import DeepSeekClient, cached_chat_json
from ...services.pdf_extract import build_prompt_body, extract_text
from .prompts import build_dimension_prompt, build_stage_a_prompt, build_stage_b_prompt

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


def collect_all_paths(tax_jsons: list[str]) -> dict[str, set[str]]:
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


def get_direct_children(tree_paths: dict[str, set[str]], tree_name: str, path: str) -> list[str]:
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


def get_papers_for_path(
    db: DB, tree_name: str, path: str, topic_name: str = "gui-agent"
) -> list[dict[str, Any]]:
    """Return ALL core papers for topic whose taxonomy_json contains this path.
    Sorted by venue priority (tier 1 first) then year DESC.
    """
    like = f'%{tree_name}%{path}%'
    papers = []
    for pt in db.iter_paper_topics(
        topic_name,
        "relevance = 'core' AND taxonomy_json LIKE ?",
        [like],
    ):
        p = db.get_paper(pt["paper_id"])
        if p:
            p["taxonomy_json"] = pt.get("taxonomy_json")
            papers.append(p)
    papers.sort(key=lambda p: (_venue_priority(p.get("venue")), -(p.get("year") or 0)))
    return papers


def process_dimension_root(
    tree_name: str,
    cfg: Config,
    tree_paths: dict[str, set[str]],
    db_path: Path,
    llm: DeepSeekClient | None = None,
    topic_name: str = "gui-agent",
) -> tuple[str, str, str, str, int, dict[str, Any], dict]:
    """Process a dimension root (tree_name with empty path).

    Returns (tree, path, desc_en, desc_zh, paper_count, metadata, meta).
    Caller handles DB writes.
    """
    worker_name = threading.current_thread().name
    own_llm = llm is None
    llm = llm or DeepSeekClient(cfg)
    db = DB(db_path)

    try:
        sub_categories = get_direct_children(tree_paths, tree_name, "")
        if not sub_categories:
            return tree_name, "", "", "", 0, {}, {
                "worker": worker_name,
                "cached": False,
                "errors": 0,
            }

        messages = build_dimension_prompt(tree_name, sub_categories)
        stage_cfg = cfg.llm.stage10_category_desc or cfg.llm.stage3_classify

        out = cached_chat_json(
            llm, db,
            paper_id=f"catdesc_dim_{tree_name}",
            stage="category_desc_dim",
            model=stage_cfg.model,
            prompt_version="v1",
            messages=messages,
            temperature=0.3,
            max_tokens=512,
            topic_name=topic_name,
        )
        data = out.get("content", {})
        desc_en = data.get("desc_en", "").strip()
        desc_zh = data.get("desc_zh", "").strip()
        cached = out.get("cached", False)
        u = out.get("usage") or {}
        return tree_name, "", desc_en, desc_zh, 0, {}, {
            "worker": worker_name,
            "cached": cached,
            "errors": 0,
            "usage": dict(u) if u else {},
        }
    except Exception as exc:
        console.print(f"[red]Failed dimension root {tree_name}: {exc}[/red]")
        return tree_name, "", "", "", 0, {}, {
            "worker": worker_name,
            "cached": False,
            "errors": 1,
            "last_error": str(exc)[:500],
        }
    finally:
        db.close()
        if own_llm:
            pass


def stage_a_select(
    db: DB,
    llm: DeepSeekClient,
    cfg: Config,
    tree_name: str,
    path: str,
    papers: list[dict[str, Any]],
    topic_name: str = "",
) -> list[dict[str, Any]]:
    """Run Phase A: return the subset of papers selected by DeepSeek."""
    if len(papers) <= _TARGET_SELECTED_PAPERS:
        return papers

    capped = papers[:_MAX_ABSTRACTS_FOR_SELECTION]
    messages = build_stage_a_prompt(tree_name, path, capped, _TARGET_SELECTED_PAPERS)
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
        topic_name=topic_name,
    )
    data = out.get("content", {})
    selected_ids = set(data.get("selected_paper_ids", []))
    selected = [p for p in papers if p["paper_id"] in selected_ids]

    # fallback: if DeepSeek returned none or invalid IDs, just take top N
    if not selected:
        selected = papers[:_TARGET_SELECTED_PAPERS]

    return selected


def extract_pdf_snippets(papers: list[dict]) -> list[tuple[str, str]]:
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


def process_category(
    tree_name: str,
    path: str,
    cfg: Config,
    db_path: Path,
    llm: DeepSeekClient | None = None,
    topic_name: str = "gui-agent",
) -> tuple[str, str, str, str, int, dict[str, Any], dict]:
    """Process one sub-category through Phase A + Phase B.

    Returns (tree, path, desc_en, desc_zh, paper_count, metadata, meta).
    Caller handles DB writes.
    """
    worker_name = threading.current_thread().name
    own_llm = llm is None
    llm = llm or DeepSeekClient(cfg)
    db = DB(db_path)

    try:
        # ---- Phase A: gather & select papers ----
        all_papers = get_papers_for_path(db, tree_name, path, topic_name)
        paper_count = len(all_papers)

        if not all_papers:
            return tree_name, path, "", "", 0, {}, {
                "worker": worker_name,
                "cached": False,
                "errors": 0,
            }

        selected = stage_a_select(db, llm, cfg, tree_name, path, all_papers, topic_name)
        if not selected:
            selected = all_papers[:_TARGET_SELECTED_PAPERS]

        # ---- Phase B: extract text & generate description ----
        snippets = extract_pdf_snippets(selected)
        if not snippets:
            # fallback: use abstracts
            snippets = [
                (p["title"], p.get("abstract", "") or "")
                for p in selected
                if p.get("abstract")
            ]

        level = len(path.split("/"))
        messages = build_stage_b_prompt(tree_name, path, level, snippets)
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
            topic_name=topic_name,
        )
        data = out.get("content", {})
        desc_en = data.get("desc_en", "").strip()
        desc_zh = data.get("desc_zh", "").strip()
        metadata = data.get("metadata", {})
        cached = out.get("cached", False)
        u = out.get("usage") or {}
        return tree_name, path, desc_en, desc_zh, paper_count, metadata, {
            "worker": worker_name,
            "cached": cached,
            "errors": 0,
            "usage": dict(u) if u else {},
        }
    except Exception as exc:
        console.print(f"[red]Failed {tree_name}/{path}: {exc}[/red]")
        return tree_name, path, "", "", 0, {}, {
            "worker": worker_name,
            "cached": False,
            "errors": 1,
            "last_error": str(exc)[:500],
        }
    finally:
        db.close()
        if own_llm:
            pass  # no close needed
