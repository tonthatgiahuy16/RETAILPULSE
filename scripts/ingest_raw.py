"""Run the Slice 1 PostgreSQL migration and raw workbook ingestion."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from retailpulse.ingestion.raw_loader import connect_psycopg, ingest_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_MIGRATION = PROJECT_ROOT / "migrations" / "001_raw_lineage.sql"


def parse_timezone_aware_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp must include a timezone, for example +07:00")
    return parsed


def apply_raw_migration(connection: object) -> None:
    migration_sql = RAW_MIGRATION.read_text(encoding="utf-8")
    cursor = connection.cursor()  # type: ignore[attr-defined]
    try:
        cursor.execute(migration_sql)
        connection.commit()  # type: ignore[attr-defined]
    except Exception:
        connection.rollback()  # type: ignore[attr-defined]
        raise
    finally:
        cursor.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--source-retrieved-at", required=True, type=parse_timezone_aware_timestamp)
    parser.add_argument(
        "--apply-migration",
        action="store_true",
        help="Apply migrations/001_raw_lineage.sql before loading (persistent database change).",
    )
    parser.add_argument("--dsn-env", default="DATABASE_URL")
    args = parser.parse_args()

    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        raise SystemExit(f"Set {args.dsn_env} before connecting to PostgreSQL.")

    connection = connect_psycopg(dsn)
    try:
        if args.apply_migration:
            apply_raw_migration(connection)
        result = ingest_workbook(
            args.workbook,
            source_uri=args.source_uri,
            source_retrieved_at=args.source_retrieved_at,
            connection_factory=lambda: connection,
        )
    finally:
        connection.close()  # type: ignore[attr-defined]

    print(
        json.dumps(
            {
                "batch_id": str(result.batch_id),
                "status": result.status,
                "source_file_id": result.source_file_id,
                "source_row_count": result.source_row_count,
                "committed_raw_row_count": result.committed_raw_row_count,
            }
        )
    )


if __name__ == "__main__":
    main()
