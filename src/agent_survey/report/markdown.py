"""Export JSON snapshot + markdown survey + classification table."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from ..core.config import Config
from ..core.console import console
from ..core.db import DB


def _load(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def export_json(cfg: Config) -> dict:
    out_dir = cfg.abs_dir("json")
    db = DB(cfg.abs_path("db"))
    try:
        papers = []
        for r in db.iter_papers():
            r = dict(r)
            for k in (
                "authors_json",
                "prefilter_hit",
                "domain_secondary_json",
                "method_tags_json",
                "deepdive_json",
                "stage_status_json",
            ):
                r[k] = _load(r.get(k))
            papers.append(r)
        (out_dir / "papers.json").write_text(
            json.dumps(papers, ensure_ascii=False, indent=2)
        )

        # taxonomy
        domain_counter: Counter = Counter()
        method_counter: Counter = Counter()
        rel_counter: Counter = Counter()
        venue_counter: Counter = Counter()
        for r in papers:
            if r.get("relevance") and r["relevance"] != "irrelevant":
                domain_counter[r.get("domain_primary") or "Uncategorized"] += 1
                for m in r.get("method_tags_json") or []:
                    method_counter[m] += 1
                rel_counter[r["relevance"]] += 1
                venue_counter[r.get("venue")] += 1
        tax = {
            "relevance": dict(rel_counter),
            "domain_primary": dict(domain_counter),
            "method_tags": dict(method_counter),
            "by_venue": dict(venue_counter),
        }
        (out_dir / "taxonomy.json").write_text(
            json.dumps(tax, ensure_ascii=False, indent=2)
        )
        console.print(f"[green]wrote JSON to {out_dir}[/green]")
        return {"papers": len(papers), "taxonomy": tax}
    finally:
        db.close()


def render_survey_markdown(cfg: Config) -> dict:
    md_dir = cfg.abs_dir("markdown")
    db = DB(cfg.abs_path("db"))
    try:
        rows = list(
            db.iter_papers("relevance IS NOT NULL AND relevance != 'irrelevant'")
        )
        if not rows:
            console.print("[yellow]no classified papers yet[/yellow]")
            return {"papers": 0}

        # ---- classification_table.md
        rows_sorted = sorted(
            rows,
            key=lambda r: (
                r.get("domain_primary") or "~",
                -(r.get("year") or 0),
                r.get("venue") or "",
            ),
        )
        table_lines = [
            "# Classification Table",
            "",
            "| Domain | Venue | Year | Title | Relevance | Methods | Tags | TL;DR |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in rows_sorted:
            method_tags = _load(r.get("method_tags_json")) or []
            secondary = _load(r.get("domain_secondary_json")) or []
            title = (r.get("title") or "").replace("|", "/")
            tldr = (r.get("tldr") or "").replace("|", "/").replace("\n", " ")
            table_lines.append(
                f"| {r.get('domain_primary') or ''} "
                f"| {r.get('venue') or ''} "
                f"| {r.get('year') or ''} "
                f"| {title} "
                f"| {r.get('relevance') or ''} "
                f"| {', '.join(method_tags)} "
                f"| {', '.join(secondary)} "
                f"| {tldr} |"
            )
        (md_dir / "classification_table.md").write_text("\n".join(table_lines))

        # ---- survey.md grouped by domain
        by_domain = defaultdict(list)
        for r in rows_sorted:
            by_domain[r.get("domain_primary") or "Uncategorized"].append(r)

        lines = [
            "# AI Agent Survey — Draft",
            "",
            f"_Auto-generated from {len(rows)} papers across {cfg.years.start}-{cfg.years.end}._",
            "",
            "## Overview",
            "",
        ]
        dom_counts = Counter({k: len(v) for k, v in by_domain.items()})
        for k, v in dom_counts.most_common():
            lines.append(f"- **{k}**: {v}")
        lines.append("")

        for dom, items in sorted(by_domain.items(), key=lambda x: -len(x[1])):
            lines.append(f"## {dom} ({len(items)})")
            lines.append("")
            for r in items:
                venue = r.get("venue") or ""
                year = r.get("year") or ""
                title = r.get("title") or ""
                tldr = r.get("tldr") or ""
                url = r.get("url") or (
                    f"https://arxiv.org/abs/{r['arxiv_id']}" if r.get("arxiv_id") else ""
                )
                link = f"[{title}]({url})" if url else title
                lines.append(f"- **{link}** — *{venue} {year}*")
                if tldr:
                    lines.append(f"  - {tldr}")
            lines.append("")
        (md_dir / "survey.md").write_text("\n".join(lines))

        console.print(f"[green]wrote survey.md and classification_table.md to {md_dir}[/green]")
        return {"papers": len(rows), "domains": dict(dom_counts)}
    finally:
        db.close()
