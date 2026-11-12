"""Tests for the source-file identity contract."""

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

from retailpulse.ingestion.source_snapshot import (
    compute_sha256,
    describe_snapshot,
    materialized_snapshot,
)


TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / ".test-tmp"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "scripts" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FIXTURE_BUILDER = _load_script("build_ci_fixture")
MODEL_FIXTURE_BUILDER = _load_script("build_model_fixture")


def project_temp_directory() -> tempfile.TemporaryDirectory[str]:
    """Use a writable project-local temp root in the Windows sandbox."""

    TEST_TEMP_ROOT.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)


class SourceSnapshotTests(unittest.TestCase):
    def test_checked_in_ci_fixtures_match_generators(self) -> None:
        """Committed workbooks must not silently drift from their generators."""
        from openpyxl import load_workbook

        def workbook_rows(path: Path) -> tuple[tuple[str, tuple[tuple[object, ...], ...]], ...]:
            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                return tuple(
                    (sheet.title, tuple(tuple(row) for row in sheet.iter_rows(values_only=True)))
                    for sheet in workbook.worksheets
                )
            finally:
                workbook.close()

        for builder, filename in (
            (FIXTURE_BUILDER, "mini_retail.xlsx"),
            (MODEL_FIXTURE_BUILDER, "model_evaluation_retail.xlsx"),
        ):
            with self.subTest(filename=filename):
                checked_in = PROJECT_ROOT / "tests" / "fixtures" / filename
                with project_temp_directory() as directory:
                    generated_path = Path(directory) / filename
                    original_output = builder.OUTPUT
                    builder.OUTPUT = generated_path
                    try:
                        builder.main()
                    finally:
                        builder.OUTPUT = original_output
                    self.assertEqual(workbook_rows(checked_in), workbook_rows(generated_path))

    def test_snapshot_uses_content_hash_not_filename(self) -> None:
        payload = b"retailpulse-source-fixture\n"
        with project_temp_directory() as directory:
            source = Path(directory) / "renamable.xlsx"
            source.write_bytes(payload)

            snapshot = describe_snapshot(source, source_uri="https://example.test/source.xlsx")

        self.assertEqual(snapshot.original_filename, "renamable.xlsx")
        self.assertEqual(snapshot.byte_size, len(payload))
        self.assertEqual(snapshot.sha256_hex, hashlib.sha256(payload).hexdigest())
        self.assertTrue(snapshot.observed_at.tzinfo is not None)

    def test_changed_content_changes_hash(self) -> None:
        with project_temp_directory() as directory:
            source = Path(directory) / "source.xlsx"
            source.write_bytes(b"first")
            first_hash = compute_sha256(source)
            source.write_bytes(b"second")

            self.assertNotEqual(first_hash, compute_sha256(source))

    def test_empty_file_is_rejected(self) -> None:
        with project_temp_directory() as directory:
            source = Path(directory) / "empty.xlsx"
            source.touch()

            with self.assertRaisesRegex(ValueError, "empty"):
                compute_sha256(source)

    def test_blank_source_uri_is_rejected(self) -> None:
        with project_temp_directory() as directory:
            source = Path(directory) / "source.xlsx"
            source.write_bytes(b"fixture")

            with self.assertRaisesRegex(ValueError, "source_uri"):
                describe_snapshot(source, source_uri="   ")

    def test_materialized_snapshot_keeps_the_bytes_that_were_hashed(self) -> None:
        original_payload = b"original workbook bytes"
        with project_temp_directory() as directory:
            source = Path(directory) / "source.xlsx"
            source.write_bytes(original_payload)

            with materialized_snapshot(source, source_uri="https://example.test/source.xlsx") as snapshot:
                source.write_bytes(b"replacement workbook bytes")
                staged_path = snapshot.local_path
                self.assertEqual(staged_path.read_bytes(), original_payload)
                self.assertEqual(snapshot.sha256_hex, hashlib.sha256(original_payload).hexdigest())

            self.assertFalse(staged_path.exists())
