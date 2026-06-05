"""Core workers for short-titles stage."""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.progress import Progress

from ...core.console import console
from ...services.llm import DeepSeekClient
from ...services.pdf_extract import extract_text
from .prompts import _RETRY_TEMPLATE, _SYSTEM, _USER_TEMPLATE


def _pdf_snippet(pdf_path: str | None, max_chars: int = 1200) -> str:
    """Extract first ~2 pages of PDF text, truncated."""
    if not pdf_path:
        return ""
    p = Path(pdf_path)
    if not p.exists():
        return ""
    try:
        text = extract_text(p, max_pages=2)
        return text[:max_chars].strip()
    except Exception:
        return ""


def _batch_titles(
    items: list[tuple[str, str, str]],
    batch_size: int = 20,
    existing: list[str] | None = None,
    workers: int = 5,
) -> dict[str, str]:
    """Call DeepSeek in batches with parallel workers.

    items: list of (paper_id, title, pdf_snippet)
    """
    from ...core.config import load_config

    cfg = load_config()
    client = DeepSeekClient(cfg)
    mapping: dict[str, str] = {}

    batches = [items[i : i + batch_size] for i in range(0, len(items), batch_size)]

    with Progress(console=console) as prog:
        task = prog.add_task(
            "retrying duplicates" if existing else "generating short titles",
            total=len(batches),
        )

        def worker(batch):
            if existing:
                lines = "\n".join(f"{i+1}. {t}" for i, (_, t, _) in enumerate(batch))
                existing_str = "\n".join(f"- {s}" for s in existing)
                content = _RETRY_TEMPLATE.format(
                    n=len(batch), titles=lines, existing=existing_str
                )
            else:
                blocks = []
                for idx, (_, title, snippet) in enumerate(batch, 1):
                    snippet_line = f"Excerpt: {snippet[:800]}" if snippet else ""
                    blocks.append(f"{idx}. Title: {title}\n   {snippet_line}")
                content = _USER_TEMPLATE.format(n=len(batch), papers="\n\n".join(blocks))

            messages = [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": content},
            ]
            try:
                result = client.chat_json(
                    model="deepseek-v4-flash",
                    messages=messages,
                    temperature=0.0,
                    max_tokens=4096,
                )
            except Exception as exc:
                console.print(f"[red]Batch failed: {exc}[/red]")
                return {}
            data = result.get("content", {})
            batch_map = data.get("mapping", {})
            return batch_map

        with ThreadPoolExecutor(max_workers=workers) as exe:
            futures = {exe.submit(worker, b): b for b in batches}
            for fut in as_completed(futures):
                try:
                    batch_map = fut.result()
                except Exception as exc:
                    console.print(f"[red]Worker crashed: {exc}[/red]")
                    batch_map = {}
                mapping.update(batch_map)
                prog.advance(task)

    return mapping


def _resolve_duplicates(
    items: list[tuple[str, str, str]],
    mapping: dict[str, str],
    batch_size: int,
    workers: int = 5,
) -> dict[str, str]:
    """Detect duplicate short titles and retry once."""
    all_shorts = [mapping.get(t, "") for _, t, _ in items]
    counts = Counter(all_shorts)
    dups = {s for s, c in counts.items() if c > 1 and s}

    if not dups:
        return mapping

    console.print(f"[yellow]Found {len(dups)} duplicate short titles, retrying...[/yellow]")
    dup_items = [(pid, t, s) for pid, t, s in items if mapping.get(t) in dups]
    existing = list(set(all_shorts))
    retry_map = _batch_titles(dup_items, batch_size=batch_size, existing=existing, workers=workers)
    mapping.update(retry_map)

    # Final check — fallback with numbered suffix for any remaining dups
    all_shorts2 = [mapping.get(t, "") for _, t, _ in items]
    counts2 = Counter(all_shorts2)
    remaining_dups = {s for s, c in counts2.items() if c > 1 and s}
    if remaining_dups:
        console.print(f"[yellow]{len(remaining_dups)} duplicates remain after retry, appending suffix...[/yellow]")
        for dup_short in remaining_dups:
            dup_pids = [pid for pid, t, _ in items if mapping.get(t) == dup_short]
            for idx, pid in enumerate(dup_pids[1:], start=1):
                title = next(t for p, t, _ in items if p == pid)
                base = mapping.get(title, title)
                if len(base) > 30:
                    base = base[:28]
                mapping[title] = f"{base} ({idx})"

    return mapping
