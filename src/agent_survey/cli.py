"""CLI for agent-survey."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import sys

import typer

from .analysis import abstract_coverage as s_abstract_coverage
from .analysis import estimate_cost as s_estimate_cost
from .analysis import keyword_stats as s_keyword_stats
from .analysis.stats import print_overview
from .core.config import load_config
from .core.console import console, save_log
from .core.db import DB
from .report import markdown as r_md
from .report import obsidian as r_obs
from .stages import s00_harvest as s_harvest
from .stages import s00b_search_recall as s_recall
from .stages import s01_enrich as s_enrich
from .stages import s01_enrich_web as s_enrich_web
from .stages import s02_prefilter as s_prefilter
from .stages import s03_classify as s_classify
from .stages import s04_fulltext as s_fulltext
from .stages import s05_deepdive as s_deepdive
from .stages import s06_topics as s_topics
from .stages import s06b_subtopic_dedup as s_dedup
from .stages import s07_taxonomy as s_taxonomy
from .stages import s08_citation as s_citation
from .stages import s09_short_titles as s_short_titles
from .stages import s10_category_desc as s_category_desc
from .stages import s11_summary as s_summary
from .tui import run as run_tui

app = typer.Typer(help="Agent Survey — crawl + classify AI agent papers from SE/Security/AI venues")


def _with_logfile(cmd_name: str):
    """Decorator: dump the recorded Rich transcript to output/logs/{cmd}_{ts}.log
    after the command finishes (success or failure).
    """

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            finally:
                cfg = load_config()
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                logs_dir = cfg.project_root / "output" / "logs"
                log_path = logs_dir / f"{cmd_name}_{ts}.log"
                try:
                    save_log(log_path, clear=False)
                    console.print(f"[dim]log saved to {log_path}[/dim]")
                except Exception as e:
                    console.print(f"[red]failed to save log: {e}[/red]")

        return wrapper

    return deco


@app.command()
@_with_logfile("harvest")
def harvest(
    force: bool = False,
    workers: int = typer.Option(
        0,
        "--workers",
        "-w",
        help="parallel DBLP fetchers; 0 = use config.network.max_concurrency (default 4)",
    ),
):
    """Stage 0: pull DBLP listings for every (venue, year)."""
    cfg = load_config()
    s_harvest.run(cfg, force=force, workers=workers or None)


@app.command("search-recall")
@_with_logfile("search_recall")
def search_recall(
    per_query: int = 200,
    no_arxiv: bool = typer.Option(False, "--no-arxiv"),
):
    """Search-recall branch: S2/arXiv query search, match back to DBLP rows."""
    cfg = load_config()
    s_recall.run(cfg, per_query=per_query, enable_arxiv=not no_arxiv)


@app.command()
@_with_logfile("enrich")
def enrich(
    force: bool = False,
    patch: bool = typer.Option(False, "--patch", help="re-enrich papers with suspiciously short abstracts"),
    limit: int = typer.Option(0, help="0 = no limit"),
    all_papers: bool = typer.Option(False, "--all", help="also enrich irrelevant papers"),
    workers: int = typer.Option(5, "--workers", "-w", help="concurrent enrichment workers"),
):
    """Stage 1: fetch abstracts via arXiv → S2 → OpenReview fallback."""
    cfg = load_config()
    s_enrich.run(cfg, force=force, patch=patch, limit=limit or None, all_papers=all_papers, workers=workers)


@app.command("enrich-web")
@_with_logfile("enrich_web")
def enrich_web(
    limit: int = typer.Option(0, help="0 = no limit"),
    workers: int = typer.Option(1, "--workers", "-w", help="concurrent Playwright workers (arXiv crawl-delay=3s)"),
):
    """Stage 1b: fetch abstracts for failed papers via Playwright + arXiv."""
    cfg = load_config()
    s_enrich_web.run(cfg, limit=limit or None, workers=workers)


@app.command()
@_with_logfile("prefilter")
def prefilter():
    """Stage 2: keyword regex filter over title+abstract."""
    cfg = load_config()
    s_prefilter.run(cfg)


@app.command()
@_with_logfile("classify")
def classify(
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
    prefilter_only: bool = typer.Option(False, "--prefilter-only", help="only classify prefilter hits (cheaper, ~$0.2)"),
    batch_size: int = typer.Option(10, "--batch-size", help="papers per LLM call"),
    workers: int = typer.Option(2, "--workers", "-w", help="parallel API workers"),
):
    """Stage 3: LLM (Flash) venue-aware batch classify.

    Two strategies:
    - default (full): classify EVERY paper (slower, ~$6-7, but most thorough)
    - --prefilter-only: only classify keyword hits (faster, ~$0.2)
    """
    cfg = load_config()
    s_classify.run(
        cfg,
        only_prefilter_hits=prefilter_only,
        force=force,
        limit=limit or None,
        batch_size=batch_size,
        workers=workers,
    )


@app.command("abstract-coverage")
@_with_logfile("abstract_coverage")
def abstract_coverage():
    """Show abstract coverage (good / bad / missing) by venue."""
    cfg = load_config()
    s_abstract_coverage.run(cfg)


@app.command("keyword-stats")
@_with_logfile("keyword_stats")
def keyword_stats():
    """Analyze keyword hit statistics across all papers."""
    cfg = load_config()
    s_keyword_stats.run(cfg)


@app.command("enrich-arxiv")
@_with_logfile("enrich_arxiv")
def enrich_arxiv(
    workers: int = typer.Option(5, "--workers", "-w", help="concurrent enrichment workers"),
):
    """Backfill abstracts for SE/Security core venues (deprecated, use `enrich`)."""
    cfg = load_config()
    s_enrich.run_arxiv(cfg, workers=workers)


@app.command("estimate-cost")
@_with_logfile("estimate_cost")
def estimate_cost():
    """Estimate DeepSeek API cost for venue-aware classification."""
    cfg = load_config()
    s_estimate_cost.run(cfg)


@app.command()
@_with_logfile("fulltext")
def fulltext(
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
    scope: str = typer.Option("", "--scope", help="core | related | adjacent (empty = all classified)"),
    workers: int = typer.Option(1, "--workers", "-w", help="concurrent download workers"),
):
    """Stage 4: download arXiv PDFs for classified papers."""
    cfg = load_config()
    s_fulltext.run(cfg, force=force, limit=limit or None, scope=scope or None, workers=workers)


@app.command()
@_with_logfile("deepdive")
def deepdive(
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
):
    """Stage 5: LLM (Pro) structured extraction on PDF body."""
    cfg = load_config()
    s_deepdive.run(cfg, force=force, limit=limit or None)


@app.command("classify-topics")
@_with_logfile("topic_classify")
def classify_topics(
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
    batch_size: int = typer.Option(10, "--batch-size", help="papers per LLM call"),
    workers: int = typer.Option(2, "--workers", "-w", help="parallel API workers"),
    auto_create: float = typer.Option(0.8, "--auto-create", help="confidence threshold for auto-creating new topics"),
):
    """Stage 6: incremental multi-label topic classification.

    Focus: agent testing, agent security, dataset/benchmark generation.
    Auto-creates new topics when confidence >= threshold.
    """
    cfg = load_config()
    s_topics.run(
        cfg,
        force=force,
        limit=limit or None,
        batch_size=batch_size,
        workers=workers,
        auto_create_threshold=auto_create,
    )


@app.command("dedup")
@_with_logfile("subtopic_dedup")
def dedup(
    scope: str = typer.Option("core", "--scope", help="core | related | adjacent"),
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
    batch_size: int = typer.Option(20, "--batch-size", help="papers per LLM call"),
    workers: int = typer.Option(2, "--workers", "-w", help="parallel API workers"),
    dry_run: bool = typer.Option(False, "--dry-run", help="only run Stage A (sub-topic discovery), skip dedup"),
):
    """Stage 6b: sub-topic discovery + dedup before deepdive.

    Three independent scopes, each with different dedup strictness:
      - core     : most conservative (only remove near-identical follow-ups)
      - related  : moderate (remove clear duplicates and minor extensions)
      - adjacent : most aggressive (remove incremental work even on different datasets)

    Run all three to compare and decide PDF download priority.
    """
    cfg = load_config()
    s_dedup.run(
        cfg,
        scope=scope,
        force=force,
        limit=limit or None,
        batch_size=batch_size,
        workers=workers,
        dry_run=dry_run,
    )


@app.command("taxonomy")
@_with_logfile("taxonomy_classify")
def taxonomy(
    scope: str = typer.Option("core", "--scope", help="core | related | adjacent"),
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
    batch_size: int = typer.Option(10, "--batch-size", help="papers per LLM call"),
    workers: int = typer.Option(2, "--workers", "-w", help="parallel API workers"),
):
    """Stage 7: multi-dimensional taxonomy classification.

    Maps papers to 3 independent trees:
      1. application-domain  — where the agent operates
      2. technical-approach  — core technique
      3. research-goal       — what the paper studies

    Plus cross-cutting tags (performance, testing, attack, defense, benchmark).
    """
    cfg = load_config()
    s_taxonomy.run(
        cfg,
        scope=scope,
        force=force,
        limit=limit or None,
        batch_size=batch_size,
        workers=workers,
    )


@app.command()
@_with_logfile("citation")
def citation(
    scope: str = typer.Option("core", "--scope", help="core | related | adjacent"),
    force: bool = False,
):
    """Stage 8: extract citations from PDFs and build citation graph.

    Generates docs/citation_graph.html (interactive D3.js force-directed graph).
    """
    cfg = load_config()
    s_citation.run(cfg, scope=scope, force=force)


@app.command("short-titles")
@_with_logfile("short_titles")
def short_titles(
    force: bool = False,
    scope: str = typer.Option("core", "--scope", help="core | related | adjacent | all (classified)"),
    batch_size: int = typer.Option(20, "--batch-size", help="titles per LLM call"),
    workers: int = typer.Option(5, "--workers", "-w", help="parallel LLM workers"),
    use_pdf: bool = typer.Option(True, "--use-pdf/--no-pdf", help="read PDF excerpts for better abbreviations"),
):
    """Generate abbreviated short titles for long paper titles via DeepSeek."""
    cfg = load_config()
    s_short_titles.run(cfg, force=force, scope=scope, batch_size=batch_size, workers=workers, use_pdf=use_pdf)


@app.command("category-desc")
@_with_logfile("category_desc")
def category_desc(
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
    workers: int = typer.Option(3, "--workers", "-w", help="parallel LLM workers"),
):
    """Stage 10: generate bilingual descriptions for taxonomy categories via DeepSeek."""
    cfg = load_config()
    s_category_desc.run(cfg, force=force, limit=limit or None, workers=workers)


@app.command("summary")
@_with_logfile("summary")
def summary(
    force: bool = False,
    workers: int = typer.Option(20, "--workers", "-w", help="parallel LLM workers"),
):
    """Stage 11: generate 3-4 sentence bilingual summaries for every paper via DeepSeek Flash."""
    cfg = load_config()
    s_summary.run(cfg, force=force, workers=workers)


@app.command("generate-docs")
@_with_logfile("generate_docs")
def generate_docs():
    """Generate static docs/ site from DB data."""
    import subprocess
    cfg = load_config()
    script = cfg.project_root / "scripts" / "generate_docs.py"
    subprocess.run([sys.executable, str(script)], check=True)


@app.command()
@_with_logfile("report")
def report():
    """Generate Obsidian vault + JSON + Markdown survey."""
    cfg = load_config()
    r_md.export_json(cfg)
    r_md.render_survey_markdown(cfg)
    r_obs.write_vault(cfg)


@app.command()
@_with_logfile("tui")
def tui():
    """Launch interactive TUI menu."""
    run_tui()


@app.command()
@_with_logfile("stats")
def stats():
    """Print the current DB overview."""
    cfg = load_config()
    db = DB(cfg.abs_path("db"))
    try:
        print_overview(db, "DB overview")
    finally:
        db.close()


if __name__ == "__main__":
    app()
