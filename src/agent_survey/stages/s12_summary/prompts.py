"""Prompt builders for paper summary generation."""
from __future__ import annotations

_SYSTEM = """You are an academic paper summarizer.
Read the title and abstract, then write a concise summary in 3-4 sentences.
Return strict JSON only."""

_USER_TEMPLATE = """Title: {title}

Abstract:
{abstract}

Write a 3-4 sentence summary of this paper's core contribution in BOTH English and Chinese.

- English: clear, accessible to someone familiar with CS/AI but not the exact sub-field
- Chinese: natural academic Chinese, same length and level of detail as the English version

Return strict JSON:
{{"summary_en": "...", "summary_zh": "..."}}"""


def build_messages(title: str, abstract: str) -> list[dict]:
    """Build LLM messages for a single paper summary."""
    abstract = abstract.strip()[:4000]
    user = _USER_TEMPLATE.format(title=title, abstract=abstract)
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
