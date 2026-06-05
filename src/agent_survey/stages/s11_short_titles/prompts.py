"""Prompt builders for short-titles stage."""
from __future__ import annotations

_SYSTEM = """You are a research assistant creating concise abbreviations for academic paper titles.
Respond with strict JSON only."""

_USER_TEMPLATE = """Below are {n} academic papers. For each, provide a short abbreviation (≤35 chars) of the TITLE that preserves the key concept.

The EXCERPT from the paper's PDF is provided to help you understand the actual contribution so the abbreviation is accurate and distinctive.

CRITICAL: The final collection contains thousands of papers. Every abbreviation MUST be UNIQUE and easily distinguishable from others. Do NOT produce generic abbreviations.

Rules:
- Keep well-known acronyms (e.g., LLM, GUI, OSWorld, WebArena)
- Remove filler words like "A Survey of", "Towards", "Exploring", "Investigating" when possible
- Prefer "Method: Task" format when applicable
- Preserve DISTINCTIVE keywords (method name, dataset name, domain, or specific technique) to avoid duplicates
- If two titles would naturally abbreviate to the same thing, add a distinguishing word to make them unique
- If title is already ≤50 chars, keep it as-is

Papers:
{papers}

Return JSON: {{"mapping": {"<full_title>": "<short_title>", ...}}}
"""

_RETRY_TEMPLATE = """Some abbreviations you generated are DUPLICATE or too generic. Below are the problematic titles and the conflicting abbreviations already in use.

Please regenerate UNIQUE abbreviations for these titles only. Make sure each new abbreviation is clearly different from the existing ones listed below.

Existing abbreviations (do NOT reuse):
{existing}

Titles to fix (one per line):
{titles}

Return JSON: {{"mapping": {"<full_title>": "<short_title>", ...}}}
"""
