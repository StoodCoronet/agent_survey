"""Extract citation references from PDF text and match against known papers."""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Iterator


def extract_references(text: str) -> list[str]:
    """Extract individual reference strings from the References section of PDF text."""
    if not text:
        return []

    # Find the start of references section
    ref_patterns = [
        r"\n\s*References?\s*\n",
        r"\n\s*REFERENCES?\s*\n",
        r"\n\s*Bibliography\s*\n",
        r"\n\s*BIBLIOGRAPHY\s*\n",
        r"\n\s*\d+\.?\s*References?\s*\n",
    ]

    ref_start = -1
    for pat in ref_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            ref_start = m.end()
            break

    if ref_start == -1:
        # Fallback: try to find "References" anywhere
        m = re.search(r"References?", text, re.IGNORECASE)
        if m:
            ref_start = m.end()
        else:
            return []

    ref_text = text[ref_start:]

    # Split references by common patterns:
    # 1. [1] Author... [2] Author...
    # 2. 1. Author... 2. Author...
    # 3. Author et al., Year... Author et al., Year... (newline separated)

    # Strategy: split by reference number markers, then clean
    refs: list[str] = []

    # Pattern A: [N] or N. at start of line
    numbered_split = re.split(r"\n\s*(?:\[\d+\]|\d+\.)\s*", ref_text)
    if len(numbered_split) > 2:
        refs = [r.strip() for r in numbered_split[1:] if len(r.strip()) > 20]
    else:
        # Pattern B: split by newline, merge short lines
        lines = [l.strip() for l in ref_text.splitlines() if l.strip()]
        current = ""
        for line in lines:
            # New reference usually starts with author name or year
            if re.match(r"^[A-Z][a-zA-Z\-]+(?:,|\.\s|et\s+al|\"|\d{4})", line) and len(current) > 40:
                refs.append(current.strip())
                current = line
            else:
                current += " " + line
        if current and len(current) > 20:
            refs.append(current.strip())

    # Deduplicate and filter
    seen = set()
    result = []
    for r in refs:
        # Normalize for dedup
        norm = re.sub(r"\s+", " ", r.lower())[:80]
        if norm not in seen and len(r) > 20 and len(r) < 800:
            seen.add(norm)
            result.append(r)

    return result


def build_title_signatures(papers: list[dict]) -> dict[str, list[str]]:
    """Build short title signatures for fuzzy citation matching.

    Returns {paper_id: [signature1, signature2, ...]}
    """
    sigs: dict[str, list[str]] = defaultdict(list)
    for p in papers:
        title = p.get("title", "")
        if not title:
            continue
        # Full title lowercase
        sigs[p["paper_id"]].append(title.lower())
        # First 6-8 words as short signature
        words = title.split()
        for n in (8, 6, 5):
            if len(words) >= n:
                short = " ".join(words[:n]).lower()
                sigs[p["paper_id"]].append(short)
        # Remove common prefix words for alternative signature
        cleaned = re.sub(r"^(a|an|the|towards|on|for|in)\s+", "", title, flags=re.IGNORECASE)
        if cleaned != title:
            sigs[p["paper_id"]].append(cleaned.lower())
            words_c = cleaned.split()
            for n in (6, 5, 4):
                if len(words_c) >= n:
                    sigs[p["paper_id"]].append(" ".join(words_c[:n]).lower())
    return dict(sigs)


def match_citations(
    ref_texts: list[str],
    paper_signatures: dict[str, list[str]],
) -> list[str]:
    """Match reference texts to paper IDs using title signatures.

    Returns list of matched paper_ids.
    """
    matched: list[str] = []
    for ref in ref_texts:
        ref_lower = ref.lower()
        for pid, sigs in paper_signatures.items():
            for sig in sigs:
                if sig in ref_lower and len(sig) > 15:
                    matched.append(pid)
                    break
    return matched


def build_citation_graph(
    papers: list[dict],
    paper_signatures: dict[str, list[str]],
) -> dict:
    """Build citation graph for core papers.

    Returns {
        "nodes": [{"id": paper_id, "title": ..., "in_degree": N, "out_degree": N, ...}],
        "edges": [{"source": paper_id_a, "target": paper_id_b}],
    }
    """
    from ..services.pdf_extract import extract_text

    paper_map = {p["paper_id"]: p for p in papers}
    nodes = []
    edges = []
    in_degree: dict[str, int] = defaultdict(int)

    for p in papers:
        pid = p["paper_id"]
        pdf_path = p.get("pdf_path")
        cited_ids: list[str] = []
        if pdf_path and Path(pdf_path).exists():
            text = extract_text(Path(pdf_path))
            refs = extract_references(text)
            cited_ids = match_citations(refs, paper_signatures)
            # deduplicate
            cited_ids = list(dict.fromkeys(cited_ids))

        for cited in cited_ids:
            if cited != pid and cited in paper_map:
                edges.append({"source": pid, "target": cited})
                in_degree[cited] += 1

    for p in papers:
        pid = p["paper_id"]
        out_deg = sum(1 for e in edges if e["source"] == pid)
        nodes.append({
            "id": pid,
            "title": p.get("title", ""),
            "venue": p.get("venue", ""),
            "year": p.get("year"),
            "in_degree": in_degree.get(pid, 0),
            "out_degree": out_deg,
        })

    return {"nodes": nodes, "edges": edges}
