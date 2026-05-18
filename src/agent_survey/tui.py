"""Rich TUI menu for the Agent Survey pipeline.

Usage:
    agent-survey tui

Controls:
    ↑ / ↓     选择步骤
    Enter     执行选中步骤（支持 workers 的步骤会询问并发数）
    q         退出
"""
from __future__ import annotations

import sqlite3
import sys

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from .core.config import load_config
from .core.console import console

# Steps that accept --workers
_WORKER_STEPS = {"enrich", "enrich-web", "classify", "deepdive", "fulltext", "harvest"}


def _getch() -> str:
    """Cross-platform single-character read (including arrow keys)."""
    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                ch += sys.stdin.read(2)
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        try:
            import msvcrt
            ch = msvcrt.getch().decode("utf-8", errors="ignore")
            return ch
        except Exception:
            return input().strip().lower()


def _read_line(prompt: str = "") -> str:
    """Read a line in cooked mode (safe for raw-terminal sessions)."""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        import termios

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            # Force canonical + echo mode so input() shows typed characters
            new = termios.tcgetattr(fd)
            new[3] = new[3] | termios.ICANON | termios.ECHO
            termios.tcsetattr(fd, termios.TCSADRAIN, new)
            return input().strip()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        return input().strip()


def _is_up(ch: str) -> bool:
    return ch in ("\x1b[A", "k")


def _is_down(ch: str) -> bool:
    return ch in ("\x1b[B", "j")


def _is_enter(ch: str) -> bool:
    return ch in ("\r", "\n")


def _is_quit(ch: str) -> bool:
    return ch.lower() == "q"


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

    # Enrich target: if classified, only core/related/adjacent need abstracts
    if classified > 0:
        need_enrich = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE relevance IN ('core','related','adjacent')"
        ).fetchone()[0]
        enriched = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE relevance IN ('core','related','adjacent') AND abstract IS NOT NULL AND abstract != ''"
        ).fetchone()[0]
    else:
        need_enrich = total
        enriched = with_abstract

    # Web enrich stats
    web_enriched = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE relevance IN ('core','related','adjacent') AND enrich_source = 'web'"
    ).fetchone()[0]
    need_web = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE relevance IN ('core','related','adjacent') AND (abstract IS NULL OR abstract = '' OR LENGTH(abstract) < 30)"
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
        "need_enrich": need_enrich,
        "enriched": enriched,
        "web_enriched": web_enriched,
        "need_web": need_web,
    }


def _step_status(st: dict) -> list[dict]:
    total = st["total"]

    # enrich state: done / partial / pending
    enriched = st["enriched"]
    need = st["need_enrich"]
    if enriched == 0:
        enrich_state = "pending"
        enrich_note = "未开始"
    elif enriched >= need:
        enrich_state = "done"
        enrich_note = "已完成"
    else:
        enrich_state = "partial"
        enrich_note = f"进行中 {enriched}/{need}"

    # enrich-web state
    web_enriched = st.get("web_enriched", 0)
    need_web = st.get("need_web", 0)
    if web_enriched == 0:
        web_state = "pending"
        web_note = "未开始"
    elif need_web == 0:
        web_state = "done"
        web_note = "已完成"
    else:
        web_state = "partial"
        web_note = f"进行中 {web_enriched}/{need_web}"

    return [
        {
            "idx": 1,
            "name": "harvest",
            "state": "done" if total > 0 else "pending",
            "data": f"{total:,}" if total > 0 else "--",
            "note": "已爬" if total > 0 else "未开始",
        },
        {
            "idx": 2,
            "name": "enrich",
            "state": enrich_state,
            "data": f"{enriched:,}" if enriched > 0 else "--",
            "note": enrich_note,
        },
        {
            "idx": 3,
            "name": "enrich-web",
            "state": web_state,
            "data": f"{web_enriched:,}" if web_enriched > 0 else "--",
            "note": web_note,
        },
        {
            "idx": 4,
            "name": "prefilter",
            "state": "done" if st["prefilter_hit"] > 0 else "pending",
            "data": f"{st['prefilter_hit']:,}" if st["prefilter_hit"] > 0 else "--",
            "note": "已命中" if st["prefilter_hit"] > 0 else "未开始",
        },
        {
            "idx": 5,
            "name": "classify",
            "state": "done" if st["classified"] > 0 else "pending",
            "data": f"{st['core']:,}/{st['related']:,}" if st["classified"] > 0 else "--",
            "note": "已分类" if st["classified"] > 0 else "未开始",
        },
        {
            "idx": 6,
            "name": "fulltext",
            "state": "pending",
            "data": "--",
            "note": "未开始",
        },
        {
            "idx": 7,
            "name": "deepdive",
            "state": "pending",
            "data": "--",
            "note": "未开始",
        },
        {
            "idx": 8,
            "name": "report",
            "state": "pending",
            "data": "--",
            "note": "未开始",
        },
    ]


def _build_pipeline_text(steps: list[dict], selected: int) -> Text:
    """Build compact pipeline lines using plain Text (no Table)."""
    out = Text()
    for i, s in enumerate(steps):
        is_sel = i == selected
        state = s.get("state", "pending")
        if state == "done":
            icon = "✅"
            base_style = "green"
        elif state == "partial":
            icon = "⏳"
            base_style = "yellow"
        elif s["idx"] <= 4:
            icon = "❌"
            base_style = "red"
        else:
            icon = "○"
            base_style = "dim"
        style = "bold reverse" if is_sel else base_style
        prefix = ">" if is_sel else " "
        line = f"{prefix}{icon} {s['name']:<9} {s['data']:<10} {s['note']}"
        out.append(line + "\n", style=style)
    return out


def _build_stats_text(st: dict) -> Text:
    coverage = round(st["with_abstract"] / st["total"] * 100, 1) if st["total"] else 0
    lines = (
        f"总:{st['total']:,} 摘:{st['with_abstract']:,}({coverage}%)\n"
        f"C:{st['core']:,} R:{st['related']:,} A:{st['adjacent']:,}"
    )
    return Text(lines)


def _recommend(steps: list[dict]) -> str | None:
    for s in steps:
        if s.get("state", "pending") != "done":
            return s["name"]
    return None


def _clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def run():
    st = _get_status()
    steps = _step_status(st)
    rec = _recommend(steps)

    selected = next(
        (i for i, s in enumerate(steps) if s.get("state", "pending") != "done"), 0
    )
    if selected >= len(steps):
        selected = 0

    running = True
    action: str | None = None
    action_args: list[str] = []

    def _draw():
        _clear_screen()
        pipeline = Panel(
            _build_pipeline_text(steps, selected),
            title="🤖 Pipeline",
            border_style="blue",
            padding=(0, 1),
        )
        stats = Panel(
            _build_stats_text(st),
            title="📊 概况",
            border_style="green",
            padding=(0, 1),
        )

        controls = Text()
        controls.append("↑↓选择 Enter执行 q退出", style="dim")
        if rec:
            controls.append(f" | 推荐:{rec}", style="bold yellow")

        console.print(Group(pipeline, stats, controls))

    _draw()

    while running:
        ch = _getch()
        if _is_up(ch):
            selected = (selected - 1) % len(steps)
        elif _is_down(ch):
            selected = (selected + 1) % len(steps)
        elif _is_enter(ch):
            action = steps[selected]["name"]
            if action in _WORKER_STEPS:
                _clear_screen()
                console.print(f"[bold cyan]执行步骤: {action}[/bold cyan]\n")
                val = _read_line("workers 并发数 (默认 5): ")
                workers = int(val) if val.isdigit() else 5
                action_args = ["--workers", str(workers)]
                if action == "enrich":
                    patch = _read_line("patch 模式 (修复异常 abstract, y/N): ").strip().lower()
                    if patch in ("y", "yes"):
                        action_args.append("--patch")
            running = False
        elif _is_quit(ch) or ch == "\x03":
            running = False
        else:
            continue
        if running:
            _draw()

    if action:
        cmd = [sys.executable, "-m", "agent_survey.cli", action, *action_args]
        console.print(f"[green]执行: {' '.join(cmd)}[/green]\n")
        import subprocess

        subprocess.run(cmd)
    else:
        console.print("[dim]已退出[/dim]")


if __name__ == "__main__":
    run()
