"""Stage 3: Survey Mining — auto-discover survey papers, extract keywords."""
from __future__ import annotations

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table

from ...core.config import Config, load_topic_config
from ...core.console import console
from ...core.db import DB
from ...services import arxiv as arxiv_src
from ...services.llm import DeepSeekClient
from ...services import pdf_extract
from .core import _load_stage_config, build_discovery_prompt, build_keyword_extraction_prompt

import json as _json
import httpx as _httpx
import re as _re
from collections import Counter


def _norm(s: str) -> str:
    """Normalize title for fuzzy matching."""
    return _re.sub(r"[^a-z0-9]+", "", s.lower())


def run(
    cfg: Config,
    *,
    topic_name: str = "",
    limit: int = 0,
    batch_size: int | None = None,
    workers: int | None = None,
    phase: str = "discover",
    force: bool = False,
    skip_resolve: bool = False,
) -> dict:
    """Run survey-mining pipeline."""
    sconf = _load_stage_config()
    batch_size = batch_size or sconf["llm"]["batch_size"]
    workers = workers or sconf["llm"]["workers"]
    limit = limit or sconf.get("limit", 0)
    topic_cfg = load_topic_config(topic_name)
    db = DB(cfg.abs_path("db"))
    deepseek = DeepSeekClient(cfg)
    stats: dict = {"phase": phase, "surveys_found": 0}

    try:
        candidates_path = cfg.abs_topic_dir(topic_name, "json") / "survey_candidates.json"

        if phase in ("discover", "all"):
            # Idempotent: skip if already discovered for this topic
            existing = db._conn.execute(
                "SELECT COUNT(*) FROM paper_topics WHERE topic_name=? AND survey_score IS NOT NULL",
                (topic_name,),
            ).fetchone()[0]
            if existing > 0 and not force:
                console.print(f"[green]Phase 1 already done ({existing} surveys in DB).[/green]")
                stats["surveys_found"] = existing
            else:
                if force and existing > 0:
                    console.print(f"[yellow]Force re-run: clearing {existing} prior survey records...[/yellow]")
                    db._conn.execute(
                        "UPDATE paper_topics SET survey_score = NULL, survey_keywords_json = NULL WHERE topic_name=?",
                        (topic_name,),
                    )
                    db._conn.commit()
                console.rule("[bold cyan]Phase 1: Survey Discovery")
                papers = list(db.iter_papers("abstract IS NOT NULL AND abstract != ''"))
                if limit:
                    papers = papers[:limit]
                console.print(f"Scanning {len(papers):,} papers for surveys about [cyan]{topic_name}[/cyan]")

                batches = [papers[i:i + batch_size] for i in range(0, len(papers), batch_size)]
                surveys_found: list[dict] = []

                progress = Progress(
                    TextColumn("[bold blue]{task.description}"),
                    BarColumn(), TextColumn("[{task.completed}/{task.total}]"),
                    TimeElapsedColumn(), TimeRemainingColumn(), console=console,
                )
                task = progress.add_task("survey discovery (batches)", total=len(batches))

                # Reuse shared LLM client (respects per-stage proxy + caching)
                llm_client = DeepSeekClient(cfg, stage_name="survey_mining")

                submit_t0 = time.time()
                console.print(f"[dim]Submitting {len(batches)} batches to {workers} workers...[/dim]")
                with progress:
                    with ThreadPoolExecutor(max_workers=workers) as pool:
                        futures = {}
                        for b in batches:
                            messages = build_discovery_prompt(topic_cfg, b)
                            f = pool.submit(
                                llm_client.chat_json,
                                model=sconf["llm"]["model"],
                                messages=messages,
                                temperature=sconf["llm"]["temperature"],
                                max_tokens=sconf["llm"]["max_tokens"],
                            )
                            futures[f] = b
                        submit_dt = time.time() - submit_t0
                        console.print(f"[dim]All {len(batches)} batches submitted in {submit_dt:.1f}s[/dim]")

                        done_count = 0
                        for f in as_completed(futures):
                            batch = futures[f]
                            done_count += 1
                            if done_count <= 3 or done_count % 50 == 0:
                                console.print(f"[dim]batch {done_count}/{len(batches)} completed (batch_size={len(batch)})[/dim]")
                            try:
                                result = f.result()
                                data = result.get("content", result)
                                # Support formats:
                                # New: {"surveys": [{"idx": 0, "title": "..."}, ...]}
                                # Old int: {"surveys": [3, 7, 15]}
                                # Legacy: {"papers": [{"index": 0, "is_survey": true, ...}]}
                                surveys_list = data.get("surveys", [])
                                indices: list[int] = []
                                for s in surveys_list:
                                    if isinstance(s, dict):
                                        idx = s.get("idx", -1)
                                        title = s.get("title", "")
                                        # Validate: idx must match title
                                        if 0 <= idx < len(batch):
                                            batch_title = (batch[idx].get("title") or "").strip()
                                            if _norm(batch_title) == _norm(title):
                                                indices.append(idx)
                                            else:
                                                # Mismatch: try to find by title
                                                for j, bp in enumerate(batch):
                                                    if _norm(bp.get("title") or "") == _norm(title):
                                                        indices.append(j)
                                                        break
                                    elif isinstance(s, int):
                                        indices.append(s)
                                    elif isinstance(s, str):
                                        # title-only fallback
                                        for j, bp in enumerate(batch):
                                            if _norm(bp.get("title") or "") == _norm(s):
                                                indices.append(j)
                                                break
                                if not indices:
                                    papers_list = data.get("papers", [])
                                    if isinstance(papers_list, list):
                                        for r in papers_list:
                                            if r.get("is_survey"):
                                                indices.append(r.get("index", -1))
                                for i in indices:
                                    if isinstance(i, int) and 0 <= i < len(batch):
                                        p = dict(batch[i])
                                        p["survey_relevance"] = 1.0
                                        surveys_found.append(p)
                            except Exception as e:
                                # Log raw response for debugging JSONDecodeError
                                detail = str(e)
                                if hasattr(e, '__cause__'):
                                    detail += f"  cause: {e.__cause__}"
                                raw_debug = ""
                                if isinstance(result, dict):
                                    raw_debug = result.get("raw", "")[:500]
                                console.print(f"[red]batch error: {detail[:200]}[/red]")
                                if raw_debug:
                                    console.print(f"[dim]raw response: {raw_debug}[/dim]")
                            progress.advance(task)

                stats["surveys_found"] = len(surveys_found)
                console.print(f"\n[green]Found {len(surveys_found)} survey candidates[/green]")

                # Save to DB: paper_topics.survey_score
                if surveys_found:
                    ts = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
                    for s in surveys_found:
                        title = s.get("title", "")
                        row = db._conn.execute(
                            "SELECT paper_id FROM papers WHERE title = ?", (title,)
                        ).fetchone()
                        if row:
                            db._conn.execute(
                                "INSERT INTO paper_topics (paper_id, topic_name, survey_score, updated_at) "
                                "VALUES (?, ?, ?, ?) "
                                "ON CONFLICT(paper_id, topic_name) DO UPDATE SET "
                                "survey_score=excluded.survey_score, updated_at=excluded.updated_at",
                                (row["paper_id"], topic_name, s.get("survey_relevance", 1.0), ts),
                            )
                    db._conn.commit()

                if surveys_found:
                    surveys_found.sort(key=lambda x: x.get("survey_relevance", 0), reverse=True)
                    tbl = Table(title=f"Top surveys for {topic_name}", show_header=True, box=None)
                    tbl.add_column("Rel", justify="right", style="green", width=5)
                    tbl.add_column("Title", style="cyan")
                    for s in surveys_found[:20]:
                        tbl.add_row(f"{s.get('survey_relevance', 0):.2f}", (s.get("title") or "")[:100])
                    console.print(tbl)
                    out = cfg.abs_topic_dir(topic_name, "json") / "survey_candidates.json"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(json.dumps(surveys_found, indent=2, ensure_ascii=False))
                    console.print(f"[dim]Saved to {out}[/dim]")

        if phase in ("download", "keywords", "all"):
            console.rule("[bold cyan]Phase 2: Build Download Manifest")
            candidates_path = cfg.abs_topic_dir(topic_name, "json") / "survey_candidates.json"
            if not candidates_path.exists():
                console.print("[yellow]No survey_candidates.json found. Run Phase 1 first.[/yellow]")
            else:
                candidates = _json.loads(candidates_path.read_text())
                manifest: list[dict] = []
                to_resolve: list[tuple[int, str, str]] = []  # (idx, title, venue)

                for idx, s in enumerate(candidates):
                    title = s.get("title", "")
                    row = db._conn.execute(
                        "SELECT venue, arxiv_id, pdf_url FROM papers WHERE title = ?", (title,)
                    ).fetchone()
                    venue = row["venue"] if row else "unknown"
                    aid = row["arxiv_id"] if row else None
                    purl = row["pdf_url"] if row else None

                    entry = {
                        "title": title,
                        "venue": venue,
                        "arxiv_id": aid,
                        "pdf_url": purl,
                        "source": "db",
                        "resolutions": [],
                    }
                    if aid:
                        entry["pdf_url"] = f"https://arxiv.org/pdf/{aid}.pdf"
                        entry["resolutions"].append({"stage": "db", "found": True, "arxiv_id": aid, "pdf_url": entry["pdf_url"]})
                    elif purl:
                        entry["pdf_url"] = purl
                        entry["resolutions"].append({"stage": "db", "found": True, "pdf_url": purl})
                    else:
                        entry["source"] = "missing"
                        entry["resolutions"].append({"stage": "db", "found": False})
                        to_resolve.append((idx, title, venue))
                    manifest.append(entry)

                console.print(
                    f"[dim]{len(candidates)} surveys: {len(candidates) - len(to_resolve)} with source, "
                    f"{len(to_resolve)} missing — resolving via arxiv search...[/dim]"
                )

                # Resolve missing via arxiv title search
                if to_resolve and not skip_resolve:
                    console.print(f"\n[bold cyan]Resolving {len(to_resolve)} missing surveys via arXiv...[/bold cyan]")
                    http = _httpx.Client(timeout=30, headers={"User-Agent": cfg.network.user_agent})
                    arxiv_ok = 0
                    arxiv_fail = 0
                    try:
                        for n, (idx, title, venue) in enumerate(to_resolve, 1):
                            console.print(f"  [{n}/{len(to_resolve)}] {title[:70]}...", end=" ")
                            result = arxiv_src.search_title(http, title, delay=0.5)
                            if result and result.get("arxiv_id"):
                                manifest[idx]["arxiv_id"] = result["arxiv_id"]
                                manifest[idx]["pdf_url"] = result.get("pdf_url") or f"https://arxiv.org/pdf/{result['arxiv_id']}.pdf"
                                manifest[idx]["source"] = "arxiv_search"
                                manifest[idx]["resolutions"].append({
                                    "stage": "arxiv_api",
                                    "found": True,
                                    "arxiv_id": result["arxiv_id"],
                                    "pdf_url": manifest[idx]["pdf_url"],
                                })
                                arxiv_ok += 1
                                console.print(f"[green]✓ arxiv:{result['arxiv_id']}[/green]")
                            else:
                                arxiv_fail += 1
                                manifest[idx]["resolutions"].append({
                                    "stage": "arxiv_api",
                                    "found": False,
                                })
                                console.print(f"[yellow]✗ not on arXiv[/yellow]")
                    finally:
                        http.close()

                    console.print(f"\n[green]ArXiv resolve: {arxiv_ok} success, {arxiv_fail} failed[/green]")

                    # ── arXiv Web fallback (Playwright) ────────────────────────
                    web_missing = [
                        (idx, title, venue)
                        for idx, title, venue in to_resolve
                        if not manifest[idx].get("pdf_url")
                    ]
                    if web_missing:
                        console.print(f"\n[bold cyan]Trying arXiv web search for {len(web_missing)} papers...[/bold cyan]")
                        from ...services import arxiv_web_search as arxiv_web
                        web_ok = 0
                        web_fail = 0
                        for n, (idx, title, venue) in enumerate(web_missing, 1):
                            console.print(f"  [{n}/{len(web_missing)}] {title[:70]}...", end=" ")
                            web_res = arxiv_web.search_arxiv_web(title, headless=True)
                            if web_res.success and web_res.arxiv_id:
                                manifest[idx]["arxiv_id"] = web_res.arxiv_id
                                manifest[idx]["pdf_url"] = web_res.pdf_url or f"https://arxiv.org/pdf/{web_res.arxiv_id}.pdf"
                                manifest[idx]["source"] = "arxiv_web"
                                manifest[idx]["resolutions"].append({
                                    "stage": "arxiv_web",
                                    "found": True,
                                    "arxiv_id": web_res.arxiv_id,
                                    "pdf_url": manifest[idx]["pdf_url"],
                                    "title_score": web_res.title_score,
                                    "title_matched": web_res.title_matched,
                                    "confidence": web_res.confidence,
                                    "debug_log": web_res.debug_log,
                                })
                                web_ok += 1
                                console.print(f"[green]✓ arxiv_web:{web_res.arxiv_id} ({web_res.title_matched} {web_res.title_score:.2f})[/green]")
                            else:
                                web_fail += 1
                                manifest[idx]["resolutions"].append({
                                    "stage": "arxiv_web",
                                    "found": False,
                                    "error": web_res.error or "no match",
                                    "title_score": web_res.title_score,
                                    "title_matched": web_res.title_matched,
                                    "debug_log": web_res.debug_log,
                                })
                                console.print(f"[yellow]✗ {web_res.error or 'no match'}[/yellow]")
                            # Polite delay: 5–10s random interval between web searches
                            if n < len(web_missing):
                                delay = random.uniform(5, 10)
                                time.sleep(delay)
                        console.print(f"\n[green]arXiv web resolve: {web_ok} success, {web_fail} failed[/green]")

                    # ── OpenReview fallback for AI venues ─────────────────────
                    or_venues = {"ICLR", "ICML", "NeurIPS", "COLM"}
                    or_missing = [
                        (idx, title, venue)
                        for idx, title, venue in to_resolve
                        if venue in or_venues and not manifest[idx].get("pdf_url")
                    ]
                    if or_missing:
                        console.print(f"\n[bold cyan]Trying OpenReview for {len(or_missing)} AI venue papers...[/bold cyan]")
                        from ...services import openreview as or_src
                        or_http = _httpx.Client(timeout=30, headers={"User-Agent": cfg.network.user_agent})
                        or_ok = 0
                        or_fail = 0
                        try:
                            for n, (idx, title, venue) in enumerate(or_missing, 1):
                                console.print(f"  [{n}/{len(or_missing)}] {title[:70]}...", end=" ")
                                res = or_src.search_title_pdf(or_http, title)
                                if res and res.get("pdf_url"):
                                    manifest[idx]["pdf_url"] = res["pdf_url"]
                                    manifest[idx]["source"] = "openreview"
                                    manifest[idx]["resolutions"].append({
                                        "stage": "openreview",
                                        "found": True,
                                        "forum_id": res.get("forum_id"),
                                        "pdf_url": res["pdf_url"],
                                    })
                                    or_ok += 1
                                    console.print(f"[green]✓ OR:{res['forum_id']}[/green]")
                                else:
                                    or_fail += 1
                                    manifest[idx]["resolutions"].append({
                                        "stage": "openreview",
                                        "found": False,
                                    })
                                    console.print(f"[yellow]✗ not on OpenReview[/yellow]")
                                time.sleep(1)
                        finally:
                            or_http.close()
                        console.print(f"\n[green]OpenReview resolve: {or_ok} success, {or_fail} failed[/green]")

                # Summary
                with_source = sum(1 for m in manifest if m.get("pdf_url"))
                still_missing = sum(1 for m in manifest if not m.get("pdf_url"))
                stats["manifest_total"] = len(candidates)
                stats["manifest_with_source"] = with_source
                stats["manifest_missing"] = still_missing

                # Build by-source summary for debugging
                by_source: dict[str, int] = {}
                for m in manifest:
                    src = m.get("source") or "missing"
                    by_source[src] = by_source.get(src, 0) + 1

                out_manifest = cfg.abs_topic_dir(topic_name, "json") / "download_manifest.json"
                out_manifest.write_text(_json.dumps({
                    "total": len(candidates),
                    "with_source": with_source,
                    "missing": still_missing,
                    "by_source": by_source,
                    "candidates": manifest,
                }, indent=2, ensure_ascii=False))
                console.print(f"[dim]Manifest saved to {out_manifest}[/dim]")
                console.print(f"[dim]By source: {by_source}[/dim]")

                if still_missing > 0:
                    console.print(f"[yellow]{still_missing} surveys still missing PDF source.[/yellow]")
                    console.print("[dim]Suggestions:[/dim]")
                    console.print("  • ACL/EMNLP/NAACL → try ACL Anthology: https://aclanthology.org/")
                    console.print("  • AAAI → try aaai.org/library/ or request via inter-library")
                    console.print("  • ICLR/ICML/NeurIPS → try OpenReview forum pages")
                    console.print("  • SE venues (ICSE/TOSEM) → try ACM DL or Sci-Hub")

                # ── Download PDFs ──────────────────────────────────────────
                pdf_dir = cfg.abs_topic_dir(topic_name, "pdfs")
                pdf_dir.mkdir(parents=True, exist_ok=True)

                dl_tasks: list[tuple[str, str, str, str]] = []  # (pdf_url, dest_path, title, source_tag)
                skipped = 0
                for m in manifest:
                    purl = m.get("pdf_url")
                    if not purl:
                        continue
                    aid = m.get("arxiv_id")
                    title = m.get("title", "")
                    # Check DB for existing pdf_path (supports both abs and rel paths)
                    row = db._conn.execute(
                        "SELECT pdf_path, pdf_source FROM papers WHERE title = ?", (title,)
                    ).fetchone()
                    existing_path = row["pdf_path"] if row else None
                    if existing_path:
                        abs_path = __import__("pathlib").Path(existing_path)
                        if not abs_path.is_absolute():
                            abs_path = cfg.project_root / existing_path
                        if abs_path.exists() and abs_path.stat().st_size > 1024:
                            # Already downloaded by fulltext or previous run
                            m["local_path"] = str(__import__("pathlib").Path(existing_path))
                            skipped += 1
                            continue
                    # Determine source tag for pdf_source
                    source_tag = "arxiv" if aid else (m.get("source") or "unknown")
                    if aid:
                        fname = f"{aid.replace('/', '_')}.pdf"
                    else:
                        import re as _re
                        slug = _re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:60]
                        fname = f"{slug}.pdf"
                    dest = pdf_dir / fname
                    dl_tasks.append((purl, str(dest), title, source_tag))

                if skipped:
                    console.print(f"[dim]{skipped} PDFs already cached (skipped)[/dim]")

                if dl_tasks:
                    console.print(f"\n[bold cyan]Downloading {len(dl_tasks)} PDFs...[/bold cyan]")
                    dl_ok = 0
                    dl_fail = 0
                    dl_n = 0

                    def _dl_one(purl: str, dest: str, title: str, source_tag: str) -> tuple[bool, str, str, str]:
                        http = _httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": cfg.network.user_agent})
                        try:
                            with http.stream("GET", purl) as r:
                                r.raise_for_status()
                                with open(dest, "wb") as f:
                                    for chunk in r.iter_bytes(chunk_size=65536):
                                        f.write(chunk)
                            return True, dest, title, source_tag
                        except Exception as e:
                            return False, "", title, source_tag
                        finally:
                            http.close()

                    with ThreadPoolExecutor(max_workers=5) as pool:
                        futures = {pool.submit(_dl_one, *t): t for t in dl_tasks}
                        for f in as_completed(futures):
                            ok, dest, title, source_tag = f.result()
                            dl_n += 1
                            if ok:
                                dl_ok += 1
                                rel_dest = str(__import__("pathlib").Path(dest).relative_to(cfg.project_root))
                                db._conn.execute(
                                    "UPDATE papers SET pdf_path = ?, pdf_source = ? WHERE title = ?",
                                    (rel_dest, source_tag, title),
                                )
                                for mm in manifest:
                                    if mm.get("title") == title:
                                        mm["local_path"] = rel_dest
                                        break
                                console.print(f"  [{dl_n}/{len(dl_tasks)}] [green]✓[/green] {title[:60]}...")
                            else:
                                dl_fail += 1
                                console.print(f"  [{dl_n}/{len(dl_tasks)}] [red]✗[/red] {title[:60]}...")
                    db._conn.commit()
                    console.print(f"\n[green]Download: {dl_ok} success, {dl_fail} failed, {skipped} skipped[/green]")
                    stats["pdfs_downloaded"] = dl_ok + skipped
                    stats["pdfs_failed"] = dl_fail
                    stats["pdfs_skipped"] = skipped

                    out_manifest.write_text(_json.dumps({
                        "total": len(candidates),
                        "with_source": with_source,
                        "missing": still_missing,
                        "downloaded": dl_ok + skipped,
                        "skipped": skipped,
                        "candidates": manifest,
                    }, indent=2, ensure_ascii=False))

        if phase in ("keywords", "all"):
            console.rule("[bold cyan]Phase 3: Keyword Extraction")
            candidates_path = cfg.abs_topic_dir(topic_name, "json") / "survey_candidates.json"
            manifest_path = cfg.abs_topic_dir(topic_name, "json") / "download_manifest.json"

            if not candidates_path.exists():
                console.print("[yellow]No survey_candidates.json found. Run Phase 1 first.[/yellow]")
            else:
                candidates = _json.loads(candidates_path.read_text())
                manifest_by_title: dict[str, dict] = {}
                if manifest_path.exists():
                    manifest_data = _json.loads(manifest_path.read_text())
                    for m in manifest_data.get("candidates", []):
                        manifest_by_title[m.get("title", "")] = m

                surveys_to_process: list[dict] = []
                for c in candidates:
                    title = c.get("title", "")
                    m = manifest_by_title.get(title, {})
                    local_path = m.get("local_path")
                    if local_path:
                        abs_path = cfg.project_root / local_path
                        if abs_path.exists() and abs_path.stat().st_size > 1024:
                            c["local_pdf"] = str(abs_path)
                            surveys_to_process.append(c)

                max_surveys = sconf["keywords"]["max_surveys"]
                if max_surveys:
                    surveys_to_process = surveys_to_process[:max_surveys]

                if not surveys_to_process:
                    console.print("[yellow]No downloaded survey PDFs found. Run Phase 2 (download) first.[/yellow]")
                else:
                    console.print(f"Extracting keywords from {len(surveys_to_process)} survey PDFs...")
                    per_survey = sconf["keywords"]["per_survey"]
                    min_freq = sconf["keywords"]["min_frequency"]

                    all_keywords: list[dict] = []  # {"term": ..., "source": title}

                    progress = Progress(
                        TextColumn("[bold blue]{task.description}"),
                        BarColumn(), TextColumn("[{task.completed}/{task.total}]"),
                        TimeElapsedColumn(), TimeRemainingColumn(), console=console,
                    )
                    task = progress.add_task("keyword extraction (surveys)", total=len(surveys_to_process))

                    llm_client = DeepSeekClient(cfg, stage_name="survey_mining")

                    with progress:
                        with ThreadPoolExecutor(max_workers=workers) as pool:
                            futures: dict = {}
                            for s in surveys_to_process:
                                pdf_path = Path(s["local_pdf"])
                                text = pdf_extract.extract_text(pdf_path, max_pages=20)
                                body = pdf_extract.build_prompt_body(text, max_chars=30000)
                                if not body or len(body) < 200:
                                    progress.advance(task)
                                    continue
                                messages = build_keyword_extraction_prompt(topic_cfg, body, per_survey=per_survey)
                                f = pool.submit(
                                    llm_client.chat_json,
                                    model=sconf["llm"]["model"],
                                    messages=messages,
                                    temperature=0.0,
                                    max_tokens=2048,
                                )
                                futures[f] = s

                            for f in as_completed(futures):
                                s = futures[f]
                                try:
                                    result = f.result()
                                    data = result.get("content", result)
                                    keywords_list = data.get("keywords", [])
                                    if isinstance(keywords_list, list):
                                        for kw in keywords_list:
                                            if isinstance(kw, str):
                                                term = kw.strip().lower()
                                                if term:
                                                    all_keywords.append({"term": term, "source": s.get("title", "")})
                                            elif isinstance(kw, dict):
                                                term = kw.get("term", kw.get("keyword", ""))
                                                if term:
                                                    all_keywords.append({"term": str(term).strip().lower(), "source": s.get("title", "")})
                                except Exception as e:
                                    console.print(f"[red]keyword extraction failed for {s.get('title', '')[:50]}...: {e}[/red]")
                                progress.advance(task)

                    # Aggregate by frequency
                    term_counts = Counter(k["term"] for k in all_keywords)
                    term_sources: dict[str, set[str]] = {}
                    for k in all_keywords:
                        term_sources.setdefault(k["term"], set()).add(k["source"])

                    aggregated: list[dict] = []
                    for term, count in term_counts.most_common():
                        if count >= min_freq:
                            aggregated.append({
                                "term": term,
                                "frequency": count,
                                "sources": sorted(term_sources[term]),
                            })

                    # Write back directly to topic yaml (no intermediate files)
                    mined_terms = [k["term"] for k in aggregated]
                    if mined_terms and topic_cfg.config_path:
                        import yaml as _yaml

                        topic_path = topic_cfg.config_path
                        data = _yaml.safe_load(topic_path.read_text())
                        if "keywords" not in data:
                            data["keywords"] = {}
                        data["keywords"]["survey_mined"] = mined_terms
                        topic_path.write_text(
                            _yaml.safe_dump(data, sort_keys=False, allow_unicode=True, indent=2),
                            encoding="utf-8",
                        )
                        console.print(
                            f"\n[green]Merged {len(mined_terms)} keywords into {topic_path.name} "
                            f"(keywords.survey_mined)[/green]"
                        )
                    elif not mined_terms:
                        console.print("\n[yellow]No keywords met frequency threshold.[/yellow]")

                    stats["keywords_extracted"] = len(all_keywords)
                    stats["keywords_unique"] = len(term_counts)
                    stats["keywords_filtered"] = len(aggregated)

        return stats
    finally:
        db.close()
