"""Validate RetailPulse PBIP metadata that affects report correctness."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1] / "powerbi"
EXPECTED_SNAPSHOT_CONSUMERS = {
    "bi sales_daily",
    "bi sales_line",
    "bi customer_lifecycle_snapshot",
    "bi customer_cohort_retention",
    "bi cancellation_diagnostic",
    "bi repurchase_baseline_evaluation",
    "bi repurchase_model_evaluation",
}
SNAPSHOT_TABLE = "bi source_snapshot"
EXPECTED_PAGES = [
    "retailpulse_overview",
    "retailpulse_customer",
    "retailpulse_quality",
    "retailpulse_model_evaluation",
]
CONNECTION_PARAMETERS = {"RetailPulsePostgresServer", "RetailPulsePostgresDatabase"}
EXPECTED_QUALITY_KPIS = {"baseline_precision", "baseline_recall", "baseline_accuracy"}
EXPECTED_MODEL_EVALUATION_CARDS = {
    "logistic_roc_auc",
    "logistic_pr_auc",
    "logistic_lift_top_20",
    "logistic_brier_score",
}
SNAPSHOT_GUARDED_MODEL_MEASURES = {
    "Logistic Regression ROC-AUC",
    "Logistic Regression PR-AUC",
    "Logistic Regression Lift at top 20%",
    "Logistic Regression Brier score",
    "Holdout customer count",
    "Evaluation date",
    "Evaluation method coverage",
    "Evaluation Precision at threshold",
    "Evaluation Recall at threshold",
    "Comparison decision threshold",
    "Comparison holdout customers",
    "Comparison precision at threshold",
    "Comparison recall at threshold",
    "Comparison PR-AUC",
    "Comparison ROC-AUC",
    "Comparison Lift at top 20%",
    "Comparison Brier score",
}
ROW_SCOPED_COMPARISON_MEASURES = {
    "Comparison decision threshold",
    "Comparison holdout customers",
    "Comparison precision at threshold",
    "Comparison recall at threshold",
    "Comparison PR-AUC",
    "Comparison ROC-AUC",
    "Comparison Lift at top 20%",
    "Comparison Brier score",
}

# TMDL omits properties that equal their model default. A relationship is
# many-to-one unless it states otherwise, so Power BI Desktop drops
# fromCardinality/toCardinality when a relationship is saved unchanged.
DEFAULT_FROM_CARDINALITY = "many"
DEFAULT_TO_CARDINALITY = "one"


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def parse_relationship_blocks(text: str) -> dict[str, str]:
    """Map each relationship name to its property lines, keeping only the block body."""

    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        header = re.match(r"^relationship (?!:)(.+?)\s*$", line)
        if header:
            current = header.group(1)
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return {name: "\n".join(lines) for name, lines in blocks.items()}


def relationship_property(block: str, name: str) -> str | None:
    match = re.search(rf"(?m)^\s*{name}:\s*(.+?)\s*$", block)
    return match.group(1) if match else None


def column_table(block: str, property_name: str) -> str | None:
    value = relationship_property(block, property_name)
    if value is None:
        return None
    match = re.fullmatch(r"'([^']+)'\.[^.\s]+", value)
    return match.group(1) if match else None


def effective_cardinality(block: str) -> tuple[str, str]:
    """Resolve declared cardinality, falling back to the TMDL many-to-one default."""

    from_cardinality = relationship_property(block, "fromCardinality") or DEFAULT_FROM_CARDINALITY
    to_cardinality = relationship_property(block, "toCardinality") or DEFAULT_TO_CARDINALITY
    return from_cardinality, to_cardinality


def validate_model(model_dir: Path) -> list[str]:
    errors: list[str] = []
    expressions = (model_dir / "expressions.tmdl").read_text(encoding="utf-8")
    for parameter in CONNECTION_PARAMETERS:
        if not re.search(
            rf'^expression {parameter} = .*IsParameterQuery=true.*Type="Text".*IsParameterQueryRequired=true',
            expressions,
            flags=re.MULTILINE,
        ):
            fail(errors, f"expressions.tmdl: missing required text parameter {parameter}")
    table_files = list((model_dir / "tables").glob("*.tmdl"))
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

    relationships = (model_dir / "relationships.tmdl").read_text(encoding="utf-8")
    if "relationship AutoDetected_" in relationships:
        fail(errors, "relationships.tmdl retains auto-detected relationships")
    relationship_blocks = parse_relationship_blocks(relationships)
    relationship_names = set(relationship_blocks)
    for table in sorted(EXPECTED_SNAPSHOT_CONSUMERS):
        name = "Snapshot_" + re.sub(r"[^A-Za-z0-9]+", "_", table).strip("_")
        block = relationship_blocks.get(name)
        if block is None:
            fail(errors, f"missing explicit snapshot relationship for {table}")
            continue
        from_cardinality, to_cardinality = effective_cardinality(block)
        if (from_cardinality, to_cardinality) != (DEFAULT_FROM_CARDINALITY, DEFAULT_TO_CARDINALITY):
            fail(errors, f"{name} must model {table} as many and source snapshot as one")
        if column_table(block, "fromColumn") != table:
            fail(errors, f"{name} must join from {table}.source_file_id")
        if column_table(block, "toColumn") != SNAPSHOT_TABLE:
            fail(errors, f"{name} must join to {SNAPSHOT_TABLE}.source_file_id")
    for table_name, content in tables.items():
        for relationship_name in re.findall(r"^\s*relationship: ([^\r\n]+)", content, flags=re.MULTILINE):
            if relationship_name not in relationship_names:
                fail(errors, f"{table_name}: variation refers to missing relationship {relationship_name}")
    model_evaluation = tables.get("bi repurchase_model_evaluation", "")
    for measure_name in SNAPSHOT_GUARDED_MODEL_MEASURES:
        match = re.search(
            rf"^\tmeasure '{re.escape(measure_name)}' =(?P<body>.*?)(?=^\tmeasure |^\tcolumn |^\tpartition |\Z)",
            model_evaluation,
            flags=re.MULTILINE | re.DOTALL,
        )
        if match is None or "HASONEVALUE ( 'bi repurchase_model_evaluation'[source_file_id] )" not in match.group("body"):
            fail(errors, f"bi repurchase_model_evaluation: {measure_name} must blank outside one selected snapshot")
    for measure_name in ROW_SCOPED_COMPARISON_MEASURES:
        match = re.search(
            rf"^\tmeasure '{re.escape(measure_name)}' =(?P<body>.*?)(?=^\tmeasure |^\tcolumn |^\tpartition |\Z)",
            model_evaluation,
            flags=re.MULTILINE | re.DOTALL,
        )
        if match is None or "ISINSCOPE ( 'bi repurchase_model_evaluation'[model_display_name] )" not in match.group("body"):
            fail(errors, f"bi repurchase_model_evaluation: {measure_name} must blank on the comparison total row")
    for measure_name in {
        "Logistic Regression ROC-AUC",
        "Logistic Regression PR-AUC",
        "Logistic Regression Lift at top 20%",
        "Logistic Regression Brier score",
    }:
        match = re.search(
            rf"^\tmeasure '{re.escape(measure_name)}' =(?P<body>.*?)(?=^\tmeasure |^\tcolumn |^\tpartition |\Z)",
            model_evaluation,
            flags=re.MULTILINE | re.DOTALL,
        )
        if match is None or 'model_name] = "logistic_regression_v1"' not in match.group("body"):
            fail(errors, f"bi repurchase_model_evaluation: {measure_name} must filter the persisted logistic_regression_v1 row")
    return errors


def has_persisted_filter(node: object) -> bool:
    """Detect a filter saved into a visual, which pins a slicer to one value."""

    if isinstance(node, dict):
        return "filter" in node or any(has_persisted_filter(value) for value in node.values())
    if isinstance(node, list):
        return any(has_persisted_filter(value) for value in node)
    return False


def validate_report(report_dir: Path) -> list[str]:
    errors: list[str] = []
    pages = json.loads((report_dir / "pages" / "pages.json").read_text(encoding="utf-8"))
    if pages["pageOrder"] != EXPECTED_PAGES:
        fail(errors, "dashboard page order does not match the governed report design")
    model_page_json = report_dir / "pages" / "retailpulse_model_evaluation" / "page.json"
    if not model_page_json.exists():
        fail(errors, "retailpulse_model_evaluation: missing page definition")
    elif json.loads(model_page_json.read_text(encoding="utf-8")).get("displayName") != "04 Repurchase model evaluation":
        fail(errors, "retailpulse_model_evaluation: page title must describe historical model evaluation")
    for page in EXPECTED_PAGES:
        slicer = report_dir / "pages" / page / "visuals" / "source_snapshot_slicer" / "visual.json"
        if not slicer.exists():
            fail(errors, f"{page}: missing visible source snapshot slicer")
            continue
        slicer_payload = json.loads(slicer.read_text(encoding="utf-8"))
        if (
            slicer_payload.get("visual", {}).get("visualType") != "slicer"
            or SNAPSHOT_TABLE not in json.dumps(slicer_payload)
            or "source_file_id" not in json.dumps(slicer_payload)
        ):
            fail(errors, f"{page}: source snapshot slicer has an invalid query")
        if has_persisted_filter(slicer_payload.get("visual", {}).get("objects", {})):
            fail(errors, f"{page}: source snapshot slicer must not pin a snapshot filter")
        slicers = []
        for visual_path in (report_dir / "pages" / page / "visuals").glob("*/visual.json"):
            visual = json.loads(visual_path.read_text(encoding="utf-8"))
            if visual.get("visual", {}).get("visualType") == "slicer":
                slicers.append(visual_path.parent.name)
        if slicers != ["source_snapshot_slicer"]:
            fail(errors, f"{page}: only the source snapshot slicer is allowed, found {slicers}")
    priority_table = (
        report_dir / "pages" / "retailpulse_customer" / "visuals" / "priority_table" / "visual.json"
    )
    if not priority_table.exists():
        fail(errors, "retailpulse_customer: missing priority decision table")
    else:
        payload = json.loads(priority_table.read_text(encoding="utf-8"))
        sort = (
            payload.get("visual", {})
            .get("query", {})
            .get("sortDefinition", {})
            .get("sort", [])
        )
        property_name = sort[0]["field"]["Column"]["Property"] if sort else None
        if property_name != "priority_rank":
            fail(errors, "retailpulse_customer: priority table must sort by priority_rank")

    for visual_name in EXPECTED_QUALITY_KPIS:
        visual_path = report_dir / "pages" / "retailpulse_quality" / "visuals" / visual_name / "visual.json"
        if not visual_path.exists():
            fail(errors, f"retailpulse_quality: missing {visual_name} KPI")
            continue
        visual_payload = json.loads(visual_path.read_text(encoding="utf-8"))
        if visual_payload.get("visual", {}).get("visualType") != "card":
            fail(errors, f"retailpulse_quality: {visual_name} must be a card")
        if "bi repurchase_baseline_evaluation" not in json.dumps(visual_payload):
            fail(errors, f"retailpulse_quality: {visual_name} does not use the baseline contract")
    quality_model_comparison = report_dir / "pages" / "retailpulse_quality" / "visuals" / "model_comparison"
    if quality_model_comparison.exists():
        fail(errors, "retailpulse_quality: model comparison must live on the model-evaluation page")

    model_page = report_dir / "pages" / "retailpulse_model_evaluation" / "visuals"
    for visual_name in {
        "evaluation_snapshot",
        "evaluation_holdout_size",
        "evaluation_date",
        "evaluation_method_coverage",
    }:
        provenance = model_page / visual_name / "visual.json"
        if not provenance.exists() or "bi repurchase_model_evaluation" not in provenance.read_text(encoding="utf-8"):
            fail(errors, f"retailpulse_model_evaluation: missing backtest provenance card {visual_name}")
    for visual_name in EXPECTED_MODEL_EVALUATION_CARDS:
        visual_path = model_page / visual_name / "visual.json"
        if not visual_path.exists():
            fail(errors, f"retailpulse_model_evaluation: missing {visual_name} card")
            continue
        visual_payload = json.loads(visual_path.read_text(encoding="utf-8"))
        if visual_payload.get("visual", {}).get("visualType") != "card":
            fail(errors, f"retailpulse_model_evaluation: {visual_name} must be a card")
        if "bi repurchase_model_evaluation" not in json.dumps(visual_payload):
            fail(errors, f"retailpulse_model_evaluation: {visual_name} does not use model evaluation data")
    model_comparison = model_page / "model_comparison" / "visual.json"
    if not model_comparison.exists() or "bi repurchase_model_evaluation" not in model_comparison.read_text(encoding="utf-8"):
        fail(errors, "retailpulse_model_evaluation: missing persisted model comparison")
    else:
        comparison_payload = json.loads(model_comparison.read_text(encoding="utf-8"))
        if "model_display_name" not in json.dumps(comparison_payload):
            fail(errors, "retailpulse_model_evaluation: model comparison must use business-friendly model names")
        total_show = (
            comparison_payload.get("visual", {})
            .get("objects", {})
            .get("total", [{}])[0]
            .get("properties", {})
            .get("show", {})
            .get("expr", {})
            .get("Literal", {})
            .get("Value")
        )
        if total_show != "false":
            fail(errors, "retailpulse_model_evaluation: model comparison must set totals visibility to false")
        for display_name in {
            "Comparison decision threshold",
            "Comparison holdout customers",
            "Comparison precision at threshold",
            "Comparison recall at threshold",
            "Comparison PR-AUC",
            "Comparison ROC-AUC",
            "Comparison Lift at top 20%",
            "Comparison Brier score",
        }:
            if display_name not in json.dumps(comparison_payload):
                fail(errors, f"retailpulse_model_evaluation: comparison must use total-safe measure {display_name}")
    tradeoff = model_page / "threshold_tradeoff" / "visual.json"
    if not tradeoff.exists():
        fail(errors, "retailpulse_model_evaluation: missing threshold precision/recall comparison")
    else:
        tradeoff_payload = json.loads(tradeoff.read_text(encoding="utf-8"))
        if tradeoff_payload.get("visual", {}).get("visualType") != "clusteredBarChart":
            fail(errors, "retailpulse_model_evaluation: threshold trade-off must be a clustered bar chart")
        if "model_display_name" not in json.dumps(tradeoff_payload) or "Evaluation Precision at threshold" not in json.dumps(tradeoff_payload) or "Evaluation Recall at threshold" not in json.dumps(tradeoff_payload):
            fail(errors, "retailpulse_model_evaluation: threshold chart must compare named methods on precision and recall")
    for path in report_dir.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
    return errors


def semantic_fields(model_dir: Path) -> dict[str, dict[str, set[str]]]:
    """Map each TMDL table to its declared column and measure names."""

    fields: dict[str, dict[str, set[str]]] = {}
    for path in (model_dir / "tables").glob("*.tmdl"):
        content = path.read_text(encoding="utf-8")
        match = re.search(r"^table (?:'([^']+)'|(\S+))", content, flags=re.MULTILINE)
        if not match:
            continue
        name_pattern = r"(?:'((?:[^']|'')+)'|([^\s=']+))"
        columns = {
            (quoted or bare).replace("''", "'")
            for quoted, bare in re.findall(rf"^\tcolumn {name_pattern}", content, flags=re.MULTILINE)
        }
        measures = {
            (quoted or bare).replace("''", "'")
            for quoted, bare in re.findall(rf"^\tmeasure {name_pattern}", content, flags=re.MULTILINE)
        }
        fields[match.group(1) or match.group(2)] = {"Column": columns, "Measure": measures}
    return fields


def visual_field_references(node: object):
    """Yield (kind, entity, property) for every Column/Measure reference in a visual."""

    if isinstance(node, dict):
        for kind in ("Column", "Measure"):
            reference = node.get(kind)
            if isinstance(reference, dict):
                entity = reference.get("Expression", {}).get("SourceRef", {}).get("Entity")
                property_name = reference.get("Property")
                if entity and property_name:
                    yield kind, entity, property_name
        for value in node.values():
            yield from visual_field_references(value)
    elif isinstance(node, list):
        for value in node:
            yield from visual_field_references(value)


def validate_field_references(model_dir: Path, report_dir: Path) -> list[str]:
    """Reject visuals that query a column or measure the semantic model does not define."""

    errors: list[str] = []
    fields = semantic_fields(model_dir)
    for path in sorted((report_dir / "pages").rglob("visual.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        label = path.relative_to(report_dir / "pages").parent.as_posix()
        for kind, entity, property_name in sorted(set(visual_field_references(payload))):
            table = fields.get(entity)
            if table is None:
                fail(errors, f"{label}: references missing table {entity!r}")
            elif property_name not in table[kind]:
                fail(errors, f"{label}: references missing {kind.lower()} '{entity}'[{property_name}]")
    return errors


def validate_project(root: Path = PROJECT_ROOT) -> list[str]:
    model_dir = root / "RetailPulse.SemanticModel" / "definition"
    report_dir = root / "RetailPulse.Report" / "definition"
    return (
        validate_model(model_dir)
        + validate_report(report_dir)
        + validate_field_references(model_dir, report_dir)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT,
        help="PBIP project directory (defaults to the repository's powerbi/ folder)",
    )
    args = parser.parse_args(argv)

    root: Path = args.root
    errors = validate_project(root)
    if errors:
        print("POWERBI_PROJECT=FAIL")
        print("\n".join(f"- {error}" for error in errors))
        return 1

    model_dir = root / "RetailPulse.SemanticModel" / "definition"
    pages = json.loads((root / "RetailPulse.Report" / "definition" / "pages" / "pages.json").read_text(encoding="utf-8"))
    bi_tables = sum(
        bool(re.search(r"^table 'bi ", path.read_text(encoding="utf-8"), flags=re.MULTILINE))
        for path in (model_dir / "tables").glob("*.tmdl")
    )
    print("POWERBI_PROJECT=PASS")
    print(f"BI_TABLES={bi_tables}")
    print(f"REPORT_PAGES={len(pages['pageOrder'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
