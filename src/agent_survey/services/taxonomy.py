"""Taxonomy classification helpers — dynamic trees, flat labels, extensions.

Tree structures are loaded from per-topic YAML (taxonomy.trees).
This module provides prompt building, result parsing, and extension management
for incremental leaf/tree discovery.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


# ------------------------------------------------------------------
# Prompt building
# ------------------------------------------------------------------

def _format_tree_description(trees: dict, cross_tags: list[str]) -> str:
    """Build human-readable taxonomy description from dynamic trees."""
    lines = []
    for tree_name, branches in trees.items():
        lines.append(f"\n## {tree_name}")
        for branch, leaves in branches.items():
            if leaves:
                lines.append(f"  {branch}/")
                for leaf in leaves:
                    lines.append(f"    - {leaf}")
            else:
                lines.append(f"  {branch}/ (leaf node, no sub-branches)")
    if cross_tags:
        lines.append("\n## cross-cutting tags (can appear under any leaf)")
        for tag in cross_tags:
            lines.append(f"  - {tag}")
    return "\n".join(lines)


def build_messages(papers: list[dict], tax_cfg) -> list[dict]:
    """Build LLM messages for a batch of papers using dynamic trees."""
    tree_desc = _format_tree_description(tax_cfg.trees, tax_cfg.cross_cutting_tags)
    paper_blocks = []
    for i, p in enumerate(papers, 1):
        block = f"[{i}] Title: {p['title']}\nVenue: {p.get('venue', '')} ({p.get('year', '')})\nAbstract: {p.get('abstract', '')}"
        paper_blocks.append(block)

    paper_blocks_joined = "\n---\n".join(paper_blocks)

    # Use the topic-configured user prompt template if available,
    # otherwise fall back to the built-in default.
    template = getattr(tax_cfg, "user_prompt_template", "")
    if template and template.strip():
        user = template.format(
            tree_description=tree_desc,
            count=len(papers),
            paper_blocks=paper_blocks_joined,
        )
    else:
        tree_names = list(tax_cfg.trees.keys())
        example_lines = []
        for tn in tree_names:
            key = tn.replace("-", "_")
            example_lines.append(f'      "{key}": ["{tn}/example-leaf"],')
        example_json = "\n".join(example_lines)
        first_tree_example = tree_names[0] if tree_names else "tree-name"

        user = f"""Classify the following papers using this taxonomy:

{tree_desc}

For each paper, assign:
1. One or more leaf paths per tree (e.g., "{first_tree_example}/example-leaf")
2. Zero or more cross-cutting tags
3. If a paper does not fit any existing leaf, propose new leaves as FULL paths (e.g., "tree-name/new-branch/leaf-name")

Papers to classify ({len(papers)}):
---
{paper_blocks_joined}
---

Return strict JSON:
{{
  "papers": [
    {{
      "paper_idx": 1,
{example_json}
      "cross_cutting": [],
      "new_leaves": []
    }}
  ]
}}

Use ONLY existing leaf paths when possible. Propose new leaves only when truly necessary."""
    return [
        {"role": "system", "content": tax_cfg.system_prompt},
        {"role": "user", "content": user},
    ]


# ------------------------------------------------------------------
# Result parsing
# ------------------------------------------------------------------

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
# Flat label mapping (absorbs s06 seed_topics capability)
# ------------------------------------------------------------------

def paths_to_flat_labels(taxonomy_json: dict, flat_labels: dict[str, str]) -> list[str]:
    """Convert tree paths in taxonomy_json to flat topic IDs.

    Supports exact match and prefix match:
      - exact: path "a/b/c" matches mapping "a/b/c"
      - prefix: path "a/b/c" matches mapping "a/b" (parent branch)
    """
    topics: set[str] = set()
    for tree_name, paths in taxonomy_json.items():
        if tree_name == "cross_cutting":
            continue
        if not isinstance(paths, list):
            continue
        for path in paths:
            path_str = path if isinstance(path, str) else str(path)
            # Exact match
            if path_str in flat_labels:
                topics.add(flat_labels[path_str])
                continue
            # Prefix match (mapping key is a prefix of the path)
            matched = False
            for mapped_path, label_id in flat_labels.items():
                if path_str.startswith(mapped_path + "/") or path_str == mapped_path:
                    topics.add(label_id)
                    matched = True
                    break
            if not matched:
                # Reverse prefix: path is a prefix of mapping key
                for mapped_path, label_id in flat_labels.items():
                    if mapped_path.startswith(path_str + "/") or mapped_path == path_str:
                        topics.add(label_id)
                        break
    return sorted(topics)


# ------------------------------------------------------------------
# Taxonomy extensions (incremental new leaves / trees)
# ------------------------------------------------------------------

EXTENSION_FILE = "taxonomy_extensions.json"


def _ext_path(project_root: Path, topic_name: str) -> Path:
    p = project_root / "output" / topic_name / EXTENSION_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_extensions(project_root: Path, topic_name: str) -> dict[str, Any]:
    """Load taxonomy extensions (new trees/branches/leaves discovered by LLM)."""
    path = _ext_path(project_root, topic_name)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"trees": {}, "flat_labels": {}}


def save_extensions(
    project_root: Path,
    topic_name: str,
    trees: dict[str, dict] | None = None,
    flat_labels: dict[str, str] | None = None,
) -> None:
    """Persist taxonomy extensions to output/<topic>/taxonomy_extensions.json."""
    path = _ext_path(project_root, topic_name)
    existing = load_extensions(project_root, topic_name)
    if trees:
        for tree_name, branches in trees.items():
            if tree_name not in existing["trees"]:
                existing["trees"][tree_name] = {}
            for branch, leaves in branches.items():
                if branch not in existing["trees"][tree_name]:
                    existing["trees"][tree_name][branch] = leaves
                else:
                    old = set(existing["trees"][tree_name][branch])
                    old.update(leaves)
                    existing["trees"][tree_name][branch] = sorted(old)
    if flat_labels:
        existing["flat_labels"].update(flat_labels)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_extensions_into_cfg(tax_cfg) -> None:
    """Merge saved extensions into a TaxonomyCfg instance (mutates in place)."""
    from ..core.config import PROJECT_ROOT

    ext = load_extensions(PROJECT_ROOT, tax_cfg.__dict__.get("_topic_name", ""))
    for tree_name, branches in ext.get("trees", {}).items():
        if tree_name not in tax_cfg.trees:
            tax_cfg.trees[tree_name] = {}
        for branch, leaves in branches.items():
            if branch not in tax_cfg.trees[tree_name]:
                tax_cfg.trees[tree_name][branch] = leaves
            else:
                old = set(tax_cfg.trees[tree_name][branch])
                old.update(leaves)
                tax_cfg.trees[tree_name][branch] = sorted(old)
    tax_cfg.flat_labels.update(ext.get("flat_labels", {}))


# ------------------------------------------------------------------
# New-leaf processing
# ------------------------------------------------------------------

def apply_new_leaves(
    proposals: list[str],
    trees: dict[str, dict],
    flat_labels: dict[str, str],
    auto_create: bool,
    threshold: float,
    project_root: Path,
    topic_name: str,
) -> tuple[int, list[dict]]:
    """Process new-leaf proposals: auto-create into trees or queue for review.

    Returns (auto_created_count, pending_list).
    """
    # Deduplicate
    seen: set[str] = set()
    unique: list[str] = []
    for p in proposals:
        p = p.strip().strip("/")
        if p in seen:
            continue
        seen.add(p)
        unique.append(p)

    auto_created = 0
    pending: list[dict] = []
    ext_trees: dict[str, dict] = {}
    ext_labels: dict[str, str] = {}

    for proposal in unique:
        parts = proposal.split("/")
        if len(parts) < 2:
            pending.append({"proposal": proposal, "reason": "need at least tree/branch"})
            continue

        tree_name = parts[0]
        branch_name = parts[1]
        leaf_name = parts[2] if len(parts) >= 3 else None

        # Skip if already exists
        if tree_name in trees and branch_name in trees.get(tree_name, {}):
            existing_leaves = trees[tree_name][branch_name]
            if leaf_name is None or leaf_name in existing_leaves:
                continue

        if auto_create:
            if tree_name not in trees:
                trees[tree_name] = {}
            if tree_name not in ext_trees:
                ext_trees[tree_name] = {}
            if branch_name not in trees[tree_name]:
                trees[tree_name][branch_name] = []
                ext_trees[tree_name][branch_name] = []
            if leaf_name and leaf_name not in trees[tree_name][branch_name]:
                trees[tree_name][branch_name].append(leaf_name)
                if branch_name not in ext_trees[tree_name]:
                    ext_trees[tree_name][branch_name] = []
                ext_trees[tree_name][branch_name].append(leaf_name)
            auto_created += 1
        else:
            pending.append({
                "proposal": proposal,
                "tree": tree_name,
                "branch": branch_name,
                "leaf": leaf_name,
            })

    if ext_trees:
        save_extensions(project_root, topic_name, trees=ext_trees, flat_labels=ext_labels)

    return auto_created, pending


# ------------------------------------------------------------------
# Fully-automatic maintenance: deepseek-v4-pro judge
# ------------------------------------------------------------------

def _format_tree_description_compact(trees: dict[str, dict]) -> str:
    """Compact tree description for judge prompts (no cross-tags)."""
    return _format_tree_description(trees, [])


def _build_judge_messages(
    proposals_with_papers: dict[str, list[dict]],
    trees: dict[str, dict],
) -> list[dict]:
    """Build LLM messages for the judge reviewing candidate new leaves."""
    tree_desc = _format_tree_description_compact(trees)

    candidate_blocks = []
    for proposal_path, papers in proposals_with_papers.items():
        # Truncate abstracts to ~400 chars to keep prompt size reasonable
        paper_samples = []
        for i, p in enumerate(papers[:3], 1):
            abst = (p.get("abstract") or "")[:400]
            paper_samples.append(
                f"    [{i}] Title: {p.get('title', '')}\n"
                f"        Abstract: {abst}"
            )
        samples_str = "\n".join(paper_samples) if paper_samples else "    (no abstracts)"
        candidate_blocks.append(
            f"--- Candidate: {proposal_path} ---\n"
            f"Paper count: {len(papers)}\n"
            f"Sample papers:\n{samples_str}"
        )

    candidates_str = "\n\n".join(candidate_blocks)

    system = (
        "You are a research taxonomy expert. Your task is to review candidate new leaf nodes "
        "discovered during automatic paper classification, and decide whether each candidate "
        "deserves to exist as an independent leaf in the taxonomy tree.\n\n"
        "Guidelines:\n"
        "- A leaf is worth existing ONLY if it represents a distinct, meaningful research direction "
        "  with clear boundaries from existing leaves.\n"
        "- Do NOT create leaves that are too narrow (only 1-2 specific techniques) or overlap "
        "  significantly with existing ones.\n"
        "- If a candidate is close to an existing leaf but has a unique focus, prefer keeping it "
        "  separate ONLY if the focus is substantial and well-supported by papers.\n"
        "- Consider paper count: more papers = stronger signal, but quality and distinctiveness matter more.\n"
        "- For rejected candidates, choose the closest existing leaf path as fallback.\n\n"
        "You must respond with strict JSON only."
    )

    user = (
        f"Current taxonomy trees:\n{tree_desc}\n\n"
        f"Candidates:\n\n{candidates_str}\n\n"
        "For EACH candidate, return:\n"
        "- is_worth: true if it represents a distinct research direction NOT adequately covered by existing leaves\n"
        "- fallback_leaf: if is_worth is false, the closest existing leaf path (e.g. \"tree/branch/leaf\") "
        "to reclassify these papers to; null if is_worth is true\n"
        "- reason: brief justification (1 sentence)\n\n"
        "Return strict JSON:\n"
        "{"
        '  "judgments": ['
        "    {"
        '      "proposal": "tree-name/branch/leaf",'
        '      "is_worth": true,'
        '      "fallback_leaf": null,'
        '      "reason": "..."'
        "    }"
        "  ]"
        "}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def judge_new_leaves(
    proposals_with_papers: dict[str, list[dict]],
    trees: dict[str, dict],
    cfg: Any,
    topic_name: str,
    judge_model: str = "deepseek-v4-pro",
    db: Any = None,
) -> tuple[list[str], dict[str, str], dict]:
    """Use an LLM judge to decide which candidate leaves are worth creating.

    Returns:
        approved_paths: list of proposal paths that are worth creating
        rejected_to_fallback: dict of {rejected_path: fallback_leaf_path}
        meta: dict with usage info and api_calls
    """
    from ..core.db import DB
    from ..services.llm import DeepSeekClient, cached_chat_json

    if not proposals_with_papers:
        return [], {}, {"api_calls": 0, "cached_hits": 0}

    db = db or DB(cfg.abs_path("db"))
    llm = DeepSeekClient(cfg)

    messages = _build_judge_messages(proposals_with_papers, trees)

    # Use a deterministic paper_id based on sorted proposals for cache stability
    proposal_keys = "|".join(sorted(proposals_with_papers.keys()))
    paper_id = f"taxonomy_judge_{topic_name}_{hash(proposal_keys) & 0xFFFFFFFF}"

    out = cached_chat_json(
        llm, db,
        paper_id=paper_id,
        stage="taxonomy_judge",
        model=judge_model,
        prompt_version="v1",
        messages=messages,
        temperature=0.0,
        max_tokens=2048,
        topic_name=topic_name,
        timeout=180.0,
    )

    approved: list[str] = []
    rejected: dict[str, str] = {}
    data = out.get("content", {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = {}

    judgments = data.get("judgments", []) if isinstance(data, dict) else []
    for j in judgments:
        proposal = j.get("proposal", "").strip().strip("/")
        if not proposal:
            continue
        if j.get("is_worth") is True:
            approved.append(proposal)
        else:
            fb = j.get("fallback_leaf")
            if fb:
                rejected[proposal] = fb.strip().strip("/")

    meta = {
        "api_calls": 0 if out.get("cached") else 1,
        "cached_hits": 1 if out.get("cached") else 0,
        "usage": out.get("usage") or {},
    }
    return approved, rejected, meta


def update_topic_yaml(
    config_path: Path,
    approved_paths: list[str],
) -> int:
    """Write approved new leaves into the topic YAML file (taxonomy.trees).

    Returns the number of leaves actually added.
    """
    if not config_path.exists():
        return 0

    raw = config_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not data or "taxonomy" not in data:
        return 0

    trees = data["taxonomy"].setdefault("trees", {})
    added = 0

    for path in approved_paths:
        parts = path.split("/")
        if len(parts) < 2:
            continue
        tree_name = parts[0]
        branch_name = parts[1]
        leaf_name = parts[2] if len(parts) >= 3 else None

        if tree_name not in trees:
            trees[tree_name] = {}
        if branch_name not in trees[tree_name]:
            trees[tree_name][branch_name] = []

        if leaf_name:
            if leaf_name not in trees[tree_name][branch_name]:
                trees[tree_name][branch_name].append(leaf_name)
                added += 1
        else:
            # branch itself is a leaf (empty list already present)
            pass

    # Sort leaves for consistency
    for tree_name, branches in trees.items():
        for branch_name, leaves in branches.items():
            if isinstance(leaves, list):
                branches[branch_name] = sorted(leaves)

    # Write back (pyyaml; comments are lost, but data is preserved)
    config_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, indent=2),
        encoding="utf-8",
    )
    return added


def reclassify_papers_with_fallback(
    db: Any,
    topic_name: str,
    path_to_fallback: dict[str, str],
    flat_labels: dict[str, str],
) -> int:
    """Update taxonomy_json for papers that had rejected new leaves.

    For each paper whose taxonomy_json contains a rejected path,
    replace that path with the fallback leaf path and re-derive topics_json.

    Returns the number of papers reclassified.
    """
    if not path_to_fallback:
        return 0

    reclassified = 0
    for pt in db.iter_paper_topics(topic_name):
        taxonomy_json = pt.get("taxonomy_json")
        if not taxonomy_json:
            continue
        try:
            tj = json.loads(taxonomy_json) if isinstance(taxonomy_json, str) else taxonomy_json
        except Exception:
            continue

        modified = False
        for tree_name, paths in list(tj.items()):
            if tree_name == "cross_cutting":
                continue
            if not isinstance(paths, list):
                continue
            new_paths = []
            for p in paths:
                if p in path_to_fallback:
                    fb = path_to_fallback[p]
                    if fb not in new_paths:
                        new_paths.append(fb)
                    modified = True
                else:
                    if p not in new_paths:
                        new_paths.append(p)
            if modified:
                tj[tree_name] = new_paths

        if modified:
            # Re-derive flat labels
            new_flat = paths_to_flat_labels(tj, flat_labels)
            db.upsert_paper_topic(
                pt["paper_id"], topic_name,
                {
                    "taxonomy_json": tj,
                    "topics_json": new_flat,
                },
            )
            reclassified += 1

    return reclassified


def apply_new_leaves_v2(
    proposals_with_papers: dict[str, list[dict]],
    trees: dict[str, dict],
    flat_labels: dict[str, str],
    cfg: Any,
    topic_name: str,
    auto_create: bool = True,
    min_papers: int = 3,
    judge_model: str = "deepseek-v4-pro",
    write_yaml: bool = True,
    enable_fallback: bool = True,
    db: Any = None,
) -> dict:
    """Fully-automatic new-leaf processing with LLM judge.

    Returns a dict with:
      - auto_created: number of leaves added to trees/yaml
      - reclassified: number of papers downgraded to fallback leaves
      - rejected: number of rejected proposals
      - pending: list of proposals that could not be processed
      - meta: LLM usage info
    """
    from ..core.db import DB

    db = db or DB(cfg.abs_path("db"))

    # 1. Filter by min-paper threshold
    qualified = {
        path: papers
        for path, papers in proposals_with_papers.items()
        if len(papers) >= min_papers
    }
    under_threshold = {
        path: papers
        for path, papers in proposals_with_papers.items()
        if len(papers) < min_papers
    }

    if not qualified:
        return {
            "auto_created": 0,
            "reclassified": 0,
            "rejected": 0,
            "pending": [{"proposal": p, "reason": f"only {len(papers)} paper(s) (< {min_papers})"}
                        for p, papers in under_threshold.items()],
            "meta": {"api_calls": 0, "cached_hits": 0},
        }

    # 2. Judge with reasoner
    approved, rejected_to_fallback, meta = judge_new_leaves(
        qualified, trees, cfg, topic_name,
        judge_model=judge_model, db=db,
    )

    # 3. Apply approved leaves to in-memory trees
    auto_created = 0
    for path in approved:
        parts = path.split("/")
        if len(parts) < 2:
            continue
        tree_name = parts[0]
        branch_name = parts[1]
        leaf_name = parts[2] if len(parts) >= 3 else None

        if tree_name not in trees:
            trees[tree_name] = {}
        if branch_name not in trees[tree_name]:
            trees[tree_name][branch_name] = []
        if leaf_name and leaf_name not in trees[tree_name][branch_name]:
            trees[tree_name][branch_name].append(leaf_name)
            auto_created += 1

    # 4. Write to YAML
    yaml_added = 0
    if write_yaml and auto_create and approved:
        tc = None
        try:
            from ..core.config import load_topic_config
            tc = load_topic_config(topic_name)
        except Exception:
            pass
        if tc and tc.config_path:
            yaml_added = update_topic_yaml(tc.config_path, approved)

    # 5. Reclassify rejected papers to fallback leaves
    reclassified = 0
    if enable_fallback and rejected_to_fallback:
        reclassified = reclassify_papers_with_fallback(
            db, topic_name, rejected_to_fallback, flat_labels
        )

    pending = [
        {"proposal": p, "reason": f"only {len(papers)} paper(s) (< {min_papers})"}
        for p, papers in under_threshold.items()
    ]

    return {
        "auto_created": auto_created,
        "yaml_added": yaml_added,
        "reclassified": reclassified,
        "rejected": len(rejected_to_fallback),
        "pending": pending,
        "meta": meta,
        "approved_paths": approved,
        "rejected_paths": list(rejected_to_fallback.keys()),
    }
