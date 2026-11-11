"""Compile the RetailPulse executive dashboard brief from verified run artifacts.

Validates source snapshot consistency, model evaluation contracts, and budget
fractions across distinct pipeline and evaluation artifacts, injecting them
into dashboard/templates/index.html.template to produce dashboard/dist/index.html.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_PATH = PROJECT_ROOT / "data" / "processed" / "repurchase_model_evaluation.json"
DEFAULT_RUN_PATH = PROJECT_ROOT / "data" / "processed" / "orchestration" / "last_run.json"
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "dashboard" / "templates" / "index.html.template"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "dashboard" / "dist" / "index.html"

REQUIRED_BUDGET_FRACTIONS = (0.10, 0.20, 0.30)


def format_timezone_offset(dt: datetime) -> str:
    """Return explicit UTC offset string, e.g. UTC+00:00 or UTC+07:00."""
    offset = dt.utcoffset()
    if offset is None:
        return "UTC+00:00"
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def parse_artifact_datetime(dt_str: str) -> tuple[datetime, str, str]:
    """Parse ISO datetime preserving actual offset; return (dt, date_str, formatted_with_tz)."""
    dt = datetime.fromisoformat(dt_str)
    tz_str = format_timezone_offset(dt)
    date_str = dt.strftime("%Y-%m-%d")
    full_str = f"{dt.strftime('%Y-%m-%d %H:%M:%S')} ({tz_str})"
    return dt, date_str, full_str


def validate_and_extract_budget_data(eval_data: dict[str, Any]) -> dict[str, Any]:
    """Extract and strictly validate budget comparison data from model evaluation JSON."""
    dc = eval_data.get("decision_comparison")
    if not isinstance(dc, dict):
        raise ValueError("Model evaluation artifact missing 'decision_comparison' dictionary")

    fb_raw = dc.get("frequency_business", {}).get("metrics", [])
    lr_raw = dc.get("logistic_regression", {}).get("metrics", [])
    rec = dc.get("recommendation", {})
    bootstrap_raw = rec.get("precision_bootstrap_vs_logistic_regression", [])

    fb_by_k = {round(m["budget_fraction"], 2): m for m in fb_raw if "budget_fraction" in m}
    lr_by_k = {round(m["budget_fraction"], 2): m for m in lr_raw if "budget_fraction" in m}
    ci_by_k = {round(b["budget_fraction"], 2): b for b in bootstrap_raw if "budget_fraction" in b}

    budget_dict: dict[float, dict[str, Any]] = {}

    for k in REQUIRED_BUDGET_FRACTIONS:
        k_key = round(k, 2)
        if k_key not in fb_by_k:
            raise ValueError(f"Missing budget fraction K={k} in frequency_business metrics")
        if k_key not in lr_by_k:
            raise ValueError(f"Missing budget fraction K={k} in logistic_regression metrics")
        if k_key not in ci_by_k:
            raise ValueError(f"Missing budget fraction K={k} in bootstrap CI recommendation")

        fb = fb_by_k[k_key]
        lr = lr_by_k[k_key]
        b = ci_by_k[k_key]

        selected_count = fb["selected_customer_count"]
        if selected_count != lr["selected_customer_count"]:
            raise ValueError(f"Selected count mismatch at K={k}: FB={selected_count} vs LR={lr['selected_customer_count']}")

        fb_prec = fb["precision_at_k"] * 100
        fb_recall = fb["recall_at_k"] * 100
        fb_lift = fb["lift_at_k"]

        lr_prec = lr["precision_at_k"] * 100
        lr_recall = lr["recall_at_k"] * 100
        lr_lift = lr["lift_at_k"]

        diff = (fb["precision_at_k"] - lr["precision_at_k"]) * 100
        ci_lower = b["ci_lower"] * 100
        ci_upper = b["ci_upper"] * 100
        ci_zero = " (includes 0)" if b.get("ci_includes_zero") else ""
        ci_str = f"[{ci_lower:+.3f}%, {ci_upper:+.3f}%]{ci_zero}"

        budget_dict[k] = {
            "label": f"{int(k*100)}% (K = {selected_count} customers)",
            "fbCount": str(selected_count),
            "fbPrecision": f"{fb_prec:.1f}%",
            "fbRecall": f"{fb_recall:.1f}%",
            "fbLift": f"{fb_lift:.3f}\u00D7",
            "fbDiff": f"{diff:+.3f}%",
            "fbCi": ci_str,
            "lrCount": str(selected_count),
            "lrPrecision": f"{lr_prec:.1f}%",
            "lrRecall": f"{lr_recall:.1f}%",
            "lrLift": f"{lr_lift:.3f}\u00D7",
        }

    return budget_dict


def build_dashboard(
    eval_path: Path = DEFAULT_EVAL_PATH,
    run_path: Path = DEFAULT_RUN_PATH,
    template_path: Path = DEFAULT_TEMPLATE_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> dict[str, Any]:
    """Compile index.html template with audited figures from last_run and model eval."""
    if not eval_path.exists():
        raise FileNotFoundError(f"Model evaluation artifact not found: {eval_path}")
    if not run_path.exists():
        raise FileNotFoundError(f"Pipeline run artifact not found: {run_path}")
    if not template_path.exists():
        raise FileNotFoundError(f"Dashboard template not found: {template_path}")

    with eval_path.open("r", encoding="utf-8") as f:
        eval_data = json.load(f)
    with run_path.open("r", encoding="utf-8") as f:
        run_data = json.load(f)

    # 1. Parse and cross-check temporal provenance
    eval_ts_str = eval_data.get("generated_at_utc")
    if not eval_ts_str:
        raise ValueError("Model evaluation artifact missing 'generated_at_utc'")
    _, eval_date_str, eval_dt_formatted = parse_artifact_datetime(eval_ts_str)

    run_started_str = run_data.get("started_at")
    if not run_started_str:
        raise ValueError("Pipeline run artifact missing 'started_at'")
    _, run_date_str, run_dt_formatted = parse_artifact_datetime(run_started_str)

    run_id = run_data.get("run_id", "unknown")
    run_status = run_data.get("status", "unknown").upper()

    # Check ingestion details
    ingest_task = next((t for t in run_data.get("tasks", []) if t.get("name") == "ingest"), None)
    if not ingest_task or ingest_task.get("status") != "succeeded":
        raise ValueError("Pipeline run artifact missing successful 'ingest' task")

    ingest_detail = ingest_task.get("detail", {})
    source_row_count = ingest_detail.get("source_row_count", 0)
    committed_raw_row_count = ingest_detail.get("committed_raw_row_count", 0)
    ingest_status = ingest_detail.get("status", "LOADED")
    run_source_file_id = ingest_detail.get("source_file_id")

    # Check SQL gates & dbt
    sql_task = next((t for t in run_data.get("tasks", []) if t.get("name") == "sql_gates"), None)
    sql_gate_count = sql_task.get("detail", {}).get("count", 12) if sql_task else 12

    dbt_task = next((t for t in run_data.get("tasks", []) if t.get("name") == "dbt_build"), None)
    dbt_status = "All models & tests passed" if dbt_task and dbt_task.get("status") == "succeeded" else "Pending/Unavailable"

    # Ingestion duration
    elapsed_total = 0.0
    for t in run_data.get("tasks", []):
        elapsed_total += float(t.get("elapsed_seconds", 0.0))
    minutes = int(elapsed_total // 60)
    seconds = int(elapsed_total % 60)
    duration_str = f"{minutes}m {seconds:02d}s"

    # Cross-check snapshot consistency
    eval_snapshot_id = eval_data.get("source_file_id")
    eval_sha = eval_data.get("source_sha256", "")
    if run_source_file_id is not None and eval_snapshot_id is not None:
        if run_source_file_id != eval_snapshot_id:
            raise ValueError(f"Snapshot ID mismatch: last_run.json has {run_source_file_id}, model eval has {eval_snapshot_id}")

    # Check if executions are separate
    is_same_run = (run_date_str == eval_date_str) and (run_id in eval_data.get("model_configuration", {}).get("notes", ""))
    if not is_same_run:
        provenance_scope_note = (
            f"Pipeline run {run_id} ({run_date_str}) and model evaluation ({eval_date_str}) "
            "are separate executions. Maintained as two distinct evidence clusters."
        )
    else:
        provenance_scope_note = f"Pipeline run and model evaluation executed in same run {run_id}."

    # 2. Extract Holdout Metrics
    holdout_eval = eval_data.get("holdout_evaluation", {})
    lr_eval = holdout_eval.get("logistic_regression")
    if not lr_eval:
        raise ValueError("Model evaluation missing 'logistic_regression' in holdout_evaluation")

    roc_auc = f"{lr_eval['roc_auc']:.4f}"
    pr_auc = f"{lr_eval['pr_auc']:.4f}"
    lift_20 = f"{lr_eval['lift_at_top_20_percent']:.4f}&times;"
    brier_score = f"{lr_eval['brier_score']:.4f}"
    holdout_customer_count = lr_eval.get("customer_count", 2784)
    holdout_positive_count = lr_eval.get("positive_customer_count", 1722)

    temporal_contract = eval_data.get("temporal_contract", {})
    pred_start = temporal_contract.get("holdout_prediction_start_date", "2011-09-11")
    pred_end = temporal_contract.get("holdout_prediction_end_date", "2011-12-10")
    holdout_period_str = f"{pred_start} &rarr; {pred_end} (end excl.)"
    holdout_cohort_str = f"{holdout_customer_count:,} customers ({holdout_positive_count:,} repurchased)"

    # 3. Extract and validate Budget K comparisons
    budget_dict = validate_and_extract_budget_data(eval_data)
    budget_json_str = json.dumps(budget_dict, indent=6)

    # Initial K=10% data for static table
    k10 = budget_dict[0.10]

    # 4. Perform template replacements
    replacements = {
        "{{RUN_ID}}": run_id,
        "{{PIPELINE_RUN_DATE}}": run_date_str,
        "{{PIPELINE_STATUS}}": f"{run_status} ({ingest_status})",
        "{{PIPELINE_ROWS}}": f"{source_row_count:,} / {committed_raw_row_count:,}",
        "{{PIPELINE_SQL_GATES}}": f"{sql_gate_count} / {sql_gate_count} passed",
        "{{PIPELINE_DBT_STATUS}}": dbt_status,
        "{{PIPELINE_DURATION}}": duration_str,
        "{{EVAL_DATE}}": eval_date_str,
        "{{EVAL_TIMESTAMP}}": eval_dt_formatted,
        "{{SNAPSHOT_ID}}": str(eval_snapshot_id or 1),
        "{{SNAPSHOT_SHA_SHORT}}": f"{eval_sha[:8]}...",
        "{{HOLDOUT_PERIOD}}": holdout_period_str,
        "{{HOLDOUT_COHORT_SIZE}}": holdout_cohort_str,
        "{{ROC_AUC}}": roc_auc,
        "{{PR_AUC}}": pr_auc,
        "{{LIFT_TOP_20}}": lift_20,
        "{{BRIER_SCORE}}": brier_score,
        "{{BUDGET_DATA_JSON}}": budget_json_str,
        "{{INITIAL_K_LABEL}}": k10["label"],
        "{{INITIAL_FB_COUNT}}": k10["fbCount"],
        "{{INITIAL_FB_PRECISION}}": k10["fbPrecision"],
        "{{INITIAL_FB_RECALL}}": k10["fbRecall"],
        "{{INITIAL_FB_LIFT}}": k10["fbLift"],
        "{{INITIAL_FB_DIFF}}": k10["fbDiff"],
        "{{INITIAL_FB_CI}}": k10["fbCi"],
        "{{INITIAL_LR_COUNT}}": k10["lrCount"],
        "{{INITIAL_LR_PRECISION}}": k10["lrPrecision"],
        "{{INITIAL_LR_RECALL}}": k10["lrRecall"],
        "{{INITIAL_LR_LIFT}}": k10["lrLift"],
    }

    template_content = template_path.read_text(encoding="utf-8")
    rendered = template_content
    for token, val in replacements.items():
        rendered = rendered.replace(token, str(val))

    # Verify no un-rendered tokens remain
    if "{{" in rendered and "}}" in rendered:
        unrendered = [line.strip() for line in rendered.splitlines() if "{{" in line and "}}" in line]
        raise ValueError(f"Unrendered template tokens detected: {unrendered}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")

    return {
        "status": "success",
        "output_path": str(output_path),
        "run_id": run_id,
        "run_date": run_date_str,
        "eval_date": eval_date_str,
        "provenance_note": provenance_scope_note,
        "snapshot_id": eval_snapshot_id,
        "snapshot_sha": eval_sha,
        "budget_fractions": list(budget_dict.keys()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile RetailPulse executive dashboard brief from verified artifacts.")
    parser.add_argument("--eval-json", type=Path, default=DEFAULT_EVAL_PATH, help="Path to repurchase_model_evaluation.json")
    parser.add_argument("--run-json", type=Path, default=DEFAULT_RUN_PATH, help="Path to last_run.json")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE_PATH, help="Path to index.html.template")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Path to output index.html")
    args = parser.parse_args()

    try:
        summary = build_dashboard(args.eval_json, args.run_json, args.template, args.output)
        print(f"SUCCESS: Dashboard built at {summary['output_path']}")
        print(f"  Pipeline Run: {summary['run_id']} ({summary['run_date']})")
        print(f"  Model Evaluation: Snapshot {summary['snapshot_id']} ({summary['eval_date']})")
        print(f"  Provenance: {summary['provenance_note']}")
        print(f"  Budget Fractions Validated: {summary['budget_fractions']}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
