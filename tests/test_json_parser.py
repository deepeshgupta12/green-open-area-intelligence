from pathlib import Path

from app.services.json_parser import parse_datacenter_json_file


def test_birla_taranya_json_parser():
    json_path = Path("data/input/342956.json")

    assert json_path.exists(), "Expected data/input/342956.json to exist."

    parsed = parse_datacenter_json_file(str(json_path))

    assert parsed.project_id == "342956"
    assert parsed.project_name == "Birla Taranya"
    assert parsed.city == "Thane"
    assert parsed.locality == "Kalwa"
    assert parsed.project_area_acres == 13.74
    assert parsed.total_units == 1339

    assert parsed.amenities
    assert parsed.rera_records
    assert parsed.master_plan is not None

    assert parsed.source_flags["has_project_json"] is True
    assert parsed.source_flags["has_project_area"] is True
    assert parsed.source_flags["has_amenities"] is True
    assert parsed.source_flags["has_master_plan_metadata"] is True

    assert len(parsed.green_amenity_signals) > 0
    assert len(parsed.open_space_signals) > 0
