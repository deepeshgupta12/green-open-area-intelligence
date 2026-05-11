from pathlib import Path

from app.schemas.master_plan_compare_schema import MasterPlanComparisonResult
from app.utils.file_utils import write_json_file


def write_master_plan_comparison_outputs(
    comparison: MasterPlanComparisonResult,
    output_dir: Path,
) -> dict[str, str]:
    json_dir = output_dir / "json"
    reports_dir = output_dir / "reports"

    json_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    comparison_json_path = json_dir / "master_plan_comparison.json"
    report_path = reports_dir / "master_plan_comparison_report.md"

    write_json_file(comparison_json_path, comparison.model_dump(mode="json"))
    report_path.write_text(build_master_plan_comparison_report(comparison), encoding="utf-8")

    return {
        "comparison_json_path": str(comparison_json_path),
        "comparison_report_path": str(report_path),
    }


def build_master_plan_comparison_report(
    comparison: MasterPlanComparisonResult,
) -> str:
    project_rows = "\n".join(
        f"| {item.project_slot} | {item.project_name or '-'} | {item.green_area_display or '-'} | {item.open_area_display or '-'} | {item.frontend_score_label or item.overall_category_rating or '-'} |"
        for item in comparison.projects
    )

    matrix_rows = "\n".join(
        f"| {row.category_label} | {row.category_status} | {row.evidence_strength} | {row.winner_project_name or '-'} | {row.frontend_winner_reason} | {row.frontend_tradeoff} | {row.frontend_category_summary} |"
        for row in comparison.category_comparison_matrix
    )

    winner_rows = "\n".join(
        f"| {item.category_label} | {item.category_status} | {item.winner_project_name if item.show_winner_badge else 'No Clear Winner'} | {item.winner_reason} |"
        for item in comparison.category_winners
    )

    evidence_rows = "\n".join(
        f"| {item.project_slot} | {item.project_name or '-'} | {item.confidence_label or '-'} | {'; '.join(item.technical_warnings[:3]) or '-'} |"
        for item in comparison.internal_evidence_quality.project_evidence
    )

    return f"""# Master Plan Comparison Report

## Frontend Overall Recommendation

| Field | Value |
|---|---|
| Winner | {comparison.overall_recommendation.winner_project_name or '-'} |
| Frontend Score Label | {comparison.overall_recommendation.frontend_score_label or comparison.overall_recommendation.rating} |
| Rating | {comparison.overall_recommendation.rating} |
| Headline | {comparison.overall_recommendation.frontend_headline} |
| Summary | {comparison.overall_recommendation.frontend_summary} |

## User-Friendly Summary

| Field | Value |
|---|---|
| Headline | {comparison.user_friendly_summary.headline} |
| Summary | {comparison.user_friendly_summary.short_summary} |
| Best for Green Living | {comparison.user_friendly_summary.best_for_green_living or '-'} |
| Best for Amenities | {comparison.user_friendly_summary.best_for_amenities or '-'} |
| Best for Family Living | {comparison.user_friendly_summary.best_for_family_living or '-'} |
| Best for Access | {comparison.user_friendly_summary.best_for_access or '-'} |
| Caution | {comparison.user_friendly_summary.caution_note or '-'} |

## Compared Projects

| Slot | Project | Green Area | Open Area | Overall Rating/Band |
|---|---|---|---|---|
{project_rows}

## Frontend Category Winners

| Category | Status | Winner Display | Frontend Reason |
|---|---|---|---|
{winner_rows}

## Frontend Category Comparison Matrix

| Category | Status | Evidence Strength | Winner | Frontend Winner Reason | Frontend Tradeoff | Frontend Category Summary |
|---|---|---|---|---|---|---|
{matrix_rows}

## Internal Evidence Quality

OpenCV used for frontend copy: {comparison.internal_evidence_quality.opencv_used_for_frontend_copy}

| Slot | Project | Confidence | Internal Technical Warnings |
|---|---|---|---|
{evidence_rows}

## Notes

{chr(10).join(f"- {note}" for note in comparison.notes)}
"""
