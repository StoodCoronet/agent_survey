"""Rich TUI menu for the Agent Survey pipeline.

Usage:
    survey_agent tui

Controls:
    ↑ / ↓     选择步骤
    Enter     执行选中步骤（支持 workers 的步骤会询问并发数）
    t         切换 / 创建 topic
    q         退出
"""
from __future__ import annotations

import json
import subprocess
import sys

from rich.align import Align
from rich.box import ROUNDED
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .core.config import Config, list_topics, load_config, resolve_topic
from .core.console import console
from .core.db import DB

# ── Anthropic-style palette ──────────────────────────────────────
C_BG = "#0F0F0F"
C_TEXT = "#E8E6E3"
C_DIM = "#9CA3AF"
C_PURPLE = "#A5A0D4"
C_BLUE = "#93C5FD"
C_GREEN = "#86EFAC"
C_YELLOW = "#FDE047"
C_RED = "#FCA5A5"
C_BORDER = "#4A4558"

# Steps that accept --workers
_WORKER_STEPS = {
    "dedup",
    "taxonomy", "deepdive", "fulltext", "short-titles",
    "category-desc", "summary",
}

# Global steps that do NOT accept --topic (they operate on the shared papers table)
_GLOBAL_STEPS = {"harvest", "enrich", "keywords-filter"}

# Survey-mining sub-phases
_SURVEY_MINING_PHASES = [
    ("continue", "▶️  Continue", "自动继续下一个未完成的 phase"),
    ("discover", "🔍 Survey Discovery", "LLM 扫描全库 → 发现 topic 相关 survey"),
    ("download", "📥 Build Download Manifest", "汇总 arxiv_id / PDF URL → 对缺失的用 arxiv/ OpenReview 搜索补全 → 生成 manifest"),
    ("keywords", "🗝️  Keyword Extraction", "从 survey PDF（或 title+abstract）提取关键词组"),
]


# ── input helpers ────────────────────────────────────────────────

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
            return msvcrt.getch().decode("utf-8", errors="ignore")
        except Exception:
            return input().strip().lower()


def _read_line(prompt: str = "") -> str:
    """Read a line in cooked mode."""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
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


def _clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


# ── topic helpers ────────────────────────────────────────────────

def _get_topics(db: DB) -> list[dict]:
    rows = db._conn.execute(
        "SELECT topic_name, display_name, description, is_active FROM topics ORDER BY topic_name"
    ).fetchall()
    return [dict(r) for r in rows]


def _choose_topic(db: DB, cfg: Config) -> str | None:
    """Interactive topic picker. Returns topic_name or None."""
    topics = _get_topics(db)
    topic_names = [t["topic_name"] for t in topics]
    options = [(t["topic_name"], f"{t['topic_name']}" + ("  [active]" if t["is_active"] else "")) for t in topics]
    options.append(("__new__", "+ New Topic"))
    sel = 0

    def _draw():
        _clear_screen()
        console.print("[bold]选择 Topic[/bold]\n")
        for i, (_, label) in enumerate(options):
            prefix = "›" if i == sel else " "
            style = f"bold {C_BLUE} reverse" if i == sel else C_DIM
            console.print(f"  {prefix} {label}", style=style)
        console.print(f"\n[dim]↑↓ 选择  Enter 确认  q 返回[/dim]")

    _draw()
    while True:
        ch = _getch()
        if _is_up(ch):
            sel = (sel - 1) % len(options)
        elif _is_down(ch):
            sel = (sel + 1) % len(options)
        elif _is_enter(ch):
            val = options[sel][0]
            if val == "__new__":
                _clear_screen()
                console.print("[bold]创建新 Topic[/bold]\n")
                name = _read_line("topic name (短横线连接, 如 llm-agent): ")
                if not name:
                    _draw()
                    continue
                if name in topic_names:
                    console.print(f"[yellow]topic '{name}' 已存在[/yellow]")
                    _read_line("按 Enter 继续...")
                    _draw()
                    continue
                console.print(f"[dim]执行: survey_agent topic new {name} ...[/dim]")
                result = subprocess.run(
                    [sys.executable, "-m", "agent_survey.cli", "topic", "new", name],
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    console.print(f"[red]创建失败:[/red]\n{result.stderr}")
                    _read_line("按 Enter 继续...")
                    _draw()
                    continue
                console.print(f"[green]topic '{name}' 创建成功[/green]")
                _read_line("按 Enter 继续...")
                return name
            return val
        elif _is_quit(ch) or ch == "\x03":
            return None
        else:
            continue
        _draw()


# ── scope picker ─────────────────────────────────────────────────

def _choose_scope(st: dict) -> str | None:
    """Interactive scope picker. Returns scope or None."""
    options = [
        ("core", f"core      {st['ft_core']:,} papers"),
        ("related", f"related   {st['ft_related']:,} papers"),
        ("adjacent", f"adjacent  {st['ft_adjacent']:,} papers"),
        ("all", f"all       {st['ft_core'] + st['ft_related'] + st['ft_adjacent']:,} papers"),
    ]
    sel = 0

    def _draw():
        _clear_screen()
        console.print("[bold]选择 scope[/bold]\n")
        for i, (_, label) in enumerate(options):
            prefix = "›" if i == sel else " "
            style = f"bold {C_BLUE} reverse" if i == sel else C_DIM
            console.print(f"  {prefix} {label}", style=style)
        console.print(f"\n[dim]↑↓ 选择  Enter 确认  q 返回[/dim]")

    _draw()
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
        _draw()


# ── status queries ───────────────────────────────────────────────

def _get_status(db: DB, topic_name: str, cfg: Config) -> dict:
    total = db.count()
    with_abstract = db.count("abstract IS NOT NULL AND abstract != ''")

    # prefilter_hit — topic-scoped dict only
    prefilter_hit = 0
    for row in db.iter_papers(
        "prefilter_hit IS NOT NULL AND prefilter_hit != '' AND prefilter_hit != '{}' AND prefilter_hit != '[]'"
    ):
        ph = row.get("prefilter_hit") or "{}"
        try:
            phd = json.loads(ph) if isinstance(ph, str) else ph
        except Exception:
            phd = {}
        if isinstance(phd, dict) and phd.get(topic_name):
            prefilter_hit += 1

    classified = db.count_topic(topic_name, "relevance IS NOT NULL AND relevance != ''")
    core = db.count_topic(topic_name, "relevance = 'core'")
    related = db.count_topic(topic_name, "relevance = 'related'")
    adjacent = db.count_topic(topic_name, "relevance = 'adjacent'")

    # Enrich stats
    if classified > 0:
        need_enrich = db._conn.execute(
            "SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id=p.paper_id "
            "WHERE pt.topic_name=? AND pt.relevance IN ('core','related','adjacent')",
            (topic_name,),
        ).fetchone()[0]
        enriched = db._conn.execute(
            "SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id=p.paper_id "
            "WHERE pt.topic_name=? AND pt.relevance IN ('core','related','adjacent') "
            "AND p.abstract IS NOT NULL AND p.abstract != ''",
            (topic_name,),
        ).fetchone()[0]
    else:
        need_enrich = total
        enriched = with_abstract

    web_enriched = db._conn.execute(
        "SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id=p.paper_id "
        "WHERE pt.topic_name=? AND pt.relevance IN ('core','related','adjacent') AND p.enrich_source='web'",
        (topic_name,),
    ).fetchone()[0]
    need_web = db._conn.execute(
        "SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id=p.paper_id "
        "WHERE pt.topic_name=? AND pt.relevance IN ('core','related','adjacent') "
        "AND (p.abstract IS NULL OR p.abstract = '' OR LENGTH(p.abstract) < 30)",
        (topic_name,),
    ).fetchone()[0]

    # Dedup
    dedup_core = db.count_topic(
        topic_name,
        "relevance = 'core' AND dedup_keep_json IS NOT NULL AND dedup_keep_json LIKE '%\"core\"%'",
    )
    dedup_related = db.count_topic(
        topic_name,
        "relevance = 'related' AND dedup_keep_json IS NOT NULL AND dedup_keep_json LIKE '%\"related\"%'",
    )
    dedup_adjacent = db.count_topic(
        topic_name,
        "relevance = 'adjacent' AND dedup_keep_json IS NOT NULL AND dedup_keep_json LIKE '%\"adjacent\"%'",
    )

    # Taxonomy
    tax_core = db.count_topic(
        topic_name,
        "relevance = 'core' AND taxonomy_json IS NOT NULL AND taxonomy_json != '' AND taxonomy_json != '{}'",
    )
    tax_related = db.count_topic(
        topic_name,
        "relevance = 'related' AND taxonomy_json IS NOT NULL AND taxonomy_json != '' AND taxonomy_json != '{}'",
    )
    tax_adjacent = db.count_topic(
        topic_name,
        "relevance = 'adjacent' AND taxonomy_json IS NOT NULL AND taxonomy_json != '' AND taxonomy_json != '{}'",
    )

    # Fulltext / PDF
    pdf_core = db._conn.execute(
        "SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id=p.paper_id "
        "WHERE pt.topic_name=? AND pt.relevance='core' AND pt.dedup_keep_json LIKE '%\"core\": true%' "
        "AND p.pdf_path IS NOT NULL AND p.pdf_path != ''",
        (topic_name,),
    ).fetchone()[0]
    pdf_related = db._conn.execute(
        "SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id=p.paper_id "
        "WHERE pt.topic_name=? AND pt.relevance='related' AND pt.dedup_keep_json LIKE '%\"related\": true%' "
        "AND p.pdf_path IS NOT NULL AND p.pdf_path != ''",
        (topic_name,),
    ).fetchone()[0]
    pdf_adjacent = db._conn.execute(
        "SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id=p.paper_id "
        "WHERE pt.topic_name=? AND pt.relevance='adjacent' AND pt.dedup_keep_json LIKE '%\"adjacent\": true%' "
        "AND p.pdf_path IS NOT NULL AND p.pdf_path != ''",
        (topic_name,),
    ).fetchone()[0]

    ft_core = db._conn.execute(
        "SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id=p.paper_id "
        "WHERE pt.topic_name=? AND pt.relevance='core' AND pt.dedup_keep_json LIKE '%\"core\": true%' "
        "AND p.arxiv_id IS NOT NULL AND p.arxiv_id != ''",
        (topic_name,),
    ).fetchone()[0]
    ft_related = db._conn.execute(
        "SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id=p.paper_id "
        "WHERE pt.topic_name=? AND pt.relevance='related' AND pt.dedup_keep_json LIKE '%\"related\": true%' "
        "AND p.arxiv_id IS NOT NULL AND p.arxiv_id != ''",
        (topic_name,),
    ).fetchone()[0]
    ft_adjacent = db._conn.execute(
        "SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id=p.paper_id "
        "WHERE pt.topic_name=? AND pt.relevance='adjacent' AND pt.dedup_keep_json LIKE '%\"adjacent\": true%' "
        "AND p.arxiv_id IS NOT NULL AND p.arxiv_id != ''",
        (topic_name,),
    ).fetchone()[0]

    # Citation
    cit_core = db._conn.execute(
        "SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id=p.paper_id "
        "WHERE pt.topic_name=? AND pt.relevance='core' AND p.citation_json IS NOT NULL AND p.citation_json != '' AND p.citation_json != '{}'",
        (topic_name,),
    ).fetchone()[0]
    cit_related = db._conn.execute(
        "SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id=p.paper_id "
        "WHERE pt.topic_name=? AND pt.relevance='related' AND p.citation_json IS NOT NULL AND p.citation_json != '' AND p.citation_json != '{}'",
        (topic_name,),
    ).fetchone()[0]
    cit_adjacent = db._conn.execute(
        "SELECT COUNT(*) FROM paper_topics pt JOIN papers p ON pt.paper_id=p.paper_id "
        "WHERE pt.topic_name=? AND pt.relevance='adjacent' AND p.citation_json IS NOT NULL AND p.citation_json != '' AND p.citation_json != '{}'",
        (topic_name,),
    ).fetchone()[0]

    short_done = db.count_topic(topic_name, "short_title IS NOT NULL AND short_title != ''")
    cat_desc_row = db._conn.execute(
        "SELECT COUNT(*) AS n FROM taxonomy_descriptions WHERE topic_name=? AND (desc_en IS NOT NULL OR desc_zh IS NOT NULL)",
        (topic_name,),
    ).fetchone()
    cat_desc_done = cat_desc_row["n"] if cat_desc_row else 0
    summary_done = db.count_topic(
        topic_name, "relevance = 'core' AND summary_en IS NOT NULL AND summary_en != ''"
    )

    # Survey-mining stats
    survey_count = db._conn.execute(
        "SELECT COUNT(*) FROM paper_topics WHERE topic_name=? AND survey_score IS NOT NULL",
        (topic_name,),
    ).fetchone()[0]
    manifest_path = cfg.abs_topic_dir(topic_name, "json") / "download_manifest.json"
    manifest_exists = manifest_path.exists()
    manifest_with_source = 0
    manifest_missing = 0
    if manifest_exists:
        try:
            mf = json.loads(manifest_path.read_text())
            manifest_with_source = mf.get("with_source", 0)
            manifest_missing = mf.get("missing", 0)
        except Exception:
            pass

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
        "survey_count": survey_count,
        "manifest_exists": manifest_exists,
        "manifest_with_source": manifest_with_source,
        "manifest_missing": manifest_missing,
    }


# ── step status builder ──────────────────────────────────────────

def _step_status(st: dict) -> list[dict]:
    enriched = st["enriched"]
    need = st["need_enrich"]
    total = st["total"]
    enrich_pct = enriched / total * 100 if total > 0 else 0
    if enriched == 0:
        enrich_state, enrich_note = "pending", "未开始"
    elif enriched >= need or enrich_pct >= 97:
        enrich_state, enrich_note = "done", f"已完成 {enrich_pct:.1f}%"
    else:
        enrich_state, enrich_note = "partial", f"进行中 {enrich_pct:.1f}% ({enriched:,})"

    web_enriched = st.get("web_enriched", 0)
    need_web = st.get("need_web", 0)
    if web_enriched == 0:
        web_state, web_note = "pending", "未开始"
    elif need_web == 0:
        web_state, web_note = "done", "已完成"
    else:
        web_state, web_note = "partial", f"进行中 {web_enriched}/{need_web}"

    dedup_core = st.get("dedup_core", 0)
    dedup_related = st.get("dedup_related", 0)
    dedup_adjacent = st.get("dedup_adjacent", 0)
    if dedup_core == 0 and dedup_related == 0 and dedup_adjacent == 0:
        dedup_state, dedup_note = "pending", "未开始"
    elif dedup_core >= st["core"] and dedup_related >= st["related"] and dedup_adjacent >= st["adjacent"]:
        dedup_state, dedup_note = "done", "已完成"
    else:
        dedup_state, dedup_note = "partial", f"c:{dedup_core}/{st['core']} r:{dedup_related}/{st['related']} a:{dedup_adjacent}/{st['adjacent']}"

    pdf_core = st.get("pdf_core", 0)
    pdf_related = st.get("pdf_related", 0)
    pdf_adjacent = st.get("pdf_adjacent", 0)
    if pdf_core + pdf_related + pdf_adjacent == 0:
        fulltext_state, fulltext_note, fulltext_data = "pending", "未开始", "--"
    elif pdf_core >= st["core"] and pdf_related >= st["related"] and pdf_adjacent >= st["adjacent"]:
        fulltext_state, fulltext_note, fulltext_data = "done", "已完成", f"c:{pdf_core},r:{pdf_related},a:{pdf_adjacent}"
    else:
        fulltext_state, fulltext_note, fulltext_data = "partial", f"c:{pdf_core} r:{pdf_related} a:{pdf_adjacent}", f"c:{pdf_core},r:{pdf_related},a:{pdf_adjacent}"

    tax_core = st.get("tax_core", 0)
    tax_related = st.get("tax_related", 0)
    tax_adjacent = st.get("tax_adjacent", 0)
    if tax_core + tax_related + tax_adjacent == 0:
        tax_state, tax_note, tax_data = "pending", "未开始", "--"
    elif tax_core >= st["core"] and tax_related >= st["related"] and tax_adjacent >= st["adjacent"]:
        tax_state, tax_note, tax_data = "done", "已完成", f"c:{tax_core},r:{tax_related},a:{tax_adjacent}"
    else:
        tax_state, tax_note, tax_data = "partial", f"c:{tax_core} r:{tax_related} a:{tax_adjacent}", f"c:{tax_core},r:{tax_related},a:{tax_adjacent}"

    cit_core = st.get("cit_core", 0)
    cit_related = st.get("cit_related", 0)
    cit_adjacent = st.get("cit_adjacent", 0)
    if cit_core + cit_related + cit_adjacent == 0:
        cit_state, cit_note, cit_data = "pending", "未开始", "--"
    elif cit_core >= st["core"] and cit_related >= st["related"] and cit_adjacent >= st["adjacent"]:
        cit_state, cit_note, cit_data = "done", "已完成", f"c:{cit_core},r:{cit_related},a:{cit_adjacent}"
    else:
        cit_state, cit_note, cit_data = "partial", f"c:{cit_core} r:{cit_related} a:{cit_adjacent}", f"c:{cit_core},r:{cit_related},a:{cit_adjacent}"

    short_done = st.get("short_done", 0)
    cat_desc_done = st.get("cat_desc_done", 0)
    summary_done = st.get("summary_done", 0)

    return [
        {"idx": 1,  "name": "harvest",         "state": "done" if st["total"] > 0 else "pending", "data": f"{st['total']:,}" if st["total"] > 0 else "--", "note": "已爬" if st["total"] > 0 else "未开始", "desc": "DBLP 爬取论文列表（venue × year），全局共享"},
        {"idx": 2,  "name": "enrich",          "state": enrich_state, "data": f"{enriched:,}" if enriched > 0 else "--", "note": enrich_note, "desc": "S2/arXiv/ACL/Crossref/Playwright 批量获取 abstract"},
        {"idx": 3,  "name": "survey-mining",   "state": "done" if st["survey_count"] > 0 else "pending", "data": f"{st['survey_count']:,}" if st["survey_count"] > 0 else "--", "note": f"发现 {st['survey_count']:,} 篇" if st["survey_count"] > 0 else "未开始", "desc": "DeepSeek-Flash 扫描全库 → 找 topic 相关 survey → 生成下载清单 → 提取关键词组"},
        {"idx": 4,  "name": "keywords-filter", "state": "done" if st["prefilter_hit"] > 0 else "pending", "data": f"{st['prefilter_hit']:,}" if st["prefilter_hit"] > 0 else "--", "note": "已命中" if st["prefilter_hit"] > 0 else "未开始", "desc": "关键词正则匹配 title+abstract，标记命中状态"},
        {"idx": 5,  "name": "classify",        "state": "done" if st["classified"] > 0 else "pending", "data": f"{st['core']:,}/{st['related']:,}" if st["classified"] > 0 else "--", "note": "已分类" if st["classified"] > 0 else "未开始", "desc": "DeepSeek-Flash 相关性分类 → core / related / adjacent"},
        {"idx": 6,  "name": "taxonomy",        "state": tax_state, "data": tax_data, "note": tax_note, "desc": "按 taxonomy 树给论文打标签"},
        {"idx": 7,  "name": "dedup",           "state": dedup_state, "data": f"c:{dedup_core},r:{dedup_related},a:{dedup_adjacent}" if dedup_core > 0 or dedup_related > 0 or dedup_adjacent > 0 else "--", "note": dedup_note, "desc": "scope 内去重，标记 dedup_keep_json"},
        {"idx": 8,  "name": "fulltext",        "state": fulltext_state, "data": fulltext_data, "note": fulltext_note, "desc": "下载 arXiv PDF（仅 dedup 保留论文）"},
        {"idx": 9,  "name": "citation",        "state": cit_state, "data": cit_data, "note": cit_note, "desc": "PDF 引用提取 → D3 引用图"},
        {"idx": 10, "name": "deepdive",        "state": "pending", "data": "--", "note": "未开始", "desc": "DeepSeek-Pro 结构化深度提取"},
        {"idx": 11, "name": "short-titles",    "state": "done" if short_done > 0 else "pending", "data": f"{short_done:,}" if short_done > 0 else "--", "note": "已完成" if short_done > 0 else "未开始", "desc": "生成短标题（≤40 字符）"},
        {"idx": 12, "name": "summary",         "state": "done" if summary_done >= st.get("core", 0) and st.get("core", 0) > 0 else "pending", "data": f"{summary_done:,}" if summary_done > 0 else "--", "note": "已完成" if summary_done >= st.get("core", 0) and st.get("core", 0) > 0 else "未开始", "desc": "core 论文双语摘要（EN/ZH）"},
        {"idx": 13, "name": "category-desc",   "state": "done" if cat_desc_done > 0 else "pending", "data": f"{cat_desc_done:,}" if cat_desc_done > 0 else "--", "note": "已完成" if cat_desc_done > 0 else "未开始", "desc": "taxonomy 节点双语描述"},
        {"idx": 14, "name": "report",          "state": "pending", "data": "--", "note": "未开始", "desc": "生成 Obsidian + Markdown + JSON 最终输出"},
    ]


# ── render helpers ───────────────────────────────────────────────

def _build_pipeline_table(steps: list[dict], selected: int) -> Table:
    """Build pipeline table with Anthropic-style minimalism."""
    t = Table(show_header=False, box=ROUNDED, border_style=C_BORDER, padding=(0, 1), expand=True)
    t.add_column("", width=3)
    t.add_column("step", width=16)
    t.add_column("data", width=14)
    t.add_column("note", ratio=1)

    for i, s in enumerate(steps):
        is_sel = i == selected
        state = s.get("state", "pending")
        if state == "done":
            icon = "●"
            color = C_GREEN
        elif state == "partial":
            icon = "◐"
            color = C_YELLOW
        elif s["idx"] <= 3:
            icon = "○"
            color = C_RED
        else:
            icon = "·"
            color = C_DIM
        sel_style = f"bold {C_BLUE} reverse" if is_sel else f"{color}"
        t.add_row(
            Text(icon, style=sel_style),
            Text(s["name"], style=sel_style),
            Text(s["data"], style=sel_style),
            Text(s["note"], style=sel_style),
        )
    return t


def _build_stats_table(st: dict) -> Table:
    t = Table(show_header=False, box=ROUNDED, border_style=C_BORDER, padding=(0, 1), expand=True)
    t.add_column("metric", style=C_DIM, width=12)
    t.add_column("value", style=C_TEXT, justify="right")
    coverage = round(st["with_abstract"] / st["total"] * 100, 1) if st["total"] else 0
    t.add_row("Total", f"{st['total']:,}")
    t.add_row("Abstract", f"{st['with_abstract']:,}  ({coverage}%)")
    t.add_row("Keywords Filter", f"{st['prefilter_hit']:,}")
    t.add_row("Core", Text(f"{st['core']:,}", style=C_GREEN))
    t.add_row("Related", Text(f"{st['related']:,}", style=C_YELLOW))
    t.add_row("Adjacent", Text(f"{st['adjacent']:,}", style=C_DIM))
    t.add_row("Classified", f"{st['classified']:,}")
    return t


def _recommend(steps: list[dict]) -> str | None:
    for s in steps:
        if s.get("state", "pending") != "done":
            return s["name"]
    return None


def _multi_select(options: list[tuple[str, str]], title: str = "选择") -> dict[str, bool] | None:
    """Interactive multi-select menu. Space toggles, Enter confirms, q cancels.

    Args:
        options: list of (key, label) tuples.
        title: menu title.

    Returns:
        dict mapping key -> bool (selected), or None if cancelled.
    """
    sel = 0
    state = {key: True for key, _ in options}

    def _draw():
        _clear_screen()
        console.print(f"[bold]{title}[/bold]\n")
        for i, (key, label) in enumerate(options):
            mark = "✓" if state[key] else " "
            prefix = "›" if i == sel else " "
            style = f"bold {C_BLUE}" if i == sel else C_TEXT
            console.print(f"  {prefix} [{mark}] {label}", style=style, markup=False)
        console.print(f"\n[dim]↑↓ 移动  Space 切换  Enter 确认  q 取消[/dim]")

    _draw()
    while True:
        ch = _getch()
        if _is_up(ch):
            sel = (sel - 1) % len(options)
        elif _is_down(ch):
            sel = (sel + 1) % len(options)
        elif ch == " ":
            key = options[sel][0]
            state[key] = not state[key]
        elif _is_enter(ch):
            return dict(state)
        elif _is_quit(ch) or ch == "\x03":
            return None
        else:
            continue
        _draw()


# ── main loop ────────────────────────────────────────────────────

def run():
    cfg = load_config()
    db = DB(cfg.abs_path("db"))

    # Always start with topic selection
    chosen = _choose_topic(db, cfg)
    if chosen is None:
        console.print("[dim]已退出[/dim]")
        db.close()
        return
    topic_name = chosen
    # Persist chosen topic so next TUI session starts here
    if cfg.active_topic != topic_name:
        import re
        base_config = cfg.project_root / "config" / "base.yaml"
        if base_config.exists():
            content = base_config.read_text()
            content = re.sub(
                r"^active_topic:.*$", f"active_topic: {topic_name}", content, flags=re.MULTILINE
            )
            base_config.write_text(content)
        else:
            # Fallback to legacy single config.yaml
            config_path = cfg.project_root / "config.yaml"
            if config_path.exists():
                content = config_path.read_text()
                content = re.sub(
                    r"^active_topic:.*$", f"active_topic: {topic_name}", content, flags=re.MULTILINE
                )
                config_path.write_text(content)
    cfg = load_config()  # reload after potential topic new/use

    while True:  # reload after potential topic new

        try:
            st = _get_status(db, topic_name, cfg)
        except Exception as e:
            console.print(f"[red]查询失败: {e}[/red]")
            db.close()
            return

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
            # Header
            header_text = Text()
            header_text.append("survey_agent", style=f"bold {C_PURPLE}")
            header_text.append("  —  ", style=C_DIM)
            header_text.append(topic_name, style=f"bold {C_TEXT}")
            if rec:
                header_text.append(f"  │  recommend: ", style=C_DIM)
                header_text.append(rec, style=f"bold {C_BLUE}")
            header = Panel(Align.left(header_text), box=ROUNDED, border_style=C_PURPLE, padding=(0, 1))

            # Pipeline panel
            pipeline = Panel(
                _build_pipeline_table(steps, selected),
                title=f"[bold {C_TEXT}]Pipeline[/bold {C_TEXT}]",
                title_align="left",
                box=ROUNDED,
                border_style=C_BORDER,
                padding=(0, 1),
            )

            # Stats panel
            stats = Panel(
                _build_stats_table(st),
                title=f"[bold {C_TEXT}]Overview[/bold {C_TEXT}]",
                title_align="left",
                box=ROUNDED,
                border_style=C_BORDER,
                padding=(0, 1),
            )

            # Footer controls
            controls = Text()
            controls.append("↑↓ select  ", style=C_DIM)
            controls.append("Enter run  ", style=C_DIM)
            controls.append("t topic  ", style=C_DIM)
            controls.append("q quit", style=C_DIM)

            # Selected step description
            desc_text = Text()
            desc_text.append(f"{steps[selected]['name']}: ", style=f"bold {C_TEXT}")
            desc_text.append(steps[selected].get("desc", ""), style=C_DIM)
            desc_panel = Panel(desc_text, box=ROUNDED, border_style=C_BORDER, padding=(0, 1))

            console.print(Group(header, pipeline, stats, controls, desc_panel))

        _draw()

        while running:
            ch = _getch()
            if _is_up(ch):
                selected = (selected - 1) % len(steps)
            elif _is_down(ch):
                selected = (selected + 1) % len(steps)
            elif ch.lower() == "t":
                chosen = _choose_topic(db, cfg)
                if chosen is not None and chosen != topic_name:
                    topic_name = chosen
                    cfg = load_config()
                _draw()  # redraw after potential switch
                continue
            elif _is_enter(ch):
                action = steps[selected]["name"]
                action_args: list[str] = []
                if action == "survey-mining":
                    # Sub-menu for survey-mining phases
                    _clear_screen()
                    console.print(f"[bold {C_PURPLE}]Survey Mining[/bold {C_PURPLE}]\n")
                    sm_options = [(p[0], f"{p[1]}  —  {p[2]}") for p in _SURVEY_MINING_PHASES]
                    sm_sel = 0
                    # Phase status checks
                    survey_count = db._conn.execute(
                        "SELECT COUNT(*) FROM paper_topics WHERE topic_name=? AND survey_score IS NOT NULL",
                        (topic_name,),
                    ).fetchone()[0]
                    manifest_path = cfg.abs_topic_dir(topic_name, "json") / "download_manifest.json"
                    manifest_done = manifest_path.exists()
                    sm_statuses = {
                        "discover": "done" if survey_count > 0 else "pending",
                        "download": "done" if manifest_done else "pending",
                        "keywords": "pending",
                    }

                    def _draw_sm():
                        _clear_screen()
                        console.print(f"[bold {C_PURPLE}]Survey Mining — 选择 Phase[/bold {C_PURPLE}]\n")
                        for i, (key, label) in enumerate(sm_options):
                            is_sel = i == sm_sel
                            status = sm_statuses.get(key, "pending")
                            if status == "done":
                                icon = "●"
                                base_color = C_GREEN
                            else:
                                icon = "○"
                                base_color = C_DIM
                            prefix = "›" if is_sel else " "
                            if is_sel:
                                style = f"bold {C_BLUE} reverse"
                            else:
                                style = base_color
                            console.print(f"  {prefix} {icon} {label}", style=style)
                        console.print(f"\n[dim]↑↓ 选择  Enter 确认  q 返回[/dim]")
                    _draw_sm()
                    sm_running = True
                    sm_phase = None
                    while sm_running:
                        ch2 = _getch()
                        if _is_up(ch2):
                            sm_sel = (sm_sel - 1) % len(sm_options)
                        elif _is_down(ch2):
                            sm_sel = (sm_sel + 1) % len(sm_options)
                        elif _is_enter(ch2):
                            sm_phase = sm_options[sm_sel][0]
                            sm_running = False
                        elif _is_quit(ch2) or ch2 == "\x03":
                            sm_running = False
                        else:
                            continue
                        _draw_sm()
                    # Handle "continue" — auto-pick next pending phase
                    if sm_phase == "continue":
                        next_phase = None
                        for key, _, _ in _SURVEY_MINING_PHASES:
                            if key == "continue":
                                continue
                            if sm_statuses.get(key, "pending") != "done":
                                next_phase = key
                                break
                        if next_phase:
                            sm_phase = next_phase
                            console.print(f"[dim]Continue → {sm_phase}[/dim]")
                        else:
                            _clear_screen()
                            console.print("[yellow]All survey-mining phases are done.[/yellow]")
                            force = _read_line("Force re-run discover from scratch? (y/N): ").strip().lower()
                            if force in ("y", "yes"):
                                sm_phase = "discover"
                                action_args.append("--force")
                            else:
                                sm_phase = None
                    if not sm_phase:
                        action = None
                        action_args = []
                        _draw()
                        continue
                    action_args = ["--phase", sm_phase]
                    # Check for existing survey records when re-running discover
                    if sm_phase == "discover":
                        existing = db._conn.execute(
                            "SELECT COUNT(*) FROM paper_topics WHERE topic_name=? AND survey_score IS NOT NULL",
                            (topic_name,),
                        ).fetchone()[0]
                        if existing > 0 and "--force" not in action_args:
                            _clear_screen()
                            console.print(f"[yellow]Phase 1 already done ({existing} surveys in DB).[/yellow]")
                            force = _read_line("Force re-run and clear prior records? (y/N): ").strip().lower()
                            if force in ("y", "yes"):
                                action_args.append("--force")
                    running = False
                    continue
                if action == "harvest":
                    _clear_screen()
                    console.print(f"[bold {C_PURPLE}]执行步骤: {action}[/bold {C_PURPLE}]\n")
                    force = _read_line("强制重新爬所有 venue (y/N): ").strip().lower()
                    if force in ("y", "yes"):
                        action_args.append("--force")
                elif action == "enrich":
                    _clear_screen()
                    console.print(f"[bold {C_PURPLE}]执行步骤: {action}[/bold {C_PURPLE}]\n")
                    console.print(f"[dim]并发策略: config/stages/enrich.yaml[/dim]\n")
                    patch = _read_line("patch 模式 (修复异常 abstract, y/N): ").strip().lower()
                    if patch in ("y", "yes"):
                        action_args.append("--patch")
                    limit_val = _read_line("限制处理数量 (直接回车跑全量): ").strip()
                    if limit_val.isdigit():
                        action_args.extend(["--limit", limit_val])
                elif action in _WORKER_STEPS:
                    _clear_screen()
                    console.print(f"[bold {C_PURPLE}]执行步骤: {action}[/bold {C_PURPLE}]\n")
                    action_args = []
                    if action == "taxonomy":
                        rel_options = [
                            ("core", f"core      {st['core']:,} papers"),
                            ("related", f"related   {st['related']:,} papers"),
                            ("adjacent", f"adjacent  {st['adjacent']:,} papers"),
                        ]
                        rel_selected = _multi_select(rel_options, title="选择 relevance levels")
                        if rel_selected is None:
                            _draw()
                            continue
                        selected_levels = [k for k, v in rel_selected.items() if v]
                        if selected_levels:
                            action_args.extend(["--relevance", ",".join(selected_levels)])
                    elif action == "fulltext":
                        scope = _choose_scope(st)
                        if scope is None:
                            _draw()
                            continue
                        if scope:
                            action_args.extend(["--scope", scope])
                    elif action == "citation":
                        scope = _choose_scope(st)
                        if scope is None:
                            _draw()
                            continue
                        action_args = []
                        if scope:
                            action_args.extend(["--scope", scope])
                    elif action == "short-titles":
                        scope = _choose_scope(st)
                        if scope is None:
                            _draw()
                            continue
                        if scope:
                            action_args.extend(["--scope", scope])
                        use_pdf = _read_line("参考 PDF (Y/n): ").strip().lower()
                        if use_pdf in ("n", "no"):
                            action_args.append("--no-pdf")
                        force = _read_line("强制重新生成 (y/N): ").strip().lower()
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
            _clear_screen()
            if action == "dedup":
                for scope in ("core", "related", "adjacent"):
                    _clear_screen()
                    console.print(f"[bold {C_PURPLE}]执行步骤: dedup --scope {scope}[/bold {C_PURPLE}]\n")
                    cmd = [
                        sys.executable, "-m", "agent_survey.cli",
                        "dedup", "--scope", scope, "--topic", topic_name, *action_args,
                    ]
                    console.print(f"[dim]{' '.join(cmd)}[/dim]\n")
                    result = subprocess.run(cmd)
                    if result.returncode != 0:
                        console.print(f"[red]dedup --scope {scope} failed[/red]")
                        break
                    console.print(f"[dim]--- scope {scope} done ---[/dim]\n")
            else:
                # global steps operate on the shared papers table, no --topic
                if action in _GLOBAL_STEPS:
                    cmd = [
                        sys.executable, "-m", "agent_survey.cli",
                        action, *action_args,
                    ]
                else:
                    cmd = [
                        sys.executable, "-m", "agent_survey.cli",
                        action, "--topic", topic_name, *action_args,
                    ]
                console.print(f"[dim]{' '.join(cmd)}[/dim]\n")
                subprocess.run(cmd)
        else:
            console.print("[dim]已退出[/dim]")
            db.close()
            return

        # After action completes, refresh stats (user can continue in TUI)
        _read_line("\n按 Enter 返回 TUI...")
        cfg = load_config()
        db.close()
        db = DB(cfg.abs_path("db"))
        topic_name = resolve_topic(None, cfg)


if __name__ == "__main__":
    run()
