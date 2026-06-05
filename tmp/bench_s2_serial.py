"""Serial S2 benchmark: measure actual per-request latency.

Randomly picks 20 papers needing abstracts and queries S2 API
one-by-one (no concurrency, no sleep).  Reports per-request
time and aggregate throughput.
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_survey.core.config import load_config
from agent_survey.core.db import DB
from agent_survey.services.s2 import S2Client


def _valid(text: str | None) -> bool:
    return bool(text) and len(text.strip()) >= 30


def main() -> None:
    cfg = load_config()
    db = DB(cfg.abs_path("db"))
    s2 = S2Client(api_key=cfg.semantic_scholar_api_key)

    rows = db._conn.execute(
        """
        SELECT paper_id, title, venue, year
        FROM papers
        WHERE (abstract IS NULL OR abstract = '' OR LENGTH(abstract) < 30)
        ORDER BY RANDOM()
        LIMIT 20
        """
    ).fetchall()

    print(f"Benchmarking S2 API — {len(rows)} papers, serial (1 worker), no sleep\n")

    times = []
    found = 0
    for i, r in enumerate(rows, 1):
        title = r["title"] or ""
        venue = r["venue"] or "?"
        start = time.perf_counter()
        data = s2.search_by_title(title)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        has_abs = data and _valid(data.get("abstract"))
        if has_abs:
            found += 1
        status = "OK" if has_abs else "MISS"
        print(
            f"[{i:02d}/20] {elapsed:5.2f}s  {status}  [{venue}] {title[:60]}"
        )

    total = sum(times)
    avg = total / len(times) if times else 0
    min_t = min(times) if times else 0
    max_t = max(times) if times else 0
    rate = len(times) / total if total else 0

    print(f"\n{'─' * 50}")
    print(f"Total time : {total:.1f}s")
    print(f"Average    : {avg:.2f}s")
    print(f"Min / Max  : {min_t:.2f}s / {max_t:.2f}s")
    print(f"Throughput : {rate:.2f} req/s  ({rate * 60:.0f} req/min)")
    print(f"Found abs  : {found}/{len(rows)} ({found / len(rows) * 100:.0f}%)")

    s2.close()
    db.close()


if __name__ == "__main__":
    main()
