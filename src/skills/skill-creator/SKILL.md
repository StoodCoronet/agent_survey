---
name: skill-creator
description: Convert a markdown procedure document into a proper Anthropic-format skill folder. Use whenever the user has written an execution guide, playbook, workflow, or pipeline procedure in markdown and wants it packaged as a folder-based skill with SKILL.md frontmatter, evals, optional scripts, and a .skill package. Also use when improving an existing skill's structure or when onboarding a new pipeline stage as a skill.
---

# Skill Creator for Survey Agent

Turn markdown execution guides into standardized, packageable skills.

## When to use

- The user pasted or wrote a markdown procedure (e.g., "how to download papers via CORE API", "how to resolve DOIs with CrossRef").
- The user says "把这个转成 skill" or "给我们这个流程写个 skill"。
- You need to onboard a new pipeline stage (harvest, enrich, classify, etc.) as a reusable agent skill.
- An existing skill needs restructuring to match Anthropic conventions.

## Inputs

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `source_md` | str | yes | Path to markdown file OR raw markdown content |
| `skill_name` | str | yes | Desired kebab-case skill name, e.g. `core-download` |
| `output_dir` | str | yes | Where to create the skill folder |
| `topic_focus` | str | no | One-line context, e.g. "survey_agent pipeline" |

## Outputs

A complete skill folder:

```
{skill_name}/
├── SKILL.md              # generated from markdown + Anthropic frontmatter
├── scripts/              # optional helper scripts
│   └── convert_md_to_skill.py
├── references/           # spec excerpts
│   └── anthropic-skill-spec.md
├── evals/
│   └── evals.json        # auto-generated test cases
└── {skill_name}.skill    # packaged zip (after validation)
```

## Procedure

### 1. Parse the source markdown

Read `source_md` and extract these sections if present:

- Title / H1 → skill title
- "When to use" / "Trigger" / "什么时候用" → trigger contexts
- Inputs table → input schema
- Outputs table → output schema
- Procedure / Steps / Flow → ordered steps
- Fallback chain / "退化链路" → fallback sources
- Integration points → where the skill plugs into code
- Examples → concrete example for SKILL.md
- Error catalog → error table

If a section is missing, infer it from surrounding content or leave a `TODO` comment in the generated SKILL.md.

### 2. Generate `SKILL.md`

Use this template:

```markdown
---
name: {skill_name}
description: {one sentence what it does}. Use when {trigger 1}, {trigger 2}, or {trigger 3}.
---

# {Title}

{one-paragraph overview}

## When to use

{bullet list of trigger conditions}

## Inputs

{markdown table}

## Outputs

{markdown table}

## Procedure

{numbered steps, imperative tone}

## Fallback chain

{ordered list}

## Integration points

{stage / file / usage table}

## Example

{concise example}

## Error catalog

{error / meaning / action table}
```

Rules:
- Keep the body under 400 lines. If source is longer, summarize or move details to `references/`.
- Use imperative instructions.
- Explain *why* for non-obvious choices.
- Avoid heavy-handed "MUST" unless safety-critical.
- Include concrete numeric thresholds (rate limits, similarity scores).

### 3. Generate `evals/evals.json`

Derive 2–4 evals from the Examples and Procedure:

```json
{
  "skill_name": "{skill_name}",
  "evals": [
    {
      "id": 1,
      "prompt": "Run the {skill_name} skill for {concrete input}",
      "expected_output": "{what success looks like}",
      "files": [],
      "expectations": [
        "Step 1 calls {expected first action}",
        "Output includes {expected field}",
        "Fallback chain is attempted in correct order"
      ]
    }
  ]
}
```

### 4. Copy bundled resources

Place these supporting files into the skill folder:

- `scripts/convert_md_to_skill.py` — the converter itself (reusable)
- `references/anthropic-skill-spec.md` — excerpt of frontmatter + schema rules

If the source markdown references code snippets that should be executable, extract them into additional `scripts/` files and update SKILL.md to point to them.

### 5. Validate

Run Anthropic's validator against the generated skill:

```bash
python reference/skills/skills/skill-creator/scripts/quick_validate.py \
  {output_dir}/{skill_name}
```

If validation fails, fix the SKILL.md frontmatter or body and re-run.

### 6. Package

Run Anthropic's packager:

```bash
python reference/skills/skills/skill-creator/scripts/package_skill.py \
  {output_dir}/{skill_name} \
  {output_dir}
```

This produces `{skill_name}.skill` (a zip file) ready for distribution.

## Why these choices

- **Folder-based**: Matches Anthropic's official convention so skills are portable across Claude Code / Claude.ai / Cowork.
- **Frontmatter in description**: The description is the trigger signal; making it explicit and "pushy" improves invocation rate.
- **Eval-driven**: Even 2–3 evals catch structural regressions when the skill is edited later.
- **Package at the end**: `.skill` files are zip archives with a standard layout; packaging validates completeness.

## Example

Input:

```json
{
  "source_md": "docs/core-api-download-guide.md",
  "skill_name": "core-download",
  "output_dir": "src/skills",
  "topic_focus": "survey_agent pipeline"
}
```

Output flow:

1. Parse markdown → extract title, inputs (title, authors, year, doi), outputs (download_url, pdf_path), procedure (6 steps), fallback chain.
2. Generate `src/skills/core-download/SKILL.md` with frontmatter and reformatted sections.
3. Generate `src/skills/core-download/evals/evals.json` with 3 test cases.
4. Copy converter script and reference spec into `scripts/` and `references/`.
5. Run `quick_validate.py` → passes.
6. Run `package_skill.py` → creates `core-download.skill`.

## Error catalog

| Error | Meaning | Action |
|-------|---------|--------|
| `quick_validate failed: No YAML frontmatter` | Generated SKILL.md missing `---` header | Regenerate frontmatter with name + description |
| `quick_validate failed: Name should be kebab-case` | `skill_name` contains underscores or uppercase | Rename to lowercase with hyphens |
| `Source markdown has no clear inputs` | Parser could not find input schema | Ask user for input/output table or infer from context |
| `Package failed: SKILL.md not found` | Output path wrong or generation skipped | Check output_dir and skill_name match |
| `Generated skill > 500 lines` | Source too verbose | Move reference tables to `references/` and link from SKILL.md |
