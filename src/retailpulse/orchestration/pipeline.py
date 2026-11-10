"""Pipeline graph composition for RetailPulse."""

from __future__ import annotations

from typing import Callable, Mapping

from retailpulse.orchestration import tasks
from retailpulse.orchestration.config import (
    DEFAULT_MODEL_OUTPUT,
    PipelineConfig,
    validate_config,
)
from retailpulse.orchestration.dag import Dag, Task


DEFAULT_HANDLERS: dict[str, Callable[..., Mapping | None]] = {
    "validate_inputs": tasks.validate_inputs,
    "migrate": tasks.migrate,
    "ingest": tasks.ingest,
    "sql_gates": tasks.sql_gates,
    "dbt_build": tasks.dbt_build,
    "train_model": tasks.train_model,
    "powerbi_refresh": tasks.powerbi_refresh,
}


def build_dag(
    handlers: Mapping[str, Callable[..., Mapping | None]] | None = None,
) -> Dag:
    """Build the governed task graph; handlers can be replaced in tests."""

    resolved = dict(DEFAULT_HANDLERS)
    if handlers:
        resolved.update(handlers)

    graph = Dag()
    graph.add(Task("validate_inputs", resolved["validate_inputs"]))
    graph.add(Task("migrate", resolved["migrate"], depends_on=("validate_inputs",)))
    graph.add(Task("ingest", resolved["ingest"], depends_on=("migrate",)))
    graph.add(Task("sql_gates", resolved["sql_gates"], depends_on=("ingest",)))
    graph.add(Task("dbt_build", resolved["dbt_build"], depends_on=("sql_gates",)))
    graph.add(Task("train_model", resolved["train_model"], depends_on=("sql_gates",)))
    graph.add(
        Task(
            "powerbi_refresh",
            resolved["powerbi_refresh"],
            depends_on=("dbt_build", "train_model"),
        )
    )
    return graph


__all__ = [
    "DEFAULT_HANDLERS",
    "DEFAULT_MODEL_OUTPUT",
    "PipelineConfig",
    "build_dag",
    "validate_config",
]
