"""Spatial entity extraction for master plans.

Three kinds of Gemini vision call, run in parallel, feed one
:class:`MasterPlanEntityMap`:

* **Structures call** (full image): the salient physical features with a
  bounding box each: wings/towers, commercial block, clubhouse, gates, pools,
  courts, large lawns, parking clusters, utility yards.
* **Site call** (full image): the legend transcribed as printed, site-level
  facts (shape, external roads, entry count) and the drawing annotations
  (title, legend block, north arrow, boundary, tree belts, external roads).
* **Marker calls** (one per image tile): the small numbered circles that key
  features to the legend. They are too small to localise on a full-size plan,
  so the image is tiled with overlap and results are mapped back.

Structured output (``response_schema``) is enforced on every call so the
model cannot return malformed JSON, and thinking is disabled because Gemini
2.5 localises better without it.

The numbered markers are the most reliable location evidence on a master
plan, so :func:`parse_master_plan_entity_payload` treats them as ground
truth: a marker whose code matches a legend row becomes that feature at that
spot, a drawing box that agrees with a marker is merged with it, and a
drawing box that contradicts the markers is discarded. Several cheap filters
remove the model's known failure modes (identical boxes, evenly spaced
runs, oversized boxes, circles on blank paper). The parser then adds the
derived metadata the frontend hover layer needs: legend linkage, category
keys, nearest residential block, per-block proximity summaries and counts.

All coordinates leave this module as fractions of the image (0.0 to 1.0).
"""

from __future__ import annotations

import io
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import numpy as np
from google.genai import types
from PIL import Image
from pydantic import BaseModel, Field

from app.config import get_settings
from app.schemas.image_schema import ImageMetadata
from app.schemas.master_plan_entity_schema import (
    ENTITY_TYPES,
    SHAPE_CLASSES,
    Diagnostic,
    EntityBox,
    EntityGroup,
    ExternalRoad,
    LegendEntry,
    MasterPlanEntity,
    MasterPlanEntityMap,
    ResidentialBlockProximity,
    SiteSummary,
)
from app.schemas.project_schema import ParsedProjectMetadata
from app.services.master_plan_understanding_engine import _infer_category as infer_category_key
from app.utils.gemini_client import MISSING_CREDENTIALS_MESSAGE, get_gemini_client
from app.utils.llm_utils import extract_json_from_text, load_image_part_for_gemini


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

ENTITY_TYPE_GROUPS: dict[str, EntityGroup] = {
    "residential_block": "structure",
    "commercial_block": "structure",
    "clubhouse": "structure",
    "security_cabin": "structure",
    "utility_yard": "structure",
    "entry_exit_gate": "structure",
    "external_road": "circulation",
    "internal_road": "circulation",
    "driveway": "circulation",
    "walkway_pathway": "circulation",
    "parking": "circulation",
    "swimming_pool": "water",
    "water_feature": "water",
    "sports_court": "amenity",
    "kids_play_area": "amenity",
    "outdoor_game": "amenity",
    "outdoor_gym": "amenity",
    "plaza": "amenity",
    "pet_park": "amenity",
    "working_pods": "amenity",
    "other_feature": "amenity",
    "lawn_garden": "landscape",
    "tree_canopy_buffer": "landscape",
    "legend_marker": "annotation",
    "legend_block": "annotation",
    "title_block": "annotation",
    "north_arrow": "annotation",
    "site_boundary": "annotation",
}

assert set(ENTITY_TYPE_GROUPS) == set(ENTITY_TYPES), "entity vocabulary drifted"

# What each focused call is allowed to return.
STRUCTURE_ENTITY_TYPES: tuple[str, ...] = (
    "residential_block",
    "commercial_block",
    "clubhouse",
    "security_cabin",
    "utility_yard",
    "entry_exit_gate",
    "parking",
    "driveway",
    "internal_road",
    "swimming_pool",
    "water_feature",
    "sports_court",
    "kids_play_area",
    "lawn_garden",
    "plaza",
)
SITE_ENTITY_TYPES: tuple[str, ...] = (
    "external_road",
    "tree_canopy_buffer",
    "site_boundary",
    "north_arrow",
    "legend_block",
    "title_block",
)

# Default category for the nine-category comparison engine when the label
# itself does not reveal one.
TYPE_DEFAULT_CATEGORY: dict[str, str | None] = {
    "residential_block": "built_density",
    "commercial_block": "built_density",
    "clubhouse": "amenity_richness",
    "security_cabin": "access_circulation",
    "utility_yard": None,
    "entry_exit_gate": "access_circulation",
    "external_road": "access_circulation",
    "internal_road": "access_circulation",
    "driveway": "access_circulation",
    "walkway_pathway": "access_circulation",
    "parking": "access_circulation",
    "swimming_pool": "water_leisure",
    "water_feature": "water_leisure",
    "sports_court": "sports_active_lifestyle",
    "kids_play_area": "family_community",
    "outdoor_game": "family_community",
    "outdoor_gym": "sports_active_lifestyle",
    "plaza": "open_space",
    "pet_park": "family_community",
    "working_pods": "amenity_richness",
    "other_feature": "amenity_richness",
    "lawn_garden": "green_landscape",
    "tree_canopy_buffer": "green_landscape",
    "legend_marker": None,
    "legend_block": None,
    "title_block": None,
    "north_arrow": None,
    "site_boundary": None,
}

# Ordered: the first alias found at the start of a word wins, so keep specific
# words before generic ones. Used for model type strings AND legend labels.
TYPE_ALIASES: tuple[tuple[str, str], ...] = (
    ("legend marker", "legend_marker"),
    ("marker", "legend_marker"),
    ("legend", "legend_block"),
    ("title", "title_block"),
    ("north", "north_arrow"),
    ("compass", "north_arrow"),
    ("boundary", "site_boundary"),
    ("security", "security_cabin"),
    ("cabin", "security_cabin"),
    ("plaza", "plaza"),
    ("gate", "entry_exit_gate"),
    ("entry", "entry_exit_gate"),
    ("exit", "entry_exit_gate"),
    ("dg", "utility_yard"),
    ("transformer", "utility_yard"),
    ("utility", "utility_yard"),
    ("stp", "utility_yard"),
    ("substation", "utility_yard"),
    ("commercial", "commercial_block"),
    ("retail", "commercial_block"),
    ("club", "clubhouse"),
    ("residential", "residential_block"),
    ("tower", "residential_block"),
    ("wing", "residential_block"),
    ("building", "residential_block"),
    ("block", "residential_block"),
    ("swimming", "swimming_pool"),
    ("pool", "swimming_pool"),
    ("water", "water_feature"),
    ("cascad", "water_feature"),
    ("fountain", "water_feature"),
    ("gym", "outdoor_gym"),
    ("fitness", "outdoor_gym"),
    ("court", "sports_court"),
    ("sport", "sports_court"),
    ("rink", "sports_court"),
    ("skating", "sports_court"),
    ("cricket", "sports_court"),
    ("net", "sports_court"),
    ("kids", "kids_play_area"),
    ("children", "kids_play_area"),
    ("play", "kids_play_area"),
    ("tot", "kids_play_area"),
    ("game", "outdoor_game"),
    ("ludo", "outdoor_game"),
    ("chess", "outdoor_game"),
    ("snake", "outdoor_game"),
    ("golf", "outdoor_game"),
    ("obstacle", "outdoor_game"),
    ("nine square", "outdoor_game"),
    ("hopscotch", "outdoor_game"),
    ("pet", "pet_park"),
    ("dog", "pet_park"),
    ("pod", "working_pods"),
    ("work", "working_pods"),
    ("lawn", "lawn_garden"),
    ("garden", "lawn_garden"),
    ("green", "lawn_garden"),
    ("orchard", "lawn_garden"),
    ("tree", "tree_canopy_buffer"),
    ("canopy", "tree_canopy_buffer"),
    ("buffer", "tree_canopy_buffer"),
    ("parking", "parking"),
    ("driveway", "driveway"),
    ("drop", "driveway"),
    ("external", "external_road"),
    ("highway", "external_road"),
    ("wide road", "external_road"),
    ("walk", "walkway_pathway"),
    ("path", "walkway_pathway"),
    ("trail", "walkway_pathway"),
    ("road", "internal_road"),
)

# Long runs of one type are where the model starts inventing pattern
# coordinates, so repetitive types are capped (largest boxes kept).
TYPE_CAPS: dict[str, int] = {
    "tree_canopy_buffer": 6,
    "walkway_pathway": 10,
    "internal_road": 6,
    "parking": 16,
    "lawn_garden": 12,
}

# Boxes above this share of the image are not a feature, except for the few
# types that legitimately span the drawing. Some types have a tighter cap:
# a tree belt is a strip, a pool is a pool, never a quarter of the plan.
MAX_RELATIVE_AREA = 0.35
AREA_EXEMPT_TYPES = {"site_boundary", "external_road", "legend_block"}
TYPE_MAX_AREA: dict[str, float] = {
    "tree_canopy_buffer": 0.06,
    "lawn_garden": 0.08,
    "parking": 0.05,
    "plaza": 0.04,
    "sports_court": 0.04,
    "swimming_pool": 0.04,
    "water_feature": 0.04,
    "kids_play_area": 0.03,
    "outdoor_gym": 0.02,
    "outdoor_game": 0.02,
    "utility_yard": 0.02,
    "entry_exit_gate": 0.015,
    "security_cabin": 0.01,
    "driveway": 0.15,
    "internal_road": 0.30,
}

# A residential footprint is never thinner than this on either side; boxes
# below it are the printed wing label, not the building.
WING_MIN_SIDE = 0.025
# Two wings whose boxes overlap this much cannot both be right.
WING_OVERLAP_IOU = 0.30
# Placeholder boxes the model emits in pairs are tiny; real neighbouring
# features that happen to share a size are not.
CROSS_TYPE_RUN_MIN = 2
CROSS_TYPE_TINY_SIDE = 0.03
MARKER_MAX_OUTPUT_TOKENS = 8192
SITE_MAX_OUTPUT_TOKENS = 8192
MAX_WING_RECOVERIES = 3
MAX_MARKER_RECOVERY_CODES = 12
# A retry after a malformed response runs warmer: at temperature 0 the model
# tends to reproduce the same repetition loop.
RETRY_TEMPERATURE = 0.25
WIDE_IMAGE_ASPECT = 1.3

# Distances are fractions of the image diagonal; pads are fractions of the image.
PROXIMITY_RADIUS = 0.18
ADJACENCY_RADIUS = 0.12
MARKER_MATCH_PAD = 0.03
MIN_BOX_SIDE = 0.003
DUPLICATE_IOU = 0.80
# Two detections of one numbered circle (overlapping tiles, or the same label
# twice) land within this centre distance, as a fraction of the image.
MARKER_DUPLICATE_DISTANCE = 0.015
COLLAPSED_BOX_MIN_GROUP = 2
CALL_ATTEMPTS = 2
PATTERN_RUN_MIN = 3
PATTERN_STEP_TOLERANCE = 0.01
MARKER_FEATURE_MIN_SIDE = 0.022
MARKER_INK_MIN_FRACTION = 0.08
MAX_STRUCTURE_ENTITIES = 30
MAX_SITE_ENTITIES = 12
MAX_MARKERS_PER_TILE = 60
MARKER_TILE_GRID = (2, 2)
MARKER_TILE_OVERLAP = 0.08
MAX_OUTPUT_TOKENS = 16384


# --------------------------------------------------------------------------- #
# Gemini structured-output contracts
# --------------------------------------------------------------------------- #

StructureTypeEnum = Enum(  # type: ignore[misc]
    "StructureTypeEnum", {name.upper(): name for name in STRUCTURE_ENTITY_TYPES}, type=str
)
SiteTypeEnum = Enum(  # type: ignore[misc]
    "SiteTypeEnum", {name.upper(): name for name in SITE_ENTITY_TYPES}, type=str
)

BOX_DESCRIPTION = "[ymin, xmin, ymax, xmax] as integers on a 0-1000 scale of this image."


class GeminiAttribute(BaseModel):
    key: str
    value: str


class GeminiStructureEntity(BaseModel):
    entity_type: StructureTypeEnum
    label: str
    legend_code: str | None = None
    box_2d: list[int] = Field(description=BOX_DESCRIPTION)
    confidence: Literal["High", "Medium", "Low"] = "Medium"
    attributes: list[GeminiAttribute] = Field(default_factory=list)
    adjacent_to: list[str] = Field(default_factory=list)


class GeminiStructureExtraction(BaseModel):
    entities: list[GeminiStructureEntity] = Field(default_factory=list)


class GeminiWing(BaseModel):
    label: str
    wing: str | None = Field(default=None, description="The wing letter or tower number as printed.")
    box_2d: list[int] = Field(description=BOX_DESCRIPTION)
    confidence: Literal["High", "Medium", "Low"] = "Medium"


class GeminiWingExtraction(BaseModel):
    wings: list[GeminiWing] = Field(default_factory=list)


class GeminiWingLabel(BaseModel):
    """What a crop of one chosen wing box actually says."""

    label: str | None = Field(default=None, description="Building name printed in the crop, e.g. 'Wing - B'.")
    wing: str | None = Field(default=None, description="The letter or number alone.")


class GeminiSiteEntity(BaseModel):
    entity_type: SiteTypeEnum
    label: str
    box_2d: list[int] = Field(description=BOX_DESCRIPTION)
    attributes: list[GeminiAttribute] = Field(default_factory=list)


class GeminiLegendItem(BaseModel):
    code: str
    label: str


class GeminiExternalRoad(BaseModel):
    label: str
    width_text: str | None = None
    side: str | None = None


ShapeClassEnum = Enum(  # type: ignore[misc]
    "ShapeClassEnum", {name.upper(): name for name in SHAPE_CLASSES}, type=str
)


class GeminiSite(BaseModel):
    shape_class: ShapeClassEnum | None = None
    north_arrow_present: bool = False
    external_roads: list[GeminiExternalRoad] = Field(default_factory=list)
    entry_exit_count: int = 0


class GeminiSiteExtraction(BaseModel):
    extraction_confidence_label: Literal["High", "Medium", "Low"] = "Medium"
    site: GeminiSite
    legend_items: list[GeminiLegendItem] = Field(default_factory=list)
    entities: list[GeminiSiteEntity] = Field(default_factory=list)


class GeminiLegendExtraction(BaseModel):
    """Fallback contract: just the legend, when the full site call fails."""

    legend_items: list[GeminiLegendItem] = Field(default_factory=list)


class GeminiMarker(BaseModel):
    legend_code: str
    box_2d: list[int] = Field(description=BOX_DESCRIPTION)


class GeminiMarkerExtraction(BaseModel):
    markers: list[GeminiMarker] = Field(default_factory=list)


def _generation_config(
    schema: type[BaseModel], temperature: float = 0.0, max_output_tokens: int = MAX_OUTPUT_TOKENS
) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=schema,
        max_output_tokens=max_output_tokens,
        # Gemini 2.5 localises better with thinking off (Google's spatial
        # understanding guidance), and it is much faster.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def extract_master_plan_entities(
    image_metadata: ImageMetadata,
    project: ParsedProjectMetadata | None = None,
) -> MasterPlanEntityMap:
    """Run the structure, site and marker calls and return a derived entity map."""
    settings = get_settings()
    if not settings.gemini_configured:
        raise ValueError(f"{MISSING_CREDENTIALS_MESSAGE} Cannot extract master-plan entities.")

    image_path = Path(image_metadata.normalized_image_path or image_metadata.image_path)
    client = get_gemini_client(settings)
    model = settings.gemini_vision_model

    with Image.open(image_path) as source:
        image = source.convert("RGB")
    width, height = image.size

    full_image_part = load_image_part_for_gemini(image_path)
    # Wide plans pack more markers per tile; split them finer so no tile
    # overruns the output budget.
    cols = 3 if width / max(height, 1) >= WIDE_IMAGE_ASPECT else MARKER_TILE_GRID[0]
    tiles = build_tile_specs(cols, MARKER_TILE_GRID[1], MARKER_TILE_OVERLAP)

    def run_call(
        prompt: str,
        part: types.Part,
        schema: type[BaseModel],
        temperature: float = 0.0,
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(CALL_ATTEMPTS):
            attempt_temperature = temperature if attempt == 0 else max(temperature, RETRY_TEMPERATURE)
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[prompt, part],
                    config=_generation_config(schema, temperature=attempt_temperature, max_output_tokens=max_output_tokens),
                )
                return parse_model_json(response.text or "{}", schema)
            except Exception as exc:  # noqa: BLE001 - retried once, then surfaced
                last_error = exc
        assert last_error is not None
        raise last_error

    def run_structures() -> tuple[dict[str, Any], dict[str, Any] | None]:
        try:
            return run_call(build_structure_prompt(project), full_image_part, GeminiStructureExtraction), None
        except Exception as exc:  # noqa: BLE001 - wings and markers still carry the map
            return {"entities": []}, {"code": "structure_pass_failed", "count": 1, "items": [str(exc)[:160]]}

    def run_site() -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Site facts plus legend; falls back to a legend-only call."""
        try:
            return run_call(build_site_prompt(), full_image_part, GeminiSiteExtraction, max_output_tokens=SITE_MAX_OUTPUT_TOKENS), None
        except Exception as site_exc:  # noqa: BLE001
            try:
                legend_payload = run_call(
                    build_legend_prompt(), full_image_part, GeminiLegendExtraction, max_output_tokens=SITE_MAX_OUTPUT_TOKENS
                )
                return (
                    {"site": {}, "legend_items": legend_payload.get("legend_items", []), "entities": []},
                    {"code": "site_pass_failed", "count": 1, "items": [str(site_exc)[:160]]},
                )
            except Exception as legend_exc:  # noqa: BLE001
                return (
                    {"site": {}, "legend_items": [], "entities": []},
                    {"code": "legend_pass_failed", "count": 1, "items": [str(site_exc)[:120], str(legend_exc)[:120]]},
                )

    def run_markers(tile: tuple[float, float, float, float]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        try:
            payload = run_call(
                build_marker_prompt(),
                _tile_part(image, tile),
                GeminiMarkerExtraction,
                max_output_tokens=MARKER_MAX_OUTPUT_TOKENS,
            )
            return map_markers_to_full_image(payload.get("markers", []), tile), None
        except Exception as exc:  # noqa: BLE001 - a lost tile must not sink the run
            return [], {"code": "marker_tile_failed", "count": 1, "items": [str(exc)[:160]]}

    def run_wings() -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Dedicated wing pass; re-asked once if the boxes look fabricated."""
        best: list[dict[str, Any]] = []
        diagnostic: dict[str, Any] | None = None
        for attempt, temperature in enumerate((0.0, 0.3)):
            try:
                payload = run_call(build_wing_prompt(), full_image_part, GeminiWingExtraction, temperature)
            except Exception as exc:  # noqa: BLE001 - structures call still has wings as fallback
                return best, {"code": "wing_pass_failed", "count": 1, "items": [str(exc)[:160]]}
            candidates = wings_to_entities(payload.get("wings", []))
            survivors = count_credible_wings(candidates)
            if survivors > count_credible_wings(best):
                best = candidates
            if candidates and survivors >= max(1, len(candidates) // 2):
                break
            if attempt == 0:
                diagnostic = {"code": "wing_pass_rerun", "count": 1}
        return best, diagnostic

    with ThreadPoolExecutor(max_workers=3 + len(tiles)) as pool:
        structure_future = pool.submit(run_structures)
        site_future = pool.submit(run_site)
        wings_future = pool.submit(run_wings)
        marker_futures = [pool.submit(run_markers, tile) for tile in tiles]

        structure_payload, structure_diagnostic = structure_future.result()
        site_payload, site_diagnostic = site_future.result()
        wing_entities, wing_diagnostic = wings_future.result()
        marker_results = [future.result() for future in marker_futures]

    marker_entities: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = [
        item for item in (structure_diagnostic, site_diagnostic, wing_diagnostic) if item
    ]
    for markers, diagnostic in marker_results:
        marker_entities.extend(markers)
        if diagnostic:
            diagnostics.append(diagnostic)

    if not structure_payload.get("entities") and not wing_entities and not marker_entities:
        failures = "; ".join(str(item.get("items", [""])[0]) for item in diagnostics if item.get("items"))
        raise RuntimeError(f"Every Gemini pass failed for this master plan: {failures or 'no detail'}")

    structure_entities = merge_structure_and_wings(
        list(structure_payload.get("entities", [])), wing_entities
    )

    # The wing passes sometimes shuffle names between footprints. Reading the
    # name printed inside each chosen box is cheap and settles it.
    wing_raws = [raw for raw in structure_entities if normalize_entity_type(raw.get("entity_type")) == "residential_block"]
    if wing_raws:
        def read_wing_label(raw: dict[str, Any]) -> str | None:
            box = _box_from_payload(raw.get("box_2d"))
            if box is None:
                return None
            try:
                payload = run_call(
                    build_wing_label_prompt(),
                    _crop_part(image, box, pad=0.15),
                    GeminiWingLabel,
                    max_output_tokens=256,
                )
            except Exception:  # noqa: BLE001 - an unreadable crop just stays unverified
                return None
            return _clean_text(payload.get("label")) or _clean_text(payload.get("wing")) or None

        with ThreadPoolExecutor(max_workers=min(8, len(wing_raws))) as pool:
            printed = list(pool.map(read_wing_label, wing_raws))
        wing_raws, wing_label_diagnostic = reconcile_wing_labels(wing_raws, printed)
        if wing_label_diagnostic:
            diagnostics.append(wing_label_diagnostic)

        # A wing missing from an otherwise sequential run (A..H, 1..N) is
        # almost always drawn; ask for it by name and verify the crop.
        missing = missing_wing_keys([wing_key(raw.get("label")) for raw in wing_raws])[:MAX_WING_RECOVERIES]
        if missing:
            sample_label = str(wing_raws[0].get("label") or "Wing - A")

            def locate_wing(key: str) -> dict[str, Any] | None:
                label = _format_wing_label_like(sample_label, key)
                try:
                    payload = run_call(build_wing_locate_prompt(label), full_image_part, GeminiWingExtraction)
                except Exception:  # noqa: BLE001
                    return None
                candidates = [
                    raw for raw in wings_to_entities(payload.get("wings", []))
                    if (box := _box_from_payload(raw.get("box_2d"))) is not None and is_credible_wing_box(box)
                ]
                if not candidates:
                    return None
                candidate = {**candidates[0], "label": label, "attributes": [{"key": "wing", "value": key.upper()}]}
                return candidate if wing_key(read_wing_label(candidate)) == key else None

            with ThreadPoolExecutor(max_workers=len(missing)) as pool:
                recovered = [raw for raw in pool.map(locate_wing, missing) if raw is not None]
            recovered = [
                raw for raw in recovered
                if all(_iou(_box_from_payload(raw["box_2d"]), _box_from_payload(other["box_2d"])) <= WING_OVERLAP_IOU for other in wing_raws)  # type: ignore[arg-type]
            ]
            wing_raws.extend(recovered)
            diagnostics.append({
                "code": "wing_recovery_pass",
                "count": len(recovered),
                "items": [f"searched:{','.join(missing)}", f"recovered:{len(recovered)}"],
            })

        structure_entities = [
            raw for raw in structure_entities if normalize_entity_type(raw.get("entity_type")) != "residential_block"
        ] + wing_raws

    # The model occasionally hallucinates circles on blank paper. A real marker
    # is a filled, numbered disc on top of the drawing, so demand some ink.
    on_drawing = [marker for marker in marker_entities if marker_has_ink(image, marker["box_2d"])]
    phantom = len(marker_entities) - len(on_drawing)
    if phantom:
        diagnostics.append({"code": "phantom_markers_discarded", "count": phantom})

    def build_payload(markers: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "extraction_confidence_label": site_payload.get("extraction_confidence_label"),
            "site": site_payload.get("site") or {},
            "legend_items": site_payload.get("legend_items", []),
            "entities": structure_entities + list(site_payload.get("entities", [])) + markers,
            "diagnostics": diagnostics,
        }

    def parse(markers: list[dict[str, Any]]) -> MasterPlanEntityMap:
        return parse_master_plan_entity_payload(
            build_payload(markers),
            image_width=width,
            image_height=height,
            project_id=project.project_id if project else None,
            project_name=project.project_name if project else None,
        )

    entity_map = parse(on_drawing)

    # Legend rows still unlocated get one targeted re-scan of the tiles. Naming
    # the codes keeps the model from inventing circles and keeps lists short.
    unlocated = [item.code for item in entity_map.legend if not item.located_on_plan][:MAX_MARKER_RECOVERY_CODES]
    if unlocated:
        def run_targeted_markers(tile: tuple[float, float, float, float]) -> list[dict[str, Any]]:
            try:
                payload = run_call(
                    build_targeted_marker_prompt(unlocated),
                    _tile_part(image, tile),
                    GeminiMarkerExtraction,
                    max_output_tokens=MARKER_MAX_OUTPUT_TOKENS,
                )
            except Exception:  # noqa: BLE001 - recovery is best effort
                return []
            wanted = {_normalize_code(code) for code in unlocated}
            return [
                marker
                for marker in map_markers_to_full_image(payload.get("markers", []), tile)
                if _normalize_code(marker.get("legend_code")) in wanted and marker_has_ink(image, marker["box_2d"])
            ]

        with ThreadPoolExecutor(max_workers=len(tiles)) as pool:
            recovered_markers = [marker for batch in pool.map(run_targeted_markers, tiles) for marker in batch]
        diagnostics.append({
            "code": "marker_recovery_pass",
            "count": len(recovered_markers),
            "items": unlocated,
        })
        if recovered_markers:
            entity_map = parse(on_drawing + recovered_markers)

    return entity_map


def build_structure_prompt(project: ParsedProjectMetadata | None = None) -> str:
    seed: dict[str, Any] = {}
    if project is not None:
        seed = {
            "project_name": project.project_name,
            "datacenter_amenities": [item.name for item in project.amenities][:40],
        }

    return f"""
Detect the main physical features drawn on this real-estate master plan. Output a JSON
object whose "entities" list has, for each feature, its 2D bounding box in "box_2d" as
[ymin, xmin, ymax, xmax] on a 0-1000 scale, a short "label" (the printed name when there
is one) and one "entity_type" from: {", ".join(STRUCTURE_ENTITY_TYPES)}

Rules:
- Box each feature tightly around the feature itself. Every box must be distinct; never
  reuse one box for two features and never place boxes in an invented regular pattern.
- Every residential wing or tower is its own entity. Put the printed name in "label"
  (for example "Wing - G") and add an attribute with key "wing" and the letter.
- Also box: commercial block, clubhouse, entry/exit gates, security cabin, DG yard or
  transformer, swimming pool, sports courts, large lawns, distinct parking clusters and
  the main internal driveway. If a feature carries a legend number, put it in "legend_code".
- Skip small amenities that are only identified by a numbered circle; they are located
  by a separate pass.
- Record any text printed on or beside a feature in "attributes" (for example key
  "road_width", value "12 m").
- "adjacent_to": up to 4 labels of entities that visibly touch or neighbour this one.
- Do not invent features that are not visible. Do not estimate areas or percentages.
- Return at most {MAX_STRUCTURE_ENTITIES} entities. Fewer accurate boxes beat many guesses.

Project database facts for context (may be empty):
{json.dumps(seed, ensure_ascii=False)}
""".strip()


def build_wing_prompt() -> str:
    return """
Detect every residential wing or tower drawn on this real-estate master plan. Output a
JSON object whose "wings" list has, for each building, its 2D bounding box in "box_2d"
as [ymin, xmin, ymax, xmax] on a 0-1000 scale, the printed name in "label" (for example
"Wing - G" or "Tower 3") and the letter or number alone in "wing".

Rules:
- The box must cover the WHOLE building footprint: the grey or white roof outline of the
  block as drawn from above. Do NOT box the small text label; the label only tells you
  the name, the footprint is the large shape the label sits on or beside.
- Footprints are big: typically several percent of the image on each side. A box that
  is only as tall as a line of text is wrong.
- Buildings differ in size, shape and spacing, so the boxes must differ too; never
  produce same-size boxes at a regular step.
- One entry per labelled building. Do not include the clubhouse, commercial block,
  security cabin or utility structures.
- Do not invent buildings that are not drawn.
""".strip()


_MARKER_OBJECT_RE = re.compile(
    r"\{[^{}]*?\"legend_code\"\s*:\s*\"(?P<code>[^\"]*)\"[^{}]*?\"box_2d\"\s*:\s*\[(?P<box>[^\]]*)\][^{}]*?\}"
    r"|\{[^{}]*?\"box_2d\"\s*:\s*\[(?P<box2>[^\]]*)\][^{}]*?\"legend_code\"\s*:\s*\"(?P<code2>[^\"]*)\"[^{}]*?\}"
)


def salvage_marker_objects(text: str) -> list[dict[str, Any]]:
    """Recover complete marker objects from a truncated marker response.

    A dense tile can push the model past its output budget mid-list. The
    objects before the cut are still well formed, so keep them.
    """
    markers: list[dict[str, Any]] = []
    for match in _MARKER_OBJECT_RE.finditer(text):
        code = match.group("code") or match.group("code2")
        box_text = match.group("box") or match.group("box2") or ""
        try:
            box = [int(float(part.strip())) for part in box_text.split(",") if part.strip()]
        except ValueError:
            continue
        if code is not None and len(box) == 4:
            markers.append({"legend_code": code, "box_2d": box})
    return markers


_LEGEND_OBJECT_RE = re.compile(
    r"\{[^{}]*?\"code\"\s*:\s*\"(?P<code>[^\"]{1,12})\"[^{}]*?\"label\"\s*:\s*\"(?P<label>[^\"]{1,80})\"[^{}]*?\}"
    r"|\{[^{}]*?\"label\"\s*:\s*\"(?P<label2>[^\"]{1,80})\"[^{}]*?\"code\"\s*:\s*\"(?P<code2>[^\"]{1,12})\"[^{}]*?\}"
)

MIN_SALVAGED_LEGEND_ITEMS = 3


def salvage_legend_items(text: str) -> list[dict[str, str]]:
    """Recover complete legend rows from a truncated or looping site response.

    Rows are de-duplicated by code in order of first appearance, which also
    collapses the repetition loop that caused the overrun.
    """
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _LEGEND_OBJECT_RE.finditer(text):
        code = (match.group("code") or match.group("code2") or "").strip()
        label = (match.group("label") or match.group("label2") or "").strip()
        key = _normalize_code(code)
        if not key or not label or key in seen:
            continue
        seen.add(key)
        items.append({"code": code, "label": label})
    return items


def parse_model_json(text: str, schema: type[BaseModel]) -> dict[str, Any]:
    """Parse a structured-output response, tolerating known deviations.

    Gemini occasionally answers a single-list schema with the bare list, a
    dense marker tile can be truncated mid-list, and the site call can loop on
    the legend until it overruns; all three are recovered here.
    """
    try:
        return extract_json_from_text(text)
    except ValueError:
        pass

    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        if schema is GeminiMarkerExtraction:
            salvaged = salvage_marker_objects(text)
            if salvaged:
                return {"markers": salvaged}
        if schema in (GeminiSiteExtraction, GeminiLegendExtraction):
            legend = salvage_legend_items(text)
            if len(legend) >= MIN_SALVAGED_LEGEND_ITEMS:
                return {"site": {}, "legend_items": legend, "entities": []}
        raise

    if isinstance(parsed, list):
        for name, field in schema.model_fields.items():
            if "list" in str(field.annotation):
                return {name: parsed}
    raise ValueError("Model response was neither a JSON object nor a bare list.")


def build_wing_locate_prompt(label: str) -> str:
    return (
        f"Locate the residential building labelled \"{label}\" on this real-estate master plan. "
        "Output a JSON object whose \"wings\" list has exactly one item with the building's "
        "footprint bounding box in \"box_2d\" as [ymin, xmin, ymax, xmax] on a 0-1000 scale, "
        "the printed name in \"label\" and the letter or number alone in \"wing\". Box the whole "
        "roof outline, not the text. If no building with that name is drawn, return an empty list."
    )


def build_targeted_marker_prompt(codes: list[str]) -> str:
    return (
        "This is a crop of a real-estate master plan. Find the small numbered circle markers whose "
        f"printed number is one of: {', '.join(codes)}. Output a JSON object whose \"markers\" list "
        "has, for each such circle actually drawn in this crop, its 2D bounding box in \"box_2d\" as "
        "[ymin, xmin, ymax, xmax] on a 0-1000 scale of this image and the number as \"legend_code\". "
        "Ignore every other circle and all legend text. If none of these numbers appear, return an "
        "empty list."
    )


def missing_wing_keys(keys: list[str | None]) -> list[str]:
    """Gaps inside a sequential set of wing identifiers (A..H or 1..N)."""
    present = sorted({key for key in keys if key})
    if len(present) < 2:
        return []
    if all(len(key) == 1 and key.isalpha() for key in present):
        first, last = ord(present[0]), ord(present[-1])
        return [chr(code) for code in range(first, last + 1) if chr(code) not in present]
    if all(key.isdigit() for key in present):
        numbers = sorted(int(key) for key in present)
        return [str(value) for value in range(numbers[0], numbers[-1] + 1) if value not in numbers]
    return []


def _format_wing_label_like(sample_label: str, key: str) -> str:
    """Build 'WING - F' from 'WING - A' and 'f', keeping the printed style."""
    cleaned = _clean_text(sample_label)
    match = _WING_KEY_RE.search(cleaned.lower())
    if match:
        start, end = match.span(1)
        return cleaned[:start] + key.upper() + cleaned[end:]
    return f"Wing - {key.upper()}"


def build_wing_label_prompt() -> str:
    return (
        "This crop shows one residential building from a real-estate master plan. Return the "
        "building name printed on or right beside it in \"label\" (for example \"Wing - B\" or "
        "\"Tower 3\") and the letter or number alone in \"wing\". If no building name is printed "
        "in the crop, return null for both. Return JSON only."
    )


_WING_KEY_RE = re.compile(r"(?:wing|tower|block|building|bldg)\s*[-–:.]?\s*([a-z]{1,2}|\d{1,3})\b")


def wing_key(text: str | None) -> str | None:
    """'WING - B' -> 'b', 'Tower 3' -> '3'; None when no identifier is present."""
    cleaned = _clean_text(text).lower()
    if not cleaned:
        return None
    match = _WING_KEY_RE.search(cleaned)
    if match:
        return match.group(1)
    token = re.sub(r"[^a-z0-9]", "", cleaned)
    return token if 1 <= len(token) <= 2 else None


def reconcile_wing_labels(
    wings: list[dict[str, Any]], printed: list[str | None]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Correct wing names against what is printed inside each box.

    A box whose printed name differs from its claimed name is relabelled to
    the printed one. When two boxes end up claiming the same wing, the
    verified box wins, then the relabelled, then the larger.
    """
    ranked: list[tuple[int, float, dict[str, Any]]] = []
    relabelled = 0
    for raw, seen_text in zip(wings, printed):
        claimed = wing_key(raw.get("label"))
        seen = wing_key(seen_text)
        box = _box_from_payload(raw.get("box_2d"))
        area = box.width * box.height if box else 0.0
        if seen is None:
            ranked.append((0, area, raw))
        elif seen == claimed:
            ranked.append((2, area, raw))
        else:
            relabelled += 1
            new_label = _clean_text(seen_text) if _WING_KEY_RE.search(_clean_text(seen_text).lower()) else f"Wing - {seen.upper()}"
            attributes = [item for item in (raw.get("attributes") or []) if not (isinstance(item, dict) and item.get("key") == "wing")]
            attributes.append({"key": "wing", "value": seen.upper()})
            ranked.append((1, area, {**raw, "label": new_label, "attributes": attributes}))

    chosen: dict[str, tuple[int, float, dict[str, Any]]] = {}
    unkeyed: list[dict[str, Any]] = []
    dropped = 0
    for rank, area, raw in ranked:
        key = wing_key(raw.get("label"))
        if key is None:
            unkeyed.append(raw)
            continue
        current = chosen.get(key)
        if current is None:
            chosen[key] = (rank, area, raw)
        elif (rank, area) > (current[0], current[1]):
            chosen[key] = (rank, area, raw)
            dropped += 1
        else:
            dropped += 1

    final = [raw for _, _, raw in chosen.values()] + unkeyed
    diagnostic = None
    if relabelled or dropped:
        diagnostic = {
            "code": "wing_labels_reconciled",
            "count": relabelled + dropped,
            "items": [f"relabelled:{relabelled}", f"dropped:{dropped}"],
        }
    return final, diagnostic


def wings_to_entities(wings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert the wing-pass payload into structure-call-shaped entity dicts."""
    entities: list[dict[str, Any]] = []
    for wing in wings or []:
        if not isinstance(wing, dict):
            continue
        attributes = []
        letter = _clean_text(wing.get("wing"))
        if letter:
            attributes.append({"key": "wing", "value": letter})
        entities.append(
            {
                "entity_type": "residential_block",
                "label": wing.get("label") or (f"Wing {letter}" if letter else ""),
                "box_2d": wing.get("box_2d"),
                "confidence": wing.get("confidence") or "Medium",
                "attributes": attributes,
            }
        )
    return entities


def is_credible_wing_box(box: EntityBox) -> bool:
    """A footprint-sized box, as opposed to a box around the printed label."""
    return min(box.width, box.height) >= WING_MIN_SIDE


def count_credible_wings(raw_wings: list[dict[str, Any]]) -> int:
    """How many wing boxes survive the fabrication and label-size filters."""
    built = [
        entity
        for index, raw in enumerate(raw_wings)
        if (entity := _build_entity(raw, index=index, legend_lookup={})) is not None
        and is_credible_wing_box(entity.box)
    ]
    built = _dedupe_entities(built)
    built, _ = _drop_oversized_boxes(built)
    built, _ = _drop_collapsed_boxes(built)
    built, _ = _drop_patterned_runs(built)
    return len(built)


def merge_structure_and_wings(
    structure_entities: list[dict[str, Any]], wing_entities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Combine wing candidates from both passes, one box per building.

    For each building name the footprint-sized box wins over a label-sized
    one, and among credible boxes the larger wins. Non-wing structures pass
    through untouched.
    """
    def raw_type(raw: Any) -> str | None:
        return normalize_entity_type(raw.get("entity_type")) if isinstance(raw, dict) else None

    others = [raw for raw in structure_entities if raw_type(raw) != "residential_block"]
    candidates = [raw for raw in structure_entities if raw_type(raw) == "residential_block"] + list(wing_entities)
    if not candidates:
        return structure_entities

    by_label: dict[str, list[tuple[dict[str, Any], EntityBox]]] = {}
    unnamed: list[dict[str, Any]] = []
    for raw in candidates:
        box = _box_from_payload(raw.get("box_2d"))
        if box is None:
            continue
        key = _label_key(raw.get("label"))
        if not key:
            unnamed.append(raw)
            continue
        by_label.setdefault(key, []).append((raw, box))

    def score(box: EntityBox) -> tuple[bool, float]:
        return (is_credible_wing_box(box), box.width * box.height)

    chosen: dict[str, tuple[dict[str, Any], EntityBox]] = {
        key: max(options, key=lambda item: score(item[1])) for key, options in by_label.items()
    }

    # Two wings cannot share a footprint. Where the chosen boxes overlap, swap
    # in the other pass's candidate for one of them if that resolves it.
    labels = list(chosen)
    for _ in range(len(labels)):
        swapped = False
        for index, label_a in enumerate(labels):
            for label_b in labels[index + 1:]:
                if _iou(chosen[label_a][1], chosen[label_b][1]) <= WING_OVERLAP_IOU:
                    continue
                for label in (label_b, label_a):
                    replacement = next(
                        (
                            option
                            for option in by_label[label]
                            if option[0] is not chosen[label][0]
                            and is_credible_wing_box(option[1])
                            and all(
                                _iou(option[1], chosen[other][1]) <= WING_OVERLAP_IOU
                                for other in labels
                                if other != label
                            )
                        ),
                        None,
                    )
                    if replacement is not None:
                        chosen[label] = replacement
                        swapped = True
                        break
                if swapped:
                    break
            if swapped:
                break
        if not swapped:
            break

    return others + [raw for raw, _ in chosen.values()] + unnamed


def build_site_prompt() -> str:
    return f"""
Read this real-estate master plan drawing and return a JSON object with:

1. "legend_items": the legend text block transcribed exactly as printed, one item per
   row with "code" (for example "01") and "label" (for example "Entry/Exit").
2. "site": "shape_class" (the overall plot outline, one of {", ".join(SHAPE_CLASSES)}),
   "north_arrow_present", "external_roads" (each with its printed "label", "width_text"
   such as "12 m" when printed, and the "side" of the plot it runs along) and
   "entry_exit_count" (how many entry/exit points are marked).
3. "entities": bounding boxes in "box_2d" as [ymin, xmin, ymax, xmax] on a 0-1000 scale
   for these drawing elements only: {", ".join(SITE_ENTITY_TYPES)}.
   Box the plot outline as one "site_boundary", every external road, the title block, the
   legend block, the north arrow, and at most 4 contiguous tree belts as
   "tree_canopy_buffer" (never individual trees).
4. "extraction_confidence_label": High, Medium or Low for how legible the plan is.

Do not box buildings, amenities or numbered circle markers here. Return at most
{MAX_SITE_ENTITIES} entities. List each legend row exactly once; never repeat items.
Return JSON only.
""".strip()


def build_legend_prompt() -> str:
    return (
        "Transcribe the legend text block printed on this real-estate master plan. Output a JSON "
        "object whose \"legend_items\" list has one item per legend row with \"code\" (for example "
        "\"01\") and \"label\" (for example \"Entry/Exit\") exactly as printed. List each row once, "
        "in the printed order, and stop when the legend ends. Return JSON only."
    )


def build_marker_prompt() -> str:
    return (
        "This is a crop of a real-estate master plan. Detect every small circular marker "
        "printed on the drawing that contains a legend number (for example 01, 7, 10, 24). "
        "Output a JSON object whose \"markers\" list has, for each circle, its 2D bounding box "
        "in \"box_2d\" as [ymin, xmin, ymax, xmax] on a 0-1000 scale of this image and the "
        "number printed inside as \"legend_code\". Box each circle tightly. Include a circle "
        "only if it is actually drawn on the plan and its number is readable; blank paper has "
        "no markers. Ignore the legend text rows and any wing name labels. "
        f"Return at most {MAX_MARKERS_PER_TILE} markers."
    )


def build_tile_specs(cols: int, rows: int, overlap: float) -> list[tuple[float, float, float, float]]:
    """Return (x0, y0, x1, y1) fractions for a cols x rows grid with overlap."""
    tiles: list[tuple[float, float, float, float]] = []
    tile_w = 1.0 / cols
    tile_h = 1.0 / rows
    for row in range(rows):
        for col in range(cols):
            x0 = max(0.0, col * tile_w - overlap)
            y0 = max(0.0, row * tile_h - overlap)
            x1 = min(1.0, (col + 1) * tile_w + overlap)
            y1 = min(1.0, (row + 1) * tile_h + overlap)
            tiles.append((round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)))
    return tiles


def map_markers_to_full_image(
    markers: list[dict[str, Any]], tile: tuple[float, float, float, float]
) -> list[dict[str, Any]]:
    """Convert tile-local 0-1000 boxes into full-image fractional entity payloads."""
    x0, y0, x1, y1 = tile
    span_x = x1 - x0
    span_y = y1 - y0
    mapped: list[dict[str, Any]] = []
    for marker in markers:
        if not isinstance(marker, dict):
            continue
        box = marker.get("box_2d")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            ymin, xmin, ymax, xmax = (float(value) / 1000.0 for value in box)
        except (TypeError, ValueError):
            continue
        mapped.append(
            {
                "entity_type": "legend_marker",
                "label": "",
                "legend_code": marker.get("legend_code"),
                "confidence": "Medium",
                # Fractional box; the parser detects the scale automatically.
                "box_2d": [
                    y0 + ymin * span_y,
                    x0 + xmin * span_x,
                    y0 + ymax * span_y,
                    x0 + xmax * span_x,
                ],
            }
        )
    return mapped


def marker_has_ink(image: Image.Image, box_2d: list[float]) -> bool:
    """True when the marker box sits on drawn content rather than blank paper.

    ``box_2d`` is [ymin, xmin, ymax, xmax] as fractions. The region is widened
    a little so a slightly loose box still sees the disc it should cover.
    """
    width, height = image.size
    try:
        ymin, xmin, ymax, xmax = (float(value) for value in box_2d)
    except (TypeError, ValueError):
        return False
    pad_x = max(0.004, (xmax - xmin) * 0.5)
    pad_y = max(0.004, (ymax - ymin) * 0.5)
    left = int(max(0.0, xmin - pad_x) * width)
    top = int(max(0.0, ymin - pad_y) * height)
    right = int(min(1.0, xmax + pad_x) * width)
    bottom = int(min(1.0, ymax + pad_y) * height)
    if right - left < 2 or bottom - top < 2:
        return False

    pixels = np.asarray(image.crop((left, top, right, bottom)), dtype=np.int16)
    chroma = pixels.max(axis=2) - pixels.min(axis=2)
    luminance = pixels.mean(axis=2)
    ink = (chroma > 40) | (luminance < 170)
    return float(ink.mean()) >= MARKER_INK_MIN_FRACTION


def _crop_part(image: Image.Image, box: EntityBox, *, pad: float) -> types.Part:
    """PNG part of the box region, widened by ``pad`` of the box size each side."""
    width, height = image.size
    pad_x = max(box.width * pad, 20 / width)
    pad_y = max(box.height * pad, 20 / height)
    return _tile_part(
        image,
        (
            _clamp(box.x_min - pad_x),
            _clamp(box.y_min - pad_y),
            _clamp(box.x_max + pad_x),
            _clamp(box.y_max + pad_y),
        ),
    )


def _tile_part(image: Image.Image, tile: tuple[float, float, float, float]) -> types.Part:
    width, height = image.size
    x0, y0, x1, y1 = tile
    crop = image.crop((int(x0 * width), int(y0 * height), int(x1 * width), int(y1 * height)))
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG", optimize=True)
    return types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/png")


def parse_master_plan_entity_payload(
    payload: dict[str, Any],
    *,
    image_width: int,
    image_height: int,
    project_id: str | None = None,
    project_name: str | None = None,
) -> MasterPlanEntityMap:
    """Pure transformation from the merged Gemini payload to the frontend contract."""
    diagnostics: list[Diagnostic] = [
        Diagnostic(
            code=str(item.get("code") or "note"),
            count=int(item.get("count") or 0),
            items=_clean_list(item.get("items")),
        )
        for item in payload.get("diagnostics", []) or []
        if isinstance(item, dict) and item.get("code")
    ]

    legend_lookup = _build_legend_lookup(payload.get("legend_items", []))

    raw_entities = payload.get("entities", []) or []
    entities: list[MasterPlanEntity] = []
    dropped = 0

    for index, raw in enumerate(raw_entities):
        entity = _build_entity(raw, index=index, legend_lookup=legend_lookup)
        if entity is None:
            dropped += 1
            continue
        entities.append(entity)

    entities = _dedupe_entities(entities)
    entities, mislabelled = _drop_mislabelled_roads(entities)
    entities, oversized = _drop_oversized_boxes(entities)
    entities, collapsed = _drop_collapsed_boxes(entities)
    entities, patterned = _drop_patterned_runs(entities)
    entities, contradicted = _derive_marker_features(entities, image_width=image_width, image_height=image_height)
    entities, capped = _apply_type_caps(entities)
    _attach_nearest_block(entities, image_width=image_width, image_height=image_height)

    legend = _build_legend_entries(payload.get("legend_items", []), entities)
    block_proximity = _build_block_proximity(entities, image_width=image_width, image_height=image_height)
    site = _build_site_summary(payload.get("site") or {}, entities)

    entity_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    for entity in entities:
        entity_counts[entity.entity_type] = entity_counts.get(entity.entity_type, 0) + 1
        group_counts[entity.entity_group] = group_counts.get(entity.entity_group, 0) + 1

    if dropped:
        diagnostics.append(Diagnostic(code="invalid_entities_dropped", count=dropped))
    if mislabelled:
        diagnostics.append(Diagnostic(code="road_label_boxes_discarded", count=mislabelled))
    if oversized:
        diagnostics.append(Diagnostic(code="oversized_boxes_discarded", count=oversized))
    if collapsed:
        diagnostics.append(Diagnostic(code="collapsed_boxes_discarded", count=collapsed))
    if patterned:
        diagnostics.append(Diagnostic(code="patterned_boxes_discarded", count=patterned))
    if contradicted:
        diagnostics.append(Diagnostic(code="marker_contradicted_boxes_discarded", count=contradicted))
    for entity_type, removed in capped.items():
        diagnostics.append(Diagnostic(code="type_cap_trimmed", count=removed, items=[entity_type]))

    unlocated = [item.code for item in legend if not item.located_on_plan]
    if unlocated:
        diagnostics.append(Diagnostic(code="legend_items_not_located", count=len(unlocated), items=unlocated))

    confidence = _derive_confidence(payload.get("extraction_confidence_label"), legend, entities)

    return MasterPlanEntityMap(
        project_id=project_id,
        project_name=project_name,
        image_width=image_width,
        image_height=image_height,
        extraction_confidence_label=confidence,
        site=site,
        legend=legend,
        entities=entities,
        entity_counts=dict(sorted(entity_counts.items(), key=lambda item: (-item[1], item[0]))),
        group_counts=dict(sorted(group_counts.items(), key=lambda item: (-item[1], item[0]))),
        block_proximity=block_proximity,
        diagnostics=diagnostics,
    )


# --------------------------------------------------------------------------- #
# Entity construction
# --------------------------------------------------------------------------- #


def _build_entity(
    raw: dict[str, Any],
    *,
    index: int,
    legend_lookup: dict[str, tuple[str, str]],
) -> MasterPlanEntity | None:
    if not isinstance(raw, dict):
        return None

    entity_type = normalize_entity_type(raw.get("entity_type"))
    if entity_type is None:
        return None

    box = _box_from_payload(raw.get("box_2d"))
    if box is None:
        return None
    if entity_type != "legend_marker" and (box.width < MIN_BOX_SIDE or box.height < MIN_BOX_SIDE):
        return None

    legend_code = _normalize_code(raw.get("legend_code"))
    legend_match = legend_lookup.get(legend_code) if legend_code else None
    printed_code = legend_match[0] if legend_match else (_clean_code(raw.get("legend_code")) or None)
    legend_label = legend_match[1] if legend_match else None

    located_by = str(raw.get("located_by") or "layout_model")
    if located_by not in {"layout_model", "legend_marker", "both"}:
        located_by = "layout_model"

    label = _clean_text(raw.get("label"))
    if not label and legend_label:
        label = legend_label
    if entity_type == "legend_marker":
        label = legend_label or (f"Marker {printed_code}" if printed_code else "")
    if not label:
        return None

    attributes = _attributes_from_payload(raw.get("attributes"))
    adjacent_to = _clean_list(raw.get("adjacent_to"))[:4]

    confidence = str(raw.get("confidence") or "Medium").strip().title()
    if confidence not in {"High", "Medium", "Low"}:
        confidence = "Medium"

    center_x, center_y = box.center

    return MasterPlanEntity(
        entity_id=str(raw.get("entity_id") or f"e{index + 1}"),
        entity_type=entity_type,
        entity_group=ENTITY_TYPE_GROUPS[entity_type],
        label=label,
        legend_code=str(printed_code) if printed_code else None,
        legend_label=legend_label,
        category_key=_category_for(entity_type, label, legend_label),
        box=box,
        center_x=round(center_x, 4),
        center_y=round(center_y, 4),
        relative_area=round(box.width * box.height, 5),
        confidence_label=confidence,
        located_by=located_by,  # type: ignore[arg-type]
        attributes=attributes,
        adjacent_to=adjacent_to,
    )


def normalize_entity_type(value: Any) -> str | None:
    """Map a model type string or a legend label onto the canonical vocabulary."""
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    text = re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower()).strip()
    if not text:
        return None
    if text.replace(" ", "_") in ENTITY_TYPE_GROUPS:
        return text.replace(" ", "_")
    for needle, canonical in TYPE_ALIASES:
        # Match at the start of a word so "pet" does not fire on "competition".
        if re.search(r"(?:^| )" + re.escape(needle), text):
            return canonical
    return None


def _box_from_payload(value: Any) -> EntityBox | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        y_min, x_min, y_max, x_max = (float(item) for item in value)
    except (TypeError, ValueError):
        return None

    # Accept either the 0-1000 integer convention or already-fractional values.
    scale = 1000.0 if max(abs(y_min), abs(x_min), abs(y_max), abs(x_max)) > 1.0 else 1.0
    x0, x1 = sorted((_clamp(x_min / scale), _clamp(x_max / scale)))
    y0, y1 = sorted((_clamp(y_min / scale), _clamp(y_max / scale)))
    if x1 <= x0 or y1 <= y0:
        return None
    return EntityBox(x_min=round(x0, 4), y_min=round(y0, 4), x_max=round(x1, 4), y_max=round(y1, 4))


def _attributes_from_payload(value: Any) -> dict[str, str]:
    attributes: dict[str, str] = {}
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, list):
        items = (
            (item.get("key"), item.get("value"))
            for item in value
            if isinstance(item, dict)
        )
    else:
        return attributes

    for key, item_value in items:
        clean_key = _clean_text(key)
        clean_value = _clean_text(item_value)
        if clean_key and clean_value:
            attributes[clean_key.lower().replace(" ", "_")] = clean_value
    return attributes


def _category_for(entity_type: str, label: str, legend_label: str | None) -> str | None:
    for candidate in (legend_label, label):
        if not candidate:
            continue
        inferred = infer_category_key(candidate)
        if inferred and inferred != "unknown":
            return inferred
    return TYPE_DEFAULT_CATEGORY.get(entity_type)


# --------------------------------------------------------------------------- #
# Filters for known model failure modes
# --------------------------------------------------------------------------- #


def _dedupe_entities(entities: list[MasterPlanEntity]) -> list[MasterPlanEntity]:
    kept: list[MasterPlanEntity] = []
    for entity in entities:
        duplicate = False
        for existing in kept:
            if existing.entity_type != entity.entity_type:
                continue
            if existing.entity_type == "legend_marker":
                # Overlapping tiles see the same circle twice. The two boxes
                # are tiny and rarely overlap cleanly, so compare centres.
                if (
                    _normalize_code(existing.legend_code) == _normalize_code(entity.legend_code)
                    and _centers_close(existing, entity, MARKER_DUPLICATE_DISTANCE)
                ):
                    duplicate = True
                    break
                continue
            if _iou(existing.box, entity.box) >= DUPLICATE_IOU:
                duplicate = True
                break
        if not duplicate:
            kept.append(entity)
    return kept


def _dedupe_marker_features(entities: list[MasterPlanEntity]) -> list[MasterPlanEntity]:
    """Collapse marker-derived features that repeat the same label at one spot."""
    kept: list[MasterPlanEntity] = []
    for entity in entities:
        if entity.located_by != "legend_marker":
            kept.append(entity)
            continue
        duplicate = any(
            existing.located_by == "legend_marker"
            and existing.entity_type == entity.entity_type
            and _label_key(existing.label) == _label_key(entity.label)
            and _centers_close(existing, entity, MARKER_DUPLICATE_DISTANCE)
            for existing in kept
        )
        if not duplicate:
            kept.append(entity)
    return kept


def _centers_close(a: MasterPlanEntity, b: MasterPlanEntity, tolerance: float) -> bool:
    return abs(a.center_x - b.center_x) <= tolerance and abs(a.center_y - b.center_y) <= tolerance


def _drop_mislabelled_roads(entities: list[MasterPlanEntity]) -> tuple[list[MasterPlanEntity], int]:
    """Drop internal-road boxes that merely box an external road's text label."""
    kept = [
        entity
        for entity in entities
        if not (
            entity.entity_type in {"internal_road", "driveway", "walkway_pathway"}
            and normalize_entity_type(entity.label) == "external_road"
        )
    ]
    return kept, len(entities) - len(kept)


def _drop_oversized_boxes(entities: list[MasterPlanEntity]) -> tuple[list[MasterPlanEntity], int]:
    kept = [
        entity
        for entity in entities
        if entity.entity_type in AREA_EXEMPT_TYPES
        or entity.relative_area <= TYPE_MAX_AREA.get(entity.entity_type, MAX_RELATIVE_AREA)
    ]
    return kept, len(entities) - len(kept)


def _drop_collapsed_boxes(entities: list[MasterPlanEntity]) -> tuple[list[MasterPlanEntity], int]:
    """Discard entities that reuse another feature's exact box.

    When the model runs out of real detections it keeps emitting entities with
    the last box it produced. The first entity on a box is kept; the rest of
    the group carries no location information and is dropped.
    """
    seen: dict[tuple[float, float, float, float], MasterPlanEntity] = {}
    doomed: set[int] = set()
    for entity in entities:
        if entity.entity_type == "legend_marker":
            continue
        key = (
            round(entity.box.x_min, 3),
            round(entity.box.y_min, 3),
            round(entity.box.x_max, 3),
            round(entity.box.y_max, 3),
        )
        if key in seen:
            doomed.add(id(entity))
        else:
            seen[key] = entity

    if not doomed:
        return entities, 0
    return [entity for entity in entities if id(entity) not in doomed], len(doomed)


def _drop_patterned_runs(entities: list[MasterPlanEntity]) -> tuple[list[MasterPlanEntity], int]:
    """Discard runs of same-type, same-size boxes laid out at an even step.

    Real parking bays or courts are never that regular on a stylised plan;
    the pattern is the model filling a list without looking at the drawing.
    """
    by_type: dict[str, list[MasterPlanEntity]] = {}
    for entity in entities:
        if entity.entity_type == "legend_marker":
            continue
        by_type.setdefault(entity.entity_type, []).append(entity)

    doomed: set[int] = set()

    def aligned_runs(members: list[MasterPlanEntity], minimum: int):
        """Yield (run, free_axis_values) for same-size boxes sharing an edge line."""
        by_size: dict[tuple[float, float], list[MasterPlanEntity]] = {}
        for entity in members:
            size = (round(entity.box.width, 3), round(entity.box.height, 3))
            by_size.setdefault(size, []).append(entity)
        for same_size in by_size.values():
            if len(same_size) < minimum:
                continue
            for axis_key, free_axis in (("y_min", "x_min"), ("x_min", "y_min")):
                aligned: dict[float, list[MasterPlanEntity]] = {}
                for entity in same_size:
                    aligned.setdefault(round(getattr(entity.box, axis_key), 3), []).append(entity)
                for run in aligned.values():
                    if len(run) >= minimum:
                        yield run, [getattr(e.box, free_axis) for e in run]

    # Same type: real bays or courts can line up, so also demand an even step.
    for members in by_type.values():
        for run, positions in aligned_runs(members, PATTERN_RUN_MIN):
            if _evenly_spaced(positions):
                doomed.update(id(entity) for entity in run)

    # Different types sharing one exact size and one edge line never happens
    # on a real drawing; it is the model emitting a column of placeholders.
    # Three or more is damning at any size; a pair only when the boxes are
    # placeholder-tiny, so two real courts drawn alike are left alone.
    everything = [entity for members in by_type.values() for entity in members]
    for run, _ in aligned_runs(everything, CROSS_TYPE_RUN_MIN):
        if len({entity.entity_type for entity in run}) < 2:
            continue
        tiny = all(max(entity.box.width, entity.box.height) <= CROSS_TYPE_TINY_SIDE for entity in run)
        if len(run) >= PATTERN_RUN_MIN or tiny:
            doomed.update(id(entity) for entity in run)

    if not doomed:
        return entities, 0
    return [entity for entity in entities if id(entity) not in doomed], len(doomed)


def _evenly_spaced(values: list[float]) -> bool:
    ordered = sorted(values)
    steps = [b - a for a, b in zip(ordered, ordered[1:])]
    if not steps or min(steps) <= 0:
        return False
    return (max(steps) - min(steps)) <= PATTERN_STEP_TOLERANCE


def _derive_marker_features(
    entities: list[MasterPlanEntity], *, image_width: int, image_height: int
) -> tuple[list[MasterPlanEntity], int]:
    """Reconcile drawing boxes with numbered legend markers.

    * A drawing box that agrees with a marker for the same feature (same
      legend code or same label, marker inside or beside the box) is merged:
      the box is kept and flagged ``both``.
    * A drawing box for a feature that has markers elsewhere, but none near
      the box, contradicts the plan's own key and is dropped.
    * Every marker not merged becomes a small feature entity of its own.
    * Markers with no legend match stay as plain ``legend_marker`` annotations.

    Returns the reconciled list and the number of contradicted boxes dropped.
    """
    markers = [entity for entity in entities if entity.entity_type == "legend_marker"]
    if not markers:
        return entities, 0
    others = [entity for entity in entities if entity.entity_type != "legend_marker"]

    matched: dict[str, list[MasterPlanEntity]] = {}
    unmatched: list[MasterPlanEntity] = []
    for marker in markers:
        key = _normalize_code(marker.legend_code)
        if marker.legend_label and key:
            matched.setdefault(key, []).append(marker)
        else:
            unmatched.append(marker)

    label_to_code = {
        _label_key(group[0].legend_label): code for code, group in matched.items()
    }

    merged_marker_ids: set[int] = set()
    kept_others: list[MasterPlanEntity] = []
    contradicted = 0

    for other in others:
        candidate_codes: set[str] = set()
        own_code = _normalize_code(other.legend_code) if other.legend_code else None
        if own_code and own_code in matched:
            candidate_codes.add(own_code)
        for text in (other.label, other.legend_label):
            code = label_to_code.get(_label_key(text))
            if code:
                candidate_codes.add(code)

        if not candidate_codes:
            kept_others.append(other)
            continue

        near = [
            marker
            for code in candidate_codes
            for marker in matched[code]
            if _point_near_box(marker.center_x, marker.center_y, other.box, pad=MARKER_MATCH_PAD)
        ]
        if not near:
            contradicted += 1
            continue

        other.located_by = "both"
        if not other.legend_code:
            other.legend_code = near[0].legend_code
            other.legend_label = near[0].legend_label
        merged_marker_ids.update(id(marker) for marker in near)
        kept_others.append(other)

    aspect = image_width / image_height if image_height else 1.0
    min_w = MARKER_FEATURE_MIN_SIDE
    min_h = MARKER_FEATURE_MIN_SIDE * aspect

    derived: list[MasterPlanEntity] = []
    per_code_counter: dict[str, int] = {}
    for code, group in matched.items():
        for marker in group:
            if id(marker) in merged_marker_ids:
                continue
            feature_type = normalize_entity_type(marker.legend_label) or "other_feature"
            box = _expand_box(marker.box, min_w=min_w, min_h=min_h)
            center_x, center_y = box.center
            per_code_counter[code] = per_code_counter.get(code, 0) + 1
            derived.append(
                MasterPlanEntity(
                    entity_id=f"m{code}-{per_code_counter[code]}",
                    entity_type=feature_type,
                    entity_group=ENTITY_TYPE_GROUPS[feature_type],
                    label=marker.legend_label or f"Marker {code}",
                    legend_code=marker.legend_code,
                    legend_label=marker.legend_label,
                    category_key=_category_for(feature_type, marker.legend_label or "", marker.legend_label),
                    box=box,
                    center_x=round(center_x, 4),
                    center_y=round(center_y, 4),
                    relative_area=round(box.width * box.height, 5),
                    confidence_label=marker.confidence_label,
                    located_by="legend_marker",
                    attributes={},
                    adjacent_to=[],
                )
            )

    return kept_others + _dedupe_marker_features(derived) + unmatched, contradicted


def _apply_type_caps(entities: list[MasterPlanEntity]) -> tuple[list[MasterPlanEntity], dict[str, int]]:
    removed: dict[str, int] = {}
    keep_ids: set[int] = set()
    for entity_type, cap in TYPE_CAPS.items():
        of_type = [entity for entity in entities if entity.entity_type == entity_type]
        if len(of_type) <= cap:
            continue
        # Marker-located features are trustworthy; trim drawn boxes first.
        of_type.sort(key=lambda item: (item.located_by != "layout_model", item.relative_area), reverse=True)
        for entity in of_type[:cap]:
            keep_ids.add(id(entity))
        removed[entity_type] = len(of_type) - cap
    if not removed:
        return entities, removed
    capped_types = set(removed)
    kept = [
        entity
        for entity in entities
        if entity.entity_type not in capped_types or id(entity) in keep_ids
    ]
    return kept, removed


# --------------------------------------------------------------------------- #
# Derived spatial metadata
# --------------------------------------------------------------------------- #


def _is_spatial(entity: MasterPlanEntity) -> bool:
    """Annotation entities other than legend markers have no spatial meaning."""
    return entity.entity_group != "annotation" or entity.entity_type == "legend_marker"


def _attach_nearest_block(entities: list[MasterPlanEntity], *, image_width: int, image_height: int) -> None:
    blocks = [entity for entity in entities if entity.entity_type == "residential_block"]
    if not blocks:
        return

    for entity in entities:
        if entity.entity_type == "residential_block" or not _is_spatial(entity):
            continue
        nearest = min(
            blocks,
            key=lambda block: _distance(entity, block, image_width, image_height),
        )
        entity.nearest_residential_block = nearest.label
        entity.nearest_residential_distance = round(
            _distance(entity, nearest, image_width, image_height), 4
        )


def _build_block_proximity(
    entities: list[MasterPlanEntity], *, image_width: int, image_height: int
) -> list[ResidentialBlockProximity]:
    blocks = [entity for entity in entities if entity.entity_type == "residential_block"]
    results: list[ResidentialBlockProximity] = []

    for block in sorted(blocks, key=lambda item: item.label):
        scored: list[tuple[float, MasterPlanEntity]] = []
        for entity in entities:
            if entity is block or entity.entity_type == "residential_block" or not _is_spatial(entity):
                continue
            scored.append((_distance(block, entity, image_width, image_height), entity))
        scored.sort(key=lambda item: item[0])

        amenities = _unique_labels(
            entity for distance, entity in scored
            if distance <= PROXIMITY_RADIUS and entity.entity_group in {"amenity", "water"}
        )[:6]
        greens = _unique_labels(
            entity for distance, entity in scored
            if distance <= PROXIMITY_RADIUS and entity.entity_group == "landscape"
        )[:4]

        def within(entity_type: str) -> bool:
            return any(
                distance <= ADJACENCY_RADIUS and entity.entity_type == entity_type
                for distance, entity in scored
            )

        nearest_amenity = next(
            (distance for distance, entity in scored if entity.entity_group in {"amenity", "water"}),
            None,
        )

        results.append(
            ResidentialBlockProximity(
                block_label=block.label,
                nearby_amenities=amenities,
                nearby_green=greens,
                near_entry_gate=within("entry_exit_gate"),
                near_external_road=within("external_road"),
                near_utility_yard=within("utility_yard"),
                near_parking=within("parking"),
                nearest_amenity_distance=round(nearest_amenity, 4) if nearest_amenity is not None else None,
            )
        )

    return results


def _build_legend_entries(raw_items: Any, entities: list[MasterPlanEntity]) -> list[LegendEntry]:
    located: dict[str, int] = {}
    for entity in entities:
        if entity.legend_code:
            key = _normalize_code(entity.legend_code) or entity.legend_code
            located[key] = located.get(key, 0) + 1

    entries: list[LegendEntry] = []
    seen: set[str] = set()
    for raw in raw_items or []:
        if not isinstance(raw, dict):
            continue
        code = _clean_code(raw.get("code"))
        label = _clean_text(raw.get("label"))
        if not code or not label:
            continue
        key = _normalize_code(code) or code
        if key in seen:
            continue
        seen.add(key)
        inferred = infer_category_key(label)
        entries.append(
            LegendEntry(
                code=code,
                label=label,
                normalized_label=label.lower(),
                category_key=None if inferred in {None, "unknown"} else inferred,
                located_on_plan=key in located,
                marker_count=located.get(key, 0),
            )
        )
    return entries


def _build_site_summary(raw_site: dict[str, Any], entities: list[MasterPlanEntity]) -> SiteSummary:
    roads = []
    for raw in raw_site.get("external_roads", []) or []:
        if not isinstance(raw, dict):
            continue
        label = _clean_text(raw.get("label"))
        if not label:
            continue
        roads.append(
            ExternalRoad(
                label=label,
                width_text=_clean_text(raw.get("width_text")) or None,
                side=_clean_text(raw.get("side")) or None,
            )
        )

    gate_count = sum(1 for entity in entities if entity.entity_type == "entry_exit_gate")
    try:
        declared_entry_count = int(raw_site.get("entry_exit_count") or 0)
    except (TypeError, ValueError):
        declared_entry_count = 0

    shape_raw = _clean_text(raw_site.get("shape_class")).lower().replace(" ", "_").replace("-", "_")
    shape_class = shape_raw if shape_raw in SHAPE_CLASSES else None

    return SiteSummary(
        shape_class=shape_class,
        north_arrow_present=bool(raw_site.get("north_arrow_present"))
        or any(entity.entity_type == "north_arrow" for entity in entities),
        external_roads=roads,
        entry_exit_count=max(declared_entry_count, gate_count),
        residential_block_labels=sorted(
            _unique_labels(entity for entity in entities if entity.entity_type == "residential_block")
        ),
        commercial_block_count=sum(1 for entity in entities if entity.entity_type == "commercial_block"),
        parking_cluster_count=sum(1 for entity in entities if entity.entity_type == "parking"),
        utility_yard_count=sum(1 for entity in entities if entity.entity_type == "utility_yard"),
    )


def _derive_confidence(
    declared: Any, legend: list[LegendEntry], entities: list[MasterPlanEntity]
) -> str:
    declared_label = str(declared or "").strip().title()
    located_ratio = (
        sum(1 for item in legend if item.located_on_plan) / len(legend) if legend else 0.0
    )
    non_marker = [entity for entity in entities if entity.entity_type != "legend_marker"]

    if len(non_marker) < 5:
        return "Low"
    if legend and located_ratio < 0.4:
        return "Low" if declared_label == "Low" else "Medium"
    if declared_label in {"High", "Medium", "Low"}:
        return declared_label
    return "High" if located_ratio >= 0.7 and len(non_marker) >= 12 else "Medium"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _build_legend_lookup(raw_items: Any) -> dict[str, tuple[str, str]]:
    lookup: dict[str, tuple[str, str]] = {}
    for raw in raw_items or []:
        if not isinstance(raw, dict):
            continue
        code = _clean_code(raw.get("code"))
        label = _clean_text(raw.get("label"))
        key = _normalize_code(code)
        if key and label and key not in lookup:
            lookup[key] = (code, label)
    return lookup


def _clean_code(value: Any) -> str:
    """Printed legend codes often carry a trailing dot ("01."); drop it."""
    return _clean_text(value).rstrip(".").strip()


def _normalize_code(value: Any) -> str | None:
    text = _clean_code(value).lower()
    if not text:
        return None
    if text.isdigit():
        return str(int(text))
    return text


def _label_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _point_near_box(x: float, y: float, box: EntityBox, *, pad: float) -> bool:
    return (box.x_min - pad) <= x <= (box.x_max + pad) and (box.y_min - pad) <= y <= (box.y_max + pad)


def _expand_box(box: EntityBox, *, min_w: float, min_h: float) -> EntityBox:
    """Grow a box around its centre so it is at least min_w x min_h."""
    center_x, center_y = box.center
    half_w = max(box.width, min_w) / 2
    half_h = max(box.height, min_h) / 2
    return EntityBox(
        x_min=round(_clamp(center_x - half_w), 4),
        y_min=round(_clamp(center_y - half_h), 4),
        x_max=round(_clamp(center_x + half_w), 4),
        y_max=round(_clamp(center_y + half_h), 4),
    )


def _distance(a: MasterPlanEntity, b: MasterPlanEntity, image_width: int, image_height: int) -> float:
    dx = (a.center_x - b.center_x) * image_width
    dy = (a.center_y - b.center_y) * image_height
    diagonal = math.hypot(image_width, image_height) or 1.0
    return math.hypot(dx, dy) / diagonal


def _iou(a: EntityBox, b: EntityBox) -> float:
    inter_w = max(0.0, min(a.x_max, b.x_max) - max(a.x_min, b.x_min))
    inter_h = max(0.0, min(a.y_max, b.y_max) - max(a.y_min, b.y_min))
    inter = inter_w * inter_h
    union = a.width * a.height + b.width * b.height - inter
    return inter / union if union > 0 else 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        value = value.value
    return " ".join(str(value).split()).strip()


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for value in values:
        text = _clean_text(value)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _unique_labels(entities) -> list[str]:
    labels: list[str] = []
    for entity in entities:
        if entity.label not in labels:
            labels.append(entity.label)
    return labels
