from pathlib import Path

from app.services.area_calculator import build_area_estimate
from app.services.category_insight_engine import build_category_comparison
from app.services.image_preprocessor import preprocess_master_plan_image
from app.services.json_parser import parse_datacenter_json_file
from app.services.master_plan_compare_engine import build_master_plan_comparison
from app.services.segmentation_engine import run_opencv_segmentation
from app.services.vision_analyzer import parse_vision_analysis_payload


BANNED_FRONTEND_TERMS = [
    "OpenCV",
    "unknown area",
    "unknown/unclassified",
    "segmentation",
    "pixel",
    "image quality",
    "area estimate confidence",
]


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
                {
                    "component_type": "road_driveway",
                    "label": "Main driveway",
                    "visual_description": "Internal driveway and access movement.",
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
            "visible_open_area_indicators": ["roads", "paved zones", "main driveway"],
            "visible_built_area_indicators": ["tower footprint"],
            "warnings": ["Image may be stylized and not to scale."],
            "model_notes": ["Qualitative estimate only."],
        }
    )


def build_single_project_bundle():
    project = parse_datacenter_json_file("data/input/342956.json")
    image_metadata = preprocess_master_plan_image(str(find_master_plan_image()))
    vision = build_mock_vision(project.project_id, project.project_name)

    segmentation = run_opencv_segmentation(
        image_metadata=image_metadata,
        project_id=project.project_id,
    )

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


def assert_frontend_clean(value: str):
    lowered = value.lower()
    for term in BANNED_FRONTEND_TERMS:
        assert term.lower() not in lowered


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
    assert len(result.category_comparison_matrix) == 9
    assert len(result.category_winners) == 9
    assert result.overall_recommendation.winner_project_slot in {"A", "B", "C"}
    assert result.overall_recommendation.one_liner
    assert result.user_friendly_summary.headline
    assert result.user_friendly_summary.caution_note
    assert result.internal_evidence_quality.opencv_used_for_frontend_copy is False
    assert result.internal_evidence_quality.project_evidence

    category_keys = {row.category_key for row in result.category_comparison_matrix}
    assert "evidence_reliability" not in category_keys

    for row in result.category_comparison_matrix:
        assert len(row.project_scores) == 3
        assert row.winner_project_slot in {"A", "B", "C"}
        assert row.winner_reason
        assert row.tradeoff
        assert row.frontend_winner_reason
        assert row.frontend_tradeoff
        assert row.frontend_category_summary
        assert row.internal_scoring

        assert row.category_status in {
            "Clear Winner",
            "Close Call",
            "Weak Differentiator",
            "Insufficient Evidence",
        }
        assert row.evidence_strength in {
            "Strong",
            "Moderate",
            "Weak",
            "Insufficient",
        }
        assert isinstance(row.show_as_decisive, bool)
        assert isinstance(row.show_as_close_call, bool)
        assert isinstance(row.show_as_insufficient, bool)

        assert_frontend_clean(row.winner_reason)
        assert_frontend_clean(row.tradeoff)
        assert_frontend_clean(row.frontend_winner_reason)
        assert_frontend_clean(row.frontend_tradeoff)
        assert_frontend_clean(row.frontend_category_summary)

        forbidden_chips = {
            "green",
            "open",
            "landscape",
            "road",
            "pathway",
            "tree",
            "pool",
            "leisure",
        }

        all_frontend_chips = row.visible_evidence + row.declared_evidence

        for chip in all_frontend_chips:
            assert chip.strip().lower() not in forbidden_chips

            if row.category_key == "green_landscape":
                assert "sewage" not in chip.lower()
                assert "treated water" not in chip.lower()
                assert "rain" not in chip.lower()

            if row.category_key == "access_circulation":
                allowed = [
                    "driveway",
                    "entry",
                    "drop",
                    "internal road",
                    "vehicular",
                    "pedestrian",
                    "access",
                    "frontage",
                    "gate",
                    "ramp",
                    "circulation",
                    "parking",
                    "movement",
                ]
                assert any(token in chip.lower() for token in allowed)

        if row.show_as_insufficient:
            assert row.show_winner_badge is False
            assert "no clear winner" in row.frontend_winner_reason.lower()

        if row.show_as_close_call:
            assert (
                "marginally" in row.frontend_winner_reason.lower()
                or "close" in row.frontend_winner_reason.lower()
            )

        if row.show_as_weak:
            assert row.winner_badge_label == "Relative Edge"
            assert (
                "not a major" in row.frontend_winner_reason.lower()
                or "directional" in row.frontend_winner_reason.lower()
            )

        if row.show_as_decisive and row.internal_scoring.score_gap >= 8:
            assert "gap is narrow" not in row.frontend_tradeoff.lower()
            assert "difference is narrow" not in row.frontend_tradeoff.lower()
            assert "gap is small" not in row.frontend_tradeoff.lower()

        assert "both projects" not in row.frontend_winner_reason.lower()
        assert "both projects" not in row.frontend_tradeoff.lower()
        assert "both projects" not in row.frontend_category_summary.lower()

        if row.category_key == "water_leisure":
            all_chips = row.visible_evidence + row.declared_evidence + row.spatial_evidence
            for chip in all_chips:
                assert "treated water" not in chip.lower()
                assert "sewage" not in chip.lower()
                assert "rain water" not in chip.lower()

        for project_score in row.project_scores:
            assert_frontend_clean(project_score.user_facing_one_liner)
            assert project_score.score_band in {
                "85–100",
                "70–84",
                "55–69",
                "Below 55",
            }
            assert project_score.frontend_score_label

    access_row = next(
        row for row in result.category_comparison_matrix
        if row.category_key == "access_circulation"
    )

    assert access_row.category_status != "Insufficient Evidence"
    assert access_row.show_as_close_call is True or access_row.show_as_weak is True
    assert (
        access_row.declared_evidence
        or access_row.visible_evidence
        or access_row.spatial_evidence
    )