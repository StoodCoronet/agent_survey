"""Core worker for taxonomy classification stage — worker touches API only, no DB."""
from __future__ import annotations

import json
from typing import Any

from ...core.config import Config
from ...services.llm import DeepSeekClient
from ...services.taxonomy import build_messages


def _extract_results(out: dict) -> list[dict]:
    """Parse LLM JSON response into list of per-paper result dicts."""
    content = out.get("content")
    if isinstance(content, str):
        data = json.loads(content)
    else:
        data = content
    papers = data.get("papers", data.get("results", data.get("data", [])))
    results = []
    for i, pr in enumerate(papers):
        if isinstance(pr, dict) and ("paper_idx" in pr or any(k not in ("paper_idx", "cross_cutting", "new_leaves") for k in pr.keys())):
            results.append(pr)
        else:
            results.append({"paper_idx": i + 1})
    return results


def process_batch(
    batch: list[dict],
    cfg: Config,
    stage_cfg: Any,
    tax_cfg,
    llm: DeepSeekClient,
    topic_name: str = "",
    max_tokens_per_paper: int = 1024,
) -> tuple[list[dict], list[dict], Exception | None, dict]:
    """
    Process one batch via API only.  Returns (batch, paper_results, error, meta).
    No DB access — caller (main thread) persists results.
    """
    try:
        messages = build_messages(batch, tax_cfg)
        out = llm.chat_json(
            model=stage_cfg.model,
            messages=messages,
            temperature=stage_cfg.temperature,
            max_tokens=(max_tokens_per_paper or 1024) * len(batch),
            timeout=getattr(stage_cfg, "timeout", 120.0),
        )
        u = out.get("usage") or {}
        results = _extract_results(out)
        return batch, results, None, {
            "usage": dict(u) if u else {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "cached": False,
            "errors": 0,
        }
    except Exception as e:
        return batch, [], e, {
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "cached": False,
            "errors": 1,
        }
