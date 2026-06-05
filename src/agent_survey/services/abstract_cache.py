"""Persistent abstract cache keyed by (venue, title).

Survives re-harvesting: when papers get new DBLK keys but same title,
enrich can skip S2/arXiv/etc and use the cached abstract directly.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


def _cache_path(db_path: Path | str) -> Path:
    """Cache lives alongside the main papers DB."""
    p = Path(db_path) if isinstance(db_path, str) else db_path
    return p.parent / "abstract_cache.sqlite"


def _hash_title(title: str) -> str:
    return hashlib.sha256(title.strip().lower().encode()).hexdigest()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS abstract_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue TEXT NOT NULL,
            title_hash TEXT NOT NULL,
            title TEXT NOT NULL,
            abstract TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(venue, title_hash)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_hash ON abstract_cache(venue, title_hash)")
    conn.commit()


def lookup(db_path: Path, venue: str, title: str) -> str | None:
    """Check if we have a cached abstract for this (venue, title)."""
    if not title:
        return None
    conn = sqlite3.connect(str(_cache_path(db_path)))
    try:
        _ensure_schema(conn)
        th = _hash_title(title)
        row = conn.execute(
            "SELECT abstract FROM abstract_cache WHERE venue=? AND title_hash=?",
            (venue, th),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def store(db_path: Path, venue: str, title: str, abstract: str) -> None:
    """Write a new abstract to the cache."""
    if not title or not abstract or len(abstract.strip()) < 30:
        return
    conn = sqlite3.connect(str(_cache_path(db_path)))
    try:
        _ensure_schema(conn)
        th = _hash_title(title)
        conn.execute(
            "INSERT OR IGNORE INTO abstract_cache (venue, title_hash, title, abstract) VALUES (?, ?, ?, ?)",
            (venue, th, title.strip(), abstract.strip()),
        )
        conn.commit()
    finally:
        conn.close()


def store_batch(db_path: Path, items: list[tuple[str, str, str]]) -> int:
    """Batch-write (venue, title, abstract) tuples. Returns count inserted."""
    if not items:
        return 0
    conn = sqlite3.connect(str(_cache_path(db_path)))
    try:
        _ensure_schema(conn)
        count = 0
        for venue, title, abstract in items:
            if not title or not abstract or len(abstract.strip()) < 30:
                continue
            th = _hash_title(title)
            conn.execute(
                "INSERT OR IGNORE INTO abstract_cache (venue, title_hash, title, abstract) VALUES (?, ?, ?, ?)",
                (venue, th, title.strip(), abstract.strip()),
            )
            count += 1
        conn.commit()
        return count
    finally:
        conn.close()
