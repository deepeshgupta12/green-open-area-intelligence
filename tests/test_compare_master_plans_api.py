from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.test_master_plan_compare_engine import build_mock_vision


client = TestClient(app)


BANNED_FRONTEND_TERMS = [
    "OpenCV",
    "unknown area",
    "unknown/unclassified",
    "segmentation",
    "pixel",
    "image quality",
    "area estimate confidence",
]


def assert_frontend_clean(value: str):
    lowered = value.lower()
    for term in BANNED_FRONTEND_TERMS:
        assert term.lower() not in lowered


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


def test_compare_master_plans_api(monkeypatch):
    def fake_vision(project, image_metadata):
        return build_mock_vision(
            project_id=project.project_id,
            project_name=project.project_name,
        )

    def fake_openai_narrative(comparison):
        return comparison

    monkeypatch.setattr("app.main.analyze_master_plan_with_openai", fake_vision)
    monkeypatch.setattr("app.main.enhance_master_plan_comparison_with_openai", fake_openai_narrative)

    json_path = Path("data/input/342956.json")
    image_path = find_master_plan_image()

    with (
        json_path.open("rb") as a_json,
        image_path.open("rb") as a_img,
        json_path.open("rb") as b_json,
        image_path.open("rb") as b_img,
        json_path.open("rb") as c_json,
        image_path.open("rb") as c_img,
    ):
        response = client.post(
            "/compare-master-plans",
            files={
                "project_a_json_file": ("a.json", a_json, "application/json"),
                "project_a_master_plan_image_file": ("a.jpg", a_img, "image/jpeg"),
                "project_b_json_file": ("b.json", b_json, "application/json"),
                "project_b_master_plan_image_file": ("b.jpg", b_img, "image/jpeg"),
                "project_c_json_file": ("c.json", c_json, "application/json"),
                "project_c_master_plan_image_file": ("c.jpg", c_img, "image/jpeg"),
            },
            data={
                "run_vision": "true",
                "run_segmentation": "true",
                "run_area_estimate": "true",
                "run_category_comparison": "true",
                "write_report": "true",
                "use_ai_narrative": "true",
                "use_ai_structure_extraction": "false",
            },
        )

    assert response.status_code == 200, response.text

    payload = response.json()

    assert payload["comparison_run_id"]
    assert len(payload["projects"]) == 3
    assert len(payload["category_comparison_matrix"]) == 9
    assert len(payload["category_winners"]) == 9
    assert payload["overall_recommendation"]["winner_project_slot"] in {"A", "B", "C"}
    assert payload["user_friendly_summary"]["headline"]
    assert payload["internal_evidence_quality"]["opencv_used_for_frontend_copy"] is False

    assert payload["run_artifacts"]["comparison_json_path"]
    assert payload["run_artifacts"]["comparison_report_path"]
    assert Path(payload["run_artifacts"]["comparison_json_path"]).exists()
    assert Path(payload["run_artifacts"]["comparison_report_path"]).exists()

    for row in payload["category_comparison_matrix"]:
        assert len(row["project_scores"]) == 3
        assert row["winner_project_slot"] in {"A", "B", "C"}
        assert row["winner_reason"]
        assert row["tradeoff"]
        assert row["frontend_winner_reason"]
        assert row["frontend_tradeoff"]
        assert row["frontend_category_summary"]

        assert row["category_status"] in {"Clear Winner", "Close Call", "Weak Differentiator", "Insufficient Evidence"}
        assert row["evidence_strength"] in {"Strong", "Moderate", "Weak", "Insufficient"}
        assert isinstance(row["show_as_decisive"], bool)
        assert isinstance(row["show_as_close_call"], bool)
        assert isinstance(row["show_as_insufficient"], bool)

        assert_frontend_clean(row["winner_reason"])
        assert_frontend_clean(row["tradeoff"])
        assert_frontend_clean(row["frontend_winner_reason"])
        assert_frontend_clean(row["frontend_tradeoff"])
        assert_frontend_clean(row["frontend_category_summary"])

        forbidden_chips = {"green", "open", "landscape", "road", "pathway", "tree", "pool", "leisure"}
        all_frontend_chips = row["visible_evidence"] + row["declared_evidence"]
        for chip in all_frontend_chips:
            assert chip.strip().lower() not in forbidden_chips
            if row["category_key"] == "green_landscape":
                assert "sewage" not in chip.lower()
                assert "treated water" not in chip.lower()
                assert "rain" not in chip.lower()
            if row["category_key"] == "access_circulation":
                allowed = ["driveway", "entry", "drop", "internal road", "vehicular", "pedestrian", "access", "frontage", "gate", "ramp"]
                assert any(token in chip.lower() for token in allowed)

        if row["show_as_insufficient"]:
            assert row["show_winner_badge"] is False
            assert "no clear winner" in row["frontend_winner_reason"].lower()
        if row["show_as_close_call"]:
            assert "marginally" in row["frontend_winner_reason"].lower() or "close" in row["frontend_winner_reason"].lower()
        if row.get("show_as_weak"):
            assert "not a major" in row["frontend_winner_reason"].lower() or "directional" in row["frontend_winner_reason"].lower()

        for project_score in row["project_scores"]:
            assert project_score["user_facing_one_liner"]
            assert project_score["score"] >= 0
            assert project_score["score"] <= 100
            assert project_score["score_band"]
            assert project_score["frontend_score_label"]
            assert_frontend_clean(project_score["user_facing_one_liner"])
