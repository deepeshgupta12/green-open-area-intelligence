"""Key-value site metrics for the master plan analysis dashboards.

Every figure is a :class:`MetricValue` that states its unit and where it came
from, so the frontend can render it, label its provenance and template any
sentence itself. Nothing in this contract is model-written prose.
"""

from typing import Literal

from pydantic import BaseModel, Field


MetricSource = Literal[
    "project_records",
    "master_plan_estimate",
    "master_plan_entities",
    "derived",
    "benchmark_dataset",
    "unavailable",
]


class MetricValue(BaseModel):
    value: float | None = None
    unit: str
    source: MetricSource = "unavailable"
    confidence_label: str | None = None
    basis: str | None = Field(
        default=None, description="Machine-readable formula key, e.g. parcel_sq_m / total_units."
    )


class SiteRecords(BaseModel):
    """Optional figures that only exist in sanction or sales records."""

    sanctioned_fsi: float | None = None
    built_up_area_sq_m: float | None = None
    clubhouse_area_sq_m: float | None = None
    undivided_land_share_sq_m: float | None = None
    open_area_percent: float | None = None
    building_footprint_sq_m: float | None = None
    homes_per_floor_min: int | None = None
    homes_per_floor_max: int | None = None


class UnitMixRow(BaseModel):
    bedroom_count: str | None = None
    unit_cat_name: str | None = None
    unit_size_sq_ft: float | None = None
    carpet_area_sq_ft: float | None = None


class FlowNode(BaseModel):
    key: str
    stage: int
    value_sq_m: float | None = None
    share_of_parcel_percent: float | None = None
    count: int | None = None
    source: MetricSource = "derived"


class FlowLink(BaseModel):
    source: str
    target: str
    value_sq_m: float | None = None
    share_percent: float | None = None
    basis: str


class CurvePoint(BaseModel):
    units_per_acre: float
    density: float


class BenchmarkProjectPoint(BaseModel):
    project_id: str | None = None
    project_name: str
    city: str | None = None
    locality: str | None = None
    project_area_acres: float
    total_units: int
    units_per_acre: float
    is_subject: bool = False


class Trendline(BaseModel):
    slope_acres_per_unit: float
    intercept_acres: float
    r_squared: float


class BenchmarkScope(BaseModel):
    scope: Literal["micromarket", "city"]
    name: str
    sample_size: int
    sufficient: bool
    median_units_per_acre: float | None = None
    mean_units_per_acre: float | None = None
    p25_units_per_acre: float | None = None
    p75_units_per_acre: float | None = None
    peak_units_per_acre: float | None = None
    subject_percentile: float | None = Field(
        default=None, description="Share of scope projects with lower density than the subject, in percent."
    )
    subject_vs_median_percent: float | None = None
    share_at_or_below_city_median_percent: float | None = None
    density_curve: list[CurvePoint] = Field(default_factory=list)
    projects: list[BenchmarkProjectPoint] = Field(default_factory=list)
    trendline: Trendline | None = None


class DensityBenchmarks(BaseModel):
    dataset_name: str
    dataset_version: str | None = None
    as_of: str | None = None
    is_sample: bool = False
    subject_units_per_acre: float | None = None
    city_median_units_per_acre: float | None = None
    scopes: list[BenchmarkScope] = Field(default_factory=list)


class SiteMetrics(BaseModel):
    project_id: str
    project_name: str | None = None
    city: str | None = None
    locality: str | None = None
    micromarket: str | None = None

    parcel_area_acres: MetricValue
    parcel_area_sq_m: MetricValue
    total_units: MetricValue
    units_per_acre: MetricValue

    open_area_percent: MetricValue
    open_area_sq_m: MetricValue
    green_area_percent: MetricValue
    green_area_sq_m: MetricValue
    building_footprint_percent: MetricValue
    building_footprint_sq_m: MetricValue

    sanctioned_fsi: MetricValue
    built_up_area_sq_m: MetricValue

    land_per_home_sq_m: MetricValue
    open_realm_per_home_sq_m: MetricValue
    green_per_home_sq_m: MetricValue
    undivided_land_share_sq_m: MetricValue
    clubhouse_area_sq_m: MetricValue

    residential_block_count: MetricValue
    homes_per_block: MetricValue
    homes_per_floor_min: MetricValue
    homes_per_floor_max: MetricValue
    outdoor_space_count: MetricValue
    declared_amenity_count: MetricValue

    unit_mix: list[UnitMixRow] = Field(default_factory=list)
    allocation_nodes: list[FlowNode] = Field(default_factory=list)
    allocation_links: list[FlowLink] = Field(default_factory=list)
    density_benchmarks: DensityBenchmarks | None = None

    constants: dict[str, float] = Field(default_factory=dict)
