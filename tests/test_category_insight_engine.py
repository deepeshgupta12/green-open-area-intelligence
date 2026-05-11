from pathlib import Path

from app.services.area_calculator import build_area_estimate
from app.services.category_insight_engine import build_category_comparison
from app.services.image_preprocessor import preprocess_master_plan_image
from app.services.json_parser import parse_datacenter_json_file
from app.services.segmentation_engine import run_opencv_segmentation
from app.services.vision_analyzer import parse_vision_analysis_payload


EXPECTED_CATEGORIES = {
    "green_landscape",
    "open_space",
    "built_density",
    "amenity_richness",
    "sports_active_lifestyle",
    "family_community",
    "water_leisure",
    "access_circulation",
    "environment_sustainability",
    "evidence_reliability",
}


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
                {
                    "component_type": "water_pool",
                    "label": "Swimming pool",
                    "visual_description": "Large pool area.",
                    "confidence": "High",
                    "likely_counts_toward_green_area": False,
                    "likely_counts_toward_open_area": True,
                    "likely_counts_as_building_footprint": False,
                },
                {
                    "component_type": "road_driveway",
                    "label": "Main driveway",
                    "visual_description": "Internal driveway.",
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


def test_category_insight_engine_builds_all_categories():
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

    result = build_category_comparison(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        segmentation=segmentation,
        area_estimate=area_estimate,
    )

    assert result.project_id == "342956"
    assert result.project_name == "Birla Taranya"

    category_keys = {item.category_key for item in result.category_scores}
    assert category_keys == EXPECTED_CATEGORIES

    for category in result.category_scores:
        assert 0 <= category.score <= 100
        assert category.rating in {"Excellent", "Strong", "Moderate", "Limited", "Weak"}
        assert category.confidence_label in {"High", "Medium", "Low", "Insufficient"}
        assert category.one_liner
        assert category.detailed_insight
        assert category.evidence_sources
        assert category.compare_module_copy.short_label
        assert category.compare_module_copy.tooltip
        assert isinstance(category.positive_signals, list)
        assert isinstance(category.risk_signals, list)
        assert isinstance(category.extracted_master_plan_details, list)

    assert 0 <= result.overall_master_plan_summary.score <= 100
    assert result.overall_master_plan_summary.rating in {
        "Excellent",
        "Strong",
        "Moderate",
        "Limited",
        "Weak",
    }
    assert result.overall_master_plan_summary.one_liner
    assert result.overall_master_plan_summary.detailed_summary
    assert result.overall_master_plan_summary.strongest_categories
