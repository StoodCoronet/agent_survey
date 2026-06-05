#!/usr/bin/env python3
"""
Mine survey/review papers from the DB by title only (fast coarse screening).

Usage:
    python scripts/mine_surveys.py [--topic TOPIC] [--output PATH]

Matches titles against survey keywords.  Optionally filters to papers that
passed prefilter for a specific topic.  Outputs paper list + venue/year stats.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_survey.core.config import load_config
from agent_survey.core.db import DB

# Title keywords for coarse survey detection
SURVEY_RE = re.compile(
    r"\b(survey|review|systematic\s+literature\s+review|SLR|"
    r"meta.analysis|overview|state.of.the.art|taxonom|"
    r"literature\s+analysis|research\s+landscape)",
    re.IGNORECASE,
)


def main():
    parser = argparse.ArgumentParser(description="Mine survey papers by title")
    parser.add_argument("--topic", "-t", default="", help="Filter to papers that passed prefilter for this topic")
    parser.add_argument("--output", "-o", default="", help="Output file (default: stdout)")
    parser.add_argument("--max-words", "-w", type=int, default=30, help="Max words for keyword extraction")
    args = parser.parse_args()

    cfg = load_config()
    db = DB(cfg.abs_path("db"))

    # Build query
    if args.topic:
        rows = db._conn.execute(
            """
            SELECT p.paper_id, p.title, p.venue, p.year, p.abstract
            FROM papers p
            JOIN paper_topics pt ON p.paper_id = pt.paper_id
            WHERE pt.topic_name = ? AND pt.prefilter_hit = 1
            """,
            (args.topic,),
        ).fetchall()
    else:
        rows = db._conn.execute(
            "SELECT paper_id, title, venue, year, abstract FROM papers"
        ).fetchall()

    # Filter by title only
    surveys = []
    for r in rows:
        title = r["title"] or ""
        if SURVEY_RE.search(title):
            surveys.append(dict(r))

    print(f"Total papers scanned: {len(rows)}")
    print(f"Survey candidates by title: {len(surveys)}\n")

    if not surveys:
        print("No survey papers found.")
        db.close()
        return

    # Stats
    venue_counter = Counter(r["venue"] for r in surveys)
    year_counter = Counter(str(r["year"]) for r in surveys)

    print("--- By Venue ---")
    for venue, c in venue_counter.most_common():
        print(f"  {venue}: {c}")

    print("\n--- By Year ---")
    for year, c in year_counter.most_common():
        print(f"  {year}: {c}")

    # Simple keyword extraction from titles
    stopwords = {
        "a", "an", "the", "and", "or", "of", "for", "in", "on", "with",
        "to", "from", "by", "using", "via", "based", " Towards", "towards",
        "survey", "review", "systematic", "literature", "analysis",
        "approach", "method", "methods", "paper", "papers", "study",
        "research", "work", "new", "novel",
    }
    title_words = Counter()
    for r in surveys:
        words = re.findall(r"[A-Za-z][a-z]*", r["title"])
        for w in words:
            w = w.lower()
            if w not in stopwords and len(w) > 2:
                title_words[w] += 1

    print("\n--- Top Title Keywords ---")
    for word, c in title_words.most_common(args.max_words):
        print(f"  {word}: {c}")

    # Output full list
    lines = ["\n--- Survey Papers ---\n"]
    for r in surveys:
        lines.append(f"[{r['venue']} {r['year']}] {r['title']}")
    out_text = "\n".join(lines)

    if args.output:
        Path(args.output).write_text(out_text, encoding="utf-8")
        print(f"\nWrote {len(surveys)} papers to {args.output}")
    else:
        print(out_text)

    db.close()


if __name__ == "__main__":
    main()
