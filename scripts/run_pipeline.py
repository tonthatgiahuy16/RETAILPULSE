"""Run the migration ledger, optional immutable ingestion, then SQL gates."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from retailpulse.ingestion.raw_loader import ingest_workbook
from retailpulse.pipeline_runner import apply_migrations, connect_from_dsn, run_sql_checks


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_timezone_aware_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp must include a timezone, for example +07:00")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--source-uri")
    parser.add_argument("--source-retrieved-at", type=parse_timezone_aware_timestamp)
    parser.add_argument("--dsn-env", default="DATABASE_URL")
    parser.add_argument("--skip-checks", action="store_true")
    args = parser.parse_args()

    if args.workbook is None and any((args.source_uri, args.source_retrieved_at)):
        parser.error("--source-uri and --source-retrieved-at require --workbook")
    if args.workbook is not None and (not args.source_uri or args.source_retrieved_at is None):
        parser.error("--workbook requires --source-uri and --source-retrieved-at")

    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        raise SystemExit(f"Set {args.dsn_env} before connecting to PostgreSQL.")

    connection = connect_from_dsn(dsn)
    try:
        migrations = apply_migrations(connection, PROJECT_ROOT / "migrations")
        ingestion = None
        if args.workbook is not None:
            ingestion = ingest_workbook(
                args.workbook,
                source_uri=args.source_uri,
                source_retrieved_at=args.source_retrieved_at,
                connection_factory=lambda: connection,
            )
        checks = () if args.skip_checks else run_sql_checks(connection, (PROJECT_ROOT / "tests" / "sql").glob("*.sql"))
    finally:
        connection.close()  # type: ignore[attr-defined]

    print(
        json.dumps(
            {
                "applied_migrations": migrations.applied,
                "already_applied_migrations": migrations.already_applied,
                "ingestion": None if ingestion is None else {
                    "batch_id": str(ingestion.batch_id),
                    "status": ingestion.status,
                    "source_file_id": ingestion.source_file_id,
                    "source_row_count": ingestion.source_row_count,
                    "committed_raw_row_count": ingestion.committed_raw_row_count,
                },
                "checks": checks,
            }
        )
    )


if __name__ == "__main__":
    main()
