import math

from app.schemas.project_schema import AmenityRecord, ParsedProjectMetadata, UnitVariant
from app.schemas.site_metrics_schema import SiteRecords
from app.services.density_benchmarks import BenchmarkDataset, BenchmarkProjectRecord, load_density_benchmarks
from app.services.master_plan_entity_extractor import parse_master_plan_entity_payload
from app.services.site_metrics_engine import ACRE_TO_SQ_M, build_site_metrics
from tests.test_master_plan_entity_extractor import build_sample_payload


def build_project(**overrides) -> ParsedProjectMetadata:
    base = dict(
        project_id="p1",
        project_name="Sample Towers",
        city="Thane",
        locality="Kalwa",
        micromarket="Thane City",
        project_area_acres=10.0,
        total_units=1000,
        amenities=[AmenityRecord(name="Swimming Pool"), AmenityRecord(name="Gymnasium")],
        unit_mix=[
            UnitVariant(bedroom_count="2", unit_size="742", carpet_area="742", unit_cat_name="Apartment"),
            UnitVariant(bedroom_count="3", unit_size="1,019", carpet_area="1019", unit_cat_name="Apartment"),
        ],
    )
    base.update(overrides)
    return ParsedProjectMetadata(**base)


def build_dataset() -> BenchmarkDataset:
    projects = []
    # 12 Kalwa projects around 60 u/ac, 20 other Thane projects around 100 u/ac.
    for index in range(12):
        projects.append(
            BenchmarkProjectRecord(
                project_id=f"k{index}", project_name=f"Kalwa {index}", city="Thane", locality="Kalwa",
                micromarket="Thane City", project_area_acres=2 + index * 0.5, total_units=int((2 + index * 0.5) * (50 + index * 2)),
            )
        )
    for index in range(20):
        projects.append(
            BenchmarkProjectRecord(
                project_id=f"t{index}", project_name=f"Thane {index}", city="Thane", locality="Thane West",
                micromarket="Thane City", project_area_acres=1 + index * 0.4, total_units=int((1 + index * 0.4) * (90 + index)),
            )
        )
    # A different city must never leak into the Thane scopes.
    projects.append(
        BenchmarkProjectRecord(project_id="b1", project_name="Blr 1", city="Bengaluru", locality="Yelahanka",
                               project_area_acres=5.0, total_units=150)
    )
    return BenchmarkDataset(name="unit-test", version="t", is_sample=True, projects=projects)


def test_core_metrics_are_derived_with_units_and_provenance():
    entity_map = parse_master_plan_entity_payload(build_sample_payload(), image_width=1800, image_height=1200)
    metrics = build_site_metrics(
        build_project(),
        open_area_percent=80.0,
        green_area_percent=30.0,
        area_confidence_label="Medium",
        entity_map=entity_map,
    )

    assert metrics.parcel_area_acres.value == 10.0
    assert metrics.parcel_area_acres.source == "project_records"
    assert math.isclose(metrics.parcel_area_sq_m.value, 10 * ACRE_TO_SQ_M, rel_tol=1e-6)
    assert metrics.units_per_acre.value == 100.0
    assert metrics.units_per_acre.basis == "total_units / parcel_area_acres"

    assert metrics.open_area_percent.source == "master_plan_estimate"
    assert metrics.open_area_percent.confidence_label == "Medium"
    assert math.isclose(metrics.open_area_sq_m.value, 10 * ACRE_TO_SQ_M * 0.8, rel_tol=1e-4)
    assert metrics.building_footprint_percent.value == 20.0
    assert math.isclose(metrics.building_footprint_sq_m.value, 10 * ACRE_TO_SQ_M * 0.2, rel_tol=1e-4)

    # Per-home figures are rounded to 2 decimals.
    assert math.isclose(metrics.land_per_home_sq_m.value, 10 * ACRE_TO_SQ_M / 1000, abs_tol=0.01)
    assert math.isclose(metrics.open_realm_per_home_sq_m.value, 10 * ACRE_TO_SQ_M * 0.8 / 1000, abs_tol=0.01)
    assert math.isclose(metrics.green_per_home_sq_m.value, 10 * ACRE_TO_SQ_M * 0.3 / 1000, abs_tol=0.01)

    # Figures that only exist in sanction records stay honestly unavailable.
    assert metrics.sanctioned_fsi.source == "unavailable"
    assert metrics.sanctioned_fsi.value is None
    assert metrics.built_up_area_sq_m.source == "unavailable"
    assert metrics.undivided_land_share_sq_m.source == "unavailable"

    # Counts from the entity map.
    assert metrics.residential_block_count.value == 2
    assert metrics.residential_block_count.source == "master_plan_entities"
    assert metrics.homes_per_block.value == 500.0
    assert metrics.outdoor_space_count.value >= 2
    assert metrics.declared_amenity_count.value == 2

    assert [row.unit_size_sq_ft for row in metrics.unit_mix] == [742.0, 1019.0]

    node_keys = {node.key for node in metrics.allocation_nodes}
    assert {"site_parcel", "open_realm", "building_plinth", "land_per_home", "outdoor_amenities", "built_up_envelope"} <= node_keys
    stage_one = sum(node.value_sq_m for node in metrics.allocation_nodes if node.stage == 1)
    assert math.isclose(stage_one, metrics.parcel_area_sq_m.value, rel_tol=1e-6)
    assert metrics.density_benchmarks is None
    assert metrics.constants["acre_to_sq_m"] == ACRE_TO_SQ_M


def test_records_override_estimates_and_fill_fsi():
    metrics = build_site_metrics(
        build_project(),
        open_area_percent=80.0,
        records=SiteRecords(sanctioned_fsi=3.0, clubhouse_area_sq_m=5000, undivided_land_share_sq_m=27.6, open_area_percent=85.0),
    )
    assert metrics.open_area_percent.value == 85.0
    assert metrics.open_area_percent.source == "project_records"
    assert metrics.building_footprint_percent.value == 15.0
    assert metrics.sanctioned_fsi.value == 3.0
    assert math.isclose(metrics.built_up_area_sq_m.value, 10 * ACRE_TO_SQ_M * 3, rel_tol=1e-6)
    assert metrics.built_up_area_sq_m.basis == "parcel_area_sq_m * sanctioned_fsi"
    assert metrics.clubhouse_area_sq_m.value == 5000
    assert metrics.undivided_land_share_sq_m.value == 27.6
    assert any(node.key == "clubhouse" for node in metrics.allocation_nodes)


def test_missing_area_or_units_degrades_gracefully():
    metrics = build_site_metrics(build_project(project_area_acres=None, total_units=None))
    assert metrics.parcel_area_acres.source == "unavailable"
    assert metrics.units_per_acre.value is None
    assert metrics.open_area_percent.source == "unavailable"
    assert metrics.allocation_nodes == []
    assert metrics.allocation_links == []


def test_density_benchmarks_scope_to_locality_and_city():
    metrics = build_site_metrics(build_project(), benchmarks=build_dataset())
    bench = metrics.density_benchmarks
    assert bench is not None
    assert bench.is_sample is True
    assert bench.subject_units_per_acre == 100.0

    scopes = {scope.scope: scope for scope in bench.scopes}
    local = scopes["micromarket"]
    city = scopes["city"]

    assert local.name == "Kalwa"
    assert local.sample_size == 12
    assert local.sufficient is True
    assert city.sample_size == 32  # 12 Kalwa + 20 Thane West; Bengaluru excluded
    assert local.median_units_per_acre < city.median_units_per_acre

    # Subject at 100 u/ac is denser than every Kalwa project in the fixture.
    assert local.subject_percentile == 100.0
    assert local.subject_vs_median_percent > 0
    assert 0 <= local.share_at_or_below_city_median_percent <= 100
    assert bench.city_median_units_per_acre == city.median_units_per_acre

    assert len(local.density_curve) == 60
    assert local.peak_units_per_acre is not None
    assert local.density_curve[0].units_per_acre == 0.0
    assert local.density_curve[-1].units_per_acre > 100.0

    subject_points = [point for point in city.projects if point.is_subject]
    assert len(subject_points) == 1
    assert subject_points[0].project_name == "Sample Towers"
    assert len(city.projects) == 33

    assert city.trendline is not None
    assert city.trendline.slope_acres_per_unit > 0
    assert 0 <= city.trendline.r_squared <= 1


def test_small_scope_is_flagged_insufficient():
    dataset = BenchmarkDataset(
        name="tiny",
        projects=[
            BenchmarkProjectRecord(project_name="A", city="Thane", locality="Kalwa", project_area_acres=2, total_units=100),
            BenchmarkProjectRecord(project_name="B", city="Thane", locality="Kalwa", project_area_acres=3, total_units=200),
        ],
    )
    bench = build_site_metrics(build_project(), benchmarks=dataset).density_benchmarks
    assert bench is not None
    local = next(scope for scope in bench.scopes if scope.scope == "micromarket")
    assert local.sufficient is False
    assert local.density_curve == []
    assert local.trendline is None
    assert local.median_units_per_acre is not None


def test_shipped_sample_dataset_loads_and_is_flagged():
    dataset = load_density_benchmarks()
    assert dataset is not None
    assert dataset.is_sample is True
    assert len(dataset.projects) >= 100
    cities = {project.city for project in dataset.projects}
    assert {"Thane", "Bengaluru"} <= cities
    assert load_density_benchmarks("data/benchmarks/does-not-exist.json") is None
