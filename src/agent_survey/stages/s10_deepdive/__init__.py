"""Stage 5: DeepSeek-Pro (reasoner) structured extraction on PDF body."""
from __future__ import annotations

from pathlib import Path

from rich.progress import Progress

from ...analysis.stats import print_overview, write_stage_stats
from ...core.config import Config, load_topic_config, resolve_topic
from ...core.console import console
from ...core.db import DB
from ...services.llm import DeepSeekClient
from .core import process_paper


def run(
    cfg: Config,
    *,
    relevance_in: list[str] | None = None,
    force: bool = False,
    limit: int | None = None,
    topic_name: str = "",
) -> dict:
    topic_name = resolve_topic(topic_name, cfg)
    tc = load_topic_config(topic_name)
    dd_cfg = tc.deepdive

    relevance_in = relevance_in or ["core", "related"]
    db = DB(cfg.abs_path("db"))
    try:
        # Query via paper_topics for relevance + papers for pdf_path
        rows = []
        for pt in db.iter_paper_topics(topic_name, "relevance IS NOT NULL AND relevance != '"):
            if pt["relevance"] not in relevance_in:
                continue
            if not pt.get("pdf_path"):
                continue
            if not force:
                existing = db.get_deepdive(pt["paper_id"], topic_name)
                if existing:
                    continue  # already done
            rows.append(pt)
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
        pending_writes: list[dict] = []
        FLUSH_EVERY = 10

        def _flush(buf: list[dict]) -> None:
            if not buf:
                return
            for item in buf:
                db.upsert_deepdive(item["paper_id"], topic_name, item["data"], commit=False)
                if item.get("code_url"):
                    existing = db.get_paper(item["paper_id"])
                    if not existing or not existing.get("code_url"):
                        db.update_paper(item["paper_id"], {"code_url": item["code_url"]}, commit=False)
                db.mark_stage(item["paper_id"], "deepdive", "done", topic_name=topic_name, commit=False)
            db._conn.commit()

        with Progress(console=console) as prog:
            task = prog.add_task(f"deepdive ({stage_cfg.model})[{topic_name}]", total=len(rows))
            for r in rows:
                title = r.get("title") or "?"
                prog.update(task, description=f"[cyan]{title[:60]}[/cyan]")
                res = process_paper(r, cfg, stage_cfg, dd_cfg, llm, db, topic_name)
                if res.get("no_text"):
                    no_text += 1
                    db.mark_stage(r["paper_id"], "deepdive", "no_text", topic_name=topic_name)
                elif res.get("success"):
                    ok += 1
                    pending_writes.append(res)
                    if len(pending_writes) >= FLUSH_EVERY:
                        _flush(pending_writes)
                        pending_writes = []
                else:
                    console.print(f"[red]deepdive failed {r['paper_id']}: {res.get('error')}[/red]")
                    failed += 1
                prog.advance(task)

            # Final flush
            _flush(pending_writes)

        stats = {"processed": ok, "failed": failed, "no_text": no_text, "total_candidates": len(rows)}
        out = write_stage_stats(cfg, "deepdive", stats)
        print_overview(db, f"after deepdive [{topic_name}]")
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
