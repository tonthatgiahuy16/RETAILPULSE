"""Summarize pipeline task and gate latency from the local JSONL run history."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from retailpulse.orchestration.observability import (
    format_summary,
    load_history,
    summarize_history,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY = Path("data/processed/orchestration/run_history.jsonl")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history",
        type=Path,
        default=DEFAULT_HISTORY,
        help="JSONL run-history file written by scripts/run_dag.py",
    )
    parser.add_argument(
        "--last",
        type=int,
        default=None,
        help="summarize only the most recent N runs",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the summary as JSON instead of a table",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = args.history if args.history.is_absolute() else PROJECT_ROOT / args.history
    try:
        entries = load_history(target)
        summary = summarize_history(entries, args.last)
    except (FileNotFoundError, ValueError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, indent=2))
        return 2
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(format_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
