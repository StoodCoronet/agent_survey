"""SQLite storage."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  paper_id TEXT PRIMARY KEY,
  dblp_key TEXT UNIQUE,
  arxiv_id TEXT,
  doi TEXT,
  title TEXT NOT NULL,
  abstract TEXT,
  venue TEXT,
  venue_area TEXT,
  venue_type TEXT,
  year INTEGER,
  authors_json TEXT,
  url TEXT,
  pdf_url TEXT,
  pdf_path TEXT,
  code_url TEXT,
  tldr TEXT,
  prefilter_hit TEXT,             -- JSON list of matched keyword categories
  relevance TEXT,                 -- core / related / adjacent / irrelevant
  domain_primary TEXT,
  domain_secondary_json TEXT,
  method_tags_json TEXT,
  deepdive_json TEXT,
  topics_json TEXT,
  stage_status_json TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_papers_venue_year ON papers(venue, year);
CREATE INDEX IF NOT EXISTS idx_papers_relevance ON papers(relevance);

CREATE TABLE IF NOT EXISTS llm_calls (
  call_id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_id TEXT,
  stage TEXT,
  model TEXT,
  prompt_version TEXT,
  input_hash TEXT UNIQUE,
  response_json TEXT,
  created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_paper ON llm_calls(paper_id, stage);

CREATE TABLE IF NOT EXISTS harvest_runs (
  venue_name TEXT NOT NULL,
  year INTEGER NOT NULL,
  status TEXT NOT NULL,            -- 'done' | 'failed' | 'empty'
  paper_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (venue_name, year)
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DB:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        # lightweight migrations
        try:
            self._conn.execute("ALTER TABLE papers ADD COLUMN enrich_source TEXT")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE papers ADD COLUMN enrich_at TEXT")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE papers ADD COLUMN topics_json TEXT")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE papers ADD COLUMN sub_topics_json TEXT")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE papers ADD COLUMN dedup_keep_json TEXT")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE papers ADD COLUMN taxonomy_json TEXT")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE papers ADD COLUMN citation_json TEXT")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE papers ADD COLUMN short_title TEXT")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE papers ADD COLUMN summary_en TEXT")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            self._conn.execute("ALTER TABLE papers ADD COLUMN summary_zh TEXT")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass
        self._conn.executescript("""
CREATE TABLE IF NOT EXISTS taxonomy_descriptions (
  tree_name TEXT NOT NULL,
  path TEXT NOT NULL,
  desc_en TEXT,
  desc_zh TEXT,
  paper_count INTEGER DEFAULT 0,
  metadata_json TEXT,
  status TEXT,
  last_error TEXT,
  created_at TEXT,
  updated_at TEXT,
  PRIMARY KEY (tree_name, path)
);
""")
        self._conn.commit()
        # migrations
        for col in ("metadata_json", "status", "last_error"):
            try:
                self._conn.execute(f"ALTER TABLE taxonomy_descriptions ADD COLUMN {col} TEXT")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass

    def close(self) -> None:
        self._conn.close()

    # ----- paper CRUD -----
    def upsert_paper(self, paper: dict[str, Any]) -> None:
        paper = dict(paper)
        paper.setdefault("created_at", now_iso())
        paper["updated_at"] = now_iso()
        for k in (
            "authors_json",
            "prefilter_hit",
            "domain_secondary_json",
            "method_tags_json",
            "deepdive_json",
            "topics_json",
            "sub_topics_json",
            "dedup_keep_json",
            "taxonomy_json",
            "citation_json",
            "stage_status_json",
        ):
            v = paper.get(k)
            if v is not None and not isinstance(v, str):
                paper[k] = json.dumps(v, ensure_ascii=False)
        cols = list(paper.keys())
        placeholders = ",".join(["?"] * len(cols))
        col_list = ",".join(cols)
        update_clause = ",".join(f"{c}=excluded.{c}" for c in cols if c != "paper_id" and c != "created_at")
        sql = (
            f"INSERT INTO papers ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT(paper_id) DO UPDATE SET {update_clause}"
        )
        self._conn.execute(sql, [paper[c] for c in cols])
        self._conn.commit()

    def update_paper(self, paper_id: str, fields: dict[str, Any]) -> None:
        fields = dict(fields)
        fields["updated_at"] = now_iso()
        for k in (
            "authors_json",
            "prefilter_hit",
            "domain_secondary_json",
            "method_tags_json",
            "deepdive_json",
            "topics_json",
            "sub_topics_json",
            "dedup_keep_json",
            "taxonomy_json",
            "citation_json",
            "stage_status_json",
        ):
            v = fields.get(k)
            if v is not None and not isinstance(v, str):
                fields[k] = json.dumps(v, ensure_ascii=False)
        if not fields:
            return
        set_clause = ",".join(f"{k}=?" for k in fields)
        self._conn.execute(
            f"UPDATE papers SET {set_clause} WHERE paper_id=?",
            list(fields.values()) + [paper_id],
        )
        self._conn.commit()

    def mark_stage(self, paper_id: str, stage: str, status: str = "done") -> None:
        row = self._conn.execute(
            "SELECT stage_status_json FROM papers WHERE paper_id=?", (paper_id,)
        ).fetchone()
        status_map: dict[str, str] = {}
        if row and row["stage_status_json"]:
            try:
                status_map = json.loads(row["stage_status_json"])
            except Exception:
                status_map = {}
        status_map[stage] = status
        self.update_paper(paper_id, {"stage_status_json": status_map})

    def get_paper(self, paper_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM papers WHERE paper_id=?", (paper_id,)
        ).fetchone()
        return dict(row) if row else None

    def iter_papers(self, where: str = "", params: Iterable[Any] = ()) -> Iterator[dict[str, Any]]:
        sql = "SELECT * FROM papers"
        if where:
            sql += f" WHERE {where}"
        for row in self._conn.execute(sql, tuple(params)):
            yield dict(row)

    def count(self, where: str = "", params: Iterable[Any] = ()) -> int:
        sql = "SELECT COUNT(*) AS n FROM papers"
        if where:
            sql += f" WHERE {where}"
        return self._conn.execute(sql, tuple(params)).fetchone()["n"]

    # ----- harvest checkpoint -----
    def get_harvest_status(self, venue_name: str, year: int) -> str | None:
        row = self._conn.execute(
            "SELECT status FROM harvest_runs WHERE venue_name=? AND year=?",
            (venue_name, year),
        ).fetchone()
        return row["status"] if row else None

    def mark_harvest_done(self, venue_name: str, year: int, paper_count: int) -> None:
        status = "done" if paper_count > 0 else "empty"
        self._conn.execute(
            "INSERT INTO harvest_runs (venue_name, year, status, paper_count, last_error, updated_at) "
            "VALUES (?, ?, ?, ?, NULL, ?) "
            "ON CONFLICT(venue_name, year) DO UPDATE SET "
            "status=excluded.status, paper_count=excluded.paper_count, "
            "last_error=NULL, updated_at=excluded.updated_at",
            (venue_name, year, status, paper_count, now_iso()),
        )
        self._conn.commit()

    def mark_harvest_failed(self, venue_name: str, year: int, err: str) -> None:
        self._conn.execute(
            "INSERT INTO harvest_runs (venue_name, year, status, paper_count, last_error, updated_at) "
            "VALUES (?, ?, 'failed', 0, ?, ?) "
            "ON CONFLICT(venue_name, year) DO UPDATE SET "
            "status='failed', last_error=excluded.last_error, updated_at=excluded.updated_at",
            (venue_name, year, err[:4000], now_iso()),
        )
        self._conn.commit()

    # ----- LLM cache -----
    def get_llm_cached(self, input_hash: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM llm_calls WHERE input_hash=?", (input_hash,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        if data.get("response_json"):
            try:
                data["response"] = json.loads(data["response_json"])
            except Exception:
                data["response"] = None
        return data

    def save_llm_call(
        self,
        paper_id: str,
        stage: str,
        model: str,
        prompt_version: str,
        input_hash: str,
        response: dict[str, Any] | str,
    ) -> None:
        resp_json = response if isinstance(response, str) else json.dumps(
            response, ensure_ascii=False
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO llm_calls "
            "(paper_id, stage, model, prompt_version, input_hash, response_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (paper_id, stage, model, prompt_version, input_hash, resp_json, now_iso()),
        )
        self._conn.commit()

    # ----- taxonomy descriptions -----
    def upsert_taxonomy_desc(
        self,
        tree_name: str,
        path: str,
        desc_en: str | None = None,
        desc_zh: str | None = None,
        paper_count: int | None = None,
        metadata: dict[str, Any] | None = None,
        status: str | None = None,
        last_error: str | None = None,
    ) -> None:
        ts = now_iso()
        metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
        self._conn.execute(
            """
            INSERT INTO taxonomy_descriptions (tree_name, path, desc_en, desc_zh, paper_count, metadata_json, status, last_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tree_name, path) DO UPDATE SET
                desc_en=COALESCE(excluded.desc_en, desc_en),
                desc_zh=COALESCE(excluded.desc_zh, desc_zh),
                paper_count=COALESCE(excluded.paper_count, paper_count),
                metadata_json=COALESCE(excluded.metadata_json, metadata_json),
                status=COALESCE(excluded.status, status),
                last_error=COALESCE(excluded.last_error, last_error),
                updated_at=excluded.updated_at
            """,
            (tree_name, path, desc_en, desc_zh, paper_count, metadata_json, status, last_error, ts, ts),
        )
        self._conn.commit()

    def set_taxonomy_status(
        self,
        tree_name: str,
        path: str,
        status: str,
        last_error: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO taxonomy_descriptions (tree_name, path, status, last_error, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tree_name, path) DO UPDATE SET
                status=excluded.status,
                last_error=excluded.last_error,
                updated_at=excluded.updated_at
            """,
            (tree_name, path, status, last_error, now_iso()),
        )
        self._conn.commit()

    def get_taxonomy_desc(self, tree_name: str, path: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM taxonomy_descriptions WHERE tree_name=? AND path=?",
            (tree_name, path),
        ).fetchone()
        return dict(row) if row else None

    def iter_taxonomy_descs(self) -> Iterator[dict[str, Any]]:
        for row in self._conn.execute("SELECT * FROM taxonomy_descriptions"):
            yield dict(row)


@contextmanager
def open_db(path: Path):
    db = DB(path)
    try:
        yield db
    finally:
        db.close()
