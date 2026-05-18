"""CLI for agent-survey."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

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
    workers: int = typer.Option(2, "--workers", "-w", help="concurrent Playwright workers"),
):
    """Stage 1b: fetch abstracts for failed papers via Playwright + Google Scholar."""
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
):
    """Stage 4: download arXiv PDFs for classified papers."""
    cfg = load_config()
    s_fulltext.run(cfg, force=force, limit=limit or None)


@app.command()
@_with_logfile("deepdive")
def deepdive(
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
):
    """Stage 5: LLM (Pro) structured extraction on PDF body."""
    cfg = load_config()
    s_deepdive.run(cfg, force=force, limit=limit or None)


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
