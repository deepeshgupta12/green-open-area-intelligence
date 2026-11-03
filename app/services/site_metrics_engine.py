"""Deterministic site metrics for the master plan analysis dashboards.

Inputs are the parsed project record, the open/green area estimate midpoints
from the existing pipeline, the spatial entity map, optional sanction records
and the density benchmark dataset. Output is :class:`SiteMetrics`: key-value
figures with units and provenance, flow nodes/links for the allocation
diagram and benchmark distributions for the density charts. No prose.
"""

from __future__ import annotations

import math
import statistics
from typing import Iterable

import numpy as np

from app.schemas.area_schema import AreaEstimateResult
from app.schemas.master_plan_entity_schema import MasterPlanEntityMap
from app.schemas.project_schema import ParsedProjectMetadata
from app.schemas.site_metrics_schema import (
    BenchmarkProjectPoint,
    BenchmarkScope,
    CurvePoint,
    DensityBenchmarks,
    FlowLink,
    FlowNode,
    MetricValue,
    SiteMetrics,
    SiteRecords,
    Trendline,
    UnitMixRow,
)
from app.services.density_benchmarks import BenchmarkDataset, BenchmarkProjectRecord


ACRE_TO_SQ_M = 4046.8564224
SQ_M_TO_SQ_FT = 10.763910417
MIN_BENCHMARK_SAMPLE = 5
CURVE_POINTS = 60


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def area_inputs_from_estimate(
    estimate: AreaEstimateResult | None,
) -> tuple[float | None, float | None, str | None]:
    """Midpoints of the open and green ranges plus the estimate's confidence label."""
    if estimate is None:
        return None, None, None
    open_mid = (estimate.open_area_percentage.min + estimate.open_area_percentage.max) / 2
    green_mid = (estimate.green_area_percentage.min + estimate.green_area_percentage.max) / 2
    return round(open_mid, 2), round(green_mid, 2), estimate.confidence.label


def build_site_metrics(
    project: ParsedProjectMetadata,
    *,
    open_area_percent: float | None = None,
    green_area_percent: float | None = None,
    area_confidence_label: str | None = None,
    entity_map: MasterPlanEntityMap | None = None,
    benchmarks: BenchmarkDataset | None = None,
    records: SiteRecords | None = None,
) -> SiteMetrics:
    records = records or SiteRecords()

    acres = project.project_area_acres if project.project_area_acres and project.project_area_acres > 0 else None
    units = project.total_units if project.total_units and project.total_units > 0 else None
    parcel_sq_m = round(acres * ACRE_TO_SQ_M, 2) if acres else None

    parcel_area_acres = _metric(acres, "acres", "project_records")
    parcel_area_sq_m = _metric(parcel_sq_m, "sq_m", "derived", basis="parcel_area_acres * 4046.8564")
    total_units = _metric(units, "units", "project_records")
    units_per_acre = _metric(
        _round(units / acres, 1) if units and acres else None,
        "units_per_acre",
        "derived",
        basis="total_units / parcel_area_acres",
    )

    # Open area: sanction records beat the master plan estimate.
    if records.open_area_percent is not None:
        open_pct = _metric(records.open_area_percent, "percent", "project_records")
    elif open_area_percent is not None:
        open_pct = _metric(open_area_percent, "percent", "master_plan_estimate", confidence=area_confidence_label,
                           basis="midpoint of open_area_percentage range")
    else:
        open_pct = _unavailable("percent")

    green_pct = (
        _metric(green_area_percent, "percent", "master_plan_estimate", confidence=area_confidence_label,
                basis="midpoint of green_area_percentage range")
        if green_area_percent is not None
        else _unavailable("percent")
    )

    open_sq_m = _metric(
        _round(parcel_sq_m * open_pct.value / 100, 2) if parcel_sq_m and open_pct.value is not None else None,
        "sq_m", "derived", confidence=open_pct.confidence_label, basis="parcel_area_sq_m * open_area_percent / 100",
    )
    green_sq_m = _metric(
        _round(parcel_sq_m * green_pct.value / 100, 2) if parcel_sq_m and green_pct.value is not None else None,
        "sq_m", "derived", confidence=green_pct.confidence_label, basis="parcel_area_sq_m * green_area_percent / 100",
    )

    if records.building_footprint_sq_m is not None and parcel_sq_m:
        footprint_sq_m = _metric(records.building_footprint_sq_m, "sq_m", "project_records")
        footprint_pct = _metric(_round(records.building_footprint_sq_m / parcel_sq_m * 100, 2), "percent", "derived",
                                basis="building_footprint_sq_m / parcel_area_sq_m * 100")
    elif open_pct.value is not None:
        footprint_pct = _metric(_round(100 - open_pct.value, 2), "percent", "derived",
                                confidence=open_pct.confidence_label, basis="100 - open_area_percent")
        footprint_sq_m = _metric(
            _round(parcel_sq_m * footprint_pct.value / 100, 2) if parcel_sq_m and footprint_pct.value is not None else None,
            "sq_m", "derived", confidence=open_pct.confidence_label, basis="parcel_area_sq_m - open_area_sq_m",
        )
    else:
        footprint_pct = _unavailable("percent")
        footprint_sq_m = _unavailable("sq_m")

    fsi = _metric(records.sanctioned_fsi, "ratio", "project_records") if records.sanctioned_fsi else _unavailable("ratio")
    if records.built_up_area_sq_m:
        built_up = _metric(records.built_up_area_sq_m, "sq_m", "project_records")
    elif fsi.value and parcel_sq_m:
        built_up = _metric(_round(parcel_sq_m * fsi.value, 2), "sq_m", "derived", basis="parcel_area_sq_m * sanctioned_fsi")
    else:
        built_up = _unavailable("sq_m")

    land_per_home = _metric(_round(parcel_sq_m / units, 2) if parcel_sq_m and units else None, "sq_m", "derived",
                            basis="parcel_area_sq_m / total_units")
    open_per_home = _metric(_round(open_sq_m.value / units, 2) if open_sq_m.value and units else None, "sq_m", "derived",
                            confidence=open_pct.confidence_label, basis="open_area_sq_m / total_units")
    green_per_home = _metric(_round(green_sq_m.value / units, 2) if green_sq_m.value and units else None, "sq_m", "derived",
                             confidence=green_pct.confidence_label, basis="green_area_sq_m / total_units")
    uds = (
        _metric(records.undivided_land_share_sq_m, "sq_m", "project_records")
        if records.undivided_land_share_sq_m
        else _unavailable("sq_m")
    )
    clubhouse = (
        _metric(records.clubhouse_area_sq_m, "sq_m", "project_records")
        if records.clubhouse_area_sq_m
        else _unavailable("sq_m")
    )

    block_count = _count_residential_blocks(entity_map)
    residential_block_count = (
        _metric(block_count, "count", "master_plan_entities", confidence=entity_map.extraction_confidence_label)
        if entity_map is not None and block_count
        else _unavailable("count")
    )
    homes_per_block = _metric(
        _round(units / block_count, 1) if units and block_count else None, "units", "derived",
        basis="total_units / residential_block_count",
    )
    homes_per_floor_min = (
        _metric(records.homes_per_floor_min, "units", "project_records") if records.homes_per_floor_min else _unavailable("units")
    )
    homes_per_floor_max = (
        _metric(records.homes_per_floor_max, "units", "project_records") if records.homes_per_floor_max else _unavailable("units")
    )
    outdoor_count = _count_outdoor_spaces(entity_map)
    outdoor_space_count = (
        _metric(outdoor_count, "count", "master_plan_entities", confidence=entity_map.extraction_confidence_label)
        if entity_map is not None
        else _unavailable("count")
    )
    declared_amenity_count = _metric(len(project.amenities), "count", "project_records")

    nodes, links = _build_allocation_flow(
        parcel_sq_m=parcel_sq_m,
        open_sq_m=open_sq_m.value,
        footprint_sq_m=footprint_sq_m.value,
        built_up_sq_m=built_up.value,
        land_per_home=land_per_home.value,
        units=units,
        outdoor_count=outdoor_count if entity_map is not None else None,
        clubhouse_sq_m=clubhouse.value,
        fsi=fsi.value,
    )

    density = (
        _build_density_benchmarks(project, units_per_acre.value, benchmarks)
        if benchmarks is not None
        else None
    )

    return SiteMetrics(
        project_id=project.project_id,
        project_name=project.project_name,
        city=project.city,
        locality=project.locality,
        micromarket=project.micromarket,
        parcel_area_acres=parcel_area_acres,
        parcel_area_sq_m=parcel_area_sq_m,
        total_units=total_units,
        units_per_acre=units_per_acre,
        open_area_percent=open_pct,
        open_area_sq_m=open_sq_m,
        green_area_percent=green_pct,
        green_area_sq_m=green_sq_m,
        building_footprint_percent=footprint_pct,
        building_footprint_sq_m=footprint_sq_m,
        sanctioned_fsi=fsi,
        built_up_area_sq_m=built_up,
        land_per_home_sq_m=land_per_home,
        open_realm_per_home_sq_m=open_per_home,
        green_per_home_sq_m=green_per_home,
        undivided_land_share_sq_m=uds,
        clubhouse_area_sq_m=clubhouse,
        residential_block_count=residential_block_count,
        homes_per_block=homes_per_block,
        homes_per_floor_min=homes_per_floor_min,
        homes_per_floor_max=homes_per_floor_max,
        outdoor_space_count=outdoor_space_count,
        declared_amenity_count=declared_amenity_count,
        unit_mix=_unit_mix(project),
        allocation_nodes=nodes,
        allocation_links=links,
        density_benchmarks=density,
        constants={"acre_to_sq_m": ACRE_TO_SQ_M, "sq_m_to_sq_ft": SQ_M_TO_SQ_FT},
    )


# --------------------------------------------------------------------------- #
# Entity-map derived counts
# --------------------------------------------------------------------------- #


def _count_residential_blocks(entity_map: MasterPlanEntityMap | None) -> int:
    if entity_map is None:
        return 0
    labels = {entity.label.strip().lower() for entity in entity_map.entities if entity.entity_type == "residential_block"}
    return len(labels)


def _count_outdoor_spaces(entity_map: MasterPlanEntityMap | None) -> int:
    if entity_map is None:
        return 0
    labels = {
        entity.label.strip().lower()
        for entity in entity_map.entities
        if entity.entity_group in {"amenity", "landscape", "water"}
    }
    return len(labels)


def _unit_mix(project: ParsedProjectMetadata) -> list[UnitMixRow]:
    rows: list[UnitMixRow] = []
    for variant in project.unit_mix:
        rows.append(
            UnitMixRow(
                bedroom_count=variant.bedroom_count,
                unit_cat_name=variant.unit_cat_name,
                unit_size_sq_ft=_to_float(variant.unit_size),
                carpet_area_sq_ft=_to_float(variant.carpet_area),
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Allocation flow (parcel -> open realm / plinth -> outcomes)
# --------------------------------------------------------------------------- #


def _build_allocation_flow(
    *,
    parcel_sq_m: float | None,
    open_sq_m: float | None,
    footprint_sq_m: float | None,
    built_up_sq_m: float | None,
    land_per_home: float | None,
    units: int | None,
    outdoor_count: int | None,
    clubhouse_sq_m: float | None,
    fsi: float | None,
) -> tuple[list[FlowNode], list[FlowLink]]:
    if not parcel_sq_m:
        return [], []

    def share(value: float | None) -> float | None:
        return _round(value / parcel_sq_m * 100, 2) if value is not None else None

    nodes = [
        FlowNode(key="site_parcel", stage=0, value_sq_m=parcel_sq_m, share_of_parcel_percent=100.0, source="project_records"),
        FlowNode(key="open_realm", stage=1, value_sq_m=open_sq_m, share_of_parcel_percent=share(open_sq_m)),
        FlowNode(key="building_plinth", stage=1, value_sq_m=footprint_sq_m, share_of_parcel_percent=share(footprint_sq_m)),
        FlowNode(key="land_per_home", stage=2, value_sq_m=land_per_home, count=units),
        FlowNode(
            key="outdoor_amenities",
            stage=2,
            value_sq_m=open_sq_m,
            share_of_parcel_percent=share(open_sq_m),
            count=outdoor_count,
            source="master_plan_entities" if outdoor_count is not None else "derived",
        ),
        FlowNode(
            key="built_up_envelope",
            stage=2,
            value_sq_m=built_up_sq_m,
            share_of_parcel_percent=share(built_up_sq_m),
            source="project_records" if fsi else "unavailable",
        ),
    ]
    if clubhouse_sq_m:
        nodes.append(FlowNode(key="clubhouse", stage=2, value_sq_m=clubhouse_sq_m, share_of_parcel_percent=share(clubhouse_sq_m), source="project_records"))

    links = [
        FlowLink(source="site_parcel", target="open_realm", value_sq_m=open_sq_m, share_percent=share(open_sq_m),
                 basis="parcel_area_sq_m * open_area_percent / 100"),
        FlowLink(source="site_parcel", target="building_plinth", value_sq_m=footprint_sq_m, share_percent=share(footprint_sq_m),
                 basis="parcel_area_sq_m - open_area_sq_m"),
        FlowLink(source="open_realm", target="land_per_home", value_sq_m=open_sq_m, share_percent=share(open_sq_m),
                 basis="parcel_area_sq_m / total_units"),
        FlowLink(source="open_realm", target="outdoor_amenities", value_sq_m=open_sq_m, share_percent=share(open_sq_m),
                 basis="open_area_sq_m"),
        FlowLink(source="building_plinth", target="built_up_envelope", value_sq_m=built_up_sq_m, share_percent=share(built_up_sq_m),
                 basis="parcel_area_sq_m * sanctioned_fsi"),
    ]
    return nodes, links


# --------------------------------------------------------------------------- #
# Density benchmarks
# --------------------------------------------------------------------------- #


def _build_density_benchmarks(
    project: ParsedProjectMetadata,
    subject_upa: float | None,
    dataset: BenchmarkDataset,
) -> DensityBenchmarks:
    records = [record for record in dataset.projects if _key(record.project_id) != _key(project.project_id)]

    city_records = [r for r in records if _key(r.city) == _key(project.city)] if project.city else []
    local_records = [r for r in city_records if project.locality and _key(r.locality) == _key(project.locality)]
    if len(local_records) < MIN_BENCHMARK_SAMPLE and project.micromarket:
        by_micromarket = [r for r in city_records if _key(r.micromarket) == _key(project.micromarket)]
        if len(by_micromarket) > len(local_records):
            local_records = by_micromarket

    city_median = _median([_upa(r) for r in city_records]) if city_records else None

    scopes: list[BenchmarkScope] = []
    local_name = project.locality or project.micromarket or "Micro-market"
    if local_records:
        scopes.append(_build_scope("micromarket", local_name, local_records, subject_upa, city_median, project))
    if city_records:
        scopes.append(_build_scope("city", project.city or "City", city_records, subject_upa, None, project))

    return DensityBenchmarks(
        dataset_name=dataset.name,
        dataset_version=dataset.version,
        as_of=dataset.as_of,
        is_sample=dataset.is_sample,
        subject_units_per_acre=subject_upa,
        city_median_units_per_acre=_round(city_median, 1) if city_median is not None else None,
        scopes=scopes,
    )


def _build_scope(
    scope: str,
    name: str,
    records: list[BenchmarkProjectRecord],
    subject_upa: float | None,
    city_median: float | None,
    project: ParsedProjectMetadata,
) -> BenchmarkScope:
    values = [_upa(r) for r in records]
    sufficient = len(values) >= MIN_BENCHMARK_SAMPLE

    curve, peak = _density_curve(values, subject_upa) if sufficient else ([], None)
    median = _median(values)

    points = [
        BenchmarkProjectPoint(
            project_id=r.project_id,
            project_name=r.project_name,
            city=r.city,
            locality=r.locality,
            project_area_acres=r.project_area_acres,
            total_units=r.total_units,
            units_per_acre=_round(_upa(r), 1),
        )
        for r in records
    ]
    if subject_upa is not None and project.project_area_acres and project.total_units:
        points.append(
            BenchmarkProjectPoint(
                project_id=project.project_id,
                project_name=project.project_name or "This project",
                city=project.city,
                locality=project.locality,
                project_area_acres=project.project_area_acres,
                total_units=project.total_units,
                units_per_acre=subject_upa,
                is_subject=True,
            )
        )

    return BenchmarkScope(
        scope=scope,  # type: ignore[arg-type]
        name=name,
        sample_size=len(values),
        sufficient=sufficient,
        median_units_per_acre=_round(median, 1),
        mean_units_per_acre=_round(statistics.fmean(values), 1),
        p25_units_per_acre=_round(_percentile(values, 25), 1),
        p75_units_per_acre=_round(_percentile(values, 75), 1),
        peak_units_per_acre=_round(peak, 1) if peak is not None else None,
        subject_percentile=(
            _round(sum(1 for v in values if v < subject_upa) / len(values) * 100, 1) if subject_upa is not None else None
        ),
        subject_vs_median_percent=(
            _round((subject_upa / median - 1) * 100, 1) if subject_upa is not None and median else None
        ),
        share_at_or_below_city_median_percent=(
            _round(sum(1 for v in values if v <= city_median) / len(values) * 100, 1) if city_median is not None else None
        ),
        density_curve=curve,
        projects=points,
        trendline=_trendline(records) if sufficient else None,
    )


def _density_curve(values: list[float], subject_upa: float | None) -> tuple[list[CurvePoint], float]:
    """Gaussian kernel density on a shared grid; returns (curve, peak position)."""
    data = np.asarray(values, dtype=float)
    spread = float(data.std(ddof=1)) if len(data) > 1 else 0.0
    bandwidth = max(3.0, 1.06 * spread * len(data) ** (-0.2))
    upper = max(float(data.max()), subject_upa or 0.0) * 1.15 + bandwidth
    grid = np.linspace(0.0, upper, CURVE_POINTS)
    kernel = np.exp(-0.5 * ((grid[:, None] - data[None, :]) / bandwidth) ** 2)
    density = kernel.sum(axis=1) / (len(data) * bandwidth * math.sqrt(2 * math.pi))
    peak = float(grid[int(density.argmax())])
    curve = [CurvePoint(units_per_acre=round(float(x), 2), density=round(float(y), 6)) for x, y in zip(grid, density)]
    return curve, peak


def _trendline(records: list[BenchmarkProjectRecord]) -> Trendline | None:
    """Least-squares acres ~ units: how much land each extra home brings."""
    xs = np.asarray([r.total_units for r in records], dtype=float)
    ys = np.asarray([r.project_area_acres for r in records], dtype=float)
    if len(xs) < 2 or float(xs.std()) == 0.0:
        return None
    slope, intercept = np.polyfit(xs, ys, 1)
    predicted = slope * xs + intercept
    ss_res = float(((ys - predicted) ** 2).sum())
    ss_tot = float(((ys - ys.mean()) ** 2).sum())
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return Trendline(
        slope_acres_per_unit=round(float(slope), 6),
        intercept_acres=round(float(intercept), 4),
        r_squared=round(max(0.0, r_squared), 4),
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _metric(
    value: float | int | None,
    unit: str,
    source: str,
    *,
    confidence: str | None = None,
    basis: str | None = None,
) -> MetricValue:
    if value is None:
        return _unavailable(unit)
    return MetricValue(value=float(value), unit=unit, source=source, confidence_label=confidence, basis=basis)  # type: ignore[arg-type]


def _unavailable(unit: str) -> MetricValue:
    return MetricValue(value=None, unit=unit, source="unavailable")


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


def _upa(record: BenchmarkProjectRecord) -> float:
    return record.total_units / record.project_area_acres


def _key(value: str | None) -> str:
    return " ".join(str(value or "").lower().split())


def _median(values: Iterable[float]) -> float | None:
    items = list(values)
    return statistics.median(items) if items else None


def _percentile(values: list[float], pct: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), pct))


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None
