"""Shared Rich console with recording enabled.

All modules should import `console` from here so that `save_text()` captures
everything after a command finishes.
"""
from __future__ import annotations

from pathlib import Path

from rich.console import Console

# record=True keeps an in-memory transcript of everything printed/rendered,
# including progress bars, tables, panels. force_terminal=True keeps ANSI
# rendering on even when stdout is redirected (though we don't rely on it).
console = Console(record=True)


def save_log(path: Path, *, clear: bool = True, html: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if html:
        console.save_html(str(path), clear=False)
    else:
        console.save_text(str(path), clear=False)
    if clear:
        console.record = True  # keep future recording
