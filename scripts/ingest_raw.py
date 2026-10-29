"""Run the Slice 1 PostgreSQL migration and raw workbook ingestion."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from retailpulse.ingestion.raw_loader import connect_psycopg, ingest_workbook
from retailpulse.pipeline_runner import (
    apply_migrations,
    refresh_ingestion_materializations,
    run_sql_checks,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
def parse_timezone_aware_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp must include a timezone, for example +07:00")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--source-retrieved-at", required=True, type=parse_timezone_aware_timestamp)
    parser.add_argument(
        "--apply-migration",
        action="store_true",
        help="Apply the migration ledger before loading, then run SQL gates.",
    )
    parser.add_argument("--dsn-env", default="DATABASE_URL")
    args = parser.parse_args()

    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        raise SystemExit(f"Set {args.dsn_env} before connecting to PostgreSQL.")

    connection = connect_psycopg(dsn)
    try:
        if args.apply_migration:
            apply_migrations(connection, PROJECT_ROOT / "migrations")
        result = ingest_workbook(
            args.workbook,
            source_uri=args.source_uri,
            source_retrieved_at=args.source_retrieved_at,
            connection_factory=lambda: connection,
        )
        if args.apply_migration:
            refresh_ingestion_materializations(connection)
            run_sql_checks(connection, (PROJECT_ROOT / "tests" / "sql").glob("*.sql"))
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
