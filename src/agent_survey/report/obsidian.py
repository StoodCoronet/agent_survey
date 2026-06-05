"""Generate Obsidian notes — one file per paper + MOC + tag notes (per-topic)."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from ..core.config import Config, load_topic_config, resolve_topic
from ..core.console import console
from ..core.db import DB


def slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9一-龥]+", "-", s).strip("-").lower()
    return s[:80]


def yaml_list(values: Iterable[str]) -> str:
    vals = [v for v in values if v]
    if not vals:
        return "[]"
    return "[" + ", ".join(f'"{v}"' for v in vals) + "]"


def _load_json(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def render_paper_note(row: dict) -> str:
    title = (row.get("title") or "").replace('"', "'")
    authors = _load_json(row.get("authors_json")) or []
    domain_secondary = _load_json(row.get("domain_secondary_json")) or []
    method_tags = _load_json(row.get("method_tags_json")) or []
    deepdive = _load_json(row.get("deepdive_json")) or {}
    taxonomy = _load_json(row.get("taxonomy_json")) or {}
    dom = row.get("domain_primary") or "Uncategorized"
    tags = [f"agent/{slugify(dom)}"]
    for d in domain_secondary:
        tags.append(f"agent/{slugify(d)}")
    for m in method_tags:
        tags.append(f"method/{slugify(m)}")
    if row.get("venue"):
        tags.append(f"venue/{slugify(row['venue'])}")
    if row.get("venue_area"):
        tags.append(f"area/{slugify(row['venue_area'])}")
    if row.get("relevance"):
        tags.append(f"relevance/{row['relevance']}")
    # taxonomy tags
    for tree_name, paths in (taxonomy or {}).items():
        if tree_name == "cross_cutting":
            for tag in (paths or []):
                tags.append(f"cross/{slugify(tag)}")
            continue
        for path in (paths or []):
            tags.append(f"tax/{slugify(tree_name)}/{slugify(path)}")

    frontmatter = [
        "---",
        f'title: "{title}"',
        f"authors: {yaml_list(authors)}",
        f"venue: {row.get('venue') or ''}",
        f"year: {row.get('year') or ''}",
        f"area: {row.get('venue_area') or ''}",
        f"doi: {row.get('doi') or ''}",
        f"arxiv: {row.get('arxiv_id') or ''}",
        f"url: {row.get('url') or ''}",
        f"pdf: {row.get('pdf_url') or ''}",
        f"code: {row.get('code_url') or ''}",
        f"relevance: {row.get('relevance') or ''}",
        f'domain_primary: "{dom}"',
        f"domain_secondary: {yaml_list(domain_secondary)}",
        f"method_tags: {yaml_list(method_tags)}",
        f"tags: {yaml_list(tags)}",
        "---",
        "",
        f"# {row.get('title') or ''}",
        "",
    ]
    body: list[str] = []
    body.append("## TL;DR")
    body.append(row.get("tldr") or "_(no tldr yet)_")
    body.append("")
    if row.get("abstract"):
        body.append("## Abstract")
        body.append(row["abstract"])
        body.append("")
    summary_en = row.get("summary_en") or ""
    summary_zh = row.get("summary_zh") or ""
    if summary_en or summary_zh:
        body.append("## Summary")
        if summary_en:
            body.append(summary_en)
        if summary_zh:
            body.append(f"*{summary_zh}*")
        body.append("")
    if deepdive:
        for key, heading in [
            ("problem", "Problem"),
            ("approach", "Approach"),
            ("novelty", "Novelty"),
            ("evaluation", "Evaluation"),
            ("key_results", "Key Results"),
            ("datasets", "Datasets"),
            ("limitations", "Limitations"),
            ("computer_use_relevance", "Relevance to Topic"),
        ]:
            v = deepdive.get(key)
            if not v:
                continue
            body.append(f"## {heading}")
            if isinstance(v, list):
                for item in v:
                    body.append(f"- {item}")
            else:
                body.append(str(v))
            body.append("")
    # taxonomy section
    if taxonomy:
        body.append("## Taxonomy")
        for tree_name, paths in taxonomy.items():
            if tree_name == "cross_cutting":
                body.append(f"- **cross-cutting**: {', '.join(paths)}")
            else:
                body.append(f"- **{tree_name}**: {', '.join(paths)}")
        body.append("")
    body.append("## Notes")
    body.append("")

    return "\n".join(frontmatter + body)


def write_vault(cfg: Config, topic_name: str = "") -> dict:
    topic_name = resolve_topic(topic_name, cfg)
    tc = load_topic_config(topic_name)
    vault = cfg.abs_topic_dir(topic_name, "obsidian")
    papers_dir = vault / "papers"
    tags_dir = vault / "tags"
    papers_dir.mkdir(parents=True, exist_ok=True)
    tags_dir.mkdir(parents=True, exist_ok=True)

    db = DB(cfg.abs_path("db"))
    try:
        rows = list(
            db.iter_paper_topics(
                topic_name, "relevance IS NOT NULL AND relevance != 'irrelevant'"
            )
        )
        by_domain: dict[str, list[dict]] = defaultdict(list)
        written = 0
        for r in rows:
            name = f"{r.get('year') or 'na'}-{slugify(r.get('venue') or 'na')}-{slugify(r.get('title') or r['paper_id'])}.md"
            path = papers_dir / name
            path.write_text(render_paper_note(r))
            written += 1
            by_domain[r.get("domain_primary") or "Uncategorized"].append(r)

        # index MOC
        moc_lines = [
            f"# {tc.description or topic_name} Survey — Index",
            "",
            f"Total papers: {written}",
            "",
            "## By Primary Domain",
            "",
        ]
        for dom, items in sorted(by_domain.items()):
            moc_lines.append(f"### {dom} ({len(items)})")
            for p in sorted(items, key=lambda x: (x.get("year") or 0), reverse=True):
                venue = p.get("venue") or ""
                year = p.get("year") or ""
                title = (p.get("title") or "").replace("[", "(").replace("]", ")")
                fname = f"{year or 'na'}-{slugify(venue or 'na')}-{slugify(p.get('title') or p['paper_id'])}"
                moc_lines.append(f"- [[papers/{fname}|{title}]] — *{venue} {year}*")
            moc_lines.append("")
        (vault / "index.md").write_text("\n".join(moc_lines))

        # per-domain tag notes
        for dom, items in by_domain.items():
            tag_path = tags_dir / f"{slugify(dom)}.md"
            lines = [f"# {dom}", "", f"{len(items)} papers", ""]
            for p in sorted(items, key=lambda x: (x.get("year") or 0), reverse=True):
                venue = p.get("venue") or ""
                year = p.get("year") or ""
                fname = f"{year or 'na'}-{slugify(venue or 'na')}-{slugify(p.get('title') or p['paper_id'])}"
                lines.append(f"- [[papers/{fname}|{p.get('title')}]] ({venue} {year})")
            tag_path.write_text("\n".join(lines))

        console.print(f"[green]wrote {written} Obsidian notes to {vault}[/green]")
        return {"written": written, "domains": {k: len(v) for k, v in by_domain.items()}}
    finally:
        db.close()
