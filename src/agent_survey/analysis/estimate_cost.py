"""Estimate DeepSeek API cost for venue-aware classification.

Usage (via CLI):
    agent-survey estimate-cost
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..core.config import Config, load_topic_config, resolve_topic
from ..core.console import console


def _count_tokens_approx(text: str) -> int:
    return max(1, len(text) // 4)


def run(cfg: Config, topic_name: str = "") -> dict:
    topic_name = resolve_topic(topic_name, cfg)
    tc = load_topic_config(topic_name)
    classify_cfg = tc.classify

    core_venues = set(classify_cfg.core_venues)
    db_path = cfg.abs_path("db")
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT venue, title, abstract FROM papers").fetchall()
    conn.close()

    core_count = 0
    noncore_count = 0
    core_with_abstract = 0
    core_input_tokens = 0
    noncore_input_tokens = 0
    output_tokens = 0
    OUTPUT_TOKENS_PER_PAPER = 120

    sys_tokens = _count_tokens_approx(classify_cfg.system_prompt)

    for venue, title, abstract in rows:
        is_core = venue in core_venues
        has_abs = bool(abstract and abstract.strip())
        if is_core:
            core_count += 1
            if has_abs:
                core_with_abstract += 1
                prompt = classify_cfg.user_prompt_template.format(
                    title=title or "", abstract=abstract, venue=venue or "", year="",
                    relevance_levels=classify_cfg.relevance_levels,
                    domain_labels=classify_cfg.domain_labels,
                    method_labels=classify_cfg.method_labels,
                )
            else:
                prompt = classify_cfg.user_prompt_title_only.format(
                    title=title or "", venue=venue or "", year="",
                    relevance_levels=classify_cfg.relevance_levels,
                    domain_labels=classify_cfg.domain_labels,
                    method_labels=classify_cfg.method_labels,
                )
            core_input_tokens += sys_tokens
            core_input_tokens += _count_tokens_approx(prompt)
        else:
            noncore_count += 1
            prompt = classify_cfg.user_prompt_title_only.format(
                title=title or "", venue=venue or "", year="",
                relevance_levels=classify_cfg.relevance_levels,
                domain_labels=classify_cfg.domain_labels,
                method_labels=classify_cfg.method_labels,
            )
            noncore_input_tokens += sys_tokens
            noncore_input_tokens += _count_tokens_approx(prompt)
        output_tokens += OUTPUT_TOKENS_PER_PAPER

    total_input = core_input_tokens + noncore_input_tokens
    total_output = output_tokens
    total = total_input + total_output

    INPUT_PRICE = 0.14
    OUTPUT_PRICE = 0.28
    input_cost = total_input / 1_000_000 * INPUT_PRICE
    output_cost = total_output / 1_000_000 * OUTPUT_PRICE
    total_cost = input_cost + output_cost

    console.print("=" * 60)
    console.print("DeepSeek API Cost Estimate")
    console.print("=" * 60)
    console.print(f"\nTopic: {topic_name}")
    console.print(f"\nPapers:")
    console.print(f"  Core venues (title+abstract):    {core_count:,}")
    console.print(f"    - with abstract:               {core_with_abstract:,}")
    console.print(f"    - without abstract:            {core_count - core_with_abstract:,}")
    console.print(f"  Non-core venues (title-only):    {noncore_count:,}")
    console.print(f"  Total:                           {core_count + noncore_count:,}")
    console.print(f"\nTokens:")
    console.print(f"  Input (core):                    {core_input_tokens:>12,}")
    console.print(f"  Input (non-core):                {noncore_input_tokens:>12,}")
    console.print(f"  Input (total):                   {total_input:>12,}")
    console.print(f"  Output (all):                    {total_output:>12,}")
    console.print(f"  Total:                           {total:>12,}")
    console.print(f"\nCost (USD):")
    console.print(f"  Input:                           ${input_cost:>10.2f}")
    console.print(f"  Output:                          ${output_cost:>10.2f}")
    console.print(f"  Total:                           ${total_cost:>10.2f}")
    console.print(f"\nPer-paper avg:                     ${total_cost / (core_count + noncore_count):.4f}")

    return {
        "topic": topic_name,
        "total_papers": core_count + noncore_count,
        "core_papers": core_count,
        "noncore_papers": noncore_count,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_tokens": total,
        "total_cost_usd": round(total_cost, 2),
    }
