"""Checkpoint stats helpers — write per-stage JSON and print summary."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from rich.table import Table

from ..core.config import Config
from ..core.console import console
from ..core.db import DB


def write_stage_stats(cfg: Config, stage: str, payload: dict) -> Path:
    stats_dir = cfg.project_root / "output" / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = stats_dir / f"{stage}_{ts}.json"
    payload = {"stage": stage, "timestamp": ts, **payload}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return out


def db_overview(db: DB, topic_name: str = "") -> dict:
    total = db.count()
    with_abstract = db.count("abstract IS NOT NULL AND abstract != ''")
    prefilter_hit = 0
    for row in db.iter_papers():
        ph = row.get("prefilter_hit") or "{}"
        try:
            phd = json.loads(ph) if isinstance(ph, str) else ph
        except Exception:
            phd = {}
        if not phd or phd in ("[]", "{}"):
            continue
        if topic_name:
            if isinstance(phd, dict) and phd.get(topic_name):
                prefilter_hit += 1
        elif isinstance(phd, (dict, list)) and phd:
            prefilter_hit += 1

    classified = db.count_topic(topic_name, "relevance IS NOT NULL AND relevance != ''") if topic_name else 0
    by_relevance = Counter()
    by_venue_year = Counter()
    for row in db.iter_papers():
        by_venue_year[(row.get("venue"), row.get("year"))] += 1
    if topic_name:
        for pt in db.iter_paper_topics(topic_name, "relevance IS NOT NULL AND relevance != ''"):
            if pt.get("relevance"):
                by_relevance[pt["relevance"]] += 1
    return {
        "total": total,
        "with_abstract": with_abstract,
        "prefilter_hit": prefilter_hit,
        "classified": classified,
        "by_relevance": dict(by_relevance),
        "by_venue_year": {f"{v}/{y}": c for (v, y), c in sorted(by_venue_year.items(), key=lambda x: x[0])},
    }


def print_overview(db: DB, title: str = "DB overview", topic_name: str = "") -> None:
    ov = db_overview(db, topic_name)
    console.rule(f"[bold cyan]{title}")
    t = Table(show_header=True)
    t.add_column("metric", style="cyan")
    t.add_column("value", style="magenta", justify="right")
    for k in ("total", "with_abstract", "prefilter_hit", "classified"):
        t.add_row(k, str(ov[k]))
    console.print(t)
    if ov["by_relevance"]:
        console.print("[bold]by relevance:[/bold]", ov["by_relevance"])
    if ov["by_venue_year"]:
        vy = Table(show_header=True)
        vy.add_column("venue")
        vy.add_column("year")
        vy.add_column("count", justify="right")
        for k, v in sorted(ov["by_venue_year"].items()):
            venue, year = k.split("/", 1)
            vy.add_row(venue, year, str(v))
        console.print(vy)
