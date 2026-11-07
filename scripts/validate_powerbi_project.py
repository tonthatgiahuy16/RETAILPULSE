"""Validate RetailPulse PBIP metadata that affects report correctness."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "powerbi"
MODEL = ROOT / "RetailPulse.SemanticModel" / "definition"
REPORT = ROOT / "RetailPulse.Report" / "definition"
EXPECTED_SNAPSHOT_CONSUMERS = {
    "bi sales_daily",
    "bi sales_line",
    "bi customer_lifecycle_snapshot",
    "bi customer_cohort_retention",
    "bi cancellation_diagnostic",
    "bi repurchase_baseline_evaluation",
}
EXPECTED_PAGES = ["retailpulse_overview", "retailpulse_customer", "retailpulse_quality"]
CONNECTION_PARAMETERS = {"RetailPulsePostgresServer", "RetailPulsePostgresDatabase"}
EXPECTED_QUALITY_KPIS = {"baseline_precision", "baseline_recall", "baseline_accuracy"}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def main() -> int:
    errors: list[str] = []
    expressions = (MODEL / "expressions.tmdl").read_text(encoding="utf-8")
    for parameter in CONNECTION_PARAMETERS:
        if not re.search(
            rf'^expression {parameter} = .*IsParameterQuery=true.*Type="Text".*IsParameterQueryRequired=true',
            expressions,
            flags=re.MULTILINE,
        ):
            fail(errors, f"expressions.tmdl: missing required text parameter {parameter}")
    table_files = list((MODEL / "tables").glob("*.tmdl"))
    tables: dict[str, str] = {}
    for path in table_files:
        content = path.read_text(encoding="utf-8")
        match = re.search(r"^table '([^']+)'", content, flags=re.MULTILINE)
        if match:
            tables[match.group(1)] = content
            if match.group(1).startswith("bi ") and "annotation PBI_ResultType = Exception" in content:
                fail(errors, f"{path.name}: source query is recorded as Exception")
            if match.group(1).startswith("bi "):
                if 'PostgreSQL.Database("localhost:5432", "retailpulse")' in content:
                    fail(errors, f"{path.name}: PostgreSQL connection is hard-coded")
                expected_source = "PostgreSQL.Database(RetailPulsePostgresServer, RetailPulsePostgresDatabase)"
                if expected_source not in content:
                    fail(errors, f"{path.name}: does not use governed PostgreSQL parameters")
        for measure_name in re.findall(r"^\s*measure (.+?) = ```\r?$", content, flags=re.MULTILINE):
            if not re.search(
                rf"^\s*measure {re.escape(measure_name)} = ```\r?\n.*?\r?\n\s*```\r?\n\s*formatString:",
                content,
                flags=re.MULTILINE | re.DOTALL,
            ):
                fail(errors, f"{path.name}: multiline measure {measure_name} must close its DAX block before formatString")

    normalized: dict[str, str] = {}
    for table in tables:
        if not table.startswith("bi "):
            continue
        identity = re.sub(r" \(\d+\)$", "", table)
        if identity in normalized:
            fail(errors, f"duplicate BI query: {normalized[identity]!r} and {table!r}")
        normalized[identity] = table

    relationships = (MODEL / "relationships.tmdl").read_text(encoding="utf-8")
    if "relationship AutoDetected_" in relationships:
        fail(errors, "relationships.tmdl retains auto-detected relationships")
    for table in EXPECTED_SNAPSHOT_CONSUMERS:
        name = "Snapshot_" + re.sub(r"[^A-Za-z0-9]+", "_", table).strip("_")
        relationship_blocks = re.split(r"(?m)(?=^relationship )", relationships)
        match = next((block for block in relationship_blocks if block.startswith(f"relationship {name}\n") or block.startswith(f"relationship {name}\r\n")), None)
        if match is None:
            fail(errors, f"missing explicit snapshot relationship for {table}")
        elif "\tfromCardinality: many" not in match or "\ttoCardinality: one" not in match:
            fail(errors, f"{name} must model {table} as many and source snapshot as one")
    relationship_names = set(re.findall(r"^relationship ([^\r\n]+)", relationships, flags=re.MULTILINE))
    for table_name, content in tables.items():
        for relationship_name in re.findall(r"^\s*relationship: ([^\r\n]+)", content, flags=re.MULTILINE):
            if relationship_name not in relationship_names:
                fail(errors, f"{table_name}: variation refers to missing relationship {relationship_name}")

    pages = json.loads((REPORT / "pages" / "pages.json").read_text(encoding="utf-8"))
    if pages["pageOrder"] != EXPECTED_PAGES:
        fail(errors, "dashboard page order does not match the governed report design")
    for page in EXPECTED_PAGES:
        slicer = REPORT / "pages" / page / "visuals" / "source_snapshot_slicer" / "visual.json"
        if not slicer.exists():
            fail(errors, f"{page}: missing visible source snapshot slicer")
            continue
        slicer_payload = json.loads(slicer.read_text(encoding="utf-8"))
        if (
            slicer_payload.get("visual", {}).get("visualType") != "slicer"
            or "bi source_snapshot" not in json.dumps(slicer_payload)
            or "source_file_id" not in json.dumps(slicer_payload)
        ):
            fail(errors, f"{page}: source snapshot slicer has an invalid query")
    for visual_name in EXPECTED_QUALITY_KPIS:
        visual_path = REPORT / "pages" / "retailpulse_quality" / "visuals" / visual_name / "visual.json"
        if not visual_path.exists():
            fail(errors, f"retailpulse_quality: missing {visual_name} KPI")
            continue
        visual_payload = json.loads(visual_path.read_text(encoding="utf-8"))
        if visual_payload.get("visual", {}).get("visualType") != "card":
            fail(errors, f"retailpulse_quality: {visual_name} must be a card")
        if "bi repurchase_baseline_evaluation" not in json.dumps(visual_payload):
            fail(errors, f"retailpulse_quality: {visual_name} does not use the baseline contract")
    for path in REPORT.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))

    if errors:
        print("POWERBI_PROJECT=FAIL")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("POWERBI_PROJECT=PASS")
    print(f"BI_TABLES={sum(name.startswith('bi ') for name in tables)}")
    print(f"REPORT_PAGES={len(pages['pageOrder'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
