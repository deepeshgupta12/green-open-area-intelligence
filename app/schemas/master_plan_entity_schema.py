"""Spatially located master-plan entities.

Everything here is resolution independent: boxes and centres are fractions of
the full image (0.0 to 1.0), so the frontend can overlay them on the original
upload, the normalised PNG, or any scaled copy.
"""

from typing import Literal

from pydantic import BaseModel, Field


EntityGroup = Literal[
    "structure",
    "circulation",
    "amenity",
    "landscape",
    "water",
    "annotation",
]

# Canonical entity vocabulary. Keep this in sync with ENTITY_TYPE_GROUPS in
# app/services/master_plan_entity_extractor.py.
ENTITY_TYPES: tuple[str, ...] = (
    # structures
    "residential_block",
    "commercial_block",
    "clubhouse",
    "security_cabin",
    "utility_yard",
    "entry_exit_gate",
    # circulation
    "external_road",
    "internal_road",
    "driveway",
    "walkway_pathway",
    "parking",
    # amenities
    "swimming_pool",
    "water_feature",
    "sports_court",
    "kids_play_area",
    "outdoor_game",
    "outdoor_gym",
    "plaza",
    "pet_park",
    "working_pods",
    "other_feature",
    # landscape
    "lawn_garden",
    "tree_canopy_buffer",
    # annotations
    "legend_marker",
    "legend_block",
    "title_block",
    "north_arrow",
    "site_boundary",
)


class EntityBox(BaseModel):
    """Axis-aligned box as fractions of image width and height."""

    x_min: float = Field(ge=0.0, le=1.0)
    y_min: float = Field(ge=0.0, le=1.0)
    x_max: float = Field(ge=0.0, le=1.0)
    y_max: float = Field(ge=0.0, le=1.0)

    @property
    def width(self) -> float:
        return max(0.0, self.x_max - self.x_min)

    @property
    def height(self) -> float:
        return max(0.0, self.y_max - self.y_min)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x_min + self.x_max) / 2, (self.y_min + self.y_max) / 2)


class MasterPlanEntity(BaseModel):
    entity_id: str
    entity_type: str
    entity_group: EntityGroup
    label: str
    legend_code: str | None = None
    legend_label: str | None = None
    category_key: str | None = None

    box: EntityBox
    center_x: float
    center_y: float
    relative_area: float = Field(
        description="Box area as a fraction of the full image area. Directional only."
    )

    confidence_label: str = "Medium"
    located_by: Literal["layout_model", "legend_marker", "both"] = Field(
        default="layout_model",
        description=(
            "layout_model: box drawn by the vision pass; legend_marker: position taken "
            "from a numbered legend circle; both: the two agreed and were merged."
        ),
    )
    attributes: dict[str, str] = Field(default_factory=dict)
    adjacent_to: list[str] = Field(default_factory=list)

    nearest_residential_block: str | None = None
    nearest_residential_distance: float | None = Field(
        default=None,
        description="Centre-to-centre distance as a fraction of the image diagonal.",
    )


class LegendEntry(BaseModel):
    code: str
    label: str
    normalized_label: str
    category_key: str | None = None
    located_on_plan: bool = False
    marker_count: int = 0


class ExternalRoad(BaseModel):
    label: str
    width_text: str | None = None
    side: str | None = None


SHAPE_CLASSES: tuple[str, ...] = (
    "rectangular",
    "square",
    "l_shaped",
    "elongated",
    "triangular",
    "irregular",
    "other",
)


class SiteSummary(BaseModel):
    shape_class: str | None = Field(
        default=None, description="One of SHAPE_CLASSES; a key, never prose."
    )
    north_arrow_present: bool = False
    external_roads: list[ExternalRoad] = Field(default_factory=list)
    entry_exit_count: int = 0
    residential_block_labels: list[str] = Field(default_factory=list)
    commercial_block_count: int = 0
    parking_cluster_count: int = 0
    utility_yard_count: int = 0


class ResidentialBlockProximity(BaseModel):
    block_label: str
    nearby_amenities: list[str] = Field(default_factory=list)
    nearby_green: list[str] = Field(default_factory=list)
    near_entry_gate: bool = False
    near_external_road: bool = False
    near_utility_yard: bool = False
    near_parking: bool = False
    nearest_amenity_distance: float | None = Field(
        default=None, description="Fraction of the image diagonal to the closest amenity or water feature."
    )


class Diagnostic(BaseModel):
    """A machine-readable processing note; the frontend owns the wording."""

    code: str
    count: int = 0
    items: list[str] = Field(default_factory=list)


class MasterPlanEntityMap(BaseModel):
    project_id: str | None = None
    project_name: str | None = None

    image_width: int
    image_height: int
    coordinate_system: Literal["fraction_of_image"] = "fraction_of_image"

    extraction_confidence_label: str = "Medium"
    site: SiteSummary = Field(default_factory=SiteSummary)
    legend: list[LegendEntry] = Field(default_factory=list)
    entities: list[MasterPlanEntity] = Field(default_factory=list)
    entity_counts: dict[str, int] = Field(default_factory=dict)
    group_counts: dict[str, int] = Field(default_factory=dict)
    block_proximity: list[ResidentialBlockProximity] = Field(default_factory=list)

    diagnostics: list[Diagnostic] = Field(default_factory=list)
