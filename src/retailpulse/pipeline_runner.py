"""Apply versioned PostgreSQL migrations and run SQL publish gates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Any, Protocol


MIGRATION_FILENAME = re.compile(r"^(?P<migration_id>0*[1-9][0-9]*)_[a-z0-9_]+\.sql$")
MIGRATION_LOCK_NAMESPACE = "retailpulse.schema_migration"


class Cursor(Protocol):
    def execute(self, query: str, parameters: tuple[Any, ...] | None = None) -> Any: ...

    def fetchall(self) -> list[tuple[Any, ...]]: ...

    def close(self) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class MigrationDriftError(RuntimeError):
    """Raised when the ledger and repository describe different migrations."""


@dataclass(frozen=True)
class Migration:
    migration_id: int
    path: Path
    checksum: str


@dataclass(frozen=True)
class MigrationRun:
    applied: tuple[str, ...]
    already_applied: tuple[str, ...]


def _checksum_matches_recorded_migration(path: Path, recorded_checksum: str) -> bool:
    """Allow only CRLF/LF checkout variation for an already-applied migration."""

    content = path.read_bytes()
    raw_checksum = sha256(content).hexdigest()
    logical_line_ending_checksum = sha256(
        content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    ).hexdigest()
    return recorded_checksum in {raw_checksum, logical_line_ending_checksum}


def discover_migrations(migrations_dir: Path) -> tuple[Migration, ...]:
    """Return contiguous, versioned SQL migrations with content checksums."""

    migrations: list[Migration] = []
    for path in migrations_dir.glob("*.sql"):
        match = MIGRATION_FILENAME.fullmatch(path.name)
        if match is None:
            raise MigrationDriftError(f"Migration filename must be NNN_name.sql: {path.name}")
        migrations.append(
            Migration(
                migration_id=int(match.group("migration_id")),
                path=path,
                checksum=sha256(path.read_bytes()).hexdigest(),
            )
        )

    migrations.sort(key=lambda migration: migration.migration_id)
    expected_ids = list(range(1, len(migrations) + 1))
    actual_ids = [migration.migration_id for migration in migrations]
    if actual_ids != expected_ids:
        raise MigrationDriftError(
            f"Migration ids must be contiguous from 1; found {actual_ids!r}"
        )
    return tuple(migrations)


def _ensure_ledger(connection: Connection) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("create schema if not exists ops")
        cursor.execute(
            """
            create table if not exists ops.schema_migration (
                migration_id integer primary key check (migration_id > 0),
                filename text not null unique,
                checksum char(64) not null,
                applied_at timestamptz not null default now()
            )
            """
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def _ledger_rows(connection: Connection) -> dict[int, tuple[str, str]]:
    cursor = connection.cursor()
    try:
        cursor.execute("select migration_id, filename, checksum from ops.schema_migration")
        return {int(row[0]): (str(row[1]), str(row[2])) for row in cursor.fetchall()}
    finally:
        cursor.close()


def _acquire_migration_lock(connection: Connection) -> None:
    """Serialize the complete ledger check-and-apply sequence per database."""

    cursor = connection.cursor()
    try:
        # This is session-scoped because each migration commits with its ledger
        # row, while other runners must not inspect history between commits.
        cursor.execute(
            "select pg_advisory_lock(hashtextextended(%s, 0))",
            (MIGRATION_LOCK_NAMESPACE,),
        )
    finally:
        cursor.close()


def _release_migration_lock(connection: Connection) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "select pg_advisory_unlock(hashtextextended(%s, 0))",
            (MIGRATION_LOCK_NAMESPACE,),
        )
    finally:
        cursor.close()


def apply_migrations(connection: Connection, migrations_dir: Path) -> MigrationRun:
    """Apply each unseen migration once and reject changed or missing history."""

    migrations = discover_migrations(migrations_dir)
    _acquire_migration_lock(connection)
    try:
        _ensure_ledger(connection)
        ledger = _ledger_rows(connection)
        repository_ids = {migration.migration_id for migration in migrations}
        orphaned_ids = sorted(set(ledger) - repository_ids)
        if orphaned_ids:
            raise MigrationDriftError(
                f"Applied migration(s) missing from repository: {orphaned_ids!r}"
            )

        applied: list[str] = []
        already_applied: list[str] = []
        for migration in migrations:
            recorded = ledger.get(migration.migration_id)
            if recorded is not None:
                filename, checksum = recorded
                if filename != migration.path.name or not _checksum_matches_recorded_migration(
                    migration.path, checksum
                ):
                    raise MigrationDriftError(
                        f"Migration {migration.migration_id} differs from its applied ledger record"
                    )
                already_applied.append(migration.path.name)
                continue

            cursor = connection.cursor()
            try:
                cursor.execute(migration.path.read_text(encoding="utf-8"))
                cursor.execute(
                    """
                    insert into ops.schema_migration (migration_id, filename, checksum)
                    values (%s, %s, %s)
                    """,
                    (migration.migration_id, migration.path.name, migration.checksum),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
            applied.append(migration.path.name)

        return MigrationRun(tuple(applied), tuple(already_applied))
    finally:
        _release_migration_lock(connection)


def run_sql_checks(connection: Connection, checks: Iterable[Path]) -> tuple[str, ...]:
    """Execute read-only SQL gates and roll back their transaction afterwards."""

    cursor = connection.cursor()
    executed: list[str] = []
    try:
        for check in sorted(checks):
            cursor.execute(check.read_text(encoding="utf-8"))
            executed.append(check.name)
        connection.rollback()
        return tuple(executed)
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def refresh_ingestion_materializations(connection: Connection) -> tuple[str, ...]:
    """Refresh derived relations whose source snapshot may have just changed."""

    cursor = connection.cursor()
    try:
        cursor.execute("set local max_parallel_workers_per_gather = 0")
        cursor.execute("refresh materialized view int.eligible_sale_line")
        cursor.execute("refresh materialized view int.cancellation_line")
        cursor.execute("refresh materialized view int.cancellation_sale_candidate_snapshot")
        cursor.execute("refresh materialized view int.customer_purchase_event_snapshot")
        cursor.execute("refresh materialized view dw.dim_date")
        cursor.execute("refresh materialized view dw.dim_customer")
        cursor.execute("refresh materialized view dw.dim_product")
        cursor.execute("refresh materialized view dw.fct_sales_line")
        connection.commit()
        return (
            "int.eligible_sale_line",
            "int.cancellation_line",
            "int.cancellation_sale_candidate_snapshot",
            "int.customer_purchase_event_snapshot",
            "dw.dim_date",
            "dw.dim_customer",
            "dw.dim_product",
            "dw.fct_sales_line",
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def connect_from_dsn(dsn: str) -> Connection:
    """Create a PostgreSQL connection without imposing a driver on unit tests."""

    try:
        import psycopg
    except ModuleNotFoundError as error:
        raise RuntimeError("PostgreSQL support is not installed. Install project dependencies.") from error
    return psycopg.connect(dsn)
