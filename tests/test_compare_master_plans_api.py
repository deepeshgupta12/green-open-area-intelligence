from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.test_master_plan_compare_engine import build_mock_vision


client = TestClient(app)


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

    monkeypatch.setattr("app.main.analyze_master_plan_with_openai", fake_vision)

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
            },
        )

    assert response.status_code == 200, response.text

    payload = response.json()

    assert payload["comparison_run_id"]
    assert len(payload["projects"]) == 3
    assert len(payload["category_comparison_matrix"]) == 10
    assert len(payload["category_winners"]) == 10

    assert payload["overall_recommendation"]["winner_project_slot"] in {"A", "B", "C"}
    assert payload["overall_recommendation"]["one_liner"]
    assert payload["overall_recommendation"]["detailed_reason"]

    assert payload["user_friendly_summary"]["headline"]
    assert payload["user_friendly_summary"]["short_summary"]
    assert payload["user_friendly_summary"]["caution_note"]

    assert payload["run_artifacts"]["comparison_json_path"]
    assert payload["run_artifacts"]["comparison_report_path"]

    assert Path(payload["run_artifacts"]["comparison_json_path"]).exists()
    assert Path(payload["run_artifacts"]["comparison_report_path"]).exists()

    for row in payload["category_comparison_matrix"]:
        assert len(row["project_scores"]) == 3
        assert row["winner_project_slot"] in {"A", "B", "C"}
        assert row["winner_reason"]
        assert row["tradeoff"]

        for project_score in row["project_scores"]:
            assert project_score["user_facing_one_liner"]
            assert project_score["score"] >= 0
            assert project_score["score"] <= 100
