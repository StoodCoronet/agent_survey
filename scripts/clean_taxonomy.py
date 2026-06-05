#!/usr/bin/env python3
"""Clean up taxonomy_json data in DB before/after classification.

Run this before generate-docs or after a taxonomy re-run to fix common
LLM-output artifacts (trailing slashes, inconsistent casing, etc.).

Usage:
    python scripts/clean_taxonomy.py --topic llm-context-management [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_survey.core.config import load_config
from agent_survey.core.db import DB


def _fix_trailing_slashes(tax: dict) -> bool:
    """Strip trailing '/' from leaf paths (but preserve ' / ' inside leaf names)."""
    changed = False
    for tree_name, leaves in tax.items():
        if not isinstance(leaves, list):
            continue
        new_leaves = []
        for leaf in leaves:
            if isinstance(leaf, str) and leaf.endswith("/") and not leaf.endswith(" / "):
                leaf = leaf[:-1]
                changed = True
            new_leaves.append(leaf)
        tax[tree_name] = new_leaves
    return changed


def _fix_missing_tree_prefix(tax: dict) -> bool:
    """Add tree-name prefix to bare leaf paths if missing."""
    changed = False
    for tree_name, leaves in tax.items():
        if not isinstance(leaves, list):
            continue
        new_leaves = []
        for leaf in leaves:
            if isinstance(leaf, str) and "/" not in leaf and leaf != "Other":
                leaf = f"{tree_name}/{leaf}"
                changed = True
            new_leaves.append(leaf)
        tax[tree_name] = new_leaves
    return changed


def _fix_inconsistent_other(tax: dict) -> bool:
    """Normalise 'other' → 'Other' in leaf paths."""
    changed = False
    for tree_name, leaves in tax.items():
        if not isinstance(leaves, list):
            continue
        new_leaves = []
        for leaf in leaves:
            if isinstance(leaf, str) and leaf.lower().endswith("/other"):
                parts = leaf.rsplit("/", 1)
                leaf = f"{parts[0]}/Other"
                changed = True
            new_leaves.append(leaf)
        tax[tree_name] = new_leaves
    return changed


def _fix_research_goal_slash_names(tax: dict) -> bool:
    """Ensure research-goal leaf names with internal '/' are kept intact."""
    changed = False
    rg = tax.get("research-goal", [])
    if not isinstance(rg, list):
        return changed
    valid = {
        "Novel Method / Algorithm",
        "Framework / System",
        "Benchmark / Dataset",
        "Empirical Study / Analysis",
        "Survey / Position Paper",
        "Theoretical Analysis",
        "Other",
    }
    new_leaves = []
    for leaf in rg:
        if isinstance(leaf, str) and "/" in leaf and leaf not in valid:
            # Heuristic: if it looks like a broken split, rejoin
            parts = [p.strip() for p in leaf.split("/")]
            if len(parts) == 2 and parts[1] in ("Algorithm", "System", "Dataset", "Analysis", "Paper"):
                reconstructed = f"{parts[0]} / {parts[1]}"
                if reconstructed in valid:
                    leaf = reconstructed
                    changed = True
        new_leaves.append(leaf)
    tax["research-goal"] = new_leaves
    return changed


def _remove_empty_trees(tax: dict) -> bool:
    """Remove tree entries that are empty lists."""
    changed = False
    empty_keys = [k for k, v in tax.items() if isinstance(v, list) and len(v) == 0]
    for k in empty_keys:
        del tax[k]
        changed = True
    return changed


def main():
    parser = argparse.ArgumentParser(description="Clean taxonomy_json in DB")
    parser.add_argument("--topic", "-t", default="", help="Topic name")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing to DB")
    args = parser.parse_args()

    cfg = load_config()
    db = DB(cfg.abs_path("db"))
    topic = args.topic or cfg.active_topic
    if not topic:
        print("No topic specified.")
        return

    rows = db.conn.execute(
        "SELECT paper_id, taxonomy_json FROM paper_topics WHERE topic_name = ? AND taxonomy_json IS NOT NULL",
        (topic,),
    ).fetchall()

    total = len(rows)
    fixed_any = 0
    fixed_slash = 0
    fixed_prefix = 0
    fixed_other = 0
    fixed_rg = 0
    fixed_empty = 0

    for paper_id, tax_json in rows:
        try:
            tax = json.loads(tax_json)
        except json.JSONDecodeError:
            continue
        if not isinstance(tax, dict):
            continue

        c1 = _fix_trailing_slashes(tax)
        c2 = _fix_missing_tree_prefix(tax)
        c3 = _fix_inconsistent_other(tax)
        c4 = _fix_research_goal_slash_names(tax)
        c5 = _remove_empty_trees(tax)

        if c1:
            fixed_slash += 1
        if c2:
            fixed_prefix += 1
        if c3:
            fixed_other += 1
        if c4:
            fixed_rg += 1
        if c5:
            fixed_empty += 1

        if c1 or c2 or c3 or c4 or c5:
            fixed_any += 1
            new_json = json.dumps(tax, ensure_ascii=False)
            if not args.dry_run:
                db.conn.execute(
                    "UPDATE paper_topics SET taxonomy_json = ? WHERE paper_id = ? AND topic_name = ?",
                    (new_json, paper_id, topic),
                )
            else:
                print(f"[DRY-RUN] {paper_id}: {tax_json[:120]}...")

    if not args.dry_run:
        db.conn.commit()

    print(f"\nTopic: {topic}")
    print(f"Total papers with taxonomy: {total}")
    print(f"Papers fixed: {fixed_any}")
    print(f"  Trailing slashes: {fixed_slash}")
    print(f"  Missing tree prefix: {fixed_prefix}")
    print(f"  Inconsistent 'other': {fixed_other}")
    print(f"  Research-goal names: {fixed_rg}")
    print(f"  Empty trees removed: {fixed_empty}")
    if args.dry_run:
        print("\n(Dry run — no changes written to DB)")


if __name__ == "__main__":
    main()
