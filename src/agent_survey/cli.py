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
from .core.config import (
    load_config,
    load_topic_config,
    list_topics,
    resolve_topic,
)
from .core.console import console, save_log
from .core.db import DB
from .report import markdown as r_md
from .report import obsidian as r_obs
from .stages import s01_harvest as s_harvest
from .stages import s02_enrich as s_enrich
from .stages.s02_enrich import run_web as s_enrich_web
from .stages import s03_survey_mining as s_survey_mining
from .stages import s04_keywords_filter as s_keywords_filter
from .stages import s05_classify as s_classify
from .stages import s06_taxonomy as s_taxonomy
from .stages import s07_dedup as s_dedup
from .stages import s08_fulltext as s_fulltext
from .stages import s09_citation as s_citation
from .stages import s10_deepdive as s_deepdive
from .stages import s11_short_titles as s_short_titles
from .stages import s12_summary as s_summary
from .stages import s13_category_desc as s_category_desc
from .tui import run as run_tui

app = typer.Typer(help="Agent Survey — crawl + classify AI agent papers from SE/Security/AI venues")

topic_app = typer.Typer(help="Manage survey topics")
app.add_typer(topic_app, name="topic")


def _topic_option(help_text: str = "Topic name (default: active topic from config)"):
    """Reusable --topic option for pipeline commands."""
    return typer.Option(None, "--topic", "-t", help=help_text)


@topic_app.command("list")
def topic_list():
    """List available survey topics."""
    topics = list_topics()
    if not topics:
        console.print("[yellow]No topics found. Create one with `topic new <name>`.[/yellow]")
        return
    cfg = load_config()
    active = cfg.active_topic
    for t in topics:
        tc = load_topic_config(t)
        marker = " [green](active)[/green]" if t == active else ""
        print(f"  {t}{marker} — {tc.name}")


@topic_app.command("show")
def topic_show(
    name: str = typer.Argument(None, help="Topic name (default: active)"),
):
    """Show topic configuration overview."""
    cfg = load_config()
    name = name or cfg.active_topic
    if not name:
        console.print("[red]No topic specified and no active_topic in config.[/red]")
        raise typer.Exit(1)
    tc = load_topic_config(name)
    console.print(f"[bold]Topic: {name}[/bold]")
    console.print(f"  Name: {tc.name}")
    console.print(f"  Description: {tc.description}")
    console.print(f"  Keywords (agent_core): {len(tc.keywords.agent_core)} patterns")
    console.print(f"  Keywords (agent_generic): {len(tc.keywords.agent_generic)} patterns")
    console.print(f"  Keywords (se_context): {len(tc.keywords.se_context)} patterns")
    console.print(f"  Keywords (sec_context): {len(tc.keywords.sec_context)} patterns")
    console.print(f"  Search queries: {len(tc.search_queries)} queries")
    console.print(f"  Domain labels: {tc.classify.domain_labels}")
    console.print(f"  Method labels: {tc.classify.method_labels}")
    console.print(f"  Relevance levels: {tc.classify.relevance_levels}")
    console.print(f"  Taxonomy trees: {list(tc.taxonomy.trees.keys())}")
    console.print(f"  Flat labels: {len(tc.taxonomy.flat_labels)}")


@topic_app.command("use")
def topic_use(
    name: str = typer.Argument(..., help="Topic name to set as active"),
):
    """Set the active topic in config.yaml."""
    cfg = load_config()
    try:
        load_topic_config(name)
    except FileNotFoundError:
        console.print(f"[red]Topic '{name}' not found in topics/.[/red]")
        raise typer.Exit(1)
    # Update config/base.yaml (config dir merge mode)
    import re
    base_config = cfg.project_root / "config" / "base.yaml"
    if base_config.exists():
        content = base_config.read_text()
        content = re.sub(r"^active_topic:.*$", f"active_topic: {name}", content, flags=re.MULTILINE)
        base_config.write_text(content)
    else:
        # Fallback to legacy single config.yaml
        config_path = cfg.project_root / "config.yaml"
        if config_path.exists():
            content = config_path.read_text()
            content = re.sub(r"^active_topic:.*$", f"active_topic: {name}", content, flags=re.MULTILINE)
            config_path.write_text(content)
    # Also update DB
    db = DB(cfg.abs_path("db"))
    try:
        db.register_topic(name, load_topic_config(name).name, load_topic_config(name).description)
        db.set_active_topic(name)
    finally:
        db.close()
    console.print(f"[green]Active topic set to '{name}'.[/green]")


@topic_app.command("new")
def topic_new(
    name: str = typer.Argument(..., help="Topic name (kebab-case, e.g. 'fuzzing')"),
    display: str = typer.Option("", "--display", "-d", help="Display name"),
    description: str = typer.Option("", "--desc", help="Description"),
    copy_from: str = typer.Option("", "--copy-from", "-c", help="Copy config from existing topic"),
):
    """Create a new topic scaffold."""
    import shutil

    cfg = load_config()
    topics_dir = cfg.project_root / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)

    target = topics_dir / f"{name}.yaml"
    if target.exists():
        console.print(f"[red]Topic '{name}' already exists at {target}[/red]")
        raise typer.Exit(1)

    if copy_from:
        source = topics_dir / f"{copy_from}.yaml"
        if not source.exists():
            console.print(f"[red]Source topic '{copy_from}' not found.[/red]")
            raise typer.Exit(1)
        shutil.copy(str(source), str(target))
        console.print(f"[green]Copied '{copy_from}' → '{name}'.[/green]")
        console.print(f"[dim]Edit {target} to customize keywords, prompts, and taxonomy.[/dim]")
    else:
        # Scaffold from built-in template
        template = f"""# =============================================================================
# Topic: {display or name}
# {description or 'Custom survey topic'}
# =============================================================================

name: "{display or name}"
description: "{description or 'Custom survey topic'}"

keywords:
  agent_core:
    - "example keyword"
  agent_generic: []
  se_context: []
  sec_context: []

search_queries:
  - "example query"

classify:
  relevance_levels:
    - core
    - related
    - adjacent
    - irrelevant
  domain_labels:
    - "Example Domain"
  method_labels:
    - "Benchmark/Dataset"
    - "Framework/System"
    - "Empirical Study"
  core_venues:
    - ICSE
    - FSE
    - ASE
    - ISSTA
  system_prompt: |
    You are a meticulous research assistant helping survey papers.
    You must respond with a strict JSON object only.
  user_prompt_template: |
    Label this paper:
    - Title: {{title}}
    - Abstract: {{abstract}}
    Return JSON with relevance, domain_primary, method_tags, tldr, rationale.
  user_prompt_title_only: |
    Label this paper (title only):
    - Title: {{title}}
    Return JSON with relevance, domain_primary, method_tags, tldr, rationale.
  batch_user_prompt_template: |
    Label {{count}} papers. Return JSON array with exactly {{count}} objects.

deepdive:
  system_prompt: |
    You are a careful research assistant extracting structured information.
    Return strict JSON only.
  user_prompt_template: |
    Analyze this paper:
    Title: {{title}}
    ---
    {{body}}
    ---
    Extract JSON with: problem, approach, evaluation, datasets, key_results.

taxonomy:
  system_prompt: |
    You are an expert research taxonomist.
  trees:
    application-domain:
      example-category: []
    technical-approach:
      example-approach: []
    research-goal:
      example-goal: []
  cross_cutting_tags: []
  flat_labels: {{}}
  auto_create_leaves: true
  auto_create_threshold: 0.8
  user_prompt_template: |
    Classify {{count}} papers using the taxonomy above. Return strict JSON.
"""
        target.write_text(template, encoding="utf-8")
        console.print(f"[green]Created topic scaffold at {target}[/green]")
        console.print(f"[dim]Edit {target} to customize keywords, prompts, and taxonomy.[/dim]")

    # Register in DB
    db = DB(cfg.abs_path("db"))
    try:
        db.register_topic(name, display or name, description or "")
    finally:
        db.close()

    console.print(f"[green]Topic '{name}' registered.[/green]")
    console.print(f"[yellow]Tip: Run `survey_agent topic use {name}` to set as active.[/yellow]")


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
    fetch_abstracts: bool = typer.Option(
        False,
        "--fetch-abstracts / --no-fetch-abstracts",
        "-a",
        help="also fetch abstracts from OpenReview and publisher sites after harvest",
    ),
    openreview: bool = typer.Option(
        True,
        "--openreview / --no-openreview",
        help="fetch OpenReview abstracts (default: True)",
    ),
    publisher: bool = typer.Option(
        True,
        "--publisher / --no-publisher",
        help="fetch publisher DOI abstracts (default: True)",
    ),
):
    """Stage 0: pull DBLP listings for every (venue, year)."""
    cfg = load_config()
    s_harvest.run(
        cfg,
        force=force,
        fetch_abstracts=fetch_abstracts,
        openreview=openreview,
        publisher=publisher,
    )


@app.command("search-recall")
@_with_logfile("search_recall")
def search_recall(
    per_query: int = 200,
    no_arxiv: bool = typer.Option(False, "--no-arxiv"),
    topic: str = _topic_option(),
):
    """Search-recall branch: S2/arXiv query search, match back to DBLP rows."""
    cfg = load_config()
    s_recall.run(cfg, per_query=per_query, enable_arxiv=not no_arxiv, topic_name=topic)


@app.command()
@_with_logfile("enrich")
def enrich(
    force: bool = False,
    patch: bool = typer.Option(False, "--patch", help="re-enrich papers with suspiciously short abstracts"),
    limit: int = typer.Option(0, help="0 = no limit"),
    classified_only: bool = typer.Option(False, "--classified-only", help="only enrich papers classified as core/related/adjacent"),
    topic: str = _topic_option(),
):
    """Stage 1: fetch abstracts via S2 → arXiv → OpenReview → venue-specific scrapers."""
    cfg = load_config()
    s_enrich.run(cfg, force=force, patch=patch, limit=limit or None, all_papers=not classified_only, topic_name=topic)


@app.command("enrich-web")
@_with_logfile("enrich_web")
def enrich_web(
    limit: int = typer.Option(0, help="0 = no limit"),
    workers: int = typer.Option(1, "--workers", "-w", help="concurrent Playwright workers (arXiv crawl-delay=3s)"),
    topic: str = _topic_option(),
):
    """Stage 1b: fetch abstracts for failed papers via Playwright + arXiv."""
    cfg = load_config()
    s_enrich_web(cfg, limit=limit or None, workers=workers, topic_name=topic)


@app.command("survey-mining")
@_with_logfile("survey_mining")
def survey_mining(
    topic: str = _topic_option(),
    limit: int = typer.Option(0, help="max papers to scan (0 = all)"),
    workers: int = typer.Option(0, "--workers", "-w", help="parallel workers (0 = from config)"),
    batch_size: int = typer.Option(0, "--batch", "-b", help="papers per call (0 = from config)"),
    phase: str = typer.Option("discover", "--phase", help="discover | download | keywords | all"),
    force: bool = typer.Option(False, "--force", "-f", help="force re-run: clear prior DB records before executing"),
    skip_resolve: bool = typer.Option(False, "--skip-resolve", help="skip arxiv/openreview search for missing PDFs (download ready ones only)"),
):
    """Stage 3: DeepSeek-Flash scans all papers → find topic-related surveys →
    download PDFs → extract keywords → feed into keywords-filter."""
    cfg = load_config()
    topic = resolve_topic(topic, cfg)
    s_survey_mining.run(
        cfg, topic_name=topic, limit=limit, workers=workers,
        batch_size=batch_size, phase=phase, force=force,
        skip_resolve=skip_resolve,
    )


@app.command("keywords-filter")
@_with_logfile("keywords_filter")
def keywords_filter(
    topic: str = _topic_option(),
):
    """Stage 4: keyword regex filter over title+abstract."""
    cfg = load_config()
    s_keywords_filter.run(cfg, topic_name=topic)


@app.command()
@_with_logfile("classify")
def classify(
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
    batch_size: int | None = typer.Option(None, "--batch-size", help="papers per LLM call (default from classify_config.yaml)"),
    workers: int | None = typer.Option(None, "--workers", "-w", help="parallel API workers (default from classify_config.yaml)"),
    topic: str = _topic_option(),
):
    """Stage 3: LLM (Flash) venue-aware batch classify."""
    cfg = load_config()
    topic_name = resolve_topic(topic, cfg)

    # Prompt for force if a large number of results already exist
    if not force:
        db = DB(cfg.abs_path("db"))
        try:
            already_done = db.count_topic(
                topic_name,
                "relevance IS NOT NULL AND relevance != ''"
            )
            if already_done >= 1000:
                msg = (
                    f"[yellow]Database already has {already_done:,} classified papers for topic '{topic_name}'.\n"
                    f"Without --force, only unclassified papers will be processed.\n"
                    f"Do you want to FORCE RE-RUN all papers? (y/N): [/yellow]"
                )
                console.print(msg, end="")
                try:
                    answer = input().strip().lower()
                except (EOFError, KeyboardInterrupt):
                    answer = "n"
                if answer in ("y", "yes"):
                    force = True
                    console.print("[red]Force re-run enabled.[/red]")
                else:
                    console.print("[dim]Proceeding without force (incremental).[/dim]")
        finally:
            db.close()

    s_classify.run(
        cfg,
        force=force,
        limit=limit or None,
        batch_size=batch_size,
        workers=workers,
        topic_name=topic,
    )


@app.command("abstract-coverage")
@_with_logfile("abstract_coverage")
def abstract_coverage(
    topic: str = _topic_option(),
):
    """Show abstract coverage (good / bad / missing) by venue."""
    cfg = load_config()
    s_abstract_coverage.run(cfg, topic_name=topic)


@app.command("keyword-stats")
@_with_logfile("keyword_stats")
def keyword_stats(
    topic: str = _topic_option(),
):
    """Analyze keyword hit statistics across all papers."""
    cfg = load_config()
    s_keyword_stats.run(cfg, topic_name=topic)


@app.command("enrich-arxiv")
@_with_logfile("enrich_arxiv")
def enrich_arxiv():
    """Backfill abstracts for SE/Security core venues (deprecated, use `enrich`)."""
    cfg = load_config()
    s_enrich.run_arxiv(cfg)


@app.command("estimate-cost")
@_with_logfile("estimate_cost")
def estimate_cost(
    topic: str = _topic_option(),
):
    """Estimate DeepSeek API cost for venue-aware classification."""
    cfg = load_config()
    s_estimate_cost.run(cfg, topic_name=topic)


@app.command()
@_with_logfile("fulltext")
def fulltext(
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
    scope: str = typer.Option("", "--scope", help="core | related | adjacent (empty = all classified)"),
    workers: int = typer.Option(1, "--workers", "-w", help="concurrent download workers"),
    topic: str = _topic_option(),
):
    """Stage 4: download arXiv PDFs for classified papers."""
    cfg = load_config()
    s_fulltext.run(cfg, force=force, limit=limit or None, scope=scope or None, workers=workers, topic_name=topic)


@app.command()
@_with_logfile("deepdive")
def deepdive(
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
    topic: str = _topic_option(),
):
    """Stage 5: LLM (Pro) structured extraction on PDF body."""
    cfg = load_config()
    s_deepdive.run(cfg, force=force, limit=limit or None, topic_name=topic)


@app.command("dedup")
@_with_logfile("subtopic_dedup")
def dedup(
    scope: str = typer.Option("core", "--scope", help="core | related | adjacent"),
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
    batch_size: int = typer.Option(20, "--batch-size", help="papers per LLM call"),
    workers: int = typer.Option(2, "--workers", "-w", help="parallel API workers"),
    dry_run: bool = typer.Option(False, "--dry-run", help="only run Stage A (sub-topic discovery), skip dedup"),
    topic: str = _topic_option(),
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
        topic_name=topic,
    )


@app.command("taxonomy")
@_with_logfile("taxonomy_classify")
def taxonomy(
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
    batch_size: int | None = typer.Option(None, "--batch-size", help="papers per LLM call (overrides stage config)"),
    workers: int | None = typer.Option(None, "--workers", "-w", help="parallel API workers (overrides stage config)"),
    relevance: str = typer.Option(
        "core,related,adjacent",
        "--relevance",
        "-r",
        help="Comma-separated relevance levels to classify (e.g. 'core' or 'core,related')",
    ),
    topic: str = _topic_option(),
):
    """Stage 7: unified multi-dimensional taxonomy classification (absorbs former s06).

    Maps all core/related/adjacent papers to dynamically-defined trees from topic config.
    Outputs both taxonomy_json (tree paths) and topics_json (flat labels).
    Supports incremental discovery of new leaves/trees via new_leaves proposals.
    """
    cfg = load_config()
    rel_levels = [r.strip() for r in relevance.split(",") if r.strip()]
    s_taxonomy.run(
        cfg,
        force=force,
        limit=limit or None,
        batch_size=batch_size,
        workers=workers,
        topic_name=topic,
        relevance_levels=rel_levels,
    )


@app.command()
@_with_logfile("citation")
def citation(
    scope: str = typer.Option("core", "--scope", help="core | related | adjacent"),
    force: bool = False,
    topic: str = _topic_option(),
):
    """Stage 8: extract citations from PDFs and build citation graph.

    Generates docs/citation_graph.html (interactive D3.js force-directed graph).
    """
    cfg = load_config()
    s_citation.run(cfg, scope=scope, force=force, topic_name=topic)


@app.command("short-titles")
@_with_logfile("short_titles")
def short_titles(
    force: bool = False,
    scope: str = typer.Option("core", "--scope", help="core | related | adjacent | all (classified)"),
    batch_size: int = typer.Option(20, "--batch-size", help="titles per LLM call"),
    workers: int = typer.Option(5, "--workers", "-w", help="parallel LLM workers"),
    use_pdf: bool = typer.Option(True, "--use-pdf/--no-pdf", help="read PDF excerpts for better abbreviations"),
    topic: str = _topic_option(),
):
    """Generate abbreviated short titles for long paper titles via DeepSeek."""
    cfg = load_config()
    s_short_titles.run(cfg, force=force, scope=scope, batch_size=batch_size, workers=workers, use_pdf=use_pdf, topic_name=topic)


@app.command("category-desc")
@_with_logfile("category_desc")
def category_desc(
    force: bool = False,
    limit: int = typer.Option(0, help="0 = no limit"),
    workers: int = typer.Option(3, "--workers", "-w", help="parallel LLM workers"),
    topic: str = _topic_option(),
):
    """Stage 10: generate bilingual descriptions for taxonomy categories via DeepSeek."""
    cfg = load_config()
    s_category_desc.run(cfg, force=force, limit=limit or None, workers=workers, topic_name=topic)


@app.command("summary")
@_with_logfile("summary")
def summary(
    force: bool = False,
    workers: int = typer.Option(20, "--workers", "-w", help="parallel LLM workers"),
    topic: str = _topic_option(),
):
    """Stage 11: generate 3-4 sentence bilingual summaries for every paper via DeepSeek Flash."""
    cfg = load_config()
    s_summary.run(cfg, force=force, workers=workers, topic_name=topic)


@app.command("serve-docs")
@_with_logfile("serve_docs")
def serve_docs(
    port: int = typer.Option(0, "--port", "-p", help="override port (default from config)"),
    topic: str = _topic_option("Topic name (default: active topic)"),
):
    """Serve the docs/ static site via python -m http.server."""
    import subprocess

    cfg = load_config()
    port = port or cfg.docs.server_port
    if topic:
        docs_dir = cfg.project_root / "docs" / topic
    else:
        docs_dir = cfg.project_root / "docs"
    if not docs_dir.exists():
        console.print(f"[red]docs/{topic or ''} not found. Run `generate-docs` first.[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Serving docs at http://localhost:{port}[/green]")
    subprocess.run(
        [sys.executable, "-m", "http.server", str(port), "--bind", "0.0.0.0"],
        cwd=str(docs_dir),
    )


@app.command("generate-docs")
@_with_logfile("generate_docs")
def generate_docs(
    topic: str = _topic_option("Topic name (default: all topics)"),
):
    """Generate static docs/ site from DB data (per-topic)."""
    import subprocess
    cfg = load_config()
    script = cfg.project_root / "scripts" / "generate_docs.py"
    args = [sys.executable, str(script)]
    if topic:
        args.extend(["--topic", topic])
    subprocess.run(args, check=True)


@app.command()
@_with_logfile("report")
def report(
    topic: str = _topic_option(),
):
    """Generate Obsidian vault + JSON + Markdown survey (per-topic)."""
    cfg = load_config()
    r_md.export_json(cfg, topic_name=topic)
    r_md.render_survey_markdown(cfg, topic_name=topic)
    r_obs.write_vault(cfg, topic_name=topic)


@app.command()
@_with_logfile("tui")
def tui():
    """Launch interactive TUI menu."""
    run_tui()


@app.command()
@_with_logfile("stats")
def stats(
    topic: str = _topic_option(),
):
    """Print the current DB overview."""
    cfg = load_config()
    db = DB(cfg.abs_path("db"))
    try:
        print_overview(db, f"DB overview [{topic or cfg.active_topic}]", topic_name=topic)
    finally:
        db.close()


if __name__ == "__main__":
    app()
