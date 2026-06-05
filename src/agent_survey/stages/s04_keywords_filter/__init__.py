"""Stage 2: keyword prefilter — mark prefilter_hit on papers.

Rule: include if (agent_core) OR (agent_generic AND (se_context OR sec_context))
"""
from __future__ import annotations

import json
import re
from collections import Counter

from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from ...core.config import Config, load_topic_config
from ...core.console import console
from ...core.db import DB
from ...analysis.stats import print_overview, write_stage_stats


def _compile(terms: list[str]) -> list[re.Pattern]:
    pats = []
    for t in terms:
        # word-ish boundary; hyphens permitted
        t_esc = re.escape(t).replace(r"\ ", r"[\s\-]+")
        pats.append(re.compile(rf"(?i)(?<![A-Za-z0-9]){t_esc}(?![A-Za-z0-9])"))
    return pats


def _match(patterns: list[re.Pattern], text: str) -> list[str]:
    hits = []
    for p in patterns:
        m = p.search(text)
        if m:
            hits.append(m.group(0))
    return hits


def run(cfg: Config, *, topic_name: str = "") -> dict:
    topic_name = topic_name or cfg.active_topic or "gui-agent"
    tc = load_topic_config(topic_name)
    kw = tc.keywords
    p_core = _compile(kw.agent_core)
    p_generic = _compile(kw.agent_generic)
    p_se = _compile(kw.se_context)
    p_sec = _compile(kw.sec_context)

    db = DB(cfg.abs_path("db"))
    try:
        hits_total = 0
        cat_counter: Counter = Counter()
        processed = 0
        rows = list(db.iter_papers())
        with Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("[{task.completed}/{task.total}]"),
            TextColumn("[green]hits: {task.fields[hits]}[/green]"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as prog:
            task = prog.add_task("keywords-filter", total=len(rows), hits=0)
            for row in rows:
                text = f"{row.get('title') or ''} {row.get('abstract') or ''}"
                hit_cats: dict[str, list[str]] = {}
                m_core = _match(p_core, text)
                m_generic = _match(p_generic, text)
                m_se = _match(p_se, text)
                m_sec = _match(p_sec, text)
                if m_core:
                    hit_cats["agent_core"] = m_core
                if m_generic and (m_se or m_sec):
                    hit_cats["agent_generic"] = m_generic
                    if m_se:
                        hit_cats["se_context"] = m_se
                    if m_sec:
                        hit_cats["sec_context"] = m_sec
                # Store topic-scoped prefilter_hit
                existing_raw = row.get("prefilter_hit") or "{}"
                try:
                    existing = json.loads(existing_raw) if isinstance(existing_raw, str) else existing_raw
                except Exception:
                    existing = {}
                if not isinstance(existing, dict):
                    existing = {}
                existing[topic_name] = hit_cats
                if hit_cats:
                    hits_total += 1
                    for c in hit_cats:
                        cat_counter[c] += 1
                    # Rich log for matched papers
                    matched_terms = ", ".join(
                        f"{cat}:[{', '.join(terms[:3])}]" for cat, terms in hit_cats.items()
                    )
                    console.print(
                        f"  [green]✓[/green] [{row.get('venue', '?')}] {row.get('title', '')[:50]}... → {matched_terms}"
                    )
                db.update_paper(row["paper_id"], {"prefilter_hit": existing})
                db.mark_stage(row["paper_id"], "prefilter", "done", topic_name=topic_name)
                processed += 1
                prog.update(task, advance=1, hits=hits_total)

        # venue/year breakdown of hits (topic-scoped)
        hit_by_venue_year: Counter = Counter()
        for r in db.iter_papers("prefilter_hit IS NOT NULL AND prefilter_hit != '{}' AND prefilter_hit != '[]'"):
            try:
                ph = json.loads(r["prefilter_hit"]) if isinstance(r["prefilter_hit"], str) else {}
            except Exception:
                ph = {}
            if ph.get(topic_name):
                hit_by_venue_year[(r.get("venue"), r.get("year"))] += 1

        stats = {
            "processed": processed,
            "hits": hits_total,
            "by_category": dict(cat_counter),
            "hits_by_venue_year": {
                f"{v}/{y}": c for (v, y), c in sorted(hit_by_venue_year.items(), key=lambda x: x[0])
            },
        }
        out = write_stage_stats(cfg, "keywords_filter", stats)
        print_overview(db, "after keywords-filter")
        console.print(f"[green]keywords-filter hits: {hits_total}/{processed}[/green]")
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
