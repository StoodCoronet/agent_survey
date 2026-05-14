"""Keyword hit statistics across harvested papers.

Reads papers from SQLite, computes per-keyword / per-combination / per-venue
breakdowns, and writes a JSON + Markdown report for human review.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import yaml
from rich.progress import Progress

from ..core.config import Config
from ..core.console import console
from ..core.db import DB


def _compile(terms: list[str]) -> list[tuple[re.Pattern, str]]:
    out = []
    for t in terms:
        t_esc = re.escape(t).replace(r"\ ", r"[\s\-]+")
        pat = re.compile(rf"(?i)(?<![A-Za-z0-9]){t_esc}(?![A-Za-z0-9])")
        out.append((pat, t))
    return out


def _match(patterns: list[tuple[re.Pattern, str]], text: str) -> list[str]:
    return [term for pat, term in patterns if pat.search(text)]


def run(cfg: Config) -> dict:
    config_path = cfg.project_root / "config.yaml"
    db_path = cfg.abs_path("db")

    with open(config_path) as f:
        yaml_cfg = yaml.safe_load(f)
    kw = yaml_cfg["keywords"]

    core = _compile(kw["agent_core"])
    generic = _compile(kw["agent_generic"])
    se = _compile(kw["se_context"])
    sec = _compile(kw["sec_context"])

    core_counts = Counter()
    generic_counts = Counter()
    se_counts = Counter()
    sec_counts = Counter()

    core_by_abs = {"has": Counter(), "no": Counter()}
    generic_by_abs = {"has": Counter(), "no": Counter()}
    se_by_abs = {"has": Counter(), "no": Counter()}
    sec_by_abs = {"has": Counter(), "no": Counter()}

    core_by_venue = defaultdict(Counter)
    generic_by_venue = defaultdict(Counter)
    se_by_venue = defaultdict(Counter)
    sec_by_venue = defaultdict(Counter)

    core_by_year = defaultdict(Counter)
    generic_by_year = defaultdict(Counter)
    se_by_year = defaultdict(Counter)
    sec_by_year = defaultdict(Counter)

    core_unique = Counter()
    generic_unique = Counter()

    combo_counts = Counter()
    combo_by_venue = defaultdict(Counter)
    combo_by_year = defaultdict(Counter)

    total_papers = 0
    papers_with_abstract = 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    total_rows = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

    with Progress(console=console) as progress:
        task = progress.add_task("[cyan]keyword stats", total=total_rows)
        cur = conn.execute("SELECT title, abstract, venue, year FROM papers")

        for row in cur:
            total_papers += 1
            title = row["title"] or ""
            abstract = row["abstract"] or ""
            text = f"{title} {abstract}"
            has_abs = bool(abstract.strip())
            if has_abs:
                papers_with_abstract += 1

            venue = row["venue"] or "unknown"
            year = row["year"] or 0

            m_core = _match(core, text)
            m_generic = _match(generic, text)
            m_se = _match(se, text)
            m_sec = _match(sec, text)

            for term in m_core:
                core_counts[term] += 1
                core_by_abs["has" if has_abs else "no"][term] += 1
                core_by_venue[term][venue] += 1
                core_by_year[term][year] += 1

            for term in m_generic:
                generic_counts[term] += 1
                generic_by_abs["has" if has_abs else "no"][term] += 1
                generic_by_venue[term][venue] += 1
                generic_by_year[term][year] += 1

            for term in m_se:
                se_counts[term] += 1
                se_by_abs["has" if has_abs else "no"][term] += 1
                se_by_venue[term][venue] += 1
                se_by_year[term][year] += 1

            for term in m_sec:
                sec_counts[term] += 1
                sec_by_abs["has" if has_abs else "no"][term] += 1
                sec_by_venue[term][venue] += 1
                sec_by_year[term][year] += 1

            if len(m_core) == 1:
                core_unique[m_core[0]] += 1
            if len(m_generic) == 1:
                generic_unique[m_generic[0]] += 1

            if m_core:
                combo = "agent_core_only"
                combo_counts[combo] += 1
                combo_by_venue[combo][venue] += 1
                combo_by_year[combo][year] += 1
                if m_generic:
                    combo = "agent_core+generic"
                    combo_counts[combo] += 1
                    combo_by_venue[combo][venue] += 1
                    combo_by_year[combo][year] += 1
            elif m_generic and (m_se or m_sec):
                if m_se and m_sec:
                    combo = "generic+se+sec"
                elif m_se:
                    combo = "generic+se"
                else:
                    combo = "generic+sec"
                combo_counts[combo] += 1
                combo_by_venue[combo][venue] += 1
                combo_by_year[combo][year] += 1

            progress.advance(task)

    conn.close()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = cfg.project_root / "output" / "stats"
    output_dir.mkdir(parents=True, exist_ok=True)

    def _top_venue_dist(by_venue: dict, term: str, n: int = 5):
        c = by_venue.get(term, Counter())
        total = sum(c.values())
        top = c.most_common(n)
        return {"total": total, "top": top}

    def _keyword_detail(counts, by_abs, by_venue, by_year, unique=None):
        out = []
        for term, cnt in counts.most_common():
            item = {
                "term": term,
                "hits": cnt,
                "coverage_pct": round(cnt / total_papers * 100, 3),
                "with_abstract": by_abs["has"].get(term, 0),
                "without_abstract": by_abs["no"].get(term, 0),
                "abstract_dependency_pct": round(
                    by_abs["has"].get(term, 0) / cnt * 100, 1
                ) if cnt else 0,
                "unique_only": unique.get(term, 0) if unique else None,
                "top_venues": _top_venue_dist(by_venue, term)["top"],
                "year_dist": dict(by_year.get(term, Counter())),
            }
            out.append(item)
        return out

    data = {
        "meta": {
            "total_papers": total_papers,
            "papers_with_abstract": papers_with_abstract,
            "abstract_coverage_pct": round(papers_with_abstract / total_papers * 100, 1),
            "generated_at": ts,
        },
        "agent_core": _keyword_detail(core_counts, core_by_abs, core_by_venue, core_by_year, core_unique),
        "agent_generic": _keyword_detail(generic_counts, generic_by_abs, generic_by_venue, generic_by_year, generic_unique),
        "se_context": _keyword_detail(se_counts, se_by_abs, se_by_venue, se_by_year),
        "sec_context": _keyword_detail(sec_counts, sec_by_abs, sec_by_venue, sec_by_year),
        "combinations": {
            "counts": dict(combo_counts.most_common()),
            "by_venue": {k: dict(v.most_common(5)) for k, v in combo_by_venue.items()},
            "by_year": {k: dict(v) for k, v in combo_by_year.items()},
        },
    }

    json_path = output_dir / f"keyword_stats_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    md_lines = [
        f"# Keyword Statistics Report ({ts})",
        "",
        f"- Total papers: **{total_papers:,}**",
        f"- With abstract: **{papers_with_abstract:,}** ({data['meta']['abstract_coverage_pct']}%)",
        f"- Rule hits: **{sum(combo_counts.values()):,}**",
        "",
        "## Hit Rule Breakdown",
        "",
    ]
    for combo, cnt in combo_counts.most_common():
        pct = round(cnt / total_papers * 100, 2)
        md_lines.append(f"- **{combo}**: {cnt:,} ({pct}%)")
    md_lines.append("")

    def _md_section(title, items, show_unique=False):
        lines = [f"## {title}", ""]
        lines.append("| term | hits | coverage% | with_abs | without_abs | abs_dep% | " + ("unique_only | " if show_unique else "") + "top venues")
        lines.append("|------|------|-----------|----------|-------------|----------|" + ("------------|" if show_unique else "") + "----------|")
        for it in items:
            top_v = ", ".join(f"{v}({c})" for v, c in it["top_venues"])
            uniq = f" {it['unique_only'] or 0} |" if show_unique else ""
            lines.append(
                f"| {it['term']} | {it['hits']} | {it['coverage_pct']}% | "
                f"{it['with_abstract']} | {it['without_abstract']} | {it['abstract_dependency_pct']}% |{uniq} {top_v}"
            )
        lines.append("")
        return lines

    md_lines.extend(_md_section("agent_core (hit = include)", data["agent_core"], show_unique=True))
    md_lines.extend(_md_section("agent_generic (need se/sec context)", data["agent_generic"], show_unique=True))
    md_lines.extend(_md_section("se_context", data["se_context"]))
    md_lines.extend(_md_section("sec_context", data["sec_context"]))

    zero_terms = []
    for group in ["agent_core", "agent_generic", "se_context", "sec_context"]:
        zero_terms += [it["term"] for it in data[group] if it["hits"] == 0]
    md_lines.extend([
        "## Heuristics", "",
        "### Zero-hit keywords", "",
    ])
    md_lines.append(", ".join(f"`{t}`" for t in zero_terms) if zero_terms else "None.")
    md_lines.append("")

    md_path = output_dir / f"keyword_stats_{ts}.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))

    console.print(f"[green]JSON: {json_path}[/green]")
    console.print(f"[green]Markdown: {md_path}[/green]")
    return data
