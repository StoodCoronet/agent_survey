"""Core worker for deepdive structured extraction."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.config import Config
from ...core.db import DB
from ...services.llm import DeepSeekClient, cached_chat_json
from ...services.pdf_extract import build_prompt_body, extract_text


def process_paper(
    row: dict,
    cfg: Config,
    stage_cfg: Any,
    dd_cfg: Any,
    llm: DeepSeekClient,
    db: DB,
    topic_name: str = "",
) -> dict[str, Any]:
    """Process a single paper deepdive. Returns result dict; caller handles DB writes."""
    try:
        title = row.get("title") or "?"
        pdf_path = Path(row["pdf_path"])
        text = extract_text(pdf_path, max_pages=40)
        if not text.strip():
            return {
                "paper_id": row["paper_id"],
                "success": True,
                "no_text": True,
            }

        body = build_prompt_body(text)
        user = dd_cfg.user_prompt_template.format(
            title=title,
            venue=row.get("venue") or "",
            year=row.get("year") or "",
            body=body,
        )
        messages = [
            {"role": "system", "content": dd_cfg.system_prompt},
            {"role": "user", "content": user},
        ]
        out = cached_chat_json(
            llm, db,
            paper_id=row["paper_id"],
            stage="deepdive",
            model=stage_cfg.model,
            prompt_version=stage_cfg.prompt_version,
            messages=messages,
            temperature=stage_cfg.temperature,
            max_tokens=stage_cfg.max_tokens,
            topic_name=topic_name,
        )
        data = out["content"]
        code_url = data.get("code_url")
        return {
            "paper_id": row["paper_id"],
            "success": True,
            "cached": out.get("cached", False),
            "data": data,
            "code_url": code_url,
        }
    except Exception as e:
        return {"paper_id": row["paper_id"], "success": False, "error": str(e)}
