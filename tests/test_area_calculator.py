from pathlib import Path

from app.services.area_calculator import build_area_estimate
from app.services.image_preprocessor import preprocess_master_plan_image
from app.services.json_parser import parse_datacenter_json_file
from app.services.segmentation_engine import run_opencv_segmentation
from app.services.vision_analyzer import parse_vision_analysis_payload


def find_master_plan_image() -> Path:
    candidates = [
        Path("data/input/master_plan.jpg"),
        Path("data/input/master_plan.jpeg"),
        Path("data/input/master_plan.png"),
        Path("data/input/master_plan.webp"),
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise AssertionError(
        "Expected one master plan image to exist in data/input with extension "
        ".jpg, .jpeg, .png, or .webp."
    )


def test_area_calculator_builds_range_estimate():
    project = parse_datacenter_json_file("data/input/342956.json")
    image_metadata = preprocess_master_plan_image(str(find_master_plan_image()))

    segmentation = run_opencv_segmentation(
        image_metadata=image_metadata,
        project_id=project.project_id,
    )

    vision = parse_vision_analysis_payload(
        {
            "project_id": "342956",
            "project_name": "Birla Taranya",
            "boundary": {
                "boundary_visible": True,
                "boundary_confidence": "High",
                "boundary_reason": "The project boundary is visible.",
                "manual_correction_recommended": False,
            },
            "detected_components": [
                {
                    "component_type": "green_landscape",
                    "label": "Green landscape",
                    "visual_description": "Visible landscaped zones.",
                    "confidence": "High",
                    "likely_counts_toward_green_area": True,
                    "likely_counts_toward_open_area": True,
                    "likely_counts_as_building_footprint": False,
                }
            ],
            "green_area_visual_estimate": {
                "qualitative_estimate": "High",
                "reasoning": "Visible green zones are prominent.",
            },
            "open_area_visual_estimate": {
                "qualitative_estimate": "Very High",
                "reasoning": "Open areas are prominent.",
            },
            "building_footprint_visual_estimate": {
                "qualitative_estimate": "Moderate",
                "reasoning": "Building footprint is visible but not dominant.",
            },
            "visible_green_area_indicators": ["landscape"],
            "visible_open_area_indicators": ["roads", "paved zones"],
            "visible_built_area_indicators": ["tower footprint"],
            "warnings": ["Image may be stylized and not to scale."],
            "model_notes": ["Qualitative estimate only."],
        }
    )

    result = build_area_estimate(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        segmentation=segmentation,
    )

    assert result.project_id == "342956"

    assert result.green_area_percentage.min >= 0
    assert result.green_area_percentage.max <= 100
    assert result.open_area_percentage.min >= 0
    assert result.open_area_percentage.max <= 100

    assert result.green_area_percentage.min <= result.green_area_percentage.max
    assert result.open_area_percentage.min <= result.open_area_percentage.max

    assert result.green_area_percentage.max <= result.open_area_percentage.max
    assert result.green_area_percentage.min <= result.open_area_percentage.min

    assert result.green_area_percentage.display.startswith("~")
    assert result.open_area_percentage.display.startswith("~")

    assert 0 <= result.confidence.score <= 1
    assert result.confidence.label in {"High", "Medium", "Low", "Insufficient"}
    assert len(result.confidence.reasons) > 0

    if result.evidence_summary["opencv_unknown_percentage"] > 70:
        assert result.confidence.score <= 0.74
        assert result.confidence.label != "High"

    assert result.compare_module_display.green_space_value
    assert result.compare_module_display.open_area_value
    assert result.compare_module_display.tooltip

    assert "opencv_unknown_percentage" in result.evidence_summary
