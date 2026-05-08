from __future__ import annotations

from app.rules.class_definitions import (
    BUILT_STRUCTURE,
    GREEN_LANDSCAPE,
    PAVED_OPEN_AREA,
    UNKNOWN_UNCLASSIFIED,
    WATER_POOL,
)
from app.schemas.area_schema import (
    AreaEstimateConfidence,
    AreaEstimateGuardrail,
    AreaEstimateResult,
    AreaRange,
    CompareModuleDisplay,
)
from app.schemas.image_schema import ImageMetadata
from app.schemas.project_schema import ParsedProjectMetadata
from app.schemas.segmentation_schema import SegmentationResult
from app.schemas.vision_schema import VisionAnalysisResult


QUALITATIVE_TO_RANGE_ANCHOR = {
    "Very Low": 8,
    "Low": 18,
    "Moderate": 32,
    "High": 48,
    "Very High": 62,
    "Unclear": 25,
}


def build_area_estimate(
    project: ParsedProjectMetadata,
    image_metadata: ImageMetadata,
    vision: VisionAnalysisResult,
    segmentation: SegmentationResult,
) -> AreaEstimateResult:
    class_percentages = {
        item.class_name: item.percentage for item in segmentation.classes
    }

    cv_green = class_percentages.get(GREEN_LANDSCAPE, 0.0)
    cv_water = class_percentages.get(WATER_POOL, 0.0)
    cv_built = class_percentages.get(BUILT_STRUCTURE, 0.0)
    cv_paved = class_percentages.get(PAVED_OPEN_AREA, 0.0)
    cv_unknown = class_percentages.get(UNKNOWN_UNCLASSIFIED, 0.0)

    vision_green_anchor = QUALITATIVE_TO_RANGE_ANCHOR.get(
        vision.green_area_visual_estimate.qualitative_estimate,
        25,
    )
    vision_open_anchor = QUALITATIVE_TO_RANGE_ANCHOR.get(
        vision.open_area_visual_estimate.qualitative_estimate,
        45,
    )
    vision_built_anchor = QUALITATIVE_TO_RANGE_ANCHOR.get(
        vision.building_footprint_visual_estimate.qualitative_estimate,
        30,
    )

    green_range = _build_green_range(
        cv_green=cv_green,
        cv_unknown=cv_unknown,
        vision_green_anchor=vision_green_anchor,
        project=project,
    )

    open_range = _build_open_range(
        cv_green=cv_green,
        cv_water=cv_water,
        cv_paved=cv_paved,
        cv_built=cv_built,
        cv_unknown=cv_unknown,
        vision_open_anchor=vision_open_anchor,
        vision_built_anchor=vision_built_anchor,
    )

    guardrail = _apply_guardrails(green_range=green_range, open_range=open_range)

    confidence = _build_confidence(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        segmentation=segmentation,
        cv_unknown=cv_unknown,
        guardrail=guardrail,
    )

    green_range.display = _format_range(green_range.min, green_range.max)
    open_range.display = _format_range(open_range.min, open_range.max)

    compare_display = CompareModuleDisplay(
        green_space_label="Estimated Green Space",
        green_space_value=green_range.display,
        open_area_label="Estimated Open Area",
        open_area_value=open_range.display,
        confidence_label=f"{confidence.label} Confidence",
        tooltip=(
            "Estimated using the project master plan, OpenAI Vision interpretation, "
            "OpenCV segmentation, and available Datacenter project signals. Actual values "
            "may vary from official layout or RERA disclosures."
        ),
    )

    warnings = []
    warnings.extend(segmentation.warnings)
    warnings.extend(vision.warnings)
    warnings.extend(guardrail.warnings)

    notes = [
        "Final values are range-based estimates, not official measurements.",
        "OpenCV segmentation is treated as visual evidence, not a standalone source of truth.",
        "OpenAI Vision qualitative output is used to adjust the range and confidence.",
        "Green Area is constrained to be less than or equal to Open Area.",
    ]

    return AreaEstimateResult(
        project_id=project.project_id,
        project_name=project.project_name,
        green_area_percentage=green_range,
        open_area_percentage=open_range,
        confidence=confidence,
        guardrails=guardrail,
        compare_module_display=compare_display,
        evidence_summary={
            "opencv_green_percentage": cv_green,
            "opencv_water_percentage": cv_water,
            "opencv_built_percentage": cv_built,
            "opencv_paved_percentage": cv_paved,
            "opencv_unknown_percentage": cv_unknown,
            "vision_green_estimate": vision.green_area_visual_estimate.qualitative_estimate,
            "vision_open_estimate": vision.open_area_visual_estimate.qualitative_estimate,
            "vision_built_estimate": vision.building_footprint_visual_estimate.qualitative_estimate,
            "image_quality_score": image_metadata.quality.score,
            "image_quality_label": image_metadata.quality.label,
            "project_area_acres": project.project_area_acres,
            "total_units": project.total_units,
            "green_signal_count": len(project.green_amenity_signals),
            "open_space_signal_count": len(project.open_space_signals),
        },
        warnings=warnings,
        notes=notes,
    )


def _build_green_range(
    cv_green: float,
    cv_unknown: float,
    vision_green_anchor: float,
    project: ParsedProjectMetadata,
) -> AreaRange:
    # OpenCV green is a lower-bound signal because stylized master plans
    # often under-detect green/tree areas. Vision and JSON signals help widen it.
    has_strong_green_json = len(project.green_amenity_signals) >= 5

    weighted_anchor = (cv_green * 0.35) + (vision_green_anchor * 0.65)

    if has_strong_green_json:
        weighted_anchor += 4

    if cv_unknown > 60:
        spread = 12
    elif cv_unknown > 35:
        spread = 9
    else:
        spread = 6

    min_value = max(cv_green, weighted_anchor - spread)
    max_value = min(100.0, weighted_anchor + spread)

    # Keep green range realistic for this evidence level.
    min_value = max(0.0, min_value)
    max_value = max(min_value + 1, max_value)

    return AreaRange(
        min=round(min_value, 1),
        max=round(max_value, 1),
        display="",
        basis="opencv_green_lower_bound_plus_vision_and_json_green_signals",
    )


def _build_open_range(
    cv_green: float,
    cv_water: float,
    cv_paved: float,
    cv_built: float,
    cv_unknown: float,
    vision_open_anchor: float,
    vision_built_anchor: float,
) -> AreaRange:
    cv_known_open = cv_green + cv_water + cv_paved

    # Two ways of estimating open area:
    # 1. known open pixels from OpenCV
    # 2. inverse of likely building footprint from Vision
    inverse_built_anchor = max(0.0, 100.0 - vision_built_anchor)

    weighted_anchor = (
        cv_known_open * 0.25
        + vision_open_anchor * 0.45
        + inverse_built_anchor * 0.30
    )

    if cv_unknown > 60:
        spread = 14
    elif cv_unknown > 35:
        spread = 10
    else:
        spread = 7

    min_value = max(cv_known_open, weighted_anchor - spread)
    max_value = min(100.0, weighted_anchor + spread)

    # Open area should generally remain above known open pixels.
    min_value = max(0.0, min_value)
    max_value = max(min_value + 1, max_value)

    return AreaRange(
        min=round(min_value, 1),
        max=round(max_value, 1),
        display="",
        basis="opencv_known_open_pixels_plus_vision_open_and_inverse_built_estimate",
    )


def _apply_guardrails(
    green_range: AreaRange,
    open_range: AreaRange,
) -> AreaEstimateGuardrail:
    warnings: list[str] = []
    adjustments: list[dict] = []

    if green_range.max > open_range.max:
        old_range = {
            "min": green_range.min,
            "max": green_range.max,
        }

        green_range.max = max(open_range.max - 1, 0)
        green_range.min = min(green_range.min, green_range.max)

        warnings.append("Green Area exceeded Open Area and was adjusted downward.")
        adjustments.append(
            {
                "field": "green_area_percentage",
                "old_range": old_range,
                "new_range": {
                    "min": green_range.min,
                    "max": green_range.max,
                },
                "reason": "Green Area cannot exceed Open Area.",
            }
        )

    if green_range.min > open_range.min:
        old_range = {
            "min": green_range.min,
            "max": green_range.max,
        }

        green_range.min = max(0, open_range.min - 1)
        green_range.max = max(green_range.min, green_range.max)

        warnings.append("Green Area minimum exceeded Open Area minimum and was adjusted.")
        adjustments.append(
            {
                "field": "green_area_percentage",
                "old_range": old_range,
                "new_range": {
                    "min": green_range.min,
                    "max": green_range.max,
                },
                "reason": "Green Area lower bound cannot exceed Open Area lower bound.",
            }
        )

    return AreaEstimateGuardrail(
        passed=len(warnings) == 0,
        warnings=warnings,
        adjustments=adjustments,
    )


def _build_confidence(
    project: ParsedProjectMetadata,
    image_metadata: ImageMetadata,
    vision: VisionAnalysisResult,
    segmentation: SegmentationResult,
    cv_unknown: float,
    guardrail: AreaEstimateGuardrail,
) -> AreaEstimateConfidence:
    score = 0.50
    reasons: list[str] = []

    if project.source_flags.get("has_project_json"):
        score += 0.08
        reasons.append("Project Datacenter JSON is available.")

    if project.project_area_acres is not None:
        score += 0.08
        reasons.append("Project area is available in Datacenter JSON.")

    if len(project.green_amenity_signals) > 0:
        score += 0.06
        reasons.append("Green amenity signals are available in project data.")

    if len(project.open_space_signals) > 0:
        score += 0.05
        reasons.append("Open-space signals are available in project data.")

    if image_metadata.quality.score >= 0.70:
        score += 0.08
        reasons.append("Master plan image quality is usable.")
    elif image_metadata.quality.score >= 0.55:
        score += 0.04
        reasons.append("Master plan image quality is acceptable.")
    else:
        score -= 0.08
        reasons.append("Master plan image quality is low.")

    if vision.boundary.boundary_visible:
        score += 0.08
        reasons.append("OpenAI Vision detected a visible project boundary.")

    if vision.boundary.boundary_confidence == "High":
        score += 0.07
        reasons.append("OpenAI Vision boundary confidence is high.")
    elif vision.boundary.boundary_confidence == "Medium":
        score += 0.03
        reasons.append("OpenAI Vision boundary confidence is medium.")
    else:
        score -= 0.08
        reasons.append("OpenAI Vision boundary confidence is weak.")

    if cv_unknown > 70:
        score -= 0.18
        reasons.append("OpenCV unknown/unclassified area is very high.")
    elif cv_unknown > 50:
        score -= 0.12
        reasons.append("OpenCV unknown/unclassified area is high.")
    elif cv_unknown > 30:
        score -= 0.06
        reasons.append("OpenCV unknown/unclassified area is moderate.")
    else:
        score += 0.05
        reasons.append("OpenCV classified most of the image into known classes.")

    if not guardrail.passed:
        score -= 0.07
        reasons.append("One or more guardrail adjustments were applied.")

    if segmentation.warnings:
        reasons.extend(segmentation.warnings)

    if vision.warnings:
        reasons.extend(vision.warnings)

    score = max(0.0, min(1.0, round(score, 2)))

    if score >= 0.80:
        label = "High"
    elif score >= 0.55:
        label = "Medium"
    elif score >= 0.30:
        label = "Low"
    else:
        label = "Insufficient"

    return AreaEstimateConfidence(
        score=score,
        label=label,
        reasons=reasons,
    )


def _format_range(min_value: float, max_value: float) -> str:
    rounded_min = int(round(min_value))
    rounded_max = int(round(max_value))

    if rounded_min == rounded_max:
        return f"~{rounded_min}%"

    return f"~{rounded_min}–{rounded_max}%"
