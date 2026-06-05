"""Core helpers for the enrich stage: worker tracking, venue skip, S2 client."""
from __future__ import annotations

import sys
import threading

from rich.table import Table

from ...services.s2 import S2Client

# Thread-local S2 clients so rate-limit sleeps stay per-thread
_thread_local = threading.local()

# Track what each worker thread is currently doing (venue/year/title/source)
_worker_jobs: dict[int, dict] = {}
_worker_lock = threading.Lock()


# Venue-level skip logic — if a venue fails too much, skip remaining papers
_VENUE_SKIP_MIN = 30  # min attempts before evaluating skip
_VENUE_SKIP_THRESHOLD = 0.65  # fail rate >= 65% -> skip venue

# Venues dominated by conference proceedings (S2 coverage >> arXiv)
_S2_FIRST_VENUES = {
    "icml",
    "neurips",
    "nips",
    "acl",
    "emnlp",
    "naacl",
    "eacl",
    "coling",
    "findings",
    "aaai",
    "ijcai",
    "aistats",
    "cvpr",
    "iccv",
    "eccv",
    "wacv",
    "icra",
    "iros",
    "rss",
    "kdd",
    "www",
    "sigir",
    "recsys",
    "cikm",
    "ubicomp",
    "chi",
    "cscw",
    "uist",
    "assets",
    "ase",
    "fse",
    "issta",
    "oopsla",
    "pldi",
    "popl",
    "icse",
    "msr",
    "usenix security",
    "ieee s&p",
    "ccs",
    "ndss",
    "raid",
}


def _is_s2_first(venue: str | None) -> bool:
    v = (venue or "").lower().replace(" proceedings", "").replace(" workshop", "").strip()
    return v in _S2_FIRST_VENUES


def _set_worker_job(row: dict, source: str = "?") -> None:
    with _worker_lock:
        _worker_jobs[threading.get_ident()] = {
            "title": row.get("title", "?"),
            "venue": row.get("venue", "?"),
            "year": row.get("year", "?"),
            "source": source,
        }


def _clear_worker_job() -> None:
    with _worker_lock:
        _worker_jobs.pop(threading.get_ident(), None)


def _build_worker_table() -> Table:
    with _worker_lock:
        items = list(_worker_jobs.items())
    table = Table(show_header=True, box=None, padding=(0, 1))
    table.add_column("Worker", style="dim", width=7)
    table.add_column("Source", style="cyan", width=9)
    table.add_column("Venue", width=9)
    table.add_column("Year", width=5)
    table.add_column("Title")
    for tid, job in sorted(items):
        table.add_row(
            f"W{tid % 1000:03d}",
            job.get("source", "?"),
            str(job.get("venue", "?"))[:9] if job.get("venue") else "?",
            str(job.get("year", "?")) if job.get("year") else "?",
            (job.get("title", "?") or "?")[:50],
        )
    if not items:
        table.add_row("—", "idle", "—", "—", "waiting for tasks...")
    return table


def _clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def _get_s2(api_key: str) -> S2Client:
    if not hasattr(_thread_local, "s2"):
        _thread_local.s2 = S2Client(api_key=api_key)
    return _thread_local.s2
