"""
Heuristic Learning Skill System
================================

Skills capture the iterative, decision-driven business processes used to
build and maintain the survey_agent pipeline.  Each skill defines a
**procedure** — a sequence of probing, testing, and decision steps — that
an agent (human or AI) can follow to adapt the system to new venues, data
sources, or structural changes in target websites.

Why skills?
-----------
Traditional scrapers break when websites change.  This system uses skills
as a **heuristic learning layer**: when a stage fails for a venue, an agent
executes the corresponding skill to probe alternatives, select a working
strategy, and persist the result.  Over time the system accumulates a
growing knowledge base of venue → strategy mappings.

Skill categories
----------------
harvest_*   — Acquiring paper metadata (title, authors, year, DOI)
enrich_*    — Filling missing abstracts
validate_*  — Data quality checks
adapt_*     — Runtime adaptation to website changes

Usage
-----
    from skills import get_skill

    skill = get_skill("harvest_strategy")
    result = skill.execute(venue="FSE", year=2024)
    # result: {"strategy": "playwright:conf.researchr.org", "papers": 135}
"""

from __future__ import annotations

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent


def list_skills() -> list[str]:
    """List available skill names (from skill_*.py files)."""
    names = []
    for p in sorted(SKILL_DIR.glob("skill_*.py")):
        name = p.stem.replace("skill_", "")
        if not name.startswith("_"):
            names.append(name)
    return names


def get_skill(name: str):
    """Load a skill definition by name.  Returns a SkillDef dataclass."""
    mod_path = f"skills.skill_{name}"
    import importlib
    mod = importlib.import_module(mod_path, package="skills")
    return mod.SKILL


# Re-export for convenience
__all__ = ["get_skill", "list_skills", "SKILL_DIR"]
