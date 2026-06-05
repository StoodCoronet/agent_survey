"""Survey mining: prompt builders and helper functions."""
from __future__ import annotations

import json
from pathlib import Path
import yaml


from ...core.config import load_stage_config


def _load_stage_config():
    """Load survey-mining config from stage-specific YAML, with defaults."""
    defaults = {
        "limit": 100,
        "llm": {"workers": 10, "batch_size": 100, "model": "deepseek-v4-flash",
                "temperature": 0.0, "max_tokens": 2048},
        "discovery": {"min_relevance": 0.6, "min_confidence": 0.5},
        "keywords": {"max_surveys": 20, "per_survey": 30, "min_frequency": 2},
    }
    data = load_stage_config("survey_mining")
    for section in defaults:
        if section in data:
            if isinstance(defaults[section], dict):
                defaults[section].update(data[section])
            else:
                defaults[section] = data[section]
    return defaults


_DEFAULT_DISCOVERY_SYSTEM = """You are a research librarian identifying survey/review/benchmark papers.
A "survey" must be one of: systematic review, literature review, survey, taxonomy,
OR a benchmark study covering MULTIPLE works (not just proposing one new method).
Return JSON: {"surveys": [{"idx": 0, "title": "Exact Title"}, {"idx": 3, "title": "Another Exact Title"}]}
Use the EXACT index and title from the list below. If idx and title mismatch, trust the title. NOTHING else."""


def build_discovery_prompt(topic_cfg, batch: list[dict]) -> list[dict]:
    """Build messages for survey discovery (Phase 1).  Reads prompt from topic config."""
    sm = getattr(topic_cfg, "survey_mining", None)
    system = (sm.discovery_system if sm and sm.discovery_system else _DEFAULT_DISCOVERY_SYSTEM)

    items = []
    for i, p in enumerate(batch):
        title = (p.get("title") or "")[:300]
        abstract = (p.get("abstract") or "")[:1500]
        items.append(f"[{i}] Title: {title}\n    Abstract: {abstract}")
    user = "Classify these papers:\n\n" + "\n\n".join(items)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_keyword_extraction_prompt(topic_name: str, topic_desc: str, paper_bodies: list[dict]) -> list[dict]:
    """Build prompt for keyword extraction from survey PDFs (Phase 3)."""
    system = f"""You are an expert at extracting technical terminology from academic papers.
Read survey papers about "{topic_name}" and extract ALL relevant
technical keywords, method names, benchmark names, and framework names.

Rules:
- Include specific techniques, benchmarks, framework names, key concepts
- Exclude generic words, author names, institution names
- Each keyword 1-5 words, lowercase preferred
- Include abbreviations AND expanded forms as separate entries

Return JSON: {{"keywords": ["term1", "term2", ...]}}
"""

    items = []
    for i, p in enumerate(paper_bodies):
        title = p.get("title", "")[:200]
        body = p.get("body", "")[:8000]
        items.append(f"--- Survey {i+1}: {title} ---\n{body}")
    user = f"Extract keywords from these surveys about {topic_name}:\n\n" + "\n\n".join(items)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
