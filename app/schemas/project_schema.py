from typing import Any

from pydantic import BaseModel, Field


class ReraRecord(BaseModel):
    rera_project_name: str | None = None
    rera_project_number: str | None = None
    qr_link: str | None = None
    launch_date: str | None = None
    completion_date: str | None = None


class AmenityRecord(BaseModel):
    name: str
    category: str | None = None
    amenity_id: str | None = None


class WowFactorRecord(BaseModel):
    text: str


class UnitVariant(BaseModel):
    category: str | None = None
    unit_name: str | None = None
    bedroom_count: str | None = None
    unit_cat_name: str | None = None
    unit_cat_type: str | None = None
    unit_size: str | None = None
    carpet_area: str | None = None
    price_text: str | None = None


class MasterPlanMetadata(BaseModel):
    image_id: str | None = None
    name: str | None = None
    image_type: str | None = None
    path: str | None = None
    url: str | None = None
    alt_tag: str | None = None
    description_html: str | None = None


class ParsedProjectMetadata(BaseModel):
    project_id: str
    project_name: str | None = None

    city: str | None = None
    locality: str | None = None
    micromarket: str | None = None
    location: str | None = None

    latitude: float | None = None
    longitude: float | None = None

    project_area_acres: float | None = None
    total_units: int | None = None
    project_category: str | None = None
    category_type: str | None = None
    status: str | None = None

    developer_name: str | None = None
    developer_id: str | None = None
    developer_grade: str | None = None
    developer_grade_category: str | None = None

    price_text: str | None = None
    low_cost_text: str | None = None
    high_cost_text: str | None = None
    sizes: str | None = None

    brochure_url: str | None = None
    project_url: str | None = None
    last_update_date: str | None = None

    rera_records: list[ReraRecord] = Field(default_factory=list)
    amenities: list[AmenityRecord] = Field(default_factory=list)
    green_amenity_signals: list[str] = Field(default_factory=list)
    open_space_signals: list[str] = Field(default_factory=list)
    wow_factors: list[WowFactorRecord] = Field(default_factory=list)
    unit_mix: list[UnitVariant] = Field(default_factory=list)
    master_plan: MasterPlanMetadata | None = None

    source_flags: dict[str, bool] = Field(default_factory=dict)
    raw_signal_summary: dict[str, Any] = Field(default_factory=dict)
