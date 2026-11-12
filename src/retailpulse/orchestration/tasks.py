"""Default task handlers, each reusing the existing governed entry points."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from retailpulse.orchestration.config import PipelineConfig, validate_config
from retailpulse.orchestration.dag import TaskContext


def _path(config: PipelineConfig, value: Path) -> Path:
    return value if value.is_absolute() else config.project_root / value


def _run(command: list[str], config: PipelineConfig) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            cwd=config.project_root,
            capture_output=True,
            text=True,
            timeout=config.command_timeout_seconds,
            check=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            f"command not found: {command[0]}; install it or disable this task"
        ) from error
    if completed.returncode != 0:
        combined = (completed.stdout + completed.stderr).strip().splitlines()
        tail = "\n".join(combined[-20:])
        raise RuntimeError(
            f"{' '.join(command)} exited with {completed.returncode}\n{tail}"
        )
    return completed


def validate_inputs(context: TaskContext) -> Mapping[str, Any]:
    errors = validate_config(context.config, context.environ)
    if errors:
        raise ValueError("; ".join(errors))
    config = context.config
    return {
        "dsn_env": config.dsn_env,
        "workbook": None if config.workbook is None else str(config.workbook),
        "with_dbt": config.with_dbt,
        "train_model": config.train_model,
        "powerbi_evidence": None
        if config.powerbi_evidence is None
        else str(config.powerbi_evidence),
    }


def migrate(context: TaskContext) -> Mapping[str, Any]:
    from retailpulse.pipeline_runner import apply_migrations, connect_from_dsn

    config = context.config
    connection = connect_from_dsn(context.dsn())
    try:
        outcome = apply_migrations(connection, config.project_root / "migrations")
    finally:
        connection.close()
    return {
        "applied": list(outcome.applied),
        "already_applied": list(outcome.already_applied),
    }


def ingest(context: TaskContext) -> Mapping[str, Any]:
    from retailpulse.ingestion.raw_loader import ingest_workbook
    from retailpulse.pipeline_runner import (
        connect_from_dsn,
        refresh_ingestion_materializations,
    )

    config = context.config
    if config.workbook is None:
        return {"skipped": True, "reason": "no workbook supplied"}
    if config.source_uri is None or config.source_retrieved_at is None:
        raise RuntimeError("workbook ingestion requires source_uri and retrieved_at")

    connection = connect_from_dsn(context.dsn())
    try:
        result = ingest_workbook(
            _path(config, config.workbook),
            source_uri=config.source_uri,
            source_retrieved_at=config.source_retrieved_at,
            connection_factory=lambda: connection,
        )
        materialized = (
            refresh_ingestion_materializations(connection)
            if config.refresh_materializations
            else ()
        )
    finally:
        connection.close()
    return {
        "batch_id": str(result.batch_id),
        "status": result.status,
        "source_file_id": result.source_file_id,
        "source_row_count": result.source_row_count,
        "committed_raw_row_count": result.committed_raw_row_count,
        "materialized_views": list(materialized),
        "refresh_skipped": not config.refresh_materializations,
    }


def sql_gates(context: TaskContext) -> Mapping[str, Any]:
    from retailpulse.pipeline_runner import connect_from_dsn, run_sql_checks

    config = context.config
    checks = sorted((config.project_root / "tests" / "sql").glob("*.sql"))
    if not checks:
        raise RuntimeError("no SQL gates found under tests/sql")
    connection = connect_from_dsn(context.dsn())
    try:
        executed = run_sql_checks(connection, checks)
    finally:
        connection.close()
    return {"executed": list(executed), "count": len(executed)}


def dbt_build(context: TaskContext) -> Mapping[str, Any]:
    config = context.config
    if not config.with_dbt:
        return {"skipped": True, "reason": "dbt disabled; pass --with-dbt"}
    profiles = config.dbt_profiles_dir or (config.project_root / "dbt")
    completed = _run(
        [
            config.dbt_executable,
            "build",
            "--project-dir",
            str(config.project_root / "dbt"),
            "--profiles-dir",
            str(profiles),
        ],
        config,
    )
    tail = completed.stdout.strip().splitlines()[-5:]
    return {"returncode": completed.returncode, "tail": tail}


def train_model(context: TaskContext) -> Mapping[str, Any]:
    import sys

    config = context.config
    if not config.train_model:
        return {"skipped": True, "reason": "model training disabled; pass --train-model"}
    output = _path(config, config.model_output)
    command = [
        sys.executable,
        str(config.project_root / "scripts" / "train_repurchase_model.py"),
        "--dsn-env",
        config.dsn_env,
        "--output",
        str(output),
    ]
    if config.source_file_id is not None:
        command.extend(["--source-file-id", str(config.source_file_id)])
    if config.model_markdown_output is not None:
        command.extend(
            ["--markdown-output", str(_path(config, config.model_markdown_output))]
        )
    completed = _run(command, config)
    return {
        "returncode": completed.returncode,
        "output": str(output),
        "stdout": completed.stdout.strip(),
    }


def powerbi_refresh(context: TaskContext) -> Mapping[str, Any]:
    config = context.config
    manual_action = (
        "Open powerbi/RetailPulse.pbip in Power BI Desktop, refresh the Import "
        "model for the selected snapshot, then record refreshed_at and "
        "source_file_id in a JSON file and pass --powerbi-evidence."
    )
    if config.powerbi_evidence is None:
        return {"manual_action": manual_action}

    path = _path(config, config.powerbi_evidence)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not {
        "refreshed_at",
        "source_file_id",
    } <= set(payload):
        raise ValueError(
            "Power BI evidence must be a JSON object with refreshed_at and source_file_id"
        )
    return {
        "verified_evidence": str(path),
        "refreshed_at": payload["refreshed_at"],
        "source_file_id": payload["source_file_id"],
        "note": "static evidence only; this task does not refresh Power BI",
    }
