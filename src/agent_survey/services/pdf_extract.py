"""PDF text extraction. Lightweight — pdfplumber text per page, naive section splitting."""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

SECTION_HEADINGS = [
    "abstract",
    "introduction",
    "background",
    "motivation",
    "related work",
    "approach",
    "method",
    "methodology",
    "design",
    "implementation",
    "system",
    "evaluation",
    "experiments",
    "experimental setup",
    "results",
    "discussion",
    "limitations",
    "threats to validity",
    "conclusion",
    "future work",
    "references",
]


def extract_text(pdf_path: Path, max_pages: int | None = None) -> str:
    if not pdf_path.exists():
        return ""
    text_parts: list[str] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            pages = pdf.pages if not max_pages else pdf.pages[:max_pages]
            for p in pages:
                try:
                    t = p.extract_text() or ""
                except Exception:
                    t = ""
                text_parts.append(t)
    except Exception:
        return ""
    return "\n".join(text_parts)


def split_sections(text: str) -> dict[str, str]:
    """Return {section_name: text} using naive heading regex."""
    if not text:
        return {}
    lines = text.splitlines()
    sections: dict[str, list[str]] = {"_preamble": []}
    current = "_preamble"
    heading_pat = re.compile(
        r"^\s*(\d+\.?\s*)?(" + "|".join(re.escape(h) for h in SECTION_HEADINGS) + r")\s*$",
        re.IGNORECASE,
    )
    for line in lines:
        m = heading_pat.match(line.strip())
        if m:
            current = m.group(2).lower()
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items() if v}


def build_prompt_body(text: str, max_chars: int = 40000) -> str:
    """Pick the most useful parts for the LLM prompt:
    abstract + intro + method + evaluation + conclusion, truncated."""
    sections = split_sections(text)
    wanted = [
        "abstract",
        "introduction",
        "background",
        "motivation",
        "approach",
        "method",
        "methodology",
        "design",
        "system",
        "evaluation",
        "experiments",
        "results",
        "discussion",
        "limitations",
        "conclusion",
    ]
    parts: list[str] = []
    used = 0
    for k in wanted:
        if k in sections:
            chunk = f"## {k.upper()}\n{sections[k]}"
            if used + len(chunk) > max_chars:
                chunk = chunk[: max_chars - used]
                parts.append(chunk)
                break
            parts.append(chunk)
            used += len(chunk)
    if not parts:
        # fallback: first N chars
        return text[:max_chars]
    return "\n\n".join(parts)
