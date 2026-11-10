"""Pipeline configuration shared by the DAG graph and task handlers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping


DEFAULT_MODEL_OUTPUT = Path("data/processed/repurchase_model_evaluation.json")


@dataclass(frozen=True)
class PipelineConfig:
    project_root: Path
    dsn_env: str = "DATABASE_URL"
    workbook: Path | None = None
    source_uri: str | None = None
    source_retrieved_at: datetime | None = None
    with_dbt: bool = False
    train_model: bool = False
    source_file_id: int | None = None
    model_output: Path = DEFAULT_MODEL_OUTPUT
    powerbi_evidence: Path | None = None
    dbt_profiles_dir: Path | None = None
    dbt_executable: str = "dbt"
    command_timeout_seconds: float = 900.0
    refresh_materializations: bool = True


def validate_config(config: PipelineConfig, environ: Mapping[str, str]) -> list[str]:
    """Return every configuration problem instead of failing on the first one."""

    errors: list[str] = []
    if config.workbook is None:
        if config.source_uri or config.source_retrieved_at is not None:
            errors.append("--source-uri and --source-retrieved-at require --workbook")
    else:
        if not config.source_uri or not config.source_uri.strip():
            errors.append("--workbook requires a non-blank --source-uri")
        if config.source_retrieved_at is None:
            errors.append("--workbook requires --source-retrieved-at")
        elif config.source_retrieved_at.tzinfo is None:
            errors.append("--source-retrieved-at must include a timezone, for example +07:00")
        if not config.workbook.exists():
            errors.append(f"workbook not found: {config.workbook}")
    if not environ.get(config.dsn_env):
        errors.append(f"set {config.dsn_env} before running database tasks")
    if config.powerbi_evidence is not None and not config.powerbi_evidence.exists():
        errors.append(f"Power BI evidence not found: {config.powerbi_evidence}")
    return errors
