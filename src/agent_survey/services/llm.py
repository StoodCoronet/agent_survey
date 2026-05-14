"""DeepSeek client via the OpenAI-compatible endpoint."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..core.config import Config
from ..core.db import DB


def input_hash(stage: str, model: str, prompt_version: str, messages: list[dict]) -> str:
    h = hashlib.sha256()
    h.update(stage.encode())
    h.update(b"|")
    h.update(model.encode())
    h.update(b"|")
    h.update(prompt_version.encode())
    h.update(b"|")
    h.update(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode())
    return h.hexdigest()[:32]


class DeepSeekClient:
    def __init__(self, cfg: Config):
        if not cfg.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not set in .env")
        self.client = OpenAI(
            api_key=cfg.deepseek_api_key,
            base_url=cfg.deepseek_base_url,
        )

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30))
    def chat_json(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        resp = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # best-effort cleanup
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                data = json.loads(content[start : end + 1])
            else:
                raise
        usage = getattr(resp, "usage", None)
        return {
            "content": data,
            "raw": content,
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            } if usage else None,
            "model": model,
        }


def cached_chat_json(
    client: DeepSeekClient,
    db: DB,
    *,
    paper_id: str,
    stage: str,
    model: str,
    prompt_version: str,
    messages: list[dict],
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    ih = input_hash(stage, model, prompt_version, messages)
    hit = db.get_llm_cached(ih)
    if hit and hit.get("response"):
        resp = dict(hit["response"])
        resp["cached"] = True
        return resp
    result = client.chat_json(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    result["cached"] = False
    db.save_llm_call(
        paper_id=paper_id,
        stage=stage,
        model=model,
        prompt_version=prompt_version,
        input_hash=ih,
        response=result,
    )
    return result


# ------------------------------------------------------------------
# Prompt templates for the LLM stages
# ------------------------------------------------------------------

DOMAIN_LABELS = [
    "GUI Agent",
    "Web Agent",
    "Computer-Use Agent",
    "SE Agent",
    "Security Agent",
    "Agent Safety & Privacy",
    "General LLM Agent",
]

METHOD_LABELS = [
    "Benchmark/Dataset",
    "Framework/System",
    "Empirical Study",
    "Attack",
    "Defense/Mitigation",
    "Evaluation Method",
    "Application",
]

RELEVANCE_LEVELS = ["core", "related", "adjacent", "irrelevant"]


STAGE3_SYSTEM = """You are a meticulous research assistant helping survey AI agent papers.
You must respond with a strict JSON object only.

Classification criteria (map paper content to these buckets):

1. RELEVANCE — four levels
   • core — the paper is about computer-use / GUI / Web / Mobile / OS / Desktop agents, or cites well-known computer-use benchmarks/systems such as OSWorld, WebArena, Mind2Web, VisualWebArena, GAIA, AgentBench, SWE-bench, computer-use, GUI automation, web navigation, screen agent, mobile agent, desktop agent, UI agent, app agent, tool-use/function-calling for UI control, etc.
   • related — the paper applies LLM agents to software engineering (testing, fuzzing, debugging, code generation, program repair, program analysis, vulnerability discovery, benchmark) OR to security/privacy (prompt injection, jailbreak, adversarial attack/defense, red-teaming, automated exploitation, malware analysis, agent security). This also includes agent-based SE tools such as code agents, test-generation agents, and software agents.
   • adjacent — general LLM-agent work (multi-agent systems, planning, reasoning, tool-use frameworks, autonomous agents, ReAct) that is NOT directly about computer-use, SE, or security.
   • irrelevant — not an agent paper, or agent work completely unrelated to the above.

2. DOMAIN — pick ONE primary
   • GUI Agent — operates through graphical user interfaces (desktop, mobile, web GUI).
   • Web Agent — specifically web browsing / web navigation.
   • Computer-Use Agent — general computer-use agents (OS-level, desktop automation, cross-app).
   • SE Agent — agent applied to software engineering (code, testing, debugging, repair, analysis).
   • Security Agent — agent applied to security tasks (attack, defense, red-team, vulnerability).
   • Agent Safety & Privacy — safety, alignment, privacy risks of agents themselves.
   • General LLM Agent — multi-agent, planning, reasoning, tool-use frameworks without a specific domain above.

3. METHOD — pick 1–3 tags
   • Benchmark/Dataset — introduces or uses a benchmark/dataset.
   • Framework/System — proposes an architecture, framework, or system.
   • Empirical Study — measurement, user study, or large-scale analysis.
   • Attack — adversarial or offensive technique.
   • Defense/Mitigation — protective technique.
   • Evaluation Method — new metric or evaluation protocol.
   • Application — concrete real-world application or case study.
"""


STAGE3_USER_TEMPLATE = """You are labeling ONE paper for an AI-agent survey focused on computer-use / GUI agents, with a secondary focus on software engineering and security/privacy.

Paper:
- Title: {title}
- Venue: {venue} ({year})
- Abstract: {abstract}

Label it with:

1. `relevance`: one of {relevance_levels}.
   - core: main topic is computer-use / GUI / Web / Mobile / OS / Desktop agent
   - related: LLM agent applied to software engineering (testing, debugging, code gen, program analysis, vuln discovery) OR security/privacy attack/defense involving agents
   - adjacent: general LLM agent work (framework, planning, tool use) not directly computer-use / SE / security
   - irrelevant: not an agent paper, or agent but unrelated to any of the above

2. `domain_primary`: pick ONE from {domain_labels}. Required.

3. `domain_secondary`: zero or more additional labels from {domain_labels}. Omit if none.

4. `method_tags`: 1-3 labels from {method_labels}.

5. `tldr`: one sentence (<=30 words), plain English, what the paper does.

6. `rationale`: one short sentence explaining the relevance choice.

Return strict JSON:
{{"relevance": "...", "domain_primary": "...", "domain_secondary": [...], "method_tags": [...], "tldr": "...", "rationale": "..."}}
If abstract is missing, use only title; still return best-effort labels but lower the relevance confidence.
"""

STAGE3_USER_TITLE_ONLY = """You are labeling ONE paper for an AI-agent survey focused on computer-use / GUI agents, with a secondary focus on software engineering and security/privacy.

Paper:
- Title: {title}
- Venue: {venue} ({year})

⚠️ Only the title is available (no abstract). Make your best judgment from the title alone. Be slightly more inclusive than strict — if the title hints at agent, computer use, GUI, web/mobile interaction, or SE/security automation, mark it as at least "related".

Label it with:

1. `relevance`: one of {relevance_levels}.
   - core: main topic is computer-use / GUI / Web / Mobile / OS / Desktop agent
   - related: LLM agent applied to software engineering (testing, debugging, code gen, program analysis, vuln discovery) OR security/privacy attack/defense involving agents
   - adjacent: general LLM agent work (framework, planning, tool use) not directly computer-use / SE / security
   - irrelevant: not an agent paper, or agent but unrelated to any of the above

2. `domain_primary`: pick ONE from {domain_labels}. Required.

3. `domain_secondary`: zero or more additional labels from {domain_labels}. Omit if none.

4. `method_tags`: 1-3 labels from {method_labels}.

5. `tldr`: one sentence (<=30 words), plain English, what the paper does.

6. `rationale`: one short sentence explaining the relevance choice.

Return strict JSON:
{{"relevance": "...", "domain_primary": "...", "domain_secondary": [...], "method_tags": [...], "tldr": "...", "rationale": "..."}}
"""


def build_classify_messages(title: str, abstract: str, venue: str, year: int | None) -> list[dict]:
    user = STAGE3_USER_TEMPLATE.format(
        title=title,
        abstract=abstract or "(not available)",
        venue=venue or "",
        year=year or "",
        relevance_levels=RELEVANCE_LEVELS,
        domain_labels=DOMAIN_LABELS,
        method_labels=METHOD_LABELS,
    )
    return [
        {"role": "system", "content": STAGE3_SYSTEM},
        {"role": "user", "content": user},
    ]


STAGE5_SYSTEM = """You are a careful research assistant extracting structured information from a paper's text.
You must respond with a strict JSON object only."""


STAGE5_USER_TEMPLATE = """Analyze the following paper text and extract a structured summary.

Title: {title}
Venue: {venue} ({year})

Paper text (truncated if long):
---
{body}
---

Extract JSON with these keys:
- problem: What problem or gap does this paper address? (1-3 sentences)
- approach: Core method / system design. (2-5 sentences, bullet-ish)
- novelty: What is genuinely new vs prior work? (1-2 sentences)
- evaluation: How is it evaluated — datasets, metrics, benchmarks, baselines. (2-4 sentences)
- datasets: list of dataset / benchmark names used or proposed. Empty list if none identified.
- key_results: 1-3 bullet strings of the main quantitative/qualitative findings.
- code_url: URL if mentioned, else null.
- limitations: 1-3 short bullet strings.
- computer_use_relevance: short note on how this relates to computer-use / GUI agent / SE / security (<=40 words).

Return strict JSON only."""


def build_deepdive_messages(title: str, venue: str, year: int | None, body: str) -> list[dict]:
    user = STAGE5_USER_TEMPLATE.format(
        title=title, venue=venue or "", year=year or "", body=body
    )
    return [
        {"role": "system", "content": STAGE5_SYSTEM},
        {"role": "user", "content": user},
    ]
