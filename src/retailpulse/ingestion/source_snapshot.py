"""File identity primitives for immutable source snapshots.

This module has no workbook or database dependency on purpose. It lets us test
the essential ingestion identity contract before wiring external boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from contextlib import contextmanager
from collections.abc import Iterator


@dataclass(frozen=True)
class SourceSnapshot:
    """Metadata that identifies one source-file payload."""

    source_uri: str
    local_path: Path
    original_filename: str
    byte_size: int
    sha256_hex: str
    observed_at: datetime


def compute_sha256(path: Path, *, chunk_size: int = 1_048_576) -> str:
    """Return the SHA-256 checksum of a regular, non-empty file.

    A checksum identifies content, unlike a filename which may be reused.
    """

    if not path.is_file():
        raise FileNotFoundError(f"Source file does not exist or is not a file: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"Source file is empty: {path}")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def describe_snapshot(path: Path, *, source_uri: str) -> SourceSnapshot:
    """Build immutable metadata for a file that has already been obtained."""

    if not source_uri.strip():
        raise ValueError("source_uri must not be blank")

    resolved_path = path.resolve()
    return SourceSnapshot(
        source_uri=source_uri,
        local_path=resolved_path,
        original_filename=resolved_path.name,
        byte_size=resolved_path.stat().st_size,
        sha256_hex=compute_sha256(resolved_path),
        observed_at=datetime.now(UTC),
    )


@contextmanager
def materialized_snapshot(path: Path, *, source_uri: str) -> Iterator[SourceSnapshot]:
    """Copy a source once, then identify and read only that immutable copy.

    The caller must consume ``snapshot.local_path`` rather than the original
    path.  This closes the time-of-check/time-of-use window where a workbook
    could change after its hash was calculated but before rows were parsed.
    The temporary copy is removed when this context exits, including failures.
    """

    if not source_uri.strip():
        raise ValueError("source_uri must not be blank")
    if not path.is_file():
        raise FileNotFoundError(f"Source file does not exist or is not a file: {path}")

    with NamedTemporaryFile(prefix="retailpulse-snapshot-", suffix=".xlsx", delete=False) as copy:
        copy_path = Path(copy.name)
        digest = sha256()
        byte_size = 0
        with path.open("rb") as source:
            while chunk := source.read(1_048_576):
                copy.write(chunk)
                digest.update(chunk)
                byte_size += len(chunk)

    if byte_size == 0:
        copy_path.unlink(missing_ok=True)
        raise ValueError(f"Source file is empty: {path}")

    snapshot = SourceSnapshot(
        source_uri=source_uri,
        local_path=copy_path,
        original_filename=path.name,
        byte_size=byte_size,
        sha256_hex=digest.hexdigest(),
        observed_at=datetime.now(UTC),
    )
    try:
        yield snapshot
    finally:
        copy_path.unlink(missing_ok=True)
