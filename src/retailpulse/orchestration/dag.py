"""Dependency-aware DAG runner for the RetailPulse batch pipeline.

The runner is deliberately small and infrastructure-free: tasks are Python
callables, dependencies are explicit, and the run record is JSON evidence.
Scheduling, retries, and downstream skipping stay testable without PostgreSQL.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4


TaskRunner = Callable[["TaskContext"], Mapping[str, Any] | None]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


@dataclass(frozen=True)
class Task:
    """One node in the pipeline graph."""

    name: str
    run: TaskRunner
    depends_on: tuple[str, ...] = ()
    max_attempts: int | None = None


@dataclass
class TaskContext:
    """Shared configuration plus artifacts produced by earlier tasks."""

    config: Any
    environ: Mapping[str, str]
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def dsn(self) -> str:
        try:
            return self.environ[self.config.dsn_env]
        except KeyError as error:
            raise RuntimeError(
                f"Set {self.config.dsn_env} before running database tasks."
            ) from error


@dataclass
class TaskResult:
    name: str
    status: str
    attempts: int
    started_at: str
    finished_at: str
    elapsed_seconds: float
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    blocked: bool = False
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "attempts": self.attempts,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": round(self.elapsed_seconds, 6),
            "detail": self.detail,
            "error": self.error,
            "blocked": self.blocked,
            "skipped_reason": self.skipped_reason,
        }


@dataclass
class RunRecord:
    run_id: str
    started_at: str
    finished_at: str
    status: str
    tasks: list[TaskResult]
    manual_actions: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "tasks": [task.to_dict() for task in self.tasks],
            "manual_actions": self.manual_actions,
        }


class DagError(ValueError):
    """Raised when the graph is malformed."""


class Dag:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def add(self, task: Task) -> "Dag":
        if task.name in self._tasks:
            raise DagError(f"duplicate task name: {task.name}")
        self._tasks[task.name] = task
        return self

    @property
    def tasks(self) -> tuple[Task, ...]:
        return tuple(self._tasks.values())

    def validate(self) -> None:
        for task in self._tasks.values():
            for dependency in task.depends_on:
                if dependency not in self._tasks:
                    raise DagError(
                        f"{task.name} depends on unknown task {dependency}"
                    )
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str, path: tuple[str, ...]) -> None:
            if name in visited:
                return
            if name in visiting:
                cycle = " -> ".join((*path, name))
                raise DagError(f"dependency cycle: {cycle}")
            visiting.add(name)
            for dependency in self._tasks[name].depends_on:
                visit(dependency, (*path, name))
            visiting.remove(name)
            visited.add(name)

        for name in self._tasks:
            visit(name, ())

    def order(self) -> tuple[str, ...]:
        """Return a stable topological order, dependencies first."""

        self.validate()
        remaining = list(self._tasks)
        done: set[str] = set()
        ordered: list[str] = []
        while remaining:
            progressed = False
            for name in list(remaining):
                if all(dependency in done for dependency in self._tasks[name].depends_on):
                    ordered.append(name)
                    done.add(name)
                    remaining.remove(name)
                    progressed = True
            if not progressed:  # pragma: no cover - validate() already catches cycles
                raise DagError("dependency cycle")
        return tuple(ordered)

    def run(
        self,
        context: TaskContext,
        *,
        default_max_attempts: int = 1,
        backoff_seconds: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        observer: Callable[[str, str, "TaskResult | None"], None] | None = None,
    ) -> RunRecord:
        order = self.order()
        results: dict[str, TaskResult] = {}
        run_started = utc_now()
        attempt_ceiling = max(1, default_max_attempts)

        for name in order:
            task = self._tasks[name]
            started = utc_now()
            started_clock = time.perf_counter()
            if observer is not None:
                observer("start", name, None)

            blocked_by = [
                dependency
                for dependency in task.depends_on
                if not _satisfied(results[dependency])
            ]
            if blocked_by:
                results[name] = TaskResult(
                    name=name,
                    status="skipped",
                    attempts=0,
                    started_at=_iso(started),
                    finished_at=_iso(utc_now()),
                    elapsed_seconds=time.perf_counter() - started_clock,
                    blocked=True,
                    skipped_reason="upstream not succeeded: " + ", ".join(blocked_by),
                )
                if observer is not None:
                    observer("finish", name, results[name])
                continue

            attempt_limit = task.max_attempts or attempt_ceiling
            last_error: str | None = None
            for attempt in range(1, attempt_limit + 1):
                try:
                    detail = dict(task.run(context) or {})
                except Exception as error:  # noqa: BLE001 - recorded as run evidence
                    last_error = f"{type(error).__name__}: {error}"
                    if attempt < attempt_limit:
                        sleep(backoff_seconds * (2 ** (attempt - 1)))
                    continue

                skipped = detail.get("skipped") is True
                status = "skipped" if skipped else "succeeded"
                result = TaskResult(
                    name=name,
                    status=status,
                    attempts=attempt,
                    started_at=_iso(started),
                    finished_at=_iso(utc_now()),
                    elapsed_seconds=time.perf_counter() - started_clock,
                    detail=detail,
                    skipped_reason=detail.get("reason") if skipped else None,
                )
                results[name] = result
                if not skipped:
                    context.artifacts[name] = detail
                break
            else:
                results[name] = TaskResult(
                    name=name,
                    status="failed",
                    attempts=attempt_limit,
                    started_at=_iso(started),
                    finished_at=_iso(utc_now()),
                    elapsed_seconds=time.perf_counter() - started_clock,
                    error=last_error,
                )
            if observer is not None:
                observer("finish", name, results[name])

        tasks = [results[name] for name in order]
        failed = any(
            result.status == "failed" or result.blocked for result in tasks
        )
        manual_actions = [
            {"task": result.name, "action": str(result.detail["manual_action"])}
            for result in tasks
            if result.detail.get("manual_action")
        ]
        return RunRecord(
            run_id=uuid4().hex[:12],
            started_at=_iso(run_started),
            finished_at=_iso(utc_now()),
            status="failed" if failed else "succeeded",
            tasks=tasks,
            manual_actions=manual_actions,
        )


def _satisfied(result: TaskResult) -> bool:
    """A task is satisfied if it succeeded or opted out without being blocked."""

    return result.status == "succeeded" or (
        result.status == "skipped" and not result.blocked
    )
