"""Estimate DeepSeek API cost for venue-aware classification.

Usage (via CLI):
    agent-survey estimate-cost
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..config import Config
from ..console import console
from ..llm.prompts import (
    STAGE3_SYSTEM,
    STAGE3_USER_TEMPLATE,
    STAGE3_USER_TITLE_ONLY,
)

CORE_VENUES = {"ICSE", "FSE", "ASE", "ISSTA", "SP", "CCS", "USS", "NDSS"}

def _count_tokens_approx(text: str) -> int:
    return max(1, len(text) // 4)

def run(cfg: Config) -> dict:
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

    for venue, title, abstract in rows:
        is_core = venue in CORE_VENUES
        has_abs = bool(abstract and abstract.strip())
        if is_core:
            core_count += 1
            if has_abs:
                core_with_abstract += 1
                prompt = STAGE3_USER_TEMPLATE.format(
                    title=title or "", abstract=abstract, venue=venue or "", year="",
                    relevance_levels="...", domain_labels="...", method_labels="...",
                )
            else:
                prompt = STAGE3_USER_TITLE_ONLY.format(
                    title=title or "", venue=venue or "", year="",
                    relevance_levels="...", domain_labels="...", method_labels="...",
                )
            core_input_tokens += _count_tokens_approx(STAGE3_SYSTEM)
            core_input_tokens += _count_tokens_approx(prompt)
        else:
            noncore_count += 1
            prompt = STAGE3_USER_TITLE_ONLY.format(
                title=title or "", venue=venue or "", year="",
                relevance_levels="...", domain_labels="...", method_labels="...",
            )
            noncore_input_tokens += _count_tokens_approx(STAGE3_SYSTEM)
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

    HIT_RATE = 0.02
    hit_papers = int((core_count + noncore_count) * HIT_RATE)
    hit_input = int(total_input * HIT_RATE)
    hit_output = int(total_output * HIT_RATE)
    hit_cost = hit_input / 1_000_000 * INPUT_PRICE + hit_output / 1_000_000 * OUTPUT_PRICE
    console.print(f"\nIf only prefilter hits ({HIT_RATE:.0%}):   {hit_papers:,} papers, ${hit_cost:.2f}")

    return {
        "total_papers": core_count + noncore_count,
        "core_papers": core_count,
        "noncore_papers": noncore_count,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_tokens": total,
        "total_cost_usd": round(total_cost, 2),
    }
