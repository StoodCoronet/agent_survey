"""Prompt builders for sub-topic dedup stage."""
from __future__ import annotations


SE_VENUES = {"ICSE", "ASE", "FSE", "TSE", "TOSEM", "ISSTA"}
SEC_VENUES = {"SP", "CCS", "USS", "NDSS"}
AI_VENUES = {"ICLR", "NeurIPS", "ICML", "AAAI"}
NLP_VENUES = {"ACL", "EMNLP", "NAACL", "COLM"}
HCI_VENUES = {"CHI", "UIST"}


def venue_tier(venue: str | None) -> str:
    if not venue:
        return "other"
    v = venue.upper()
    if v in SE_VENUES or v in SEC_VENUES:
        return "se_sec"
    if v in AI_VENUES or v in NLP_VENUES or v in HCI_VENUES:
        return "ai_nlp_hci"
    return "other"


SUBTOPIC_SYSTEM_PROMPT = """You are an expert research assistant organizing AI-agent papers into fine-grained sub-topics.

Your task: read a batch of paper titles and abstracts, then assign each paper a concise sub-topic label.

Rules:
- Sub-topic names should be 2-5 words, in English, using kebab-case (e.g., "code-agent-benchmark", "prompt-injection-attack").
- Papers that share the same core method / problem should share the same sub-topic.
- Papers that tackle different challenges or use fundamentally different techniques should get different sub-topics.
- Re-use existing sub-topic names when appropriate; only create a new one if no existing label fits.
- Output strict JSON.
"""


def build_subtopic_messages(papers: list[dict], existing_subtopics: list[str]) -> list[dict]:
    paper_blocks = []
    for i, p in enumerate(papers, 1):
        block = f"""[{i}] Title: {p['title']}
Venue: {p.get('venue', '')} ({p.get('year', '')})
Relevance: {p.get('relevance', '')}
Abstract: {p.get('abstract', '')}"""
        paper_blocks.append(block)

    subtopic_hint = "\n".join(f"- {s}" for s in existing_subtopics) if existing_subtopics else "(none yet)"
    paper_blocks_joined = "\n---\n".join(paper_blocks)

    user = f"""Existing sub-topics observed so far (re-use when possible):
{subtopic_hint}

Papers to label ({len(papers)}):
---
{paper_blocks_joined}
---

Return JSON with exactly this key:
{{
  "papers": [
    {{
      "paper_idx": 1,
      "sub_topic": "code-agent-benchmark",
      "rationale": "one sentence explaining the label"
    }}
  ]
}}

Use concise, consistent sub-topic names across papers."""
    return [
        {"role": "system", "content": SUBTOPIC_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def dedup_system_prompt(scope: str) -> str:
    """Generate scope-specific dedup system prompt."""
    base = """You are an expert research surveyor deciding which papers in a batch should be kept for an in-depth survey.

Your task: identify groups of papers that represent the SAME line of work (same method, same problem, minor variations), and select which to KEEP.

CRITICAL venue bias (your user is a SE/Security researcher):
- SE venues (ICSE, ASE, FSE, TSE, TOSEM, ISSTA) and Security venues (CCS, USS, SP, NDSS) produce focused, high-quality work.
- AI/NLP/HCI venues (AAAI, ICLR, NeurIPS, ICML, ACL, EMNLP, NAACL, CHI, UIST) tend to have more incremental variations.

Retention priority (when choosing which paper to keep from a cluster):
  1. SE/Security venue > AI/NLP/HCI venue
  2. newer year > older year
  3. higher venue reputation (e.g., ICSE/CCS > workshop)

Also: if two papers tackle DIFFERENT challenges or research questions, KEEP BOTH even if methods overlap.
"""
    if scope == "core":
        strictness = """
DEDUP STRICTNESS: VERY CONSERVATIVE (core papers).
- ONLY remove papers that are clearly follow-ups, minor extensions, or near-identical reproductions.
- If a paper introduces even a small novel technique, new dataset, or new evaluation, KEEP it.
- Do NOT remove papers just because they use the same base method.
"""
    elif scope == "related":
        strictness = """
DEDUP STRICTNESS: MODERATE (related papers).
- Remove clear duplicates and minor extensions (same method, same problem, only benchmark/dataset differs slightly).
- Keep papers that introduce meaningful new techniques or tackle different research questions.
- Be willing to remove incremental work that does not add substantial new insights.
"""
    else:  # adjacent
        strictness = """
DEDUP STRICTNESS: AGGRESSIVE (adjacent papers).
- Remove papers that use the same method even on different datasets or benchmarks.
- Only keep the most representative or earliest paper for each line of work.
- Remove minor adaptations, ablation studies, and follow-up evaluations unless they introduce fundamentally new insights.
"""
    return base + strictness + "\nOutput strict JSON.\n"


def build_dedup_messages(papers: list[dict], scope: str) -> list[dict]:
    paper_blocks = []
    for i, p in enumerate(papers, 1):
        block = f"""[{i}] Title: {p['title']}
Venue: {p.get('venue', '')} ({p.get('year', '')})
Relevance: {p.get('relevance', '')}
Abstract: {p.get('abstract', '')}"""
        paper_blocks.append(block)

    paper_blocks_joined = "\n---\n".join(paper_blocks)

    user = f"""Papers to review ({len(papers)}):
---
{paper_blocks_joined}
---

Return JSON with exactly this key:
{{
  "decisions": [
    {{
      "paper_idx": 1,
      "keep": true,
      "reason": "representative work, first to propose X"
    }},
    {{
      "paper_idx": 2,
      "keep": false,
      "reason": "same method as [1], only dataset differs"
    }}
  ]
}}

For each paper, decide keep=true or keep=false.
If keep=false, explain which paper it duplicates or why it is incremental.
If a paper is the best/only representative of a distinct line of work, always keep it."""
    return [
        {"role": "system", "content": dedup_system_prompt(scope)},
        {"role": "user", "content": user},
    ]
