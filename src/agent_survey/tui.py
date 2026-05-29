"""Rich TUI menu for the Agent Survey pipeline.

Usage:
    agent-survey tui

Controls:
    ↑ / ↓     选择步骤
    Enter     执行选中步骤（支持 workers 的步骤会询问并发数）
    q         退出
"""
from __future__ import annotations

import sys

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from .core.config import load_config
from .core.console import console
from .core.db import DB

# Steps that accept --workers
_WORKER_STEPS = {"enrich", "enrich-web", "classify", "classify-topics", "dedup", "taxonomy", "deepdive", "fulltext", "harvest", "short-titles", "category-desc", "summary"}


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
    db = DB(cfg.abs_path("db"))
    try:
        total = db.count()
        with_abstract = db.count("abstract IS NOT NULL AND abstract != ''")
        prefilter_hit = db.count("prefilter_hit IS NOT NULL AND prefilter_hit != '[]' AND prefilter_hit != '{}'")
        classified = db.count("relevance IS NOT NULL AND relevance != ''")
        core = db.count("relevance = 'core'")
        related = db.count("relevance = 'related'")
        adjacent = db.count("relevance = 'adjacent'")

        # Topic classify stats
        topic_classified = db.count(
            "relevance IN ('core','related','adjacent') AND topics_json IS NOT NULL AND topics_json != '' AND topics_json != '[]'"
        )
        topic_need = db.count(
            "relevance IN ('core','related','adjacent') AND abstract IS NOT NULL AND abstract != ''"
        )

        # Enrich target: if classified, only core/related/adjacent need abstracts
        if classified > 0:
            need_enrich = db.count("relevance IN ('core','related','adjacent')")
            enriched = db.count(
                "relevance IN ('core','related','adjacent') AND abstract IS NOT NULL AND abstract != ''"
            )
        else:
            need_enrich = total
            enriched = with_abstract

        # Web enrich stats
        web_enriched = db.count("relevance IN ('core','related','adjacent') AND enrich_source = 'web'")
        need_web = db.count(
            "relevance IN ('core','related','adjacent') AND (abstract IS NULL OR abstract = '' OR LENGTH(abstract) < 30)"
        )

        # Dedup stats by scope
        dedup_core = db.count(
            "relevance = 'core' AND abstract IS NOT NULL AND abstract != '' AND dedup_keep_json IS NOT NULL AND dedup_keep_json LIKE '%\"core\"%'"
        )
        dedup_related = db.count(
            "relevance = 'related' AND abstract IS NOT NULL AND abstract != '' AND dedup_keep_json IS NOT NULL AND dedup_keep_json LIKE '%\"related\"%'"
        )
        dedup_adjacent = db.count(
            "relevance = 'adjacent' AND abstract IS NOT NULL AND abstract != '' AND dedup_keep_json IS NOT NULL AND dedup_keep_json LIKE '%\"adjacent\"%'"
        )

        # Taxonomy stats
        tax_core = db.count(
            "relevance = 'core' AND taxonomy_json IS NOT NULL AND taxonomy_json != '' AND taxonomy_json != '{}'"
        )
        tax_related = db.count(
            "relevance = 'related' AND taxonomy_json IS NOT NULL AND taxonomy_json != '' AND taxonomy_json != '{}'"
        )
        tax_adjacent = db.count(
            "relevance = 'adjacent' AND taxonomy_json IS NOT NULL AND taxonomy_json != '' AND taxonomy_json != '{}'"
        )

        # Fulltext stats
        pdf_core = db.count(
            "relevance = 'core' AND dedup_keep_json LIKE '%\"core\": true%' AND pdf_path IS NOT NULL AND pdf_path != ''"
        )
        pdf_related = db.count(
            "relevance = 'related' AND dedup_keep_json LIKE '%\"related\": true%' AND pdf_path IS NOT NULL AND pdf_path != ''"
        )
        pdf_adjacent = db.count(
            "relevance = 'adjacent' AND dedup_keep_json LIKE '%\"adjacent\": true%' AND pdf_path IS NOT NULL AND pdf_path != ''"
        )

        # Fulltext candidates (dedup-kept with arxiv_id)
        ft_core = db.count(
            "relevance = 'core' AND dedup_keep_json LIKE '%\"core\": true%' AND arxiv_id IS NOT NULL AND arxiv_id != ''"
        )
        ft_related = db.count(
            "relevance = 'related' AND dedup_keep_json LIKE '%\"related\": true%' AND arxiv_id IS NOT NULL AND arxiv_id != ''"
        )
        ft_adjacent = db.count(
            "relevance = 'adjacent' AND dedup_keep_json LIKE '%\"adjacent\": true%' AND arxiv_id IS NOT NULL AND arxiv_id != ''"
        )

        # Citation stats (papers with citation_json extracted)
        cit_core = db.count(
            "relevance = 'core' AND citation_json IS NOT NULL AND citation_json != '' AND citation_json != '{}'"
        )
        cit_related = db.count(
            "relevance = 'related' AND citation_json IS NOT NULL AND citation_json != '' AND citation_json != '{}'"
        )
        cit_adjacent = db.count(
            "relevance = 'adjacent' AND citation_json IS NOT NULL AND citation_json != '' AND citation_json != '{}'"
        )

        # Short-titles stats
        short_done = db.count("short_title IS NOT NULL AND short_title != ''")

        # Category-desc stats
        cat_desc_row = db._conn.execute(
            "SELECT COUNT(*) AS n FROM taxonomy_descriptions WHERE desc_en IS NOT NULL OR desc_zh IS NOT NULL"
        ).fetchone()
        cat_desc_done = cat_desc_row["n"] if cat_desc_row else 0

        # Summary stats
        summary_done = db.count("relevance = 'core' AND summary_en IS NOT NULL AND summary_en != ''")

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
            "topic_classified": topic_classified,
            "topic_need": topic_need,
            "dedup_core": dedup_core,
            "dedup_related": dedup_related,
            "dedup_adjacent": dedup_adjacent,
            "pdf_core": pdf_core,
            "pdf_related": pdf_related,
            "pdf_adjacent": pdf_adjacent,
            "ft_core": ft_core,
            "ft_related": ft_related,
            "ft_adjacent": ft_adjacent,
            "tax_core": tax_core,
            "tax_related": tax_related,
            "tax_adjacent": tax_adjacent,
            "cit_core": cit_core,
            "cit_related": cit_related,
            "cit_adjacent": cit_adjacent,
            "short_done": short_done,
            "cat_desc_done": cat_desc_done,
            "summary_done": summary_done,
        }
    finally:
        db.close()


def _choose_scope(st: dict) -> str | None:
    """Interactive scope picker using ↑↓ / Enter / q. Returns scope or None."""
    options = [
        ("core", f"core     — {st['ft_core']:,} papers (most conservative, ~$0.03)"),
        ("related", f"related  — {st['ft_related']:,} papers (moderate, ~$0.21)"),
        ("adjacent", f"adjacent — {st['ft_adjacent']:,} papers (aggressive, ~$0.41)"),
        ("all", f"all      — {st['ft_core'] + st['ft_related'] + st['ft_adjacent']:,} papers (all scopes)"),
    ]
    sel = 0

    def _draw_options():
        _clear_screen()
        console.print("[bold cyan]选择 fulltext scope[/bold cyan]\n")
        for i, (val, label) in enumerate(options):
            prefix = ">" if i == sel else " "
            style = "bold reverse" if i == sel else ""
            console.print(f"{prefix} [{i + 1}] {label}", style=style)
        console.print("\n[dim]↑↓选择  Enter确认  q返回[/dim]")

    _draw_options()
    while True:
        ch = _getch()
        if _is_up(ch):
            sel = (sel - 1) % len(options)
        elif _is_down(ch):
            sel = (sel + 1) % len(options)
        elif _is_enter(ch):
            return options[sel][0] if options[sel][0] != "all" else ""
        elif _is_quit(ch) or ch == "\x03":
            return None
        else:
            continue
        _draw_options()


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

    # topic classify state
    topic_classified = st.get("topic_classified", 0)
    topic_need = st.get("topic_need", 0)
    if topic_classified == 0:
        topic_state = "pending"
        topic_note = "未开始"
    elif topic_classified >= topic_need:
        topic_state = "done"
        topic_note = "已完成"
    else:
        topic_state = "partial"
        topic_note = f"进行中 {topic_classified}/{topic_need}"

    # dedup state (3 independent scopes)
    dedup_core = st.get("dedup_core", 0)
    dedup_related = st.get("dedup_related", 0)
    dedup_adjacent = st.get("dedup_adjacent", 0)
    if dedup_core == 0 and dedup_related == 0 and dedup_adjacent == 0:
        dedup_state = "pending"
        dedup_note = "未开始"
    elif dedup_core >= st["core"] and dedup_related >= st["related"] and dedup_adjacent >= st["adjacent"]:
        dedup_state = "done"
        dedup_note = "已完成"
    else:
        dedup_state = "partial"
        dedup_note = f"c:{dedup_core}/{st['core']} r:{dedup_related}/{st['related']} a:{dedup_adjacent}/{st['adjacent']}"

    # fulltext state
    pdf_core = st.get("pdf_core", 0)
    pdf_related = st.get("pdf_related", 0)
    pdf_adjacent = st.get("pdf_adjacent", 0)
    pdf_total = pdf_core + pdf_related + pdf_adjacent
    if pdf_total == 0:
        fulltext_state = "pending"
        fulltext_note = "未开始"
        fulltext_data = "--"
    elif pdf_core >= st["core"] and pdf_related >= st["related"] and pdf_adjacent >= st["adjacent"]:
        fulltext_state = "done"
        fulltext_note = "已完成"
        fulltext_data = f"c:{pdf_core},r:{pdf_related},a:{pdf_adjacent}"
    else:
        fulltext_state = "partial"
        fulltext_note = f"c:{pdf_core} r:{pdf_related} a:{pdf_adjacent}"
        fulltext_data = f"c:{pdf_core},r:{pdf_related},a:{pdf_adjacent}"

    # taxonomy state
    tax_core = st.get("tax_core", 0)
    tax_related = st.get("tax_related", 0)
    tax_adjacent = st.get("tax_adjacent", 0)
    tax_total = tax_core + tax_related + tax_adjacent
    if tax_total == 0:
        tax_state = "pending"
        tax_note = "未开始"
        tax_data = "--"
    elif tax_core >= st["core"] and tax_related >= st["related"] and tax_adjacent >= st["adjacent"]:
        tax_state = "done"
        tax_note = "已完成"
        tax_data = f"c:{tax_core},r:{tax_related},a:{tax_adjacent}"
    else:
        tax_state = "partial"
        tax_note = f"c:{tax_core} r:{tax_related} a:{tax_adjacent}"
        tax_data = f"c:{tax_core},r:{tax_related},a:{tax_adjacent}"

    # citation state
    cit_core = st.get("cit_core", 0)
    cit_related = st.get("cit_related", 0)
    cit_adjacent = st.get("cit_adjacent", 0)
    cit_total = cit_core + cit_related + cit_adjacent
    if cit_total == 0:
        cit_state = "pending"
        cit_note = "未开始"
        cit_data = "--"
    elif cit_core >= st["core"] and cit_related >= st["related"] and cit_adjacent >= st["adjacent"]:
        cit_state = "done"
        cit_note = "已完成"
        cit_data = f"c:{cit_core},r:{cit_related},a:{cit_adjacent}"
    else:
        cit_state = "partial"
        cit_note = f"c:{cit_core} r:{cit_related} a:{cit_adjacent}"
        cit_data = f"c:{cit_core},r:{cit_related},a:{cit_adjacent}"

    short_done = st.get("short_done", 0)
    cat_desc_done = st.get("cat_desc_done", 0)
    summary_done = st.get("summary_done", 0)

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
            "data": f"{st['prefilter_hit']:,}" if st['prefilter_hit'] > 0 else "--",
            "note": "已命中" if st['prefilter_hit'] > 0 else "未开始",
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
            "name": "classify-topics",
            "state": topic_state,
            "data": f"{topic_classified:,}" if topic_classified > 0 else "--",
            "note": topic_note,
        },
        {
            "idx": 7,
            "name": "dedup",
            "state": dedup_state,
            "data": f"c:{dedup_core},r:{dedup_related},a:{dedup_adjacent}" if dedup_core > 0 or dedup_related > 0 or dedup_adjacent > 0 else "--",
            "note": dedup_note,
        },
        {
            "idx": 8,
            "name": "taxonomy",
            "state": tax_state,
            "data": tax_data,
            "note": tax_note,
        },
        {
            "idx": 9,
            "name": "fulltext",
            "state": fulltext_state,
            "data": fulltext_data,
            "note": fulltext_note,
        },
        {
            "idx": 10,
            "name": "citation",
            "state": cit_state,
            "data": cit_data,
            "note": cit_note,
        },
        {
            "idx": 11,
            "name": "deepdive",
            "state": "pending",
            "data": "--",
            "note": "未开始",
        },
        {
            "idx": 12,
            "name": "report",
            "state": "pending",
            "data": "--",
            "note": "未开始",
        },
        {
            "idx": 13,
            "name": "short-titles",
            "state": "done" if short_done > 0 else "pending",
            "data": f"{short_done:,}" if short_done > 0 else "--",
            "note": "已完成" if short_done > 0 else "未开始",
        },
        {
            "idx": 14,
            "name": "category-desc",
            "state": "done" if cat_desc_done > 0 else "pending",
            "data": f"{cat_desc_done:,}" if cat_desc_done > 0 else "--",
            "note": "已完成" if cat_desc_done > 0 else "未开始",
        },
        {
            "idx": 15,
            "name": "summary",
            "state": "done" if summary_done >= st.get("core", 0) and st.get("core", 0) > 0 else "pending",
            "data": f"{summary_done:,}" if summary_done > 0 else "--",
            "note": "已完成" if summary_done >= st.get("core", 0) and st.get("core", 0) > 0 else "未开始",
        },
        {
            "idx": 16,
            "name": "generate-docs",
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
        line = f"{prefix}{icon} {s['name']:<15} {s['data']:<10} {s['note']}"
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
                elif action == "taxonomy":
                    scope = _choose_scope(st)
                    if scope is None:
                        running = True
                        _draw()
                        continue
                    if scope:
                        action_args.extend(["--scope", scope])
                elif action == "fulltext":
                    scope = _choose_scope(st)
                    if scope is None:
                        running = True
                        _draw()
                        continue
                    if scope:
                        action_args.extend(["--scope", scope])
                elif action == "citation":
                    scope = _choose_scope(st)
                    if scope is None:
                        running = True
                        _draw()
                        continue
                    # citation is single-threaded, no workers needed
                    action_args = []
                    if scope:
                        action_args.extend(["--scope", scope])
                elif action == "short-titles":
                    scope = _choose_scope(st)
                    if scope is None:
                        running = True
                        _draw()
                        continue
                    if scope:
                        action_args.extend(["--scope", scope])
                    use_pdf = _read_line("参考 PDF (Y/n): ").strip().lower()
                    if use_pdf in ("n", "no"):
                        action_args.append("--no-pdf")
                    force = _read_line("强制重新生成 (清除已有缩写, y/N): ").strip().lower()
                    if force in ("y", "yes"):
                        action_args.append("--force")
                elif action == "category-desc":
                    force = _read_line("强制重新生成 (y/N): ").strip().lower()
                    if force in ("y", "yes"):
                        action_args.append("--force")
                elif action == "summary":
                    force = _read_line("强制重新生成 (y/N): ").strip().lower()
                    if force in ("y", "yes"):
                        action_args.append("--force")
            running = False
        elif _is_quit(ch) or ch == "\x03":
            running = False
        else:
            continue
        if running:
            _draw()

    if action:
        import subprocess

        if action == "dedup":
            # run all 3 scopes sequentially
            for scope in ("core", "related", "adjacent"):
                _clear_screen()
                console.print(f"[bold cyan]执行步骤: dedup --scope {scope}[/bold cyan]\n")
                cmd = [sys.executable, "-m", "agent_survey.cli", "dedup", "--scope", scope, *action_args]
                console.print(f"[green]执行: {' '.join(cmd)}[/green]\n")
                result = subprocess.run(cmd)
                if result.returncode != 0:
                    console.print(f"[red]dedup --scope {scope} failed, stopping[/red]")
                    break
                console.print(f"[dim]--- scope {scope} done ---[/dim]\n")
        else:
            cmd = [sys.executable, "-m", "agent_survey.cli", action, *action_args]
            console.print(f"[green]执行: {' '.join(cmd)}[/green]\n")
            subprocess.run(cmd)
    else:
        console.print("[dim]已退出[/dim]")


if __name__ == "__main__":
    run()
