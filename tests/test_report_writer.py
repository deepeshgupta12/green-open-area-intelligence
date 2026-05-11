from pathlib import Path

from app.services.area_calculator import build_area_estimate
from app.services.category_insight_engine import build_category_comparison
from app.services.image_preprocessor import preprocess_master_plan_image
from app.services.json_parser import parse_datacenter_json_file
from app.services.report_writer import write_final_outputs
from app.services.segmentation_engine import run_opencv_segmentation
from app.services.vision_analyzer import parse_vision_analysis_payload
from app.utils.file_utils import read_json_file


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

    raise AssertionError("Expected one master plan image in data/input.")


def build_mock_vision():
    return parse_vision_analysis_payload(
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


def test_report_writer_creates_markdown_and_compare_contract():
    project = parse_datacenter_json_file("data/input/342956.json")
    image_metadata = preprocess_master_plan_image(str(find_master_plan_image()))
    vision = build_mock_vision()

    segmentation = run_opencv_segmentation(
        image_metadata=image_metadata,
        project_id=project.project_id,
    )

    area_estimate = build_area_estimate(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        segmentation=segmentation,
    )

    category_comparison = build_category_comparison(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        segmentation=segmentation,
        area_estimate=area_estimate,
    )

    output_paths = write_final_outputs(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        segmentation=segmentation,
        area_estimate=area_estimate,
        category_comparison=category_comparison,
    )

    report_path = Path(output_paths["markdown_report_path"])
    contract_path = Path(output_paths["compare_contract_path"])

    assert report_path.exists()
    assert contract_path.exists()

    report_text = report_path.read_text(encoding="utf-8")

    assert "Green/Open Area Estimate Report" in report_text
    assert "Birla Taranya" in report_text
    assert "Estimated Green Area" in report_text
    assert "Estimated Open Area" in report_text
    assert "Master Plan Category Insights" in report_text
    assert "Green Landscape Planning" in report_text

    contract = read_json_file(contract_path)

    assert contract["project_id"] == "342956"
    assert contract["project_name"] == "Birla Taranya"
    assert contract["is_official_measurement"] is False
    assert contract["compare_module_display"]["green_space_value"]
    assert contract["compare_module_display"]["open_area_value"]
    assert contract["category_comparison"] is not None
    assert contract["category_comparison"]["category_scores"]
    assert contract["display_disclaimer"]
