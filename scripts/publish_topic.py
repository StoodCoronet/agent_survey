#!/usr/bin/env python3
"""After taxonomy run: clean data → generate docs.

Usage:
    python scripts/publish_topic.py --topic llm-context-management
    python scripts/publish_topic.py              # uses active topic from config.yaml
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_survey.core.config import load_config


def run(cmd: list[str], desc: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {desc}")
    print(f"{'=' * 60}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"[red]FAILED: {' '.join(cmd)}[/red]")
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="Clean taxonomy data and regenerate docs")
    parser.add_argument("--topic", "-t", default="", help="Topic name (default: active topic)")
    args = parser.parse_args()

    cfg = load_config()
    topics = []
    if args.topic == "all":
        from agent_survey.core.config import list_topics
        topics = list_topics()
        if not topics:
            print("No topics found.")
            sys.exit(1)
    else:
        topic = args.topic or cfg.active_topic
        if not topic:
            print("No topic specified and no active_topic in config.yaml.")
            sys.exit(1)
        topics = [topic]

    project_root = Path(__file__).resolve().parents[1]

    for topic in topics:
        # Step 1: clean taxonomy data
        run(
            [sys.executable, str(project_root / "scripts" / "clean_taxonomy.py"), "--topic", topic],
            f"Step 1/2: Clean taxonomy data for '{topic}'",
        )

        # Step 2: generate docs
        run(
            [sys.executable, str(project_root / "scripts" / "generate_docs.py"), "--topic", topic],
            f"Step 2/2: Generate docs for '{topic}'",
        )

        print(f"\n[green]Done! docs/{topic}/ is ready.[/green]")

    print(f"\nServe locally:  survey_agent serve-docs")
    print(f"Open:           http://localhost:{cfg.docs_port or 48000}/")


if __name__ == "__main__":
    main()
