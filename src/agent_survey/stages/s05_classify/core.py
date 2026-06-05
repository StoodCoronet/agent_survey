"""Batch worker for classification stage."""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from ...core.config import Config
from ...core.console import console
from ...core.db import DB
from ...services.llm import DeepSeekClient, cached_chat_json
from .parsers import normalize_result, parse_batch_result
from .prompts import build_batch_messages, build_single_messages


def classify_single(
    llm: DeepSeekClient,
    db: DB,
    paper: dict,
    stage_cfg: Any,
    classify_cfg,
    pt_version: str = "v1",
    topic_name: str = "",
    worker_name: str = "",
) -> tuple[dict | None, dict, bool]:
    """Returns (parsed_content, usage_dict, cached_bool)."""
    messages = build_single_messages(paper, classify_cfg)
    t0 = time.time()
    out = cached_chat_json(
        llm, db,
        paper_id=paper["paper_id"],
        stage="classify",
        model=stage_cfg.model,
        prompt_version=pt_version,
        messages=messages,
        temperature=stage_cfg.temperature,
        max_tokens=stage_cfg.max_tokens,
        topic_name=topic_name,
        timeout=getattr(stage_cfg, "timeout", 120.0),
    )
    elapsed = time.time() - t0
    cached = out.get("cached", False)
    u = out.get("usage") or {}
    # Only log slow/non-cache calls to avoid console lock contention with Live
    if not cached and elapsed > 5:
        console.print(
            f"[dim][{worker_name}] OK single {paper['paper_id']} "
            f"in{u.get('prompt_tokens', 0)} out{u.get('completion_tokens', 0)} "
            f"({elapsed:.2f}s)[/dim]"
        )
    data = out.get("content")
    if isinstance(data, dict):
        data = normalize_result(data)
    return data, u, cached


def _meta(
    worker_name: str,
    u: dict | None = None,
    c: bool = False,
    err: bool = False,
) -> dict:
    return {
        "worker": worker_name,
        "usage": dict(u) if u else {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "cached": c,
        "errors": 1 if err else 0,
    }


def _merge_meta(left: dict, right: dict) -> dict:
    worker_name = left.get("worker", "unknown")
    lu = left.get("usage") or {}
    ru = right.get("usage") or {}
    return {
        "worker": worker_name,
        "usage": {
            "prompt_tokens": (lu.get("prompt_tokens", 0) or 0) + (ru.get("prompt_tokens", 0) or 0),
            "completion_tokens": (lu.get("completion_tokens", 0) or 0) + (ru.get("completion_tokens", 0) or 0),
            "total_tokens": (lu.get("total_tokens", 0) or 0) + (ru.get("total_tokens", 0) or 0),
        },
        "cached": left.get("cached", False) or right.get("cached", False),
        "errors": (left.get("errors", 0) or 0) + (right.get("errors", 0) or 0),
    }


def process_batch_worker(
    batch: list[dict],
    cfg: Config,
    stage_cfg: Any,
    classify_cfg,
    pt_version: str = "v1",
    db: DB | None = None,
    llm: DeepSeekClient | None = None,
    topic_name: str = "",
) -> tuple[list[dict], list[dict] | None, Exception | None, dict]:
    """Worker that runs in a thread. Handles its own fallback (split-half → singles)."""
    worker_name = threading.current_thread().name
    own_db = db is None
    own_llm = llm is None
    db = db or DB(cfg.abs_path("db"))
    llm = llm or DeepSeekClient(cfg)
    pids = ", ".join([p["paper_id"] for p in batch[:3]])
    if len(batch) > 3:
        pids += f" ... ({len(batch)} total)"

    try:
        # ---- Single paper: fast path ----
        if len(batch) == 1:
            data, u, c = classify_single(llm, db, batch[0], stage_cfg, classify_cfg, pt_version + "_single", topic_name, worker_name)
            return batch, [data], None, _meta(worker_name, u, c)

        # ---- Try batch call ----
        messages = build_batch_messages(batch, classify_cfg)
        t0 = time.time()
        out = cached_chat_json(
            llm, db,
            paper_id=f"batch_{batch[0]['paper_id']}",
            stage="classify_batch",
            model=stage_cfg.model,
            prompt_version=pt_version + "_batch",
            messages=messages,
            temperature=stage_cfg.temperature,
            max_tokens=stage_cfg.max_tokens * len(batch),
            topic_name=topic_name,
            timeout=getattr(stage_cfg, "timeout", 120.0),
        )
        elapsed = time.time() - t0
        u = out.get("usage") or {}
        cached = out.get("cached", False)
        # Only log slow or non-cache calls to avoid console lock contention
        if not cached and elapsed > 2:
            console.print(
                f"[dim][{worker_name}] OK batch {pids} "
                f"in{u.get('prompt_tokens', 0)} out{u.get('completion_tokens', 0)} "
                f"({elapsed:.2f}s)[/dim]"
            )
        results = parse_batch_result(out.get("raw", json.dumps(out["content"])), len(batch))
        if len(results) == len(batch):
            return batch, results, None, _meta(worker_name, u, cached)

        # Partial / wrong count → fall through to split retry
        raise ValueError(f"Batch returned {len(results)} results, expected {len(batch)}")

    except Exception as e:
        console.print(f"[red][{worker_name}] FAIL batch {pids}: {type(e).__name__}: {e}[/red]")
        # ---- Fallback: tiny batches go straight to singles ----
        if len(batch) <= 3:
            all_results: list[dict] = []
            total_u = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            any_cached = False
            any_err = False
            for paper in batch:
                try:
                    data, u, c = classify_single(llm, db, paper, stage_cfg, classify_cfg, pt_version + "_single", topic_name, worker_name)
                    total_u["prompt_tokens"] += u.get("prompt_tokens", 0) or 0
                    total_u["completion_tokens"] += u.get("completion_tokens", 0) or 0
                    total_u["total_tokens"] += u.get("total_tokens", 0) or 0
                    if c:
                        any_cached = True
                    all_results.append(data)
                except Exception as se:
                    any_err = True
            if any_err:
                return batch, all_results or None, Exception("Some singles failed"), _meta(worker_name, total_u, any_cached, err=True)
            return batch, all_results, None, _meta(worker_name, total_u, any_cached)

        # ---- Split in half and recurse (same thread, same db/llm) ----
        console.print(f"[yellow][{worker_name}] SPLIT batch {len(batch)} → {len(batch)//2}+{len(batch)-len(batch)//2}[/yellow]")
        mid = len(batch) // 2
        left_b, left_r, left_e, left_m = process_batch_worker(
            batch[:mid], cfg, stage_cfg, classify_cfg, pt_version, db=db, llm=llm, topic_name=topic_name
        )
        right_b, right_r, right_e, right_m = process_batch_worker(
            batch[mid:], cfg, stage_cfg, classify_cfg, pt_version, db=db, llm=llm, topic_name=topic_name
        )

        combined = _merge_meta(left_m, right_m)
        if left_e and right_e:
            return batch, None, ValueError("Both halves failed"), combined
        all_results = (left_r or []) + (right_r or [])
        return batch, all_results, None, combined

    finally:
        if own_db:
            db.close()
