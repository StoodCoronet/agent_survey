"""Prompt builders for classification stage."""
from __future__ import annotations

from typing import Any


def _paper_prompt_block(paper: dict, idx: int, core_venues: set) -> str:
    # All papers get title + abstract (DeepSeek-Flash is cheap enough)
    has_abs = bool(paper.get("abstract") and paper.get("abstract").strip())
    if has_abs:
        return f"""[{idx}] Title: {paper['title']}
Venue: {paper.get('venue', '')} ({paper.get('year', '')})
Abstract: {paper['abstract']}"""
    return f"""[{idx}] Title: {paper['title']}
Venue: {paper.get('venue', '')} ({paper.get('year', '')})
Only title available."""


def build_batch_messages(papers: list[dict], classify_cfg) -> list[dict]:
    """Build LLM messages for batch."""
    core_venues = set(classify_cfg.core_venues or [])
    blocks = [_paper_prompt_block(p, i + 1, core_venues) for i, p in enumerate(papers)]
    n = len(papers)
    user = classify_cfg.batch_user_prompt_template.format(
        count=n,
        relevance_levels=classify_cfg.relevance_levels,
        domain_labels=classify_cfg.domain_labels,
        method_labels=classify_cfg.method_labels,
        paper_blocks="\n---\n".join(blocks),
    )
    return [
        {"role": "system", "content": classify_cfg.system_prompt},
        {"role": "user", "content": user},
    ]


def build_single_messages(paper: dict, classify_cfg) -> list[dict]:
    """Build LLM messages for a single paper."""
    has_abs = bool(paper.get("abstract") and paper.get("abstract").strip())
    if has_abs:
        user = classify_cfg.user_prompt_template.format(
            title=paper.get("title") or "",
            abstract=paper.get("abstract") or "",
            venue=paper.get("venue") or "",
            year=paper.get("year") or "",
            relevance_levels=classify_cfg.relevance_levels,
            domain_labels=classify_cfg.domain_labels,
            method_labels=classify_cfg.method_labels,
        )
    else:
        user = classify_cfg.user_prompt_title_only.format(
            title=paper.get("title") or "",
            venue=paper.get("venue") or "",
            year=paper.get("year") or "",
            relevance_levels=classify_cfg.relevance_levels,
            domain_labels=classify_cfg.domain_labels,
            method_labels=classify_cfg.method_labels,
        )
    return [
        {"role": "system", "content": classify_cfg.system_prompt},
        {"role": "user", "content": user},
    ]
