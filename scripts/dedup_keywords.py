#!/usr/bin/env python3
"""Auto-deduplicate keywords using DeepSeek-Pro (reasoner).

Usage:
    conda activate survey_agent
    PYTHONPATH=src python scripts/dedup_keywords.py
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from agent_survey.core.config import load_config
from agent_survey.core.console import console
from agent_survey.services.llm import DeepSeekClient


def main():
    cfg = load_config()
    topic_name = cfg.active_topic or "llm-context-management"

    # Load raw keywords
    raw_path = cfg.abs_topic_dir(topic_name, "json") / "keywords_raw.json"
    raw = json.loads(raw_path.read_text())

    # Flatten and count frequency
    all_kw = []
    for item in raw:
        all_kw.extend(item["keywords"])

    freq = Counter([k.lower().strip() for k in all_kw])
    console.print(f"[dim]Total instances: {len(all_kw)}, unique: {len(freq)}[/dim]")

    # Build deduplication prompt
    # Include all unique keywords with frequency, sorted by frequency
    kw_lines = []
    for kw, cnt in freq.most_common():
        kw_lines.append(f"- {kw} ({cnt})")

    kw_block = "\n".join(kw_lines)

    system_msg = """You are an expert in academic keyword taxonomy and terminology standardization.

Your task is to deduplicate and organize a large list of keywords extracted from survey papers.

Rules:
1. Merge semantically similar keywords into one representative term. Examples:
   - "kv cache compression" + "kv cache reduction" + "kv cache pruning" → pick the most common or merge into a broader term
   - "retrieval-augmented generation" + "retrieval augmented generation" + "rag" → standardize to one form
   - "position interpolation" vs "length extrapolation" vs "length generalization" → keep as separate if they are truly distinct concepts
2. Remove overly generic terms: "deep learning", "neural network", "machine learning", "large language model", "natural language processing"
3. After deduplication, produce 50-100 most representative and specific keywords
4. Group them into 5-10 high-level categories

Output strict YAML only:"""

    user_msg = f"""Here is a list of {len(freq)} unique keywords extracted from {len(raw)} survey papers about LLM context management. Each keyword is shown with its frequency (number of papers that mentioned it):

{kw_block}

Please deduplicate and organize. Output strict YAML:"""

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

    console.print("[bold]Calling DeepSeek-Pro for global deduplication...[/bold]")
    deepseek = DeepSeekClient(cfg)
    resp = deepseek.client.chat.completions.create(
        model="deepseek-reasoner",
        messages=messages,
        temperature=0.0,
        max_tokens=4096,
    )
    raw_text = resp.choices[0].message.content or ""
    console.print(f"[dim]Raw response length: {len(raw_text)}[/dim]")

    # Extract YAML from response
    yaml_match = re.search(r"```ya?ml\s*(.*?)```", raw_text, re.DOTALL)
    if yaml_match:
        yaml_content = yaml_match.group(1).strip()
    else:
        # Maybe no code block
        yaml_content = raw_text.strip()

    # Save to tmp/
    tmp_dir = cfg.project_root / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    out_path = tmp_dir / "keywords_deduped.yaml"
    out_path.write_text(yaml_content, encoding="utf-8")

    console.print(f"[green]Deduplicated keywords saved to {out_path}[/green]")

    # Also save raw response for inspection
    raw_path = tmp_dir / "keywords_deduped_raw.txt"
    raw_path.write_text(raw_text, encoding="utf-8")
    console.print(f"[dim]Raw response saved to {raw_path}[/dim]")

    # Show preview
    lines = yaml_content.split("\n")
    console.print("\n[bold]Preview:[/bold]")
    for line in lines[:30]:
        console.print(line)
    if len(lines) > 30:
        console.print(f"... ({len(lines) - 30} more lines)")


if __name__ == "__main__":
    main()
