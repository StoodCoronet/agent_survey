#!/usr/bin/env python3
"""
Convert a markdown procedure document into an Anthropic-format skill folder.

Usage:
    python convert_md_to_skill.py <source.md> <skill-name> <output-dir>

Example:
    python convert_md_to_skill.py docs/core-guide.md core-download src/skills
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
ANTHROPIC_SKILL_CREATOR = REPO_ROOT / "reference" / "skills" / "skills" / "skill-creator"
VALIDATOR = ANTHROPIC_SKILL_CREATOR / "scripts" / "quick_validate.py"
PACKAGER = ANTHROPIC_SKILL_CREATOR / "scripts" / "package_skill.py"


def _read_source(source_path: Path) -> str:
    return source_path.read_text(encoding="utf-8")


def _extract_title(text: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else "Untitled Skill"


def _extract_section(text: str, *headings: str) -> str | None:
    """Extract the first matching section by heading (case-insensitive).

    Stops at the next H1 or H2 heading. H3/H4 subheadings inside the section
    are preserved so that multi-step procedures are captured correctly.
    """
    for heading in headings:
        pattern = rf"(?:^|\n)##\s*{re.escape(heading)}\s*\n(.*?)(?=\n#{{1,2}}\s|\Z)"
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()
        # Fallback: allow H1/H3 headings as section start
        pattern = rf"(?:^|\n)#{{1,3}}\s*{re.escape(heading)}\s*\n(.*?)(?=\n#{{1,2}}\s|\Z)"
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()
    return None


def _extract_trigger(text: str) -> str:
    section = (
        _extract_section(text, "When to use", "Trigger", "触发条件")
        or _extract_section(text, "Role")
        or ""
    )
    # Collapse bullets into a single sentence
    lines = [line.strip("-* ") for line in section.splitlines() if line.strip().startswith(("-", "*"))]
    if not lines:
        lines = [line.strip() for line in section.splitlines() if line.strip()]
    triggers = "; ".join(lines[:3])
    return triggers or "the user asks for help with this workflow"


def _extract_inputs_outputs(text: str, label: str) -> str:
    section = _extract_section(text, label) or ""
    # If there's a markdown table, return it as-is
    if "|" in section:
        # Find the first table
        lines = section.splitlines()
        table_lines: list[str] = []
        in_table = False
        for line in lines:
            if line.strip().startswith("|"):
                in_table = True
                table_lines.append(line)
            elif in_table:
                break
        return "\n".join(table_lines)
    return ""


def _extract_steps(text: str) -> list[str]:
    section = (
        _extract_section(text, "Procedure", "Steps", "步骤", "流程")
        or ""
    )
    steps: list[str] = []
    current: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        # Only treat markdown headings (### 1. Title) as new steps.
        # Plain numbered lists inside a step are preserved as content.
        if re.match(r"^#{1,4}\s+\d+[.:\)\s]", stripped):
            if current:
                steps.append("\n".join(current).strip())
                current = []
            current.append(re.sub(r"^#{1,4}\s+\d+[.:\)\s]+", "", stripped).strip())
        elif stripped:
            current.append(stripped)
    if current:
        steps.append("\n".join(current).strip())
    return steps


def _extract_fallback(text: str) -> str:
    section = _extract_section(text, "Fallback chain", "退化链路", "Fallback")
    if not section:
        return ""
    lines = [line.strip("-* 1234567890.") for line in section.splitlines() if line.strip().startswith(("-", "*")) or re.match(r"^\d+[.:\)\s]", line.strip())]
    return "\n".join(f"{i+1}. {line}" for i, line in enumerate(lines[:8]) if line)


def _extract_integration(text: str) -> str:
    section = _extract_section(text, "Integration points", "集成点", "Integration")
    if not section:
        return ""
    return section


def _extract_example(text: str) -> str:
    section = _extract_section(text, "Example", "Examples", "示例", "例子")
    return section or ""


def _extract_error_catalog(text: str) -> str:
    section = _extract_section(text, "Error catalog", "错误表", "Errors")
    if not section:
        return ""
    # Keep the table if present
    return section


def _build_overview(title: str, trigger: str) -> str:
    return f"{title} — a reusable playbook for the survey_agent pipeline. Triggered when {trigger.lower()}."


def _build_skill_md(skill_name: str, source_text: str) -> str:
    title = _extract_title(source_text)
    trigger_phrase = _extract_trigger(source_text)
    overview = _build_overview(title, trigger_phrase)

    when_to_use = _extract_section(source_text, "When to use", "Trigger", "触发条件") or "- User needs help with this workflow."
    inputs = _extract_inputs_outputs(source_text, "Inputs") or "| Field | Type | Required | Notes |\n|-------|------|----------|-------|"
    outputs = _extract_inputs_outputs(source_text, "Outputs") or "| Field | Type | Meaning |\n|-------|------|---------|"
    steps_list = _extract_steps(source_text)
    fallback = _extract_fallback(source_text)
    integration = _extract_integration(source_text)
    example = _extract_example(source_text)
    errors = _extract_error_catalog(source_text)

    steps_md = "\n\n".join(f"### {i+1}. {step.splitlines()[0]}\n" + "\n".join(step.splitlines()[1:]) for i, step in enumerate(steps_list[:8]))
    if not steps_md:
        steps_md = "### 1. Execute the workflow\nFollow the source markdown procedure."

    sections = [
        f"---\nname: {skill_name}\ndescription: {overview} Use when {trigger_phrase}.\n---",
        f"# {title}",
        overview,
        "## When to use",
        when_to_use,
        "## Inputs",
        inputs,
        "## Outputs",
        outputs,
        "## Procedure",
        steps_md,
    ]

    if fallback:
        sections += ["## Fallback chain", fallback]
    if integration:
        sections += ["## Integration points", integration]
    if example:
        sections += ["## Example", example]
    if errors:
        sections += ["## Error catalog", errors]

    return "\n\n".join(sections) + "\n"


def _build_evals(skill_name: str, source_text: str) -> dict:
    title = _extract_title(source_text)
    trigger = _extract_trigger(source_text)
    example = _extract_example(source_text)
    eval_prompt = f"Apply the {skill_name} skill to a typical scenario: {trigger.split(';')[0] if trigger else 'run the workflow'}."
    if example:
        first_line = example.splitlines()[0]
        eval_prompt += f" Context: {first_line[:200]}"

    return {
        "skill_name": skill_name,
        "evals": [
            {
                "id": 1,
                "prompt": eval_prompt,
                "expected_output": f"The skill follows the {title} procedure and produces the expected outputs.",
                "files": [],
                "expectations": [
                    "Reads inputs correctly",
                    "Follows procedure steps in order",
                    "Uses fallback chain when primary source fails",
                ],
            },
            {
                "id": 2,
                "prompt": f"Validate that the {skill_name} skill has proper Anthropic-format frontmatter and structure.",
                "expected_output": "Skill passes quick_validate.py without errors.",
                "files": [],
                "expectations": [
                    "SKILL.md starts with YAML frontmatter",
                    "Frontmatter contains name and description",
                    "Name is kebab-case",
                ],
            },
        ],
    }


def _copy_supporting_files(skill_dir: Path) -> None:
    refs_dir = skill_dir / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)
    spec_src = Path(__file__).parent.parent / "references" / "anthropic-skill-spec.md"
    if spec_src.exists():
        shutil.copy2(spec_src, refs_dir / "anthropic-skill-spec.md")

    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_src = Path(__file__)
    shutil.copy2(script_src, scripts_dir / script_src.name)


def _run_validator(skill_dir: Path) -> tuple[bool, str]:
    if not VALIDATOR.exists():
        return False, f"Validator not found at {VALIDATOR}"
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(skill_dir)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def _run_packager(skill_dir: Path, output_dir: Path) -> tuple[bool, str]:
    if not PACKAGER.exists():
        return False, f"Packager not found at {PACKAGER}"
    # package_skill.py uses a sibling package import (from scripts.quick_validate).
    # Add the skill-creator root to PYTHONPATH so `scripts` resolves.
    skill_creator_root = PACKAGER.parent.parent
    env = os.environ.copy()
    env["PYTHONPATH"] = str(skill_creator_root) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, str(PACKAGER), str(skill_dir), str(output_dir)],
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def convert(source_md: Path, skill_name: str, output_dir: Path) -> Path:
    source_text = _read_source(source_md)

    skill_dir = output_dir / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_md = _build_skill_md(skill_name, source_text)
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    evals = _build_evals(skill_name, source_text)
    evals_dir = skill_dir / "evals"
    evals_dir.mkdir(parents=True, exist_ok=True)
    (evals_dir / "evals.json").write_text(json.dumps(evals, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    _copy_supporting_files(skill_dir)

    valid, msg = _run_validator(skill_dir)
    print(f"Validation: {'PASS' if valid else 'FAIL'} - {msg}")
    if not valid:
        raise RuntimeError(f"Skill validation failed: {msg}")

    ok, pkg_msg = _run_packager(skill_dir, output_dir)
    print(f"Packaging: {'PASS' if ok else 'FAIL'} - {pkg_msg}")
    if not ok:
        raise RuntimeError(f"Skill packaging failed: {pkg_msg}")

    return skill_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a markdown guide into an Anthropic-format skill.")
    parser.add_argument("source_md", help="Path to source markdown file")
    parser.add_argument("skill_name", help="Kebab-case skill name")
    parser.add_argument("output_dir", help="Directory where skill folder will be created")
    args = parser.parse_args()

    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", args.skill_name):
        print(f"ERROR: skill_name '{args.skill_name}' must be kebab-case (lowercase letters, digits, hyphens)")
        return 1

    source_path = Path(args.source_md)
    if not source_path.exists():
        print(f"ERROR: source markdown not found: {source_path}")
        return 1

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        skill_dir = convert(source_path, args.skill_name, out)
        print(f"\nCreated skill at: {skill_dir}")
        package = out / f"{args.skill_name}.skill"
        if package.exists():
            print(f"Packaged skill:   {package}")
    except Exception as e:
        print(f"ERROR: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
