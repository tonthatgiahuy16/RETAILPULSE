"""Run the RetailPulse DAG once or on a fixed interval."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from retailpulse.orchestration import PipelineConfig, build_dag, validate_config
from retailpulse.orchestration.dag import RunRecord, TaskContext
from retailpulse.orchestration.observability import append_history


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("data/processed/orchestration/last_run.json")
DEFAULT_HISTORY = Path("data/processed/orchestration/run_history.jsonl")


def parse_timezone_aware_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "Timestamp must include a timezone, for example +07:00"
        )
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--source-uri")
    parser.add_argument("--source-retrieved-at", type=parse_timezone_aware_timestamp)
    parser.add_argument("--dsn-env", default="DATABASE_URL")
    parser.add_argument("--with-dbt", action="store_true")
    parser.add_argument("--train-model", action="store_true")
    parser.add_argument("--source-file-id", type=int)
    parser.add_argument("--model-output", type=Path)
    parser.add_argument("--model-markdown-output", type=Path)
    parser.add_argument("--powerbi-evidence", type=Path)
    parser.add_argument("--dbt-profiles-dir", type=Path)
    parser.add_argument("--dbt-executable", default="dbt")
    parser.add_argument("--command-timeout-seconds", type=float, default=900.0)
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="skip materialized-view refresh after ingestion (only when raw is unchanged)",
    )
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--backoff-seconds", type=float, default=2.0)
    parser.add_argument("--interval-seconds", type=float)
    parser.add_argument("--max-runs", type=int, default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--history-output",
        type=Path,
        default=DEFAULT_HISTORY,
        help="append-only JSONL run history (default: data/processed/orchestration/run_history.jsonl)",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="do not append this run to the run-history file",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> PipelineConfig:
    model_output = args.model_output or Path("data/processed/repurchase_model_evaluation.json")
    return PipelineConfig(
        project_root=PROJECT_ROOT,
        dsn_env=args.dsn_env,
        workbook=args.workbook,
        source_uri=args.source_uri,
        source_retrieved_at=args.source_retrieved_at,
        with_dbt=args.with_dbt,
        train_model=args.train_model,
        source_file_id=args.source_file_id,
        model_output=model_output,
        model_markdown_output=args.model_markdown_output,
        powerbi_evidence=args.powerbi_evidence,
        dbt_profiles_dir=args.dbt_profiles_dir,
        dbt_executable=args.dbt_executable,
        command_timeout_seconds=args.command_timeout_seconds,
        refresh_materializations=not args.skip_refresh,
    )


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def write_record(record: RunRecord, output: Path) -> Path:
    target = resolve_path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(record.to_dict(), indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return target


def log_progress(event: str, name: str, result: object | None) -> None:
    if event == "start":
        print(f"[dag] {name} started", file=sys.stderr, flush=True)
        return
    status = getattr(result, "status", "?")
    elapsed = getattr(result, "elapsed_seconds", 0.0)
    detail = ""
    error = getattr(result, "error", None)
    reason = getattr(result, "skipped_reason", None)
    if error:
        detail = f" error={error.splitlines()[0]}"
    elif reason:
        detail = f" reason={reason}"
    print(f"[dag] {name} {status} {elapsed:.1f}s{detail}", file=sys.stderr, flush=True)


def notify_failure(record: RunRecord) -> None:
    url = os.environ.get("RETAILPULSE_ALERT_WEBHOOK")
    if not url:
        return
    failed = [
        f"{task.name}: {task.error or task.skipped_reason}"
        for task in record.tasks
        if task.status != "succeeded"
    ]
    payload = json.dumps(
        {
            "text": f"RetailPulse run {record.run_id} failed",
            "run_id": record.run_id,
            "failures": failed,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
    except Exception as error:  # noqa: BLE001 - alerting must not mask the run result
        print(f"ALERT_DELIVERY_FAILED={type(error).__name__}: {error}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    graph = build_dag()
    if args.dry_run:
        print(" -> ".join(graph.order()))
        return 0

    config = build_config(args)
    errors = validate_config(config, os.environ)
    if errors:
        print(json.dumps({"status": "config_error", "errors": errors}, indent=2))
        return 2

    context = TaskContext(config=config, environ=os.environ)
    last_status = "failed"
    runs = 0
    try:
        while True:
            record = graph.run(
                context,
                default_max_attempts=args.max_attempts,
                backoff_seconds=args.backoff_seconds,
                observer=log_progress,
            )
            target = write_record(record, args.output)
            history_target = None
            if not args.no_history:
                history_target = append_history(
                    record, resolve_path(args.history_output)
                )
            last_status = record.status
            runs += 1
            print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False, default=str))
            print(f"RUN_RECORD={target}", file=sys.stderr)
            if history_target is not None:
                print(f"RUN_HISTORY={history_target}", file=sys.stderr)
            if record.status != "succeeded":
                notify_failure(record)
            if not args.interval_seconds or runs >= args.max_runs:
                break
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        print("ORCHESTRATION_INTERRUPTED", file=sys.stderr)
        return 130
    return 0 if last_status == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
