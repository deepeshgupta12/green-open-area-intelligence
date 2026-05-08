from pathlib import Path

from app.config import get_settings
from app.schemas.area_schema import AreaEstimateResult
from app.schemas.image_schema import ImageMetadata
from app.schemas.project_schema import ParsedProjectMetadata
from app.schemas.segmentation_schema import SegmentationResult
from app.schemas.vision_schema import VisionAnalysisResult
from app.utils.file_utils import write_json_file


def write_final_outputs(
    project: ParsedProjectMetadata,
    image_metadata: ImageMetadata,
    vision: VisionAnalysisResult,
    segmentation: SegmentationResult,
    area_estimate: AreaEstimateResult,
) -> dict[str, str]:
    settings = get_settings()

    report_path = (
        settings.data_output_reports_dir
        / f"{project.project_id}_area_estimate_report.md"
    )

    compare_contract_path = (
        settings.data_output_json_dir
        / f"{project.project_id}_compare_module_contract.json"
    )

    report_content = build_markdown_report(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        segmentation=segmentation,
        area_estimate=area_estimate,
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_content, encoding="utf-8")

    compare_contract = build_compare_module_contract(
        project=project,
        area_estimate=area_estimate,
    )

    write_json_file(compare_contract_path, compare_contract)

    return {
        "markdown_report_path": str(report_path),
        "compare_contract_path": str(compare_contract_path),
    }


def build_compare_module_contract(
    project: ParsedProjectMetadata,
    area_estimate: AreaEstimateResult,
) -> dict:
    return {
        "project_id": project.project_id,
        "project_name": project.project_name,
        "city": project.city,
        "locality": project.locality,
        "compare_module_display": area_estimate.compare_module_display.model_dump(mode="json"),
        "green_area_percentage": area_estimate.green_area_percentage.model_dump(mode="json"),
        "open_area_percentage": area_estimate.open_area_percentage.model_dump(mode="json"),
        "confidence": area_estimate.confidence.model_dump(mode="json"),
        "guardrails": area_estimate.guardrails.model_dump(mode="json"),
        "warnings": area_estimate.warnings,
        "evidence_summary": area_estimate.evidence_summary,
        "notes": area_estimate.notes,
        "is_official_measurement": False,
        "source_basis": "master_plan_image_plus_datacenter_json_plus_ai_vision_plus_opencv",
        "display_disclaimer": (
            "Estimated from the project master plan and available project data. "
            "Actual values may vary from official layout or RERA disclosures."
        ),
    }


def build_markdown_report(
    project: ParsedProjectMetadata,
    image_metadata: ImageMetadata,
    vision: VisionAnalysisResult,
    segmentation: SegmentationResult,
    area_estimate: AreaEstimateResult,
) -> str:
    confidence_reasons = "\n".join(
        f"- {reason}" for reason in area_estimate.confidence.reasons
    )

    warnings = "\n".join(
        f"- {warning}" for warning in area_estimate.warnings
    ) or "- None"

    segmentation_rows = "\n".join(
        f"| {item.class_name} | {item.pixel_count} | {item.percentage}% |"
        for item in segmentation.classes
    )

    evidence_rows = "\n".join(
        f"| {key} | {value} |"
        for key, value in area_estimate.evidence_summary.items()
    )

    guardrail_adjustments = (
        "\n".join(
            f"- {adjustment}"
            for adjustment in area_estimate.guardrails.adjustments
        )
        if area_estimate.guardrails.adjustments
        else "- None"
    )

    return f"""# Green/Open Area Estimate Report

## 1. Project Summary

| Field | Value |
|---|---|
| Project ID | {project.project_id} |
| Project Name | {project.project_name or "-"} |
| City | {project.city or "-"} |
| Locality | {project.locality or "-"} |
| Developer | {project.developer_name or "-"} |
| Project Area | {project.project_area_acres or "-"} acres |
| Total Units | {project.total_units or "-"} |
| Status | {project.status or "-"} |

## 2. Final Area Estimate

| Metric | Value |
|---|---|
| Estimated Green Area | {area_estimate.green_area_percentage.display} |
| Estimated Open Area | {area_estimate.open_area_percentage.display} |
| Confidence Score | {area_estimate.confidence.score} |
| Confidence Label | {area_estimate.confidence.label} |
| Guardrails Passed | {area_estimate.guardrails.passed} |

## 3. Compare Module Display

| Field | Value |
|---|---|
| Green Space Label | {area_estimate.compare_module_display.green_space_label} |
| Green Space Value | {area_estimate.compare_module_display.green_space_value} |
| Open Area Label | {area_estimate.compare_module_display.open_area_label} |
| Open Area Value | {area_estimate.compare_module_display.open_area_value} |
| Confidence Label | {area_estimate.compare_module_display.confidence_label} |
| Tooltip | {area_estimate.compare_module_display.tooltip} |

## 4. Image Metadata

| Field | Value |
|---|---|
| Source Image | {image_metadata.image_path} |
| Normalized Image | {image_metadata.normalized_image_path} |
| Width | {image_metadata.dimensions.width} |
| Height | {image_metadata.dimensions.height} |
| Quality Score | {image_metadata.quality.score} |
| Quality Label | {image_metadata.quality.label} |

## 5. OpenAI Vision Summary

| Field | Value |
|---|---|
| Boundary Visible | {vision.boundary.boundary_visible} |
| Boundary Confidence | {vision.boundary.boundary_confidence} |
| Manual Correction Recommended | {vision.boundary.manual_correction_recommended} |
| Green Area Visual Estimate | {vision.green_area_visual_estimate.qualitative_estimate} |
| Open Area Visual Estimate | {vision.open_area_visual_estimate.qualitative_estimate} |
| Building Footprint Visual Estimate | {vision.building_footprint_visual_estimate.qualitative_estimate} |

## 6. OpenCV Segmentation Summary

| Class | Pixels | Percentage |
|---|---:|---:|
{segmentation_rows}

## 7. Evidence Summary

| Evidence | Value |
|---|---|
{evidence_rows}

## 8. Confidence Reasons

{confidence_reasons}

## 9. Warnings

{warnings}

## 10. Guardrail Adjustments

{guardrail_adjustments}

## 11. Product Notes

- This is an estimated output, not an official RERA/developer measurement.
- Green Area is constrained to be less than or equal to Open Area.
- OpenCV segmentation is treated as visual evidence, not a standalone source of truth.
- OpenAI Vision qualitative output is used to adjust the range and confidence.
- The output is designed for internal review and compare-module consumption.
"""
