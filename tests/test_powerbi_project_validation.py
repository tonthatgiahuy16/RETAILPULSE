"""Regression tests for the Power BI PBIP metadata validator.

Power BI Desktop rewrites TMDL when it saves a project and omits relationship
properties that equal their model defaults. These tests pin both serialization
forms so a Desktop save cannot silently break the CI metadata gate, and prove
that genuine relationship drift is still rejected.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_TEMP_ROOT = PROJECT_ROOT / ".test-tmp"
POWERBI_ROOT = PROJECT_ROOT / "powerbi"
RELATIONSHIPS = Path("RetailPulse.SemanticModel") / "definition" / "relationships.tmdl"

SPEC = importlib.util.spec_from_file_location(
    "validate_powerbi_project", PROJECT_ROOT / "scripts" / "validate_powerbi_project.py"
)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def project_temp_directory() -> tempfile.TemporaryDirectory[str]:
    """Use a writable project-local temp root in the Windows sandbox."""

    TEST_TEMP_ROOT.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)


class PowerBiProjectValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = project_temp_directory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "powerbi"
        shutil.copytree(POWERBI_ROOT, self.root)
        self.relationships_path = self.root / RELATIONSHIPS

    def relationships_text(self) -> str:
        return self.relationships_path.read_text(encoding="utf-8")

    def write_relationships(self, text: str) -> None:
        self.relationships_path.write_text(text, encoding="utf-8")

    def with_explicit_cardinality(self) -> str:
        return re.sub(
            r"(?m)^(relationship Snapshot_\S+\r?\n)",
            r"\1\tfromCardinality: many\n\ttoCardinality: one\n",
            self.relationships_text(),
        )

    def test_repository_project_passes(self) -> None:
        """The committed PBIP files, as saved by Power BI Desktop, must pass."""

        self.assertEqual(VALIDATOR.validate_project(POWERBI_ROOT), [])

    def test_cli_reports_pass_for_repository_project(self) -> None:
        """The exact command used by CI must exit 0 and print a PASS marker."""

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = VALIDATOR.main(["--root", str(POWERBI_ROOT)])
        self.assertEqual(exit_code, 0)
        self.assertIn("POWERBI_PROJECT=PASS", output.getvalue())

    def test_desktop_default_cardinality_omission_is_accepted(self) -> None:
        """Omitting many-to-one defaults, which Desktop does on save, is valid."""

        explicit = self.with_explicit_cardinality()
        self.write_relationships(explicit)
        self.assertEqual(VALIDATOR.validate_project(self.root), [])

        stripped = re.sub(r"(?m)^\t(?:from|to)Cardinality:.*\r?\n", "", explicit)
        self.assertNotIn("fromCardinality", stripped)
        self.write_relationships(stripped)
        self.assertEqual(VALIDATOR.validate_project(self.root), [])

    def test_explicit_cardinality_is_accepted(self) -> None:
        self.write_relationships(self.with_explicit_cardinality())
        self.assertEqual(VALIDATOR.validate_project(self.root), [])

    def test_pinned_slicer_filter_is_rejected(self) -> None:
        """A slicer filter saved with a literal pins the report to one snapshot."""

        slicer = (
            self.root
            / "RetailPulse.Report"
            / "definition"
            / "pages"
            / "retailpulse_customer"
            / "visuals"
            / "source_snapshot_slicer"
            / "visual.json"
        )
        payload = json.loads(slicer.read_text(encoding="utf-8"))
        payload["visual"]["objects"] = {
            "general": [{"properties": {"filter": {"filter": {"Version": 2}}}}]
        }
        slicer.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        errors = VALIDATOR.validate_project(self.root)
        self.assertIn(
            "retailpulse_customer: source snapshot slicer must not pin a snapshot filter",
            errors,
        )

    def test_wrong_explicit_cardinality_is_rejected(self) -> None:
        drifted = self.with_explicit_cardinality().replace(
            "relationship Snapshot_bi_sales_daily\n\tfromCardinality: many\n\ttoCardinality: one\n",
            "relationship Snapshot_bi_sales_daily\n\tfromCardinality: one\n\ttoCardinality: many\n",
        )
        self.write_relationships(drifted)
        errors = VALIDATOR.validate_project(self.root)
        self.assertIn(
            "Snapshot_bi_sales_daily must model bi sales_daily as many and source snapshot as one",
            errors,
        )

    def test_missing_snapshot_relationship_is_rejected(self) -> None:
        text = self.relationships_text()
        start = text.index("relationship Snapshot_bi_sales_line")
        end = text.index("relationship Snapshot_bi_customer_lifecycle_snapshot")
        self.write_relationships(text[:start] + text[end:])
        errors = VALIDATOR.validate_project(self.root)
        self.assertIn("missing explicit snapshot relationship for bi sales_line", errors)

    def test_default_cardinality_does_not_hide_miswired_relationship(self) -> None:
        """Dropping defaults must still require the relation to join the right tables."""

        text = self.relationships_text().replace(
            "relationship Snapshot_bi_sales_daily\n\tfromColumn: 'bi sales_daily'.source_file_id",
            "relationship Snapshot_bi_sales_daily\n\tfromColumn: 'bi sales_line'.source_file_id",
        )
        self.write_relationships(text)
        errors = VALIDATOR.validate_project(self.root)
        self.assertIn("Snapshot_bi_sales_daily must join from bi sales_daily.source_file_id", errors)

    def test_priority_table_sorts_by_priority_rank(self) -> None:
        self.assertEqual(VALIDATOR.validate_project(self.root), [])
        path = (
            self.root
            / "RetailPulse.Report"
            / "definition"
            / "pages"
            / "retailpulse_customer"
            / "visuals"
            / "priority_table"
            / "visual.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        sort = payload["visual"]["query"]["sortDefinition"]["sort"]
        self.assertEqual(sort[0]["field"]["Column"]["Property"], "priority_rank")
        self.assertEqual(sort[0]["direction"], "Ascending")

        del payload["visual"]["query"]["sortDefinition"]
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        errors = VALIDATOR.validate_project(self.root)
        self.assertIn(
            "retailpulse_customer: priority table must sort by priority_rank", errors
        )

    def test_quality_page_explains_accuracy_against_base_rate(self) -> None:
        self.assertEqual(VALIDATOR.validate_project(self.root), [])
        base_rate = (
            self.root
            / "RetailPulse.Report"
            / "definition"
            / "pages"
            / "retailpulse_quality"
            / "visuals"
            / "base_rate"
            / "visual.json"
        )
        payload = json.loads(base_rate.read_text(encoding="utf-8"))
        self.assertEqual(payload["visual"]["visualType"], "card")
        self.assertIn("Repurchase base rate", json.dumps(payload))
        semantic_table = (
            POWERBI_ROOT
            / "RetailPulse.SemanticModel"
            / "definition"
            / "tables"
            / "bi repurchase_baseline_evaluation.tmdl"
        ).read_text(encoding="utf-8")
        self.assertIn("measure 'Repurchase base rate' =", semantic_table)

    def test_cancellation_chart_reports_candidate_reason(self) -> None:
        self.assertEqual(VALIDATOR.validate_project(self.root), [])
        chart = (
            self.root
            / "RetailPulse.Report"
            / "definition"
            / "pages"
            / "retailpulse_quality"
            / "visuals"
            / "cancellation_status"
            / "visual.json"
        )
        payload = json.loads(chart.read_text(encoding="utf-8"))
        category = payload["visual"]["query"]["queryState"]["Category"]["projections"][0]
        self.assertEqual(category["field"]["Column"]["Property"], "candidate_reason")

    def test_model_comparison_reads_persisted_evaluation(self) -> None:
        self.assertEqual(VALIDATOR.validate_project(self.root), [])
        table = (
            self.root
            / "RetailPulse.Report"
            / "definition"
            / "pages"
            / "retailpulse_quality"
            / "visuals"
            / "model_comparison"
            / "visual.json"
        )
        payload = json.loads(table.read_text(encoding="utf-8"))
        self.assertIn("bi repurchase_model_evaluation", json.dumps(payload))
        self.assertIn("lift_at_top_20_percent", json.dumps(payload))

    def tables_dir(self) -> Path:
        return self.root / "RetailPulse.SemanticModel" / "definition" / "tables"

    def test_visual_referencing_missing_measure_is_rejected(self) -> None:
        """A Desktop save that drops a measure must not leave visuals silently broken."""

        path = self.tables_dir() / "bi customer_lifecycle_snapshot.tmdl"
        text = path.read_text(encoding="utf-8")
        stripped = re.sub(r"(?m)^\tmeasure 'Monetary spend \(£\)' = .*\r?\n(?:\t\t.*\r?\n)*\r?\n", "", text)
        self.assertNotEqual(text, stripped)
        path.write_text(stripped, encoding="utf-8")
        errors = VALIDATOR.validate_project(self.root)
        self.assertIn(
            "retailpulse_customer/visuals/segment_spend: references missing measure "
            "'bi customer_lifecycle_snapshot'[Monetary spend (£)]",
            errors,
        )

    def test_visual_referencing_missing_column_is_rejected(self) -> None:
        path = self.tables_dir() / "bi cancellation_diagnostic.tmdl"
        text = path.read_text(encoding="utf-8")
        stripped = re.sub(r"(?m)^\tcolumn candidate_reason\r?\n(?:\t\t.*\r?\n|\r?\n)*?(?=\t\S)", "", text)
        self.assertNotEqual(text, stripped)
        path.write_text(stripped, encoding="utf-8")
        errors = VALIDATOR.validate_project(self.root)
        self.assertIn(
            "retailpulse_quality/visuals/cancellation_status: references missing column "
            "'bi cancellation_diagnostic'[candidate_reason]",
            errors,
        )


BUILD_SPEC = importlib.util.spec_from_file_location(
    "build_powerbi_report", PROJECT_ROOT / "scripts" / "build_powerbi_report.py"
)
assert BUILD_SPEC is not None and BUILD_SPEC.loader is not None
BUILDER = importlib.util.module_from_spec(BUILD_SPEC)
BUILD_SPEC.loader.exec_module(BUILDER)


def visual_contract(payload: dict) -> dict:
    """Keep the parts of a visual that carry meaning; ignore Desktop key order and formatting."""

    visual = payload["visual"]
    query = visual.get("query", {})
    containers = visual.get("visualContainerObjects", {})

    def text(key: str) -> object:
        entries = containers.get(key) or [{}]
        return entries[0].get("properties", {}).get("text")

    return {
        "visualType": visual["visualType"],
        "position": {key: payload["position"][key] for key in ("x", "y", "width", "height")},
        "queryState": {
            role: [(item["queryRef"], item["field"]) for item in state["projections"]]
            for role, state in query.get("queryState", {}).items()
        },
        "sortDefinition": query.get("sortDefinition"),
        "title": text("title"),
        "subTitle": text("subTitle"),
        "objects": visual.get("objects"),
    }


class PowerBiReportGeneratorDriftTests(unittest.TestCase):
    def test_checked_in_visuals_match_generator(self) -> None:
        """A Desktop save of a stale session must not silently revert the generated design."""

        report_dir = POWERBI_ROOT / "RetailPulse.Report" / "definition"
        with project_temp_directory() as temp:
            generated = Path(temp)
            original_root = BUILDER.ROOT
            BUILDER.ROOT = generated
            try:
                BUILDER.build()
            finally:
                BUILDER.ROOT = original_root

            generated_visuals = {
                path.relative_to(generated).as_posix() for path in generated.rglob("visual.json")
            }
            checked_in_visuals = {
                path.relative_to(report_dir).as_posix() for path in report_dir.rglob("visual.json")
            }
            self.assertEqual(generated_visuals, checked_in_visuals)
            for relative in sorted(generated_visuals):
                with self.subTest(visual=relative):
                    expected = json.loads((generated / relative).read_text(encoding="utf-8"))
                    actual = json.loads((report_dir / relative).read_text(encoding="utf-8"))
                    self.assertEqual(visual_contract(actual), visual_contract(expected))

            expected_pages = json.loads((generated / "pages" / "pages.json").read_text(encoding="utf-8"))
            actual_pages = json.loads((report_dir / "pages" / "pages.json").read_text(encoding="utf-8"))
            self.assertEqual(actual_pages["pageOrder"], expected_pages["pageOrder"])


if __name__ == "__main__":
    unittest.main()
