"""Taxonomy classification trees and prompt building.

Three independent trees:
1. application-domain   — where the agent operates
2. technical-approach   — core technique
3. research-goal        — what the paper studies

Plus cross-cutting tags that can appear under any leaf.
"""
from __future__ import annotations

import json
from typing import Any

# ------------------------------------------------------------------
# Tree skeletons (manually curated; LLM maps papers to leaf paths)
# ------------------------------------------------------------------

TREES: dict[str, dict] = {
    "application-domain": {
        "web-agent": [
            "web-navigation",
            "web-shop",
            "web-information-seeking",
            "web-task-automation",
            "web-h5-hybrid",
        ],
        "mobile-agent": [
            "android-native",
            "ios-native",
            "mobile-cross-platform",
        ],
        "desktop-agent": [
            "os-level-control",
            "gui-app-control",
            "code-ide-integration",
        ],
        "code-agent": [
            "code-generation",
            "code-repair",
            "test-generation",
            "repo-level-understanding",
        ],
        "embodied-agent": [
            "robot-manipulation",
            "vision-language-navigation",
            "game-playing-agent",
        ],
        "scientific-research-agent": [
            "literature-review",
            "experiment-design",
            "data-analysis",
        ],
        "creative-agent": [
            "content-generation",
            "design-assistant",
        ],
        "multi-domain-agent": [],
    },
    "technical-approach": {
        "planning": [
            "llm-planning",
            "symbolic-planning",
            "hierarchical-planning",
        ],
        "learning": [
            "rl-based",
            "imitation-learning",
            "self-improvement",
        ],
        "tool-use": [
            "function-calling",
            "tool-learning",
            "retrieval-augmented",
        ],
        "multi-agent": [
            "collaborative-agent",
            "competitive-agent",
            "role-playing-agent",
        ],
        "perception": [
            "gui-grounding",
            "vision-language-model",
            "web-page-understanding",
        ],
        "memory": [
            "episodic-memory",
            "semantic-memory",
            "long-context",
        ],
        "deep-research": [
            "tool-chain-orchestration",
            "iterative-verification",
            "multi-source-synthesis",
        ],
        "safety-alignment": [
            "guardrail",
            "human-in-the-loop",
            "constrained-generation",
        ],
    },
    "research-goal": {
        "benchmark-evaluation": [
            "new-benchmark",
            "comprehensive-evaluation",
            "ablation-study",
        ],
        "attack-redteam": [
            "jailbreak-attack",
            "prompt-injection",
            "adversarial-manipulation",
            "automated-redteaming",
        ],
        "defense-security": [
            "prompt-defense",
            "agent-sandboxing",
            "monitoring-detection",
            "privacy-protection",
        ],
        "framework-system": [
            "agent-architecture",
            "tool-ecosystem",
            "workflow-orchestration",
        ],
        "dataset-resource": [
            "training-dataset",
            "synthetic-data",
            "annotation-tool",
        ],
        "analysis-survey": [
            "taxonomy-survey",
            "failure-analysis",
            "capability-assessment",
        ],
    },
}

CROSS_CUTTING_TAGS = [
    "performance",
    "testing-verification",
    "attack-vulnerability",
    "defense-mitigation",
    "benchmark-evaluation",
]


def _format_tree() -> str:
    """Return a human-readable description of the taxonomy trees."""
    lines = []
    for tree_name, branches in TREES.items():
        lines.append(f"\n## {tree_name}")
        for branch, leaves in branches.items():
            if leaves:
                lines.append(f"  {branch}/")
                for leaf in leaves:
                    lines.append(f"    - {leaf}")
            else:
                lines.append(f"  {branch}/ (leaf node, no sub-branches)")
    lines.append("\n## cross-cutting tags (can appear under any leaf)")
    for tag in CROSS_CUTTING_TAGS:
        lines.append(f"  - {tag}")
    return "\n".join(lines)


SYSTEM_PROMPT = """You are an expert research taxonomist classifying AI-agent papers into a multi-dimensional taxonomy.

Rules:
- A paper can belong to MULTIPLE trees and MULTIPLE paths within each tree.
- Assign paths at the LEAF level (e.g., "web-agent/web-navigation", not just "web-agent").
- If a paper does not fit any existing leaf, propose a new leaf name (kebab-case).
- Cross-cutting tags are secondary attributes, not primary tree paths.
- Output strict JSON only."""


def build_messages(papers: list[dict]) -> list[dict]:
    """Build LLM messages for a batch of papers."""
    paper_blocks = []
    for i, p in enumerate(papers, 1):
        block = f"""[{i}] Title: {p['title']}
Venue: {p.get('venue', '')} ({p.get('year', '')})
Abstract: {p.get('abstract', '')}"""
        paper_blocks.append(block)

    user = f"""Classify the following papers using this taxonomy:

{_format_tree()}

For each paper, assign:
1. One or more leaf paths per tree (e.g., "application-domain/web-agent/web-navigation")
2. Zero or more cross-cutting tags

Papers to classify ({len(papers)}):
---
{"\n---\n".join(paper_blocks)}
---

Return strict JSON:
{{
  "papers": [
    {{
      "paper_idx": 1,
      "application_domain": ["web-agent/web-navigation"],
      "technical_approach": ["planning/llm-planning"],
      "research_goal": ["benchmark-evaluation/new-benchmark"],
      "cross_cutting": ["performance", "benchmark-evaluation"],
      "new_leaves": []
    }}
  ]
}}

Use ONLY existing leaf paths when possible. Propose new leaves only when truly necessary."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_result(raw: dict | str) -> list[dict]:
    """Parse LLM JSON response into list of classification dicts."""
    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = raw
    if isinstance(data, dict) and "papers" in data:
        return data["papers"]
    return []


def merge_into_taxonomy_json(
    existing: dict[str, Any] | None,
    new_paths: dict[str, list[str]],
) -> dict[str, Any]:
    """Merge new classification paths into existing taxonomy_json."""
    if existing is None:
        existing = {}
    result = dict(existing)
    for tree_name, paths in new_paths.items():
        existing_paths = set(result.get(tree_name, []))
        existing_paths.update(paths)
        result[tree_name] = sorted(existing_paths)
    return result


# ------------------------------------------------------------------
# Legacy TaxonomyManager (kept for s06_topics.py compatibility)
# ------------------------------------------------------------------

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Topic:
    id: str
    name: str
    name_zh: str
    desc: str
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    paper_count: int = 0
    created_at: str = ""
    source: str = "auto"  # 'seed' | 'auto' | 'manual'


SEED_TOPICS: list[Topic] = [
    Topic(
        id="sec_attack",
        name="Agent Attack",
        name_zh="Agent 攻击",
        desc="越狱、提示注入、对抗攻击、数据投毒、后门攻击",
        source="seed",
    ),
    Topic(
        id="sec_defense",
        name="Agent Defense & Safety",
        name_zh="Agent 防御与安全",
        desc="安全防护、对齐、隐私保护、恶意行为检测、可信计算",
        source="seed",
    ),
    Topic(
        id="test_benchmark",
        name="Agent Benchmark & Evaluation",
        name_zh="Agent 基准与评估",
        desc="能力评测基准、安全性评估、数据集构建、指标设计",
        source="seed",
    ),
    Topic(
        id="test_redteam",
        name="Agent Red Teaming",
        name_zh="Agent 红队测试",
        desc="自动化攻击发现、漏洞挖掘、对抗性测试、渗透测试",
        source="seed",
    ),
    Topic(
        id="test_generation",
        name="Agent Test Generation",
        name_zh="Agent 测试生成",
        desc="自动化生成测试用例、测试场景、测试数据、模糊测试",
        source="seed",
    ),
    Topic(
        id="arch_framework",
        name="Agent Architecture & Framework",
        name_zh="Agent 架构与框架",
        desc="系统架构、记忆管理、规划推理、工具调用、多智能体协作",
        source="seed",
    ),
    Topic(
        id="app_general",
        name="Agent General Application",
        name_zh="Agent 通用应用",
        desc="非测试/非安全的其他 agent 应用场景（代码生成、GUI 操作、Web 自动化等）",
        source="seed",
    ),
    Topic(
        id="dataset_generation",
        name="Dataset & Benchmark Generation",
        name_zh="数据集与基准生成",
        desc="为评测或解决 agent 问题而专门构建的数据集、基准、评测环境",
        source="seed",
    ),
]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class TaxonomyManager:
    """Manages the topic taxonomy: seed topics + incremental additions."""

    def __init__(self, path: Path):
        self.path = path
        self.topics: dict[str, Topic] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for tid, td in data.get("topics", {}).items():
                    self.topics[tid] = Topic(**td)
                return
            except Exception:
                pass
        # initialize with seed topics
        for t in SEED_TOPICS:
            t.created_at = _now_iso()
            self.topics[t.id] = t
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": _now_iso(),
            "topics": {tid: asdict(t) for tid, t in self.topics.items()},
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_for_prompt(self) -> list[dict[str, str]]:
        """Return flat list of topic dicts for LLM prompt."""
        return [
            {
                "id": t.id,
                "name": t.name,
                "name_zh": t.name_zh,
                "desc": t.desc,
            }
            for t in sorted(self.topics.values(), key=lambda x: x.id)
        ]

    def add_topic(
        self,
        parent_id: str | None,
        name: str,
        name_zh: str,
        desc: str,
        source: str = "auto",
    ) -> Topic:
        """Add a new topic and persist."""
        # generate id from name
        base = name.lower().replace(" ", "_").replace("&", "and")[:30]
        tid = base
        suffix = 1
        while tid in self.topics:
            tid = f"{base}_{suffix}"
            suffix += 1

        topic = Topic(
            id=tid,
            name=name,
            name_zh=name_zh,
            desc=desc,
            parent_id=parent_id,
            created_at=_now_iso(),
            source=source,
        )
        self.topics[tid] = topic
        if parent_id and parent_id in self.topics:
            if tid not in self.topics[parent_id].children:
                self.topics[parent_id].children.append(tid)
        self._save()
        return topic

    def bump_count(self, topic_ids: list[str]) -> None:
        """Increment paper_count for matched topics."""
        changed = False
        for tid in topic_ids:
            if tid in self.topics:
                self.topics[tid].paper_count += 1
                changed = True
        if changed:
            self._save()

    def topic_names(self, topic_ids: list[str]) -> list[str]:
        return [
            f"{self.topics[tid].name} ({self.topics[tid].name_zh})"
            for tid in topic_ids
            if tid in self.topics
        ]
