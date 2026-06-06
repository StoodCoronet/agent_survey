# Anthropic Skill Format Reference

Quick reference for the official Anthropic skill layout.

## Folder anatomy

```
skill-name/
├── SKILL.md              # required
│   ├── YAML frontmatter
│   └── Markdown body
├── scripts/              # optional executable helpers
├── references/           # optional docs loaded on demand
├── assets/               # optional templates / icons / fonts
├── evals/                # test cases (excluded from .skill package)
└── LICENSE.txt           # optional
```

## Frontmatter

Required keys:

- `name`: kebab-case, lowercase letters/digits/hyphens, max 64 chars
- `description`: what the skill does + when to trigger it. Be explicit and "pushy" so Claude invokes it. Max 1024 chars. No `<` or `>`.

Optional keys:

- `license`: e.g. "Complete terms in LICENSE.txt"
- `allowed-tools`: list of tools this skill expects
- `compatibility`: dependencies / requirements, max 500 chars
- `metadata`: arbitrary nested dict

Example:

```yaml
---
name: core-download
description: Discover and download open-access PDFs using CORE API v3. Use this skill whenever arXiv, Semantic Scholar, or OpenReview fail to return a PDF.
---
```

## Body style

- Imperative instructions.
- Keep `< 500 lines` ideally; use references/ for deep detail.
- Include: When to use, Inputs, Outputs, Procedure, Examples, Error catalog.
- Explain *why* rather than ALL CAPS MUST.

## Validation

Use `quick_validate.py` from Anthropic's skill-creator:

```bash
python scripts/quick_validate.py /path/to/skill-folder
```

Checks:
- SKILL.md exists
- Frontmatter is valid YAML
- `name` and `description` are present
- No unexpected frontmatter keys
- Name is kebab-case
- Description length and characters

## Packaging

Use `package_skill.py`:

```bash
python scripts/package_skill.py /path/to/skill-folder [output-dir]
```

Produces `{skill-name}.skill`, a zip archive excluding `evals/`, `__pycache__/`, `*.pyc`, `.DS_Store`.
