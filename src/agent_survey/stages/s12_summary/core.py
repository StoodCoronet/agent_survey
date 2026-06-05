"""Core worker for single-paper summary generation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.config import Config
from ...core.db import DB
from ...services.llm import DeepSeekClient, cached_chat_json
from .prompts import build_messages


def process_paper(
    paper_id: str,
    cfg: Config,
    db_path: Path,
    llm: DeepSeekClient,
    topic_name: str = "",
) -> dict[str, Any]:
    """Process a single paper. Returns result dict; caller handles DB writes to paper_topics."""
    db = DB(db_path)
    try:
        paper = db.get_paper(paper_id)
        if not paper:
            return {"paper_id": paper_id, "success": False, "error": "not found"}

        title = paper.get("title", "")
        abstract = paper.get("abstract", "") or ""

        if not abstract.strip():
            return {
                "paper_id": paper_id,
                "success": True,
                "cached": False,
                "no_abstract": True,
            }

        messages = build_messages(title, abstract)
        stage_cfg = cfg.llm.stage11_summary or cfg.llm.stage3_classify

        out = cached_chat_json(
            llm,
            db,
            paper_id=paper_id,
            stage="summary",
            model=stage_cfg.model,
            prompt_version=stage_cfg.prompt_version,
            messages=messages,
            temperature=stage_cfg.temperature,
            max_tokens=stage_cfg.max_tokens,
            topic_name=topic_name,
        )
        data = out.get("content", {})
        summary_en = data.get("summary_en", "").strip()
        summary_zh = data.get("summary_zh", "").strip()

        return {
            "paper_id": paper_id,
            "success": True,
            "cached": out.get("cached", False),
            "usage": out.get("usage") or {},
            "summary_en": summary_en,
            "summary_zh": summary_zh,
        }
    except Exception as exc:
        return {"paper_id": paper_id, "success": False, "error": str(exc)}
    finally:
        db.close()
