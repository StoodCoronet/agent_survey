"""Stage 5: DeepSeek-Pro (reasoner) structured extraction on PDF body."""
from __future__ import annotations

import json
from pathlib import Path

from rich.progress import Progress

from ..config import Config
from ..console import console
from ..db import DB
from ..llm.client import DeepSeekClient, cached_chat_json
from ..llm.prompts import build_deepdive_messages
from ..pdf.extract import build_prompt_body, extract_text
from .stats import print_overview, write_stage_stats


def run(
    cfg: Config,
    *,
    relevance_in: list[str] | None = None,
    force: bool = False,
    limit: int | None = None,
) -> dict:
    relevance_in = relevance_in or ["core", "related"]
    db = DB(cfg.abs_path("db"))
    try:
        rel_list = ",".join("?" * len(relevance_in))
        where_parts = [
            f"relevance IN ({rel_list})",
            "pdf_path IS NOT NULL AND pdf_path != ''",
        ]
        if not force:
            where_parts.append("(deepdive_json IS NULL OR deepdive_json = '')")
        where = " AND ".join(where_parts)
        rows = list(db.iter_papers(where, relevance_in))
        if limit:
            rows = rows[:limit]
        if not rows:
            console.print("[yellow]nothing to deepdive[/yellow]")
            return {"processed": 0}

        llm = DeepSeekClient(cfg)
        stage_cfg = cfg.llm.stage5_deepdive
        ok = 0
        failed = 0
        no_text = 0

        with Progress(console=console) as prog:
            task = prog.add_task(f"deepdive ({stage_cfg.model})", total=len(rows))
            for r in rows:
                prog.update(task, description=f"[cyan]{r['title'][:60]}[/cyan]")
                pdf_path = Path(r["pdf_path"])
                text = extract_text(pdf_path, max_pages=40)
                if not text.strip():
                    no_text += 1
                    db.mark_stage(r["paper_id"], "deepdive", "no_text")
                    prog.advance(task)
                    continue
                body = build_prompt_body(text)
                messages = build_deepdive_messages(
                    title=r.get("title") or "",
                    venue=r.get("venue") or "",
                    year=r.get("year"),
                    body=body,
                )
                try:
                    out = cached_chat_json(
                        llm,
                        db,
                        paper_id=r["paper_id"],
                        stage="deepdive",
                        model=stage_cfg.model,
                        prompt_version=stage_cfg.prompt_version,
                        messages=messages,
                        temperature=stage_cfg.temperature,
                        max_tokens=stage_cfg.max_tokens,
                    )
                    data = out["content"]
                    db.update_paper(
                        r["paper_id"],
                        {
                            "deepdive_json": json.dumps(data, ensure_ascii=False),
                            "code_url": data.get("code_url") or r.get("code_url"),
                        },
                    )
                    db.mark_stage(r["paper_id"], "deepdive", "done")
                    ok += 1
                except Exception as e:
                    console.print(f"[red]deepdive failed {r['paper_id']}: {e}[/red]")
                    failed += 1
                prog.advance(task)

        stats = {"processed": ok, "failed": failed, "no_text": no_text, "total_candidates": len(rows)}
        out = write_stage_stats(cfg, "deepdive", stats)
        print_overview(db, "after deepdive")
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
