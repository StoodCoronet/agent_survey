"""Backfill arXiv abstracts for core venues (SE Big-4 + Security Big-4).

Usage (via CLI):
    agent-survey enrich-arxiv --workers 3
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import httpx
from rich.progress import Progress

from ..config import Config
from ..console import console
from ..db import DB
from ..sources.arxiv import search_title

CORE_VENUES = {"ICSE", "FSE", "ASE", "ISSTA", "SP", "CCS", "USS", "NDSS"}
REQ_DELAY = 3.0


async def _fetch_one(
    client: httpx.Client,
    semaphore: asyncio.Semaphore,
    paper_id: str,
    title: str,
) -> tuple[str, str | None, str | None]:
    async with semaphore:
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, search_title, client, title)
            await asyncio.sleep(REQ_DELAY)
            if result and result.get("abstract"):
                return paper_id, result["abstract"], result.get("arxiv_id")
        except Exception:
            pass
        return paper_id, None, None


def run(cfg: Config, workers: int = 2) -> dict:
    db_path = cfg.abs_path("db")
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        f"""
        SELECT paper_id, title FROM papers
        WHERE venue IN ({','.join('?' * len(CORE_VENUES))})
          AND (abstract IS NULL OR LENGTH(TRIM(abstract)) = 0)
        """,
        list(CORE_VENUES),
    ).fetchall()
    conn.close()

    total = len(rows)
    console.print(f"Core-venue papers without abstract: {total}")
    if total == 0:
        return {"processed": 0, "filled": 0}

    semaphore = asyncio.Semaphore(workers)
    client = httpx.Client(timeout=30, headers={"User-Agent": "agent-survey/0.1"})

    tasks = [
        _fetch_one(client, semaphore, pid, title)
        for pid, title in rows
    ]

    filled = 0
    processed = 0
    conn = sqlite3.connect(str(db_path))

    with Progress(console=console) as prog:
        task = prog.add_task("[cyan]arxiv enrich", total=total)
        for coro in asyncio.as_completed(tasks):
            paper_id, abstract, arxiv_id = asyncio.get_event_loop().run_until_complete(coro)
            processed += 1
            if abstract:
                conn.execute(
                    "UPDATE papers SET abstract = ?, arxiv_id = COALESCE(arxiv_id, ?) WHERE paper_id = ?",
                    (abstract, arxiv_id, paper_id),
                )
                filled += 1
            if processed % 50 == 0:
                conn.commit()
            prog.advance(task)

    conn.commit()
    conn.close()
    client.close()

    console.print(f"[green]Done: {processed} checked, {filled} filled[/green]")
    return {"processed": processed, "filled": filled}
