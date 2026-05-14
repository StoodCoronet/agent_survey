"""Rich TUI menu for the Agent Survey pipeline.

Usage:
    agent-survey tui
"""
from __future__ import annotations

import sqlite3

from rich.align import Align
from rich.panel import Panel
from rich.table import Table

from .core.config import load_config
from .core.console import console
from .core.db import DB


def _get_status() -> dict:
    cfg = load_config()
    db_path = cfg.abs_path("db")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    with_abstract = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE abstract IS NOT NULL AND abstract != ''"
    ).fetchone()[0]
    prefilter_hit = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE prefilter_hit IS NOT NULL AND prefilter_hit != '[]' AND prefilter_hit != '{}'"
    ).fetchone()[0]
    classified = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE relevance IS NOT NULL AND relevance != ''"
    ).fetchone()[0]
    core = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE relevance = 'core'"
    ).fetchone()[0]
    related = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE relevance = 'related'"
    ).fetchone()[0]
    adjacent = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE relevance = 'adjacent'"
    ).fetchone()[0]
    conn.close()

    return {
        "total": total,
        "with_abstract": with_abstract,
        "prefilter_hit": prefilter_hit,
        "classified": classified,
        "core": core,
        "related": related,
        "adjacent": adjacent,
    }


def _step_status(st: dict) -> list[dict]:
    total = st["total"]
    return [
        {
            "idx": 1,
            "name": "harvest",
            "done": total > 0,
            "data": f"{total:,}" if total > 0 else "--",
            "note": "数据已爬" if total > 0 else "未开始",
        },
        {
            "idx": 2,
            "name": "enrich",
            "done": st["with_abstract"] > 0,
            "data": f"{st['with_abstract']:,} abs" if st["with_abstract"] > 0 else "--",
            "note": "有摘要" if st["with_abstract"] > 0 else "未开始",
        },
        {
            "idx": 3,
            "name": "prefilter",
            "done": st["prefilter_hit"] > 0,
            "data": f"{st['prefilter_hit']:,} hits" if st["prefilter_hit"] > 0 else "--",
            "note": "关键词命中" if st["prefilter_hit"] > 0 else "未开始",
        },
        {
            "idx": 4,
            "name": "classify",
            "done": st["classified"] > 0,
            "data": f"core:{st['core']:,} rel:{st['related']:,}" if st["classified"] > 0 else "--",
            "note": "LLM分类完成" if st["classified"] > 0 else "未开始",
        },
        {
            "idx": 5,
            "name": "fulltext",
            "done": False,
            "data": "--",
            "note": "未开始",
        },
        {
            "idx": 6,
            "name": "deepdive",
            "done": False,
            "data": "--",
            "note": "未开始",
        },
        {
            "idx": 7,
            "name": "report",
            "done": False,
            "data": "--",
            "note": "未开始",
        },
    ]


def _recommend(steps: list[dict], st: dict) -> str | None:
    for s in steps:
        if not s["done"]:
            return s["name"]
    return None


def run():
    st = _get_status()
    steps = _step_status(st)
    rec = _recommend(steps, st)

    # ---- Pipeline table ----
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column(style="cyan", width=4)
    t.add_column(style="bold", width=12)
    t.add_column(width=18)
    t.add_column(style="dim")

    for s in steps:
        icon = "✅" if s["done"] else "❌" if s["idx"] <= 4 and not s["done"] else "○"
        style = "green" if s["done"] else "red" if icon == "❌" else "dim"
        t.add_row(
            f"[{style}]{icon}[/{style}]",
            f"[{style}]{s['name']}[/{style}]",
            s["data"],
            s["note"],
        )

    pipeline_panel = Panel(t, title="🤖 Agent Survey Pipeline", border_style="blue")

    # ---- Stats panel ----
    coverage = round(st["with_abstract"] / st["total"] * 100, 1) if st["total"] else 0
    stats_text = (
        f"总论文: {st['total']:,}  |  有摘要: {st['with_abstract']:,} ({coverage}%)\n"
        f"core: {st['core']:,}  |  related: {st['related']:,}  |  adjacent: {st['adjacent']:,}"
    )
    stats_panel = Panel(stats_text, title="📊 当前数据库概况", border_style="green")

    # ---- Render ----
    console.print(pipeline_panel)
    console.print(stats_panel)

    if rec:
        console.print(f"\n[bold yellow]💡 推荐下一步: {rec}[/bold yellow]")
    else:
        console.print("\n[bold green]✨ 所有步骤已完成！[/bold green]")

    console.print("\n[dim]输入步骤号 (1-7) 执行，r 执行推荐，q 退出[/dim]")

    # ---- Input loop ----
    mapping = {
        "1": "harvest",
        "2": "enrich",
        "3": "prefilter",
        "4": "classify",
        "5": "fulltext",
        "6": "deepdive",
        "7": "report",
    }

    while True:
        try:
            choice = console.input("[bold cyan]> [/bold cyan]").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "q" or choice == "":
            break

        if choice == "r" and rec:
            choice = str(next(s["idx"] for s in steps if s["name"] == rec))

        if choice in mapping:
            cmd = mapping[choice]
            console.print(f"[green]执行: agent-survey {cmd}[/green]\n")
            # Import and run dynamically to avoid circular imports
            import subprocess
            import sys
            subprocess.run([sys.executable, "-m", "agent_survey.cli", cmd])
        else:
            console.print("[red]无效输入，请输入 1-7, r 或 q[/red]")


if __name__ == "__main__":
    run()
