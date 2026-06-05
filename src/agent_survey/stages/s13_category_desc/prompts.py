"""Prompt builders for category-desc stage."""
from __future__ import annotations


def build_dimension_prompt(tree_name: str, sub_categories: list[str]) -> list[dict]:
    system = (
        "You are a research taxonomy expert. "
        "Explain the rationale behind a taxonomy dimension in AI-agent research. "
        "Respond with strict JSON only."
    )
    cats_block = "\n".join(f"- {sc}" for sc in sub_categories)
    user = f"""Our survey taxonomy has a dimension called "{tree_name}". It is divided into the following sub-categories:
{cats_block}

Please write a concise bilingual description:
1. What this dimension captures in AI-agent research
2. Why these sub-categories are grouped under this dimension (what is the organising principle?)
3. What aspects of agent research this classification tries to organise

Requirements:
- 3-4 sentences in English (desc_en)
- 3-4 sentences in Chinese (desc_zh)
- Keep it accessible to someone unfamiliar with the field
- Do NOT mention individual papers; this is a meta-level description of the dimension itself

Return strict JSON:
{{
  "desc_en": "...",
  "desc_zh": "..."
}}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_stage_a_prompt(tree_name: str, path: str, papers: list[dict], target_selected: int = 20) -> list[dict]:
    parts = path.split("/")
    level = len(parts)

    abstracts_block = "\n\n---\n\n".join(
        f"[{i+1}] {p['paper_id']}\nTitle: {p.get('title', '')}\nVenue: {p.get('venue', '')} ({p.get('year', '')})\nAbstract: {p.get('abstract') or '(no abstract)'}"
        for i, p in enumerate(papers)
    )

    system = (
        "You are a research survey expert. Your task is to pick the most representative papers "
        "from a list of abstracts so that a later LLM can write a high-quality category description. "
        "Respond with strict JSON only."
    )

    user = f"""We need to write a description for taxonomy category: "{path}"
Tree: {tree_name}  |  Level: {level}

Below are {len(papers)} papers belonging to this category. Each has an ID, title, venue, year, and abstract.

Selection rules (in order of importance):
1. DIVERSITY — pick papers that cover *different* angles / methods within this category. Avoid abstracts that look like minor variants of the same idea.
2. RECENCY — prefer 2025/2024 over 2023. Only include 2023 if it is a foundational/unique work.
3. VENUE — top-tier venues (ICSE, FSE, ASE, ISSTA, S&P, CCS, USENIX Security, NDSS, TOSEM, TSE) are preferred.
4. DEPTH — prefer papers with richer abstracts (detailed method, evaluation, dataset) over shallow / teaser abstracts.

Please select exactly {target_selected} paper IDs (use the `paper_id` field) that together give the best overview of this category. If fewer than {target_selected} papers exist, return all of them.

{abstracts_block}

Return strict JSON:
{{
  "selected_paper_ids": ["paper_id_1", "paper_id_2", ...],
  "reasoning": "brief explanation of why these papers were chosen"
}}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_stage_b_prompt(tree_name: str, path: str, level: int, snippets: list[tuple[str, str]]) -> list[dict]:
    parts = path.split("/")
    parent = parts[-2] if level > 1 else "(root)"
    leaf = parts[-1]

    papers_text = "\n\n---\n\n".join(
        f"Paper: {title}\n{body[:2500]}" for title, body in snippets
    )

    if level == 1:
        emphasis = (
            "This is a SUB-CATEGORY (first level under the dimension). "
            "Use plain, accessible language to explain what this sub-field does. "
            "What is the typical goal? What kind of tasks or problems do researchers in this area tackle?"
        )
    else:
        emphasis = (
            "This is a LEAF category (concrete direction). Describe the specific techniques, core methods, and main challenges. "
            "What makes this direction distinct from sibling categories?"
        )

    system = (
        "You are a research taxonomy expert. Based on the provided paper excerpts, "
        "write a concise bilingual description of what this taxonomy category represents. "
        "Respond with strict JSON only."
    )

    user = f"""Category: "{path}"
Tree: {tree_name}
Level: {level} (parent = "{parent}")
Selected papers for analysis: {len(snippets)}

Emphasis: {emphasis}

Paper excerpts:
{papers_text}

Requirements:
- 3-4 sentences in English (desc_en)
- 3-4 sentences in Chinese (desc_zh)
- Focus on what kind of research this category covers
- Mention the typical tasks, methods, or goals
- Keep it accessible to someone unfamiliar with the field

Also provide structured metadata about this category:
- methods: list of 2-5 typical methods / techniques used in this category (strings)
- datasets: list of 0-5 commonly used datasets or benchmarks (strings)
- trends: one sentence describing the recent trend or evolution of this category

Return strict JSON:
{{
  "desc_en": "...",
  "desc_zh": "...",
  "metadata": {{
    "methods": ["..."],
    "datasets": ["..."],
    "trends": "..."
  }}
}}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
