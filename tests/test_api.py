from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


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


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "ok"
    assert "app_name" in payload
    assert payload["default_port"] == 2345


def test_estimate_endpoint_without_openai_vision():
    json_path = Path("data/input/342956.json")
    image_path = find_master_plan_image()

    assert json_path.exists()

    with json_path.open("rb") as json_file, image_path.open("rb") as image_file:
        response = client.post(
            "/estimate",
            files={
                "project_json_file": ("342956.json", json_file, "application/json"),
                "master_plan_image_file": (
                    image_path.name,
                    image_file,
                    "image/jpeg",
                ),
            },
            data={
                "run_vision": "false",
                "run_segmentation": "true",
                "run_area_estimate": "false",
                "run_category_comparison": "false",
                "write_report": "false",
            },
        )

    assert response.status_code == 200

    payload = response.json()

    assert payload["run_id"]
    assert payload["run_artifacts"]
    assert payload["project_metadata"]["project_id"] == "342956"
    assert payload["project_metadata"]["project_name"] == "Birla Taranya"
    assert payload["image_metadata"]["dimensions"]["width"] > 0
    assert payload["segmentation_result"] is not None
    assert payload["vision_analysis"] is None
    assert payload["area_estimate"] is None
    assert payload["category_comparison"] is None
    assert payload["final_outputs"] is None

    artifacts = payload["run_artifacts"]

    assert Path(artifacts["input_project_json_path"]).exists()
    assert Path(artifacts["input_master_plan_image_path"]).exists()
    assert Path(artifacts["project_metadata_json_path"]).exists()
    assert Path(artifacts["image_metadata_json_path"]).exists()
    assert Path(artifacts["segmentation_result_json_path"]).exists()
    assert Path(artifacts["run_summary_json_path"]).exists()

    assert artifacts["vision_analysis_json_path"] is None
    assert artifacts["area_estimate_json_path"] is None
    assert artifacts["markdown_report_path"] is None
    assert artifacts["compare_contract_path"] is None
    assert artifacts["category_comparison_json_path"] is None


def test_invalid_area_estimate_without_vision_returns_400():
    json_path = Path("data/input/342956.json")
    image_path = find_master_plan_image()

    with json_path.open("rb") as json_file, image_path.open("rb") as image_file:
        response = client.post(
            "/estimate",
            files={
                "project_json_file": ("342956.json", json_file, "application/json"),
                "master_plan_image_file": (
                    image_path.name,
                    image_file,
                    "image/jpeg",
                ),
            },
            data={
                "run_vision": "false",
                "run_segmentation": "true",
                "run_area_estimate": "true",
                "run_category_comparison": "false",
                "write_report": "false",
            },
        )

    assert response.status_code == 400
    assert "run_area_estimate=true requires run_vision=true" in response.json()["detail"]


def test_invalid_category_comparison_without_area_estimate_returns_400():
    json_path = Path("data/input/342956.json")
    image_path = find_master_plan_image()

    with json_path.open("rb") as json_file, image_path.open("rb") as image_file:
        response = client.post(
            "/estimate",
            files={
                "project_json_file": ("342956.json", json_file, "application/json"),
                "master_plan_image_file": (
                    image_path.name,
                    image_file,
                    "image/jpeg",
                ),
            },
            data={
                "run_vision": "false",
                "run_segmentation": "true",
                "run_area_estimate": "false",
                "run_category_comparison": "true",
                "write_report": "false",
            },
        )

    assert response.status_code == 400
    assert "run_category_comparison=true requires run_area_estimate=true" in response.json()["detail"]
