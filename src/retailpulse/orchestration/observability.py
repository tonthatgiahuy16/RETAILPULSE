"""Compact run history and latency summaries for the in-repo DAG runner.

The full run record stays in ``last_run.json``. This module appends a smaller,
append-only history line per run so repeated runs can be compared without
rewriting the full evidence file.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from retailpulse.orchestration.dag import RunRecord


def _elapsed_seconds(started_at: str, finished_at: str) -> float:
    started = datetime.fromisoformat(started_at)
    finished = datetime.fromisoformat(finished_at)
    return round(max(0.0, (finished - started).total_seconds()), 6)


def slowest_timings(
    timings: Iterable[dict[str, Any]], limit: int = 3
) -> list[dict[str, Any]]:
    """Return the slowest timing entries, highest first."""

    if limit < 1:
        raise ValueError("A slowest-items limit must be at least 1")
    ordered = sorted(
        timings,
        key=lambda item: float(item.get("elapsed_seconds", 0.0)),
        reverse=True,
    )
    return [
        {
            "name": str(item.get("name", "unknown")),
            "elapsed_seconds": round(float(item.get("elapsed_seconds", 0.0)), 6),
        }
        for item in ordered[:limit]
    ]


def _task_detail_timings(record: RunRecord, task_name: str, key: str) -> list[dict[str, Any]]:
    for task in record.tasks:
        if task.name != task_name:
            continue
        value = task.detail.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []
    return []


def run_history_entry(record: RunRecord) -> dict[str, Any]:
    """Build one compact history line from a full run record."""

    source_file_id = None
    for task in record.tasks:
        if task.name == "ingest":
            source_file_id = task.detail.get("source_file_id")
            break
    return {
        "run_id": record.run_id,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "status": record.status,
        "elapsed_seconds": _elapsed_seconds(record.started_at, record.finished_at),
        "source_file_id": source_file_id,
        "tasks": [
            {
                "name": task.name,
                "status": task.status,
                "attempts": task.attempts,
                "elapsed_seconds": round(task.elapsed_seconds, 6),
            }
            for task in record.tasks
        ],
        "slowest_tasks": slowest_timings(
            (
                {"name": task.name, "elapsed_seconds": task.elapsed_seconds}
                for task in record.tasks
            )
        ),
        "slowest_sql_gates": slowest_timings(
            _task_detail_timings(record, "sql_gates", "timings")
        ),
        "slowest_materialized_views": slowest_timings(
            _task_detail_timings(record, "ingest", "materialized_view_timings")
        ),
    }


def append_history(record: RunRecord, path: Path) -> Path:
    """Append one compact JSON line to the run-history file."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(run_history_entry(record), ensure_ascii=False) + "\n")
    return target


def load_history(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL run history, rejecting malformed lines with their number."""

    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Run history not found: {target}")
    entries: list[dict[str, Any]] = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Invalid run history JSON on line {number}: {error.msg}"
            ) from error
        if not isinstance(payload, dict):
            raise ValueError(f"Run history line {number} is not a JSON object")
        entries.append(payload)
    return entries


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def summarize_history(
    entries: list[dict[str, Any]], last: int | None = None
) -> dict[str, Any]:
    """Summarize task latency across the most recent runs."""

    if last is not None:
        if last < 1:
            raise ValueError("--last must be at least 1")
        entries = entries[-last:]
    if not entries:
        raise ValueError("Cannot summarize an empty run history")

    seconds_by_task: dict[str, list[float]] = {}
    status_counts: dict[str, dict[str, int]] = {}
    for entry in entries:
        for task in entry.get("tasks", []):
            if not isinstance(task, dict):
                continue
            name = str(task.get("name", "unknown"))
            seconds_by_task.setdefault(name, []).append(
                float(task.get("elapsed_seconds", 0.0))
            )
            counts = status_counts.setdefault(name, {})
            status = str(task.get("status", "unknown"))
            counts[status] = counts.get(status, 0) + 1

    tasks = [
        {
            "name": name,
            "runs": len(values),
            "median_seconds": round(_median(values), 6),
            "max_seconds": round(max(values), 6),
            "latest_seconds": round(values[-1], 6),
            "status_counts": status_counts[name],
        }
        for name, values in seconds_by_task.items()
    ]
    tasks.sort(key=lambda item: item["median_seconds"], reverse=True)
    run_seconds = [float(entry.get("elapsed_seconds", 0.0)) for entry in entries]
    latest = entries[-1]
    return {
        "run_count": len(entries),
        "succeeded_count": sum(1 for entry in entries if entry.get("status") == "succeeded"),
        "failed_count": sum(1 for entry in entries if entry.get("status") == "failed"),
        "latest_run_id": latest.get("run_id"),
        "latest_status": latest.get("status"),
        "latest_elapsed_seconds": round(run_seconds[-1], 6),
        "median_run_seconds": round(_median(run_seconds), 6),
        "max_run_seconds": round(max(run_seconds), 6),
        "tasks": tasks,
        "latest_slowest_sql_gates": latest.get("slowest_sql_gates", []),
        "latest_slowest_materialized_views": latest.get(
            "slowest_materialized_views", []
        ),
    }


def format_summary(summary: dict[str, Any]) -> str:
    """Render a human-readable latency summary."""

    lines = [
        f"Runs: {summary['run_count']} "
        f"(succeeded {summary['succeeded_count']}, failed {summary['failed_count']})",
        f"Latest: {summary['latest_run_id']} {summary['latest_status']} "
        f"{summary['latest_elapsed_seconds']:.1f}s",
        f"Median run: {summary['median_run_seconds']:.1f}s; "
        f"max: {summary['max_run_seconds']:.1f}s",
        "",
        f"{'Task':<24}{'Runs':>5}{'Median(s)':>12}{'Max(s)':>10}{'Latest(s)':>11}",
        "-" * 62,
    ]
    for task in summary["tasks"]:
        lines.append(
            f"{task['name']:<24}{task['runs']:>5}"
            f"{task['median_seconds']:>12.1f}{task['max_seconds']:>10.1f}"
            f"{task['latest_seconds']:>11.1f}"
        )
    for title, key in (
        ("Slowest SQL gates (latest)", "latest_slowest_sql_gates"),
        ("Slowest materialized views (latest)", "latest_slowest_materialized_views"),
    ):
        items = summary.get(key) or []
        if not items:
            continue
        lines.extend(["", f"{title}:"])
        lines.extend(
            f"  {item['name']}: {item['elapsed_seconds']:.1f}s" for item in items
        )
    return "\n".join(lines)
