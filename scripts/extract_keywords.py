#!/usr/bin/env python3
"""Phase 3: Extract keywords from survey PDFs using DeepSeek-Flash.

Usage:
    conda activate survey_agent
    PYTHONPATH=src python scripts/extract_keywords.py

Outputs:
    - DB: paper_topics.survey_keywords_json
    - output/{topic}/json/keywords_raw.json
    - output/{topic}/json/keywords_dedup_prompt.txt
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pdfplumber
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from agent_survey.core.config import load_config
from agent_survey.core.db import DB
from agent_survey.services.llm import DeepSeekClient, cached_chat_json

console = Console()

SYSTEM_PROMPT = """You are an expert at extracting key technical concepts from academic survey papers.

Your task: read the paper title, abstract, and text excerpt, then extract 5-10 core keywords or key phrases that best represent the paper's technical contributions.

Requirements:
- Each keyword should be 1-4 English words
- Focus on technical methods, core concepts, and application scenarios
- Do NOT include overly generic terms like "deep learning", "neural network", "machine learning", "large language model"
- Prefer specific techniques: e.g., "KV cache compression", "context window extension", "positional encoding"
- Output in English, sorted by importance (most important first)
- Return strict JSON: {"keywords": ["keyword1", "keyword2", ...]}"""

PROMPT_VERSION = "v1"
MODEL = "deepseek-chat"
MAX_PAGES = 10
MAX_TEXT_LEN = 12000  # chars, roughly 3-4k tokens


def extract_pdf_text(pdf_path: str, max_pages: int = MAX_PAGES) -> str:
    """Extract text from first N pages of PDF."""
    path = Path(pdf_path)
    if not path.exists():
        return ""
    # Support relative paths
    if not path.is_absolute():
        cfg = load_config()
        path = cfg.project_root / path
    try:
        with pdfplumber.open(str(path)) as pdf:
            pages = pdf.pages[:max_pages]
            texts = []
            for p in pages:
                text = p.extract_text()
                if text:
                    texts.append(text)
            full = "\n".join(texts)
            if len(full) > MAX_TEXT_LEN:
                full = full[:MAX_TEXT_LEN] + "\n...[truncated]"
            return full
    except Exception as e:
        console.print(f"[red]PDF extract error: {e}[/red]")
        return ""


def build_prompt(title: str, abstract: str | None, pdf_text: str) -> list[dict]:
    abstract = abstract or ""
    user_text = f"Title: {title}\n\nAbstract:\n{abstract}\n\nPaper text (first {MAX_PAGES} pages):\n{pdf_text}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]


def main():
    cfg = load_config()
    topic_name = cfg.active_topic or "llm-context-management"
    db = DB(cfg.abs_path("db"))
    deepseek = DeepSeekClient(cfg)

    # Find surveys with PDF
    rows = db._conn.execute(
        """
        SELECT p.paper_id, p.title, p.abstract, p.pdf_path, p.dblp_key
        FROM papers p
        JOIN paper_topics pt ON p.paper_id = pt.paper_id
        WHERE pt.topic_name = ?
          AND pt.survey_score IS NOT NULL
          AND (p.pdf_path IS NOT NULL AND p.pdf_path != '')
        ORDER BY p.venue, p.title
        """,
        (topic_name,),
    ).fetchall()

    console.print(f"[bold]Extracting keywords from {len(rows)} survey PDFs...[/bold]")

    all_keywords: list[dict] = []
    processed = 0
    skipped = 0
    errors = 0

    progress = Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[{task.completed}/{task.total}]"),
        TimeElapsedColumn(),
        console=console,
    )

    with progress:
        task = progress.add_task("keyword extraction", total=len(rows))

        for row in rows:
            paper_id = row["paper_id"]
            title = row["title"]
            abstract = row["abstract"]
            pdf_path = row["pdf_path"]
            dblp_key = row["dblp_key"]

            # Check if already extracted
            existing = db._conn.execute(
                "SELECT survey_keywords_json FROM paper_topics WHERE paper_id = ? AND topic_name = ?",
                (paper_id, topic_name),
            ).fetchone()
            if existing and existing["survey_keywords_json"]:
                try:
                    kw_data = json.loads(existing["survey_keywords_json"])
                    keywords = kw_data.get("keywords", [])
                    all_keywords.append({"title": title, "dblp_key": dblp_key, "keywords": keywords})
                    skipped += 1
                    progress.advance(task)
                    continue
                except Exception:
                    pass

            # Extract PDF text
            pdf_text = extract_pdf_text(pdf_path)
            if not pdf_text:
                console.print(f"[yellow]No text extracted: {title[:50]}...[/yellow]")
                errors += 1
                progress.advance(task)
                continue

            # Call LLM
            messages = build_prompt(title, abstract, pdf_text)
            try:
                result = cached_chat_json(
                    deepseek,
                    db,
                    paper_id=paper_id,
                    stage="survey_keywords",
                    model=MODEL,
                    prompt_version=PROMPT_VERSION,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=512,
                    topic_name=topic_name,
                )
                data = result.get("content", {})
                keywords = data.get("keywords", [])
                if not keywords and isinstance(data, list):
                    keywords = data

                # Store in DB
                kw_json = json.dumps({"keywords": keywords}, ensure_ascii=False)
                db._conn.execute(
                    "UPDATE paper_topics SET survey_keywords_json = ? WHERE paper_id = ? AND topic_name = ?",
                    (kw_json, paper_id, topic_name),
                )
                db._conn.commit()

                all_keywords.append({"title": title, "dblp_key": dblp_key, "keywords": keywords})
                processed += 1

                cached_mark = "[dim](cached)[/dim]" if result.get("cached") else ""
                console.print(f"  [{processed}] {title[:45]}... → {len(keywords)} keywords {cached_mark}")

            except Exception as e:
                console.print(f"[red]Error extracting keywords for {title[:40]}: {e}[/red]")
                errors += 1

            progress.advance(task)

    console.print(f"\n[green]Done: {processed} extracted, {skipped} skipped (cached), {errors} errors[/green]")

    # Save raw keywords
    out_dir = cfg.abs_topic_dir(topic_name, "json")
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_path = out_dir / "keywords_raw.json"
    raw_path.write_text(json.dumps(all_keywords, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[dim]Raw keywords saved to {raw_path}[/dim]")

    # Generate deduplication prompt
    all_kw_flat = []
    for item in all_keywords:
        all_kw_flat.extend(item["keywords"])

    # Frequency count
    from collections import Counter
    freq = Counter([k.lower().strip() for k in all_kw_flat])
    top_kw = freq.most_common(300)

    dedup_prompt = f"""Here is a list of keywords extracted from {len(all_keywords)} survey papers about LLM context management.

Total unique keywords (before dedup): {len(freq)}
Top keywords by frequency:
"""
    for kw, count in top_kw[:100]:
        dedup_prompt += f"- {kw} ({count})\n"

    dedup_prompt += """
Please perform the following tasks:
1. Merge semantically similar keywords (e.g., "KV cache compression" and "KV cache pruning" → merge or pick the more common one)
2. Remove overly generic terms (e.g., "deep learning", "neural network", "machine learning")
3. Group related keywords into 5-10 high-level categories if possible
4. Return a clean, deduplicated list of 50-100 most representative keywords

Output format (YAML):
```yaml
categories:
  - name: "Efficiency & Compression"
    keywords:
      - "KV cache compression"
      - "context window extension"
      - ...
  - name: "..."
    keywords:
      - ...
```
"""

    dedup_path = out_dir / "keywords_dedup_prompt.txt"
    dedup_path.write_text(dedup_prompt, encoding="utf-8")
    console.print(f"[dim]Deduplication prompt saved to {dedup_path}[/dim]")

    # Also save flat list for easy copy-paste
    flat_path = out_dir / "keywords_flat.txt"
    flat_path.write_text("\n".join([f"{kw} ({count})" for kw, count in top_kw]), encoding="utf-8")
    console.print(f"[dim]Flat keyword list saved to {flat_path}[/dim]")

    db.close()


if __name__ == "__main__":
    main()
