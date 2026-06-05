"""Visualize abstract coverage gaps by venue (topic-aware)."""
from __future__ import annotations

import sqlite3
from collections import Counter

from rich.console import Console
from rich.table import Table

from ..core.config import Config, resolve_topic
from ..core.db import DB


def run(cfg: Config, topic_name: str = ""):
    topic_name = resolve_topic(topic_name, cfg)
    db = DB(cfg.abs_path("db"))
    try:
        # Join paper_topics for topic-scoped relevance, papers for abstract
        base_sql = """
            SELECT p.venue, COUNT(*) as cnt
            FROM papers p
            JOIN paper_topics pt ON p.paper_id = pt.paper_id
            WHERE pt.topic_name = ? AND pt.relevance IN ('core','related','adjacent')
        """

        no_abs = list(db._conn.execute(
            base_sql + " AND (p.abstract IS NULL OR p.abstract = '') GROUP BY p.venue ORDER BY cnt DESC",
            (topic_name,)
        ).fetchall())

        bad_abs = list(db._conn.execute(
            base_sql + " AND p.abstract IS NOT NULL AND p.abstract != ''"
            " AND (LENGTH(p.abstract) < 30 OR p.abstract IN ('.', ',', '...', 'null', '[]', '{}'))"
            " GROUP BY p.venue ORDER BY cnt DESC",
            (topic_name,)
        ).fetchall())

        good_abs = list(db._conn.execute(
            base_sql + " AND p.abstract IS NOT NULL AND p.abstract != ''"
            " AND LENGTH(p.abstract) >= 30"
            " AND p.abstract NOT IN ('.', ',', '...', 'null', '[]', '{}')"
            " GROUP BY p.venue ORDER BY cnt DESC",
            (topic_name,)
        ).fetchall())

        console = Console()
        console.rule(f"[bold cyan]Abstract Coverage by Venue — {topic_name}")

        all_venues = set()
        for r in no_abs + bad_abs + good_abs:
            all_venues.add(r["venue"] or "?")

        t = Table(show_header=True, box=None)
        t.add_column("Venue", style="cyan")
        t.add_column("Good", justify="right", style="green")
        t.add_column("Bad (<30/garbage)", justify="right", style="yellow")
        t.add_column("Missing", justify="right", style="red")
        t.add_column("Total", justify="right", style="white")
        t.add_column("Coverage", justify="right", style="magenta")

        no_map = {r["venue"] or "?": r["cnt"] for r in no_abs}
        bad_map = {r["venue"] or "?": r["cnt"] for r in bad_abs}
        good_map = {r["venue"] or "?": r["cnt"] for r in good_abs}

        rows = []
        for v in sorted(all_venues):
            g = good_map.get(v, 0)
            b = bad_map.get(v, 0)
            m = no_map.get(v, 0)
            total = g + b + m
            coverage = f"{g/total:.0%}" if total else "--"
            rows.append((v, g, b, m, total, coverage))

        rows.sort(key=lambda x: -x[4])

        for v, g, b, m, total, coverage in rows:
            t.add_row(v, str(g), str(b), str(m), str(total), coverage)

        console.print(t)

        total_good = sum(good_map.values())
        total_bad = sum(bad_map.values())
        total_missing = sum(no_map.values())
        total_all = total_good + total_bad + total_missing

        console.print()
        console.print(f"[green]Total good:     {total_good:,}[/green]")
        console.print(f"[yellow]Total bad:      {total_bad:,}[/yellow]")
        console.print(f"[red]Total missing:  {total_missing:,}[/red]")
        if total_all:
            console.print(f"[white]Overall:        {total_good/total_all:.1%}[/white]")
    finally:
        db.close()


if __name__ == "__main__":
    from ..core.config import load_config
    run(load_config())
