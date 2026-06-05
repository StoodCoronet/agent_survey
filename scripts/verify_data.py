"""Data integrity verification script for Agent Survey.

Run on any machine with the DB file:
    python scripts/verify_data.py [path/to/db.sqlite]

Produces a structured report to stdout + optional markdown file.
Exit code 0 = all checks pass, 1 = any critical failure.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any


class CheckResult:
    def __init__(self, name: str, status: str, detail: str = "", data: dict | None = None):
        self.name = name
        self.status = status  # "PASS" | "WARN" | "FAIL"
        self.detail = detail
        self.data = data or {}


class Verifier:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.results: list[CheckResult] = []
        self._critical_failures = 0

    def close(self):
        self.conn.close()

    def _check(self, name: str, condition: bool, detail: str = "", data: dict | None = None) -> CheckResult:
        status = "PASS" if condition else "FAIL"
        if not condition:
            self._critical_failures += 1
        r = CheckResult(name, status, detail, data)
        self.results.append(r)
        return r

    def _warn(self, name: str, condition: bool, detail: str = "", data: dict | None = None) -> CheckResult:
        status = "PASS" if condition else "WARN"
        r = CheckResult(name, status, detail, data)
        self.results.append(r)
        return r

    # ------------------------------------------------------------------
    # Schema checks
    # ------------------------------------------------------------------
    def check_schema(self):
        required_tables = ["papers", "llm_calls", "harvest_runs", "taxonomy_descriptions"]
        cur = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r["name"] for r in cur}
        for t in required_tables:
            self._check(f"table_exists:{t}", t in tables, f"missing table {t}" if t not in tables else "")

        # papers columns
        cur = self.conn.execute("PRAGMA table_info(papers)")
        cols = {r["name"] for r in cur}
        required_cols = [
            "paper_id", "title", "abstract", "venue", "year", "relevance",
            "taxonomy_json", "short_title", "summary_en", "summary_zh",
            "stage_status_json", "created_at", "updated_at",
        ]
        for c in required_cols:
            self._check(f"papers_col:{c}", c in cols, f"missing column {c}" if c not in cols else "")

        # taxonomy_descriptions columns
        cur = self.conn.execute("PRAGMA table_info(taxonomy_descriptions)")
        tcols = {r["name"] for r in cur}
        for c in ["tree_name", "path", "desc_en", "desc_zh", "metadata_json", "status"]:
            self._check(f"taxonomy_col:{c}", c in tcols, f"missing column {c}" if c not in tcols else "")

    # ------------------------------------------------------------------
    # Data volume checks
    # ------------------------------------------------------------------
    def check_volumes(self):
        total = self.conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        core = self.conn.execute("SELECT COUNT(*) FROM papers WHERE relevance='core'").fetchone()[0]
        related = self.conn.execute("SELECT COUNT(*) FROM papers WHERE relevance='related'").fetchone()[0]
        adjacent = self.conn.execute("SELECT COUNT(*) FROM papers WHERE relevance='adjacent'").fetchone()[0]
        irrelevant = self.conn.execute("SELECT COUNT(*) FROM papers WHERE relevance='irrelevant'").fetchone()[0]

        self._check("volume:total_papers", total > 0, f"total={total}", {"total": total})
        self._warn("volume:core_papers", core > 0, f"core={core}", {"core": core})
        self.results.append(CheckResult("volume:breakdown", "INFO", "", {
            "core": core, "related": related, "adjacent": adjacent, "irrelevant": irrelevant
        }))

        # Harvest completeness
        cur = self.conn.execute("SELECT status, COUNT(*) AS n FROM harvest_runs GROUP BY status")
        harvest = {r["status"]: r["n"] for r in cur}
        self.results.append(CheckResult("harvest:status", "INFO", "", harvest))

        failed_harvest = harvest.get("failed", 0)
        self._warn("harvest:no_failures", failed_harvest == 0, f"{failed_harvest} failed harvest runs", {"failed": failed_harvest})

    # ------------------------------------------------------------------
    # Field completeness checks
    # ------------------------------------------------------------------
    def check_field_completeness(self):
        core_where = "WHERE relevance='core'"

        checks = [
            ("abstract", f"{core_where} AND (abstract IS NULL OR abstract='')"),
            ("summary_en", f"{core_where} AND (summary_en IS NULL OR summary_en='')"),
            ("summary_zh", f"{core_where} AND (summary_zh IS NULL OR summary_zh='')"),
            ("short_title", f"{core_where} AND (short_title IS NULL OR short_title='')"),
            ("taxonomy_json", f"{core_where} AND (taxonomy_json IS NULL OR taxonomy_json='' OR taxonomy_json='{{}}')"),
            ("pdf_path", f"{core_where} AND (pdf_path IS NULL OR pdf_path='')"),
        ]

        core_total = self.conn.execute("SELECT COUNT(*) FROM papers WHERE relevance='core'").fetchone()[0]
        for field, cond in checks:
            missing = self.conn.execute(f"SELECT COUNT(*) FROM papers {cond}").fetchone()[0]
            pct = (1 - missing / core_total) * 100 if core_total else 0
            status = "PASS" if missing == 0 else ("WARN" if pct >= 90 else "FAIL")
            r = CheckResult(f"completeness:{field}", status, f"{missing}/{core_total} missing ({pct:.1f}%)", {"missing": missing, "total": core_total, "pct": round(pct, 2)})
            self.results.append(r)
            if status == "FAIL":
                self._critical_failures += 1

    # ------------------------------------------------------------------
    # Taxonomy checks
    # ------------------------------------------------------------------
    def check_taxonomy(self):
        total_nodes = self.conn.execute("SELECT COUNT(*) FROM taxonomy_descriptions").fetchone()[0]
        with_desc = self.conn.execute("SELECT COUNT(*) FROM taxonomy_descriptions WHERE desc_en IS NOT NULL AND desc_en!=''").fetchone()[0]
        missing_desc = total_nodes - with_desc

        self._warn("taxonomy:all_described", missing_desc == 0,
                   f"{missing_desc}/{total_nodes} nodes missing desc_en",
                   {"total": total_nodes, "with_desc": with_desc, "missing": missing_desc})

        # Check for failed nodes
        failed = self.conn.execute("SELECT COUNT(*) FROM taxonomy_descriptions WHERE status='failed'").fetchone()[0]
        self._warn("taxonomy:no_failures", failed == 0, f"{failed} nodes with status='failed'", {"failed": failed})

        # Check taxonomy_json parseability
        bad_tax = 0
        bad_samples = []
        for r in self.conn.execute("SELECT paper_id, taxonomy_json FROM papers WHERE relevance='core' AND taxonomy_json IS NOT NULL AND taxonomy_json!='' AND taxonomy_json!='{}'"):
            try:
                data = json.loads(r["taxonomy_json"])
                if not isinstance(data, dict):
                    bad_tax += 1
                    bad_samples.append(r["paper_id"])
            except Exception:
                bad_tax += 1
                bad_samples.append(r["paper_id"])

        self._check("taxonomy:json_valid", bad_tax == 0,
                    f"{bad_tax} papers have invalid taxonomy_json" + (f" e.g. {bad_samples[:3]}" if bad_samples else ""),
                    {"bad_count": bad_tax, "samples": bad_samples[:5]})

    # ------------------------------------------------------------------
    # LLM cache checks
    # ------------------------------------------------------------------
    def check_llm_cache(self):
        total_calls = self.conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0]
        self.results.append(CheckResult("llm_cache:total", "INFO", f"{total_calls} cached calls", {"total": total_calls}))

        by_stage = {}
        for r in self.conn.execute("SELECT stage, COUNT(*) AS n FROM llm_calls GROUP BY stage"):
            by_stage[r["stage"]] = r["n"]
        self.results.append(CheckResult("llm_cache:by_stage", "INFO", "", by_stage))

    # ------------------------------------------------------------------
    # Relevance distribution sanity
    # ------------------------------------------------------------------
    def check_relevance_distribution(self):
        cur = self.conn.execute("SELECT relevance, COUNT(*) AS n FROM papers WHERE relevance IS NOT NULL GROUP BY relevance")
        dist = {r["relevance"]: r["n"] for r in cur}
        self.results.append(CheckResult("relevance:distribution", "INFO", "", dist))

        # Sanity: core should be minority but not zero
        core = dist.get("core", 0)
        total = sum(dist.values())
        core_pct = core / total * 100 if total else 0
        self._warn("relevance:core_sanity", 5 <= core_pct <= 50,
                   f"core={core} ({core_pct:.1f}%) — expected 5-50%",
                   {"core": core, "total": total, "pct": round(core_pct, 2)})

    # ------------------------------------------------------------------
    # Stage status tracking
    # ------------------------------------------------------------------
    def check_stage_status(self):
        stages_found = Counter()
        for r in self.conn.execute("SELECT stage_status_json FROM papers WHERE stage_status_json IS NOT NULL AND stage_status_json!=''"):
            try:
                data = json.loads(r["stage_status_json"])
                if isinstance(data, dict):
                    for stage in data.keys():
                        stages_found[stage] += 1
            except Exception:
                pass

        self.results.append(CheckResult("stage_status:tracked", "INFO", "", dict(stages_found)))

    # ------------------------------------------------------------------
    # Run all
    # ------------------------------------------------------------------
    def run_all(self):
        print(f"[verify_data] Checking: {self.db_path}")
        print(f"[verify_data] DB size: {self.db_path.stat().st_size / 1024 / 1024:.1f} MB\n")

        self.check_schema()
        self.check_volumes()
        self.check_field_completeness()
        self.check_taxonomy()
        self.check_llm_cache()
        self.check_relevance_distribution()
        self.check_stage_status()

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def print_report(self):
        print("=" * 60)
        print("DATA INTEGRITY REPORT")
        print("=" * 60)

        for r in self.results:
            icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "INFO": "ℹ️"}.get(r.status, "?")
            print(f"{icon} {r.name:<35} {r.status}")
            if r.detail:
                print(f"   → {r.detail}")
            if r.data:
                # Pretty print small dicts inline
                data_str = json.dumps(r.data, ensure_ascii=False)
                if len(data_str) < 100:
                    print(f"   → {data_str}")
                else:
                    print(f"   → {json.dumps(r.data, ensure_ascii=False, indent=2)}")

        print("=" * 60)
        total = len([r for r in self.results if r.status in ("PASS", "FAIL", "WARN")])
        passes = len([r for r in self.results if r.status == "PASS"])
        warns = len([r for r in self.results if r.status == "WARN"])
        fails = len([r for r in self.results if r.status == "FAIL"])
        print(f"Summary: {passes}/{total} PASS, {warns} WARN, {fails} FAIL")
        print(f"Critical failures: {self._critical_failures}")
        print("=" * 60)

    def write_markdown(self, path: Path):
        lines = ["# Agent Survey — Data Integrity Report\n"]
        lines.append(f"**DB**: `{self.db_path}`  \n")
        lines.append(f"**Size**: {self.db_path.stat().st_size / 1024 / 1024:.1f} MB  \n")
        lines.append(f"**Generated**: {__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}Z  \n\n")

        lines.append("| Check | Status | Detail |\n")
        lines.append("|-------|--------|--------|\n")

        for r in self.results:
            detail = r.detail.replace("|", "\\|") if r.detail else ""
            lines.append(f"| {r.name} | {r.status} | {detail} |\n")

        lines.append("\n## Detailed Data\n\n")
        for r in self.results:
            if r.data:
                lines.append(f"### {r.name}\n")
                lines.append(f"```json\n{json.dumps(r.data, ensure_ascii=False, indent=2)}\n```\n\n")

        total = len([r for r in self.results if r.status in ("PASS", "FAIL", "WARN")])
        passes = len([r for r in self.results if r.status == "PASS"])
        warns = len([r for r in self.results if r.status == "WARN"])
        fails = len([r for r in self.results if r.status == "FAIL"])
        lines.append(f"\n**Summary**: {passes}/{total} PASS, {warns} WARN, {fails} FAIL\n")

        path.write_text("".join(lines), encoding="utf-8")
        print(f"\n[verify_data] Markdown report written to: {path}")


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/db/papers.sqlite")
    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}")
        sys.exit(1)

    v = Verifier(db_path)
    try:
        v.run_all()
        v.print_report()

        md_path = Path("output/data_integrity_report.md")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        v.write_markdown(md_path)

        sys.exit(1 if v._critical_failures > 0 else 0)
    finally:
        v.close()


if __name__ == "__main__":
    main()
