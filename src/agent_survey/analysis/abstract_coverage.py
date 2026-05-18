"""Visualize abstract coverage gaps by venue."""
from __future__ import annotations

import sqlite3
from collections import Counter

from rich.console import Console
from rich.table import Table

from ..core.config import load_config


def run(cfg=None):
    if cfg is None:
        cfg = load_config()
    db_path = cfg.abs_path("db")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 1. Papers with no abstract at all
    cur = conn.execute(
        """
        SELECT venue, COUNT(*) as cnt
        FROM papers
        WHERE relevance IN ('core','related','adjacent')
          AND (abstract IS NULL OR abstract = '')
        GROUP BY venue
        ORDER BY cnt DESC
        """
    )
    no_abs = list(cur.fetchall())

    # 2. Papers with suspiciously short / garbage abstracts
    cur = conn.execute(
        """
        SELECT venue, COUNT(*) as cnt
        FROM papers
        WHERE relevance IN ('core','related','adjacent')
          AND abstract IS NOT NULL AND abstract != ''
          AND (LENGTH(abstract) < 30 OR abstract IN ('.', ',', '...', 'null', '[]', '{}'))
        GROUP BY venue
        ORDER BY cnt DESC
        """
    )
    bad_abs = list(cur.fetchall())

    # 3. Papers with good abstracts
    cur = conn.execute(
        """
        SELECT venue, COUNT(*) as cnt
        FROM papers
        WHERE relevance IN ('core','related','adjacent')
          AND abstract IS NOT NULL AND abstract != ''
          AND LENGTH(abstract) >= 30
          AND abstract NOT IN ('.', ',', '...', 'null', '[]', '{}')
        GROUP BY venue
        ORDER BY cnt DESC
        """
    )
    good_abs = list(cur.fetchall())

    conn.close()

    console = Console()
    console.rule("[bold cyan]Abstract Coverage by Venue")

    # Build combined table
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

    # Sort by total descending
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
    console.print(f"[white]Overall:        {total_good/total_all:.1%}[/white]" if total_all else "")


if __name__ == "__main__":
    run()
