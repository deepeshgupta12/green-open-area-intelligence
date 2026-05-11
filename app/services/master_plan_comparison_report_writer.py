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
        f"| {item.project_slot} | {item.project_name or '-'} | {item.green_area_display or '-'} | {item.open_area_display or '-'} | {item.overall_category_score or '-'} | {item.overall_category_rating or '-'} |"
        for item in comparison.projects
    )

    matrix_rows = "\n".join(
        f"| {row.category_label} | {row.winner_project_name or '-'} | {row.winner_reason} | {row.tradeoff} |"
        for row in comparison.category_comparison_matrix
    )

    winner_rows = "\n".join(
        f"| {item.category_label} | {item.winner_project_name or '-'} | {item.winner_score} | {item.winner_reason} |"
        for item in comparison.category_winners
    )

    return f"""# Master Plan Comparison Report

## Overall Recommendation

| Field | Value |
|---|---|
| Winner | {comparison.overall_recommendation.winner_project_name or '-'} |
| Score | {comparison.overall_recommendation.score} |
| Rating | {comparison.overall_recommendation.rating} |
| One-Liner | {comparison.overall_recommendation.one_liner} |
| Detailed Reason | {comparison.overall_recommendation.detailed_reason} |

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

| Slot | Project | Green Area | Open Area | Overall Score | Rating |
|---|---|---|---|---:|---|
{project_rows}

## Category Winners

| Category | Winner | Winner Score | Reason |
|---|---|---:|---|
{winner_rows}

## Category Comparison Matrix

| Category | Winner | Winner Reason | Tradeoff |
|---|---|---|---|
{matrix_rows}

## Notes

{chr(10).join(f"- {note}" for note in comparison.notes)}
"""
