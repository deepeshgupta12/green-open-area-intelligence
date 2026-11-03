import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.master_plan_entity_extractor import parse_master_plan_entity_payload
from tests.test_compare_master_plans_api import find_master_plan_image
from tests.test_master_plan_compare_engine import build_mock_vision
from tests.test_master_plan_entity_extractor import build_sample_payload


client = TestClient(app)


def test_master_plan_entities_endpoint(monkeypatch):
    captured: dict = {}

    def fake_extract(image_metadata, project=None):
        captured["project"] = project
        return parse_master_plan_entity_payload(
            build_sample_payload(),
            image_width=image_metadata.dimensions.width,
            image_height=image_metadata.dimensions.height,
            project_id=project.project_id if project else None,
            project_name=project.project_name if project else None,
        )

    monkeypatch.setattr("app.main.extract_master_plan_entities", fake_extract)

    image_path = find_master_plan_image()
    json_path = Path("data/input/342956.json")

    with image_path.open("rb") as image_file, json_path.open("rb") as json_file:
        response = client.post(
            "/master-plan/entities",
            files={
                "master_plan_image_file": ("plan.jpg", image_file, "image/jpeg"),
                "project_json_file": ("project.json", json_file, "application/json"),
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["run_id"]
    assert captured["project"] is not None
    entity_map = payload["entity_map"]
    assert entity_map["project_id"] == captured["project"].project_id
    assert entity_map["coordinate_system"] == "fraction_of_image"
    assert entity_map["image_width"] > 0
    assert len(entity_map["entities"]) == 6
    assert entity_map["entities"][0]["box"]["x_min"] <= entity_map["entities"][0]["box"]["x_max"]
    assert Path(payload["run_artifacts"]["master_plan_entity_map_json_path"]).exists()


def test_master_plan_analysis_endpoint_returns_key_value_metrics(monkeypatch):
    def fake_extract(image_metadata, project=None):
        return parse_master_plan_entity_payload(
            build_sample_payload(),
            image_width=image_metadata.dimensions.width,
            image_height=image_metadata.dimensions.height,
            project_id=project.project_id if project else None,
            project_name=project.project_name if project else None,
        )

    def fake_vision(project, image_metadata):
        return build_mock_vision(project_id=project.project_id, project_name=project.project_name)

    monkeypatch.setattr("app.main.extract_master_plan_entities", fake_extract)
    monkeypatch.setattr("app.main.analyze_master_plan_with_gemini", fake_vision)

    records = {"sanctioned_fsi": 3.24, "clubhouse_area_sq_m": 5368, "undivided_land_share_sq_m": 27.6}

    with find_master_plan_image().open("rb") as image_file, Path("data/input/342956.json").open("rb") as json_file:
        response = client.post(
            "/master-plan/analysis",
            files={
                "master_plan_image_file": ("plan.jpg", image_file, "image/jpeg"),
                "project_json_file": ("project.json", json_file, "application/json"),
            },
            data={"run_area_estimate": "true", "site_records_json": json.dumps(records)},
        )

    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["entity_map"]["coordinate_system"] == "fraction_of_image"
    assert payload["area_estimate"] is not None
    metrics = payload["site_metrics"]
    assert metrics is not None

    # Every figure is a typed key-value with provenance; no prose fields.
    for key in ("parcel_area_acres", "total_units", "units_per_acre", "open_area_percent", "land_per_home_sq_m"):
        assert set(metrics[key]) == {"value", "unit", "source", "confidence_label", "basis"}
    assert metrics["parcel_area_acres"]["value"] == 13.74
    assert metrics["total_units"]["value"] == 1339
    assert metrics["open_area_percent"]["source"] == "master_plan_estimate"
    assert metrics["sanctioned_fsi"] == {"value": 3.24, "unit": "ratio", "source": "project_records", "confidence_label": None, "basis": None}
    assert metrics["built_up_area_sq_m"]["basis"] == "parcel_area_sq_m * sanctioned_fsi"
    assert metrics["residential_block_count"]["value"] == 2
    assert metrics["density_benchmarks"]["is_sample"] is True
    assert {scope["scope"] for scope in metrics["density_benchmarks"]["scopes"]} == {"micromarket", "city"}
    assert metrics["allocation_links"]
    assert all("basis" in link for link in metrics["allocation_links"])
    assert Path(payload["run_artifacts"]["site_metrics_json_path"]).exists()


def test_master_plan_analysis_rejects_bad_site_records(monkeypatch):
    with find_master_plan_image().open("rb") as image_file:
        response = client.post(
            "/master-plan/analysis",
            files={"master_plan_image_file": ("plan.jpg", image_file, "image/jpeg")},
            data={"site_records_json": "{not json"},
        )
    assert response.status_code == 400


def test_master_plan_endpoints_accept_an_image_url(monkeypatch):
    def fake_extract(image_metadata, project=None):
        return parse_master_plan_entity_payload(
            build_sample_payload(),
            image_width=image_metadata.dimensions.width,
            image_height=image_metadata.dimensions.height,
        )

    fetched: dict = {}

    def fake_download(url, destination_dir, *, max_bytes):
        # Stand in for the network: copy the fixture plan into the run folder.
        fetched["url"] = url
        fetched["max_bytes"] = max_bytes
        destination = Path(destination_dir) / "plan-from-url.jpg"
        destination.write_bytes(find_master_plan_image().read_bytes())
        return destination

    monkeypatch.setattr("app.main.extract_master_plan_entities", fake_extract)
    monkeypatch.setattr("app.main.download_image", fake_download)

    response = client.post(
        "/master-plan/entities",
        data={"master_plan_image_url": "https://example.com/plans/sattva-lumina.jpg"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert fetched["url"] == "https://example.com/plans/sattva-lumina.jpg"
    assert fetched["max_bytes"] > 0
    assert payload["source_image_url"] == "https://example.com/plans/sattva-lumina.jpg"
    assert payload["image_url"] == f"/master-plan/runs/{payload['run_id']}/image"

    # The stored copy is served back for display.
    image = client.get(payload["image_url"])
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/")

    assert client.get("/master-plan/runs/not-a-run-id/image").status_code == 404
    assert client.get("/master-plan/runs/00000000-0000-0000-0000-000000000000/image").status_code == 404


def test_master_plan_endpoints_require_a_source(monkeypatch):
    response = client.post("/master-plan/analysis", data={"run_area_estimate": "false"})
    assert response.status_code == 400
    assert "master_plan_image_url" in response.json()["detail"]


def test_master_plan_endpoints_reject_bad_urls(monkeypatch):
    from app.utils.remote_image import RemoteImageError

    def failing_download(url, destination_dir, *, max_bytes):
        raise RemoteImageError("Image URL must point to a public host.")

    monkeypatch.setattr("app.main.download_image", failing_download)
    response = client.post("/master-plan/entities", data={"master_plan_image_url": "http://127.0.0.1/plan.jpg"})
    assert response.status_code == 400
    assert "public host" in response.json()["detail"]


def test_master_plan_entities_endpoint_without_project_json(monkeypatch):
    def fake_extract(image_metadata, project=None):
        assert project is None
        return parse_master_plan_entity_payload(
            build_sample_payload(),
            image_width=image_metadata.dimensions.width,
            image_height=image_metadata.dimensions.height,
        )

    monkeypatch.setattr("app.main.extract_master_plan_entities", fake_extract)

    with find_master_plan_image().open("rb") as image_file:
        response = client.post(
            "/master-plan/entities",
            files={"master_plan_image_file": ("plan.jpg", image_file, "image/jpeg")},
        )

    assert response.status_code == 200, response.text
    assert response.json()["entity_map"]["project_id"] is None


def test_master_plan_analysis_estimates_green_and_open_area_without_project_json(monkeypatch):
    seen: dict = {}

    def fake_extract(image_metadata, project=None):
        return parse_master_plan_entity_payload(
            build_sample_payload(),
            image_width=image_metadata.dimensions.width,
            image_height=image_metadata.dimensions.height,
        )

    def fake_vision(project, image_metadata):
        seen["project"] = project
        return build_mock_vision(project_id=project.project_id, project_name=project.project_name)

    monkeypatch.setattr("app.main.extract_master_plan_entities", fake_extract)
    monkeypatch.setattr("app.main.analyze_master_plan_with_gemini", fake_vision)

    with find_master_plan_image().open("rb") as image_file:
        response = client.post(
            "/master-plan/analysis",
            files={"master_plan_image_file": ("plan.jpg", image_file, "image/jpeg")},
            data={"run_area_estimate": "true"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    # The estimate runs on the image alone with an empty project record...
    assert seen["project"].project_id.startswith("plan-")
    assert seen["project"].source_flags == {"has_project_json": False}
    assert payload["area_estimate"] is not None
    assert payload["area_estimate"]["green_area_percentage"]["max"] <= payload["area_estimate"]["open_area_percentage"]["max"]
    assert "Project Datacenter JSON is available." not in payload["area_estimate"]["confidence"]["reasons"]
    # ...while the record-based metrics stay absent and the diagnostic says why.
    assert payload["site_metrics"] is None
    assert any(item["code"] == "project_json_missing" for item in payload["diagnostics"])


def test_block_plan_estimate_is_low_confidence(monkeypatch):
    def fake_extract(image_metadata, project=None):
        payload = build_sample_payload()
        payload["legend_items"] = []  # a line drawing prints no legend
        entity_map = parse_master_plan_entity_payload(
            payload, image_width=image_metadata.dimensions.width, image_height=image_metadata.dimensions.height
        )
        return entity_map.model_copy(update={"site": entity_map.site.model_copy(update={"drawing_style": "block_plan"})})

    def fake_vision(project, image_metadata):
        return build_mock_vision(project_id=project.project_id, project_name=project.project_name)

    monkeypatch.setattr("app.main.extract_master_plan_entities", fake_extract)
    monkeypatch.setattr("app.main.analyze_master_plan_with_gemini", fake_vision)

    with find_master_plan_image().open("rb") as image_file:
        response = client.post(
            "/master-plan/analysis",
            files={"master_plan_image_file": ("plan.jpg", image_file, "image/jpeg")},
            data={"run_area_estimate": "true"},
        )

    assert response.status_code == 200, response.text
    estimate = response.json()["area_estimate"]
    assert estimate["confidence"]["label"] == "Low" and estimate["confidence"]["score"] <= 0.4
    assert any("block plan" in reason for reason in estimate["confidence"]["reasons"])
    assert estimate["compare_module_display"]["confidence_label"] == "Low Confidence"


def test_qa_loop_output_is_what_the_endpoint_returns(monkeypatch, tmp_path):
    from app.config import get_settings
    from app.schemas.agent_schema import QaTrail
    from app.schemas.master_plan_entity_schema import Diagnostic

    def fake_extract(image_metadata, project=None):
        return parse_master_plan_entity_payload(
            build_sample_payload(), image_width=image_metadata.dimensions.width, image_height=image_metadata.dimensions.height
        )

    seen: dict = {}

    def fake_qa_loop(entity_map, area_estimate, *, image_path, project, run_id, output_dir, **kwargs):
        seen["image_path"] = image_path
        seen["output_dir"] = output_dir
        fixed = entity_map.model_copy(update={"diagnostics": [*entity_map.diagnostics, Diagnostic(code="qa_stub_applied", count=1)]})
        trail = QaTrail(run_id=run_id, plan_style="rendered", final_verdict="pass", final_score=1.0, adopted_round=1)
        return fixed, area_estimate, trail

    monkeypatch.setattr("app.main.extract_master_plan_entities", fake_extract)
    monkeypatch.setattr("app.main.run_qa_loop", fake_qa_loop)
    monkeypatch.setattr(get_settings(), "qa_agents_enabled", True)

    with find_master_plan_image().open("rb") as image_file:
        response = client.post("/master-plan/entities", files={"master_plan_image_file": ("plan.jpg", image_file, "image/jpeg")})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert any(item["code"] == "qa_stub_applied" for item in payload["entity_map"]["diagnostics"])
    # The agents saw the same (normalised) image the extractor used, and the stored map is the fixed one.
    assert str(seen["image_path"]).endswith(".png") or str(seen["image_path"]).endswith(".jpg")
    stored = json.loads(Path(payload["run_artifacts"]["master_plan_entity_map_json_path"]).read_text())
    assert any(item["code"] == "qa_stub_applied" for item in stored["diagnostics"])
    assert "response" not in payload or "qa" not in payload  # nothing about the agents in the API contract
    assert "qa_trail" not in payload and "qa" not in payload


def _analysis_response(monkeypatch, with_json: bool, legend_rows: bool = True) -> dict:
    def fake_extract(image_metadata, project=None):
        payload = build_sample_payload()
        if not legend_rows:
            payload["legend_items"] = []
        return parse_master_plan_entity_payload(
            payload,
            image_width=image_metadata.dimensions.width,
            image_height=image_metadata.dimensions.height,
            project_id=project.project_id if project else None,
            project_name=project.project_name if project else None,
        )

    def fake_vision(project, image_metadata):
        return build_mock_vision(project_id=project.project_id, project_name=project.project_name)

    monkeypatch.setattr("app.main.extract_master_plan_entities", fake_extract)
    monkeypatch.setattr("app.main.analyze_master_plan_with_gemini", fake_vision)
    files = {"master_plan_image_file": ("plan.jpg", find_master_plan_image().read_bytes(), "image/jpeg")}
    if with_json:
        files["project_json_file"] = ("project.json", Path("data/input/342956.json").read_bytes(), "application/json")
    response = client.post("/master-plan/analysis", files=files, data={"run_area_estimate": "true"})
    assert response.status_code == 200, response.text
    return response.json()


def test_analysis_response_has_one_shape_whatever_the_plan(monkeypatch):
    from app.schemas.master_plan_entity_schema import ENTITY_TYPES

    with_records = _analysis_response(monkeypatch, with_json=True)
    plan_only = _analysis_response(monkeypatch, with_json=False)
    no_legend = _analysis_response(monkeypatch, with_json=False, legend_rows=False)

    expected_top = {"run_id", "image_url", "source_image_url", "entity_map", "site_metrics", "area_estimate", "image_metadata", "diagnostics", "run_artifacts"}
    for payload in (with_records, plan_only, no_legend):
        assert set(payload) == expected_top
        assert set(payload["entity_map"]) == set(with_records["entity_map"])
        assert set(payload["entity_map"]["site"]) == set(with_records["entity_map"]["site"])
        assert list(payload["entity_map"]["group_counts"]) == ["structure", "circulation", "amenity", "landscape", "water", "annotation"]
        assert list(payload["entity_map"]["entity_counts"]) == list(ENTITY_TYPES)
        assert set(payload["run_artifacts"]) == {
            "input_master_plan_image_path", "input_project_json_path", "normalized_image_path", "master_plan_entity_map_json_path",
            "area_estimate_json_path", "site_metrics_json_path", "qa_trail_json_path",
        }
        assert set(payload["area_estimate"]) == set(with_records["area_estimate"])

    # Figures that could not be produced are null, never missing.
    assert plan_only["site_metrics"] is None and with_records["site_metrics"] is not None
    assert plan_only["entity_map"]["site"]["printed_records"] is None
    assert plan_only["run_artifacts"]["site_metrics_json_path"] is None and plan_only["run_artifacts"]["input_project_json_path"] is None
    assert plan_only["entity_map"]["group_counts"]["water"] == 0
    assert all(set(item) == {"code", "count", "items"} for item in plan_only["diagnostics"])
