from pathlib import Path

from app.services.area_calculator import build_area_estimate
from app.services.category_insight_engine import build_category_comparison
from app.services.image_preprocessor import preprocess_master_plan_image
from app.services.json_parser import parse_datacenter_json_file
from app.services.master_plan_compare_engine import build_master_plan_comparison
from app.services.segmentation_engine import run_opencv_segmentation
from app.services.vision_analyzer import parse_vision_analysis_payload


def find_master_plan_image() -> Path:
    for candidate in [
        Path("data/input/master_plan.jpg"),
        Path("data/input/master_plan.jpeg"),
        Path("data/input/master_plan.png"),
        Path("data/input/master_plan.webp"),
    ]:
        if candidate.exists():
            return candidate

    raise AssertionError("Expected one master plan image in data/input.")


def build_mock_vision(project_id="342956", project_name="Birla Taranya"):
    return parse_vision_analysis_payload(
        {
            "project_id": project_id,
            "project_name": project_name,
            "boundary": {
                "boundary_visible": True,
                "boundary_confidence": "High",
                "boundary_reason": "The project boundary is visible.",
                "manual_correction_recommended": False,
            },
            "detected_components": [
                {
                    "component_type": "green_landscape",
                    "label": "Central landscaped garden",
                    "visual_description": "Visible landscaped zones.",
                    "confidence": "High",
                    "likely_counts_toward_green_area": True,
                    "likely_counts_toward_open_area": True,
                    "likely_counts_as_building_footprint": False,
                },
                {
                    "component_type": "sports_court_play_area",
                    "label": "Sports courts",
                    "visual_description": "Multiple sports courts.",
                    "confidence": "High",
                    "likely_counts_toward_green_area": False,
                    "likely_counts_toward_open_area": True,
                    "likely_counts_as_building_footprint": False,
                },
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


def build_single_project_bundle():
    project = parse_datacenter_json_file("data/input/342956.json")
    image_metadata = preprocess_master_plan_image(str(find_master_plan_image()))
    vision = build_mock_vision(project.project_id, project.project_name)
    segmentation = run_opencv_segmentation(image_metadata=image_metadata, project_id=project.project_id)
    area = build_area_estimate(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        segmentation=segmentation,
    )
    category = build_category_comparison(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        segmentation=segmentation,
        area_estimate=area,
    )
    return project, area, category


def test_master_plan_compare_engine_builds_three_project_comparison():
    project, area, category = build_single_project_bundle()

    result = build_master_plan_comparison(
        project_a=project,
        area_a=area,
        category_a=category,
        project_b=project,
        area_b=area,
        category_b=category,
        project_c=project,
        area_c=area,
        category_c=category,
        comparison_run_id="test-run",
    )

    assert result.comparison_run_id == "test-run"
    assert len(result.projects) == 3
    assert len(result.category_comparison_matrix) == 10
    assert len(result.category_winners) == 10
    assert result.overall_recommendation.winner_project_slot in {"A", "B", "C"}
    assert result.overall_recommendation.one_liner
    assert result.user_friendly_summary.headline
    assert result.user_friendly_summary.caution_note

    for row in result.category_comparison_matrix:
        assert len(row.project_scores) == 3
        assert row.winner_project_slot in {"A", "B", "C"}
        assert row.winner_reason
        assert row.tradeoff
