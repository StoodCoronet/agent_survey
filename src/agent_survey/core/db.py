"""SQLite storage."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .console import console

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
  prefilter_hit TEXT,             -- JSON: {topic_name: [matched_rules]}
  stage_status_json TEXT,         -- JSON: {topic_name: {stage: status}}
  created_at TEXT,
  updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_papers_venue_year ON papers(venue, year);

-- Per-topic classification results (paper x topic)
CREATE TABLE IF NOT EXISTS paper_topics (
  paper_id TEXT NOT NULL,
  topic_name TEXT NOT NULL,
  relevance TEXT,                 -- core / related / adjacent / irrelevant
  domain_primary TEXT,
  domain_secondary_json TEXT,
  method_tags_json TEXT,
  tldr TEXT,
  rationale TEXT,
  dedup_keep_json TEXT,           -- JSON: {core: bool, related: bool, adjacent: bool}
  topics_json TEXT,               -- stage6 topic labels
  sub_topics_json TEXT,
  taxonomy_json TEXT,             -- stage7 taxonomy classification
  short_title TEXT,
  summary_en TEXT,
  summary_zh TEXT,
  created_at TEXT,
  updated_at TEXT,
  PRIMARY KEY (paper_id, topic_name)
);

CREATE INDEX IF NOT EXISTS idx_paper_topics_topic ON paper_topics(topic_name);
CREATE INDEX IF NOT EXISTS idx_paper_topics_relevance ON paper_topics(topic_name, relevance);

-- Per-topic deepdive extraction results
CREATE TABLE IF NOT EXISTS topic_deepdive (
  paper_id TEXT NOT NULL,
  topic_name TEXT NOT NULL,
  deepdive_json TEXT,             -- structured extraction fields
  body_snapshot TEXT,             -- PDF text excerpt used
  created_at TEXT,
  updated_at TEXT,
  PRIMARY KEY (paper_id, topic_name)
);

-- Registered topics
CREATE TABLE IF NOT EXISTS topics (
  topic_name TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  description TEXT DEFAULT '',
  is_active INTEGER DEFAULT 0,
  created_at TEXT,
  updated_at TEXT
);

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
  status TEXT NOT NULL,
  paper_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (venue_name, year)
);

CREATE TABLE IF NOT EXISTS taxonomy_descriptions (
  topic_name TEXT NOT NULL DEFAULT 'gui-agent',
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
  PRIMARY KEY (topic_name, tree_name, path)
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
        self._run_migrations()

    def _run_migrations(self) -> None:
        """Idempotent migrations."""

        # Always-run migrations (new columns)
        pt_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(paper_topics)")}
        for col, col_type in [("survey_score", "REAL"), ("survey_keywords_json", "TEXT")]:
            if col not in pt_cols:
                try:
                    self._conn.execute(f"ALTER TABLE paper_topics ADD COLUMN {col} {col_type}")
                    self._conn.commit()
                except sqlite3.OperationalError:
                    pass

        # pdf_source for tracking PDF download provenance
        p_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(papers)")}
        if "pdf_source" not in p_cols:
            try:
                self._conn.execute("ALTER TABLE papers ADD COLUMN pdf_source TEXT DEFAULT NULL")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass

        # Legacy migration: old papers columns → paper_topics
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(papers)")}
        legacy_topic_cols = {"relevance", "domain_primary", "domain_secondary_json",
                             "method_tags_json", "tldr", "deepdive_json",
                             "topics_json", "sub_topics_json", "dedup_keep_json",
                             "taxonomy_json", "citation_json", "short_title",
                             "summary_en", "summary_zh", "enrich_source", "enrich_at"}

        has_legacy = legacy_topic_cols & cols
        if not has_legacy:
            return  # already migrated

        # Check if migration already done (paper_topics has data)
        row = self._conn.execute("SELECT COUNT(*) AS n FROM paper_topics").fetchone()
        if row and row["n"] > 0:
            return  # already migrated

        default_topic = "gui-agent"
        ts = now_iso()

        # Register the default topic
        self._conn.execute(
            "INSERT OR IGNORE INTO topics (topic_name, display_name, description, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (default_topic, "GUI Agent Survey", "Computer-use / GUI agent papers", ts, ts),
        )
        self._conn.commit()

        # Migrate paper-level topic data → paper_topics
        paper_ids = set()
        # Determine which legacy columns exist
        legacy_select_cols = ["paper_id", "relevance", "domain_primary", "domain_secondary_json",
                              "method_tags_json", "tldr", "deepdive_json", "topics_json",
                              "sub_topics_json", "dedup_keep_json", "taxonomy_json",
                              "short_title", "summary_en", "summary_zh"]
        if "citation_json" in cols:
            legacy_select_cols.append("citation_json")
        for r in self._conn.execute(
            f"SELECT {','.join(legacy_select_cols)} FROM papers"
        ):
            if not any(r[c] for c in ["relevance", "domain_primary", "tldr",
                                       "deepdive_json", "topics_json", "taxonomy_json"]):
                continue
            paper_id = r["paper_id"]
            paper_ids.add(paper_id)
            self._conn.execute(
                "INSERT OR IGNORE INTO paper_topics "
                "(paper_id, topic_name, relevance, domain_primary, domain_secondary_json, "
                "method_tags_json, tldr, dedup_keep_json, topics_json, sub_topics_json, "
                "taxonomy_json, short_title, summary_en, summary_zh, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    paper_id, default_topic,
                    r["relevance"], r["domain_primary"], r["domain_secondary_json"],
                    r["method_tags_json"], r["tldr"], r["dedup_keep_json"],
                    r["topics_json"], r["sub_topics_json"], r["taxonomy_json"],
                    r["short_title"], r["summary_en"], r["summary_zh"],
                    ts, ts,
                ),
            )
            # Migrate deepdive
            if r["deepdive_json"]:
                self._conn.execute(
                    "INSERT OR IGNORE INTO topic_deepdive "
                    "(paper_id, topic_name, deepdive_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (paper_id, default_topic, r["deepdive_json"], ts, ts),
                )
            # Migrate citation (stays on papers table)
            if "citation_json" in r.keys():
                cit = r["citation_json"]
                if cit:
                    try:
                        self._conn.execute("ALTER TABLE papers ADD COLUMN citation_json TEXT")
                    except sqlite3.OperationalError:
                        pass
                    self._conn.execute(
                        "UPDATE papers SET citation_json = ? WHERE paper_id = ?",
                        (cit, paper_id),
                    )

        # Migrate stage_status for papers that have topic data
        for r in self._conn.execute("SELECT paper_id, stage_status_json FROM papers"):
            if r["paper_id"] in paper_ids:
                status = {}
                if r["stage_status_json"]:
                    try:
                        status = json.loads(r["stage_status_json"])
                    except Exception:
                        status = {}
                if isinstance(status, dict):
                    # wrap under topic key if it isn't already
                    if any(k in status for k in ("harvest", "enrich", "classify", "deepdive")):
                        self._conn.execute(
                            "UPDATE papers SET stage_status_json = ? WHERE paper_id = ?",
                            (json.dumps({default_topic: status}, ensure_ascii=False), r["paper_id"]),
                        )

        self._conn.commit()
        console.print(f"[green]migrated {len(paper_ids)} papers to multi-topic schema[/green]")

        # Migrate taxonomy_descriptions: add topic_name column if missing
        td_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(taxonomy_descriptions)")}
        if "topic_name" not in td_cols:
            try:
                self._conn.execute("ALTER TABLE taxonomy_descriptions ADD COLUMN topic_name TEXT NOT NULL DEFAULT 'gui-agent'")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass

            # Migrate paper_topics: add survey_mining columns
            pt_cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(paper_topics)")}
            for col, col_type in [("survey_score", "REAL"), ("survey_keywords_json", "TEXT")]:
                if col not in pt_cols:
                    try:
                        self._conn.execute(f"ALTER TABLE paper_topics ADD COLUMN {col} {col_type}")
                        self._conn.commit()
                    except sqlite3.OperationalError:
                        pass

    def close(self) -> None:
        self._conn.close()

    # ----- paper CRUD -----
    def upsert_paper(self, paper: dict[str, Any], commit: bool = True) -> None:
        paper = dict(paper)
        paper.setdefault("created_at", now_iso())
        paper["updated_at"] = now_iso()
        for k in ("authors_json", "prefilter_hit", "stage_status_json"):
            v = paper.get(k)
            if v is not None and not isinstance(v, str):
                paper[k] = json.dumps(v, ensure_ascii=False)
        # strip per-topic keys that now live in paper_topics
        for tk in ("domain_secondary_json", "method_tags_json", "deepdive_json",
                    "topics_json", "sub_topics_json", "dedup_keep_json",
                    "taxonomy_json", "citation_json"):
            paper.pop(tk, None)
        cols = list(paper.keys())
        placeholders = ",".join(["?"] * len(cols))
        col_list = ",".join(cols)
        update_clause = ",".join(f"{c}=excluded.{c}" for c in cols if c != "paper_id" and c != "created_at")
        sql = (
            f"INSERT INTO papers ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT(paper_id) DO UPDATE SET {update_clause}"
        )
        self._conn.execute(sql, [paper[c] for c in cols])
        if commit:
            self._conn.commit()

    def update_paper(self, paper_id: str, fields: dict[str, Any], commit: bool = True) -> None:
        fields = dict(fields)
        fields["updated_at"] = now_iso()
        for k in ("authors_json", "prefilter_hit", "stage_status_json"):
            v = fields.get(k)
            if v is not None and not isinstance(v, str):
                fields[k] = json.dumps(v, ensure_ascii=False)
        # strip per-topic keys
        for tk in ("domain_secondary_json", "method_tags_json", "deepdive_json",
                    "topics_json", "sub_topics_json", "dedup_keep_json",
                    "taxonomy_json", "citation_json"):
            fields.pop(tk, None)
        if not fields:
            return
        set_clause = ",".join(f"{k}=?" for k in fields)
        self._conn.execute(
            f"UPDATE papers SET {set_clause} WHERE paper_id=?",
            list(fields.values()) + [paper_id],
        )
        if commit:
            self._conn.commit()

    def mark_stage(self, paper_id: str, stage: str, status: str = "done", topic_name: str = "", commit: bool = True) -> None:
        row = self._conn.execute(
            "SELECT stage_status_json FROM papers WHERE paper_id=?", (paper_id,)
        ).fetchone()
        status_map: dict[str, Any] = {}
        if row and row["stage_status_json"]:
            try:
                status_map = json.loads(row["stage_status_json"])
            except Exception:
                status_map = {}
        # If status_map has topic-scoped keys (e.g. {"gui-agent": {...}}), nest under topic
        if topic_name:
            if topic_name not in status_map or not isinstance(status_map.get(topic_name), dict):
                status_map[topic_name] = {}
            status_map[topic_name][stage] = status
        else:
            status_map[stage] = status
        self.update_paper(paper_id, {"stage_status_json": status_map}, commit=commit)

    def get_stage_status(self, paper_id: str, stage: str, topic_name: str = "") -> str | None:
        row = self._conn.execute(
            "SELECT stage_status_json FROM papers WHERE paper_id=?", (paper_id,)
        ).fetchone()
        if not row or not row["stage_status_json"]:
            return None
        try:
            smap = json.loads(row["stage_status_json"])
        except Exception:
            return None
        if topic_name:
            return smap.get(topic_name, {}).get(stage)
        return smap.get(stage)

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

    # ----- paper_topics CRUD -----
    def upsert_paper_topic(self, paper_id: str, topic_name: str, fields: dict[str, Any], commit: bool = True) -> None:
        fields = dict(fields)
        fields.setdefault("created_at", now_iso())
        fields["updated_at"] = now_iso()
        for k in ("domain_secondary_json", "method_tags_json", "dedup_keep_json",
                   "topics_json", "sub_topics_json", "taxonomy_json"):
            v = fields.get(k)
            if v is not None and not isinstance(v, str):
                fields[k] = json.dumps(v, ensure_ascii=False)
        cols = ["paper_id", "topic_name"] + list(fields.keys())
        placeholders = ",".join(["?"] * len(cols))
        update_clause = ",".join(f"{c}=excluded.{c}" for c in fields.keys())
        sql = (
            f"INSERT INTO paper_topics ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(paper_id, topic_name) DO UPDATE SET {update_clause}"
        )
        self._conn.execute(sql, [paper_id, topic_name] + [fields[c] for c in fields.keys()])
        if commit:
            self._conn.commit()

    def get_paper_topic(self, paper_id: str, topic_name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM paper_topics WHERE paper_id=? AND topic_name=?",
            (paper_id, topic_name),
        ).fetchone()
        return dict(row) if row else None

    def iter_paper_topics(self, topic_name: str, where: str = "",
                          params: Iterable[Any] = ()) -> Iterator[dict[str, Any]]:
        sql = (
            "SELECT pt.*, p.title, p.abstract, p.venue, p.venue_area, p.year, "
            "p.authors_json, p.doi, p.url, p.arxiv_id, p.pdf_url, p.pdf_path, "
            "p.code_url, p.prefilter_hit, p.enrich_source, p.citation_json, p.stage_status_json, "
            "td.deepdive_json "
            "FROM paper_topics pt "
            "JOIN papers p ON pt.paper_id = p.paper_id "
            "LEFT JOIN topic_deepdive td ON pt.paper_id = td.paper_id AND pt.topic_name = td.topic_name "
            "WHERE pt.topic_name = ?"
        )
        if where:
            # prefix bare column names with pt. to avoid ambiguity with papers columns
            qualified = re.sub(r'\b(relevance|domain_primary|tldr|taxonomy_json|topics_json|dedup_keep_json|summary_en|summary_zh|short_title|domain_secondary_json|method_tags_json|sub_topics_json|rationale)\b', r'pt.\1', where)
            sql += f" AND {qualified}"
        for row in self._conn.execute(sql, (topic_name,) + tuple(params)):
            yield dict(row)

    def count_topic(self, topic_name: str, where: str = "",
                    params: Iterable[Any] = ()) -> int:
        sql = "SELECT COUNT(*) AS n FROM paper_topics WHERE topic_name = ?"
        if where:
            sql += f" AND {where}"
        return self._conn.execute(sql, (topic_name,) + tuple(params)).fetchone()["n"]

    def upsert_deepdive(self, paper_id: str, topic_name: str,
                        deepdive: dict[str, Any], commit: bool = True) -> None:
        ts = now_iso()
        self._conn.execute(
            "INSERT OR REPLACE INTO topic_deepdive "
            "(paper_id, topic_name, deepdive_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (paper_id, topic_name, json.dumps(deepdive, ensure_ascii=False), ts, ts),
        )
        if commit:
            self._conn.commit()

    def get_deepdive(self, paper_id: str, topic_name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM topic_deepdive WHERE paper_id=? AND topic_name=?",
            (paper_id, topic_name),
        ).fetchone()
        if row:
            d = dict(row)
            if d.get("deepdive_json"):
                try:
                    d["deepdive"] = json.loads(d["deepdive_json"])
                except Exception:
                    pass
            return d
        return None

    # ----- topics registry -----
    def register_topic(self, topic_name: str, display_name: str,
                       description: str = "", commit: bool = True) -> None:
        ts = now_iso()
        self._conn.execute(
            "INSERT OR REPLACE INTO topics (topic_name, display_name, description, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, ?, ?)",
            (topic_name, display_name, description, ts, ts),
        )
        if commit:
            self._conn.commit()

    def list_topics(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM topics ORDER BY topic_name")]

    def set_active_topic(self, topic_name: str, commit: bool = True) -> None:
        self._conn.execute("UPDATE topics SET is_active = 0")
        self._conn.execute("UPDATE topics SET is_active = 1 WHERE topic_name = ?", (topic_name,))
        if commit:
            self._conn.commit()

    # ----- harvest checkpoint -----
    def get_harvest_status(self, venue_name: str, year: int) -> str | None:
        row = self._conn.execute(
            "SELECT status FROM harvest_runs WHERE venue_name=? AND year=?",
            (venue_name, year),
        ).fetchone()
        return row["status"] if row else None

    def mark_harvest_done(self, venue_name: str, year: int, paper_count: int, commit: bool = True) -> None:
        status = "done" if paper_count > 0 else "empty"
        self._conn.execute(
            "INSERT INTO harvest_runs (venue_name, year, status, paper_count, last_error, updated_at) "
            "VALUES (?, ?, ?, ?, NULL, ?) "
            "ON CONFLICT(venue_name, year) DO UPDATE SET "
            "status=excluded.status, paper_count=excluded.paper_count, "
            "last_error=NULL, updated_at=excluded.updated_at",
            (venue_name, year, status, paper_count, now_iso()),
        )
        if commit:
            self._conn.commit()

    def mark_harvest_failed(self, venue_name: str, year: int, err: str, commit: bool = True) -> None:
        self._conn.execute(
            "INSERT INTO harvest_runs (venue_name, year, status, paper_count, last_error, updated_at) "
            "VALUES (?, ?, 'failed', 0, ?, ?) "
            "ON CONFLICT(venue_name, year) DO UPDATE SET "
            "status='failed', last_error=excluded.last_error, updated_at=excluded.updated_at",
            (venue_name, year, err[:4000], now_iso()),
        )
        if commit:
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
        commit: bool = True,
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
        if commit:
            self._conn.commit()

    # ----- taxonomy descriptions (topic-aware) -----
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
        topic_name: str = "gui-agent",
        commit: bool = True,
    ) -> None:
        ts = now_iso()
        metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
        self._conn.execute(
            """
            INSERT INTO taxonomy_descriptions (topic_name, tree_name, path, desc_en, desc_zh, paper_count, metadata_json, status, last_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic_name, tree_name, path) DO UPDATE SET
                desc_en=COALESCE(excluded.desc_en, desc_en),
                desc_zh=COALESCE(excluded.desc_zh, desc_zh),
                paper_count=COALESCE(excluded.paper_count, paper_count),
                metadata_json=COALESCE(excluded.metadata_json, metadata_json),
                status=COALESCE(excluded.status, status),
                last_error=COALESCE(excluded.last_error, last_error),
                updated_at=excluded.updated_at
            """,
            (topic_name, tree_name, path, desc_en, desc_zh, paper_count, metadata_json, status, last_error, ts, ts),
        )
        if commit:
            self._conn.commit()

    def set_taxonomy_status(
        self,
        tree_name: str,
        path: str,
        status: str,
        last_error: str | None = None,
        topic_name: str = "gui-agent",
        commit: bool = True,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO taxonomy_descriptions (topic_name, tree_name, path, status, last_error, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic_name, tree_name, path) DO UPDATE SET
                status=excluded.status,
                last_error=excluded.last_error,
                updated_at=excluded.updated_at
            """,
            (topic_name, tree_name, path, status, last_error, now_iso()),
        )
        if commit:
            self._conn.commit()

    def get_taxonomy_desc(self, tree_name: str, path: str, topic_name: str = "gui-agent") -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM taxonomy_descriptions WHERE topic_name=? AND tree_name=? AND path=?",
            (topic_name, tree_name, path),
        ).fetchone()
        return dict(row) if row else None

    def iter_taxonomy_descs(self, topic_name: str = "") -> Iterator[dict[str, Any]]:
        if topic_name:
            for row in self._conn.execute(
                "SELECT * FROM taxonomy_descriptions WHERE topic_name=?", (topic_name,)
            ):
                yield dict(row)
        else:
            for row in self._conn.execute("SELECT * FROM taxonomy_descriptions"):
                yield dict(row)


@contextmanager
def open_db(path: Path):
    db = DB(path)
    try:
        yield db
    finally:
        db.close()
