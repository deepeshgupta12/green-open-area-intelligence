"""Fixer agent: resolve the reviewer's findings with verified tools, then resubmit.

Every recipe reuses something the extractor already trusts (a pixel
measurement, a focused crop check, a recovery pass). A model opinion from
the reviewer alone never removes a feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from google.genai import types
from PIL import Image

from app.schemas.agent_schema import Finding, FixAction, Playbook
from app.schemas.area_schema import AreaEstimateResult
from app.schemas.master_plan_entity_schema import Diagnostic, MasterPlanEntity, MasterPlanEntityMap
from app.schemas.project_schema import ParsedProjectMetadata
from app.services.master_plan_entity_extractor import (
    WATER_MIN_BLUE_SHARE,
    GeminiFootprintCheck,
    GeminiWaterCheck,
    _crop_part,
    _with_entities,
    apply_water_verdicts,
    build_footprint_check_prompt,
    build_water_check_prompt,
    recover_footprints,
    unsupported_water_entities,
    water_ink_share,
    wing_key,
)
from app.agents.reviewer import OVERSIZE_EXEMPT_TYPES, OVERSIZED_RELATIVE_AREA


@dataclass
class FixContext:
    image: Image.Image | None
    image_part: types.Part | None
    call: Callable[..., dict[str, Any]] | None
    project: ParsedProjectMetadata | None


# --------------------------------------------------------------------------- #
# Pure recipes (no model)
# --------------------------------------------------------------------------- #


def dedupe_block_labels(entity_map: MasterPlanEntityMap) -> tuple[MasterPlanEntityMap, int]:
    """Keep the first block per name; later duplicates become unnamed footprints/blocks."""
    prefix = "Footprint" if entity_map.site.drawing_style == "block_plan" else "Block"
    taken = {entity.label for entity in entity_map.entities}
    seen: set[str] = set()
    renamed = 0
    entities: list[MasterPlanEntity] = []
    for entity in entity_map.entities:
        if entity.entity_type != "residential_block":
            entities.append(entity)
            continue
        key = wing_key(entity.label) or entity.label.strip().lower()
        if key in seen:
            number = 1
            while f"{prefix} {number}" in taken:
                number += 1
            label = f"{prefix} {number}"
            taken.add(label)
            attributes = {k: v for k, v in entity.attributes.items() if k != "wing"}
            entities.append(entity.model_copy(update={"label": label, "attributes": attributes}))
            renamed += 1
        else:
            seen.add(key)
            entities.append(entity)
    if not renamed:
        return entity_map, 0
    diagnostics = list(entity_map.diagnostics) + [Diagnostic(code="qa_duplicate_labels_renamed", count=renamed)]
    return _with_entities(entity_map, entities, diagnostics), renamed


def drop_entities(entity_map: MasterPlanEntityMap, entity_ids: set[str], code: str) -> tuple[MasterPlanEntityMap, int]:
    doomed = [entity for entity in entity_map.entities if entity.entity_id in entity_ids]
    if not doomed:
        return entity_map, 0
    entities = [entity for entity in entity_map.entities if entity.entity_id not in entity_ids]
    diagnostics = list(entity_map.diagnostics) + [Diagnostic(code=code, count=len(doomed), items=[entity.label for entity in doomed][:8])]
    return _with_entities(entity_map, entities, diagnostics), len(doomed)


def clamp_estimate(estimate: AreaEstimateResult) -> AreaEstimateResult:
    """Green never exceeds open."""
    green, open_ = estimate.green_area_percentage, estimate.open_area_percentage
    new_min, new_max = min(green.min, open_.min), min(green.max, open_.max)
    if (new_min, new_max) == (green.min, green.max):
        return estimate
    clamped = green.model_copy(update={"min": new_min, "max": new_max, "display": f"~{round(new_min)}–{round(new_max)}%"})
    notes = [*estimate.notes, "QA fixer clamped the green range to the open range."]
    display = estimate.compare_module_display.model_copy(update={"green_space_value": clamped.display})
    return estimate.model_copy(update={"green_area_percentage": clamped, "notes": notes, "compare_module_display": display})


def downgrade_estimate(estimate: AreaEstimateResult, reason: str) -> AreaEstimateResult:
    confidence = estimate.confidence.model_copy(
        update={"label": "Low", "score": round(min(estimate.confidence.score, 0.4), 2), "reasons": [*estimate.confidence.reasons, reason]}
    )
    display = estimate.compare_module_display.model_copy(update={"confidence_label": "Low Confidence"})
    return estimate.model_copy(update={"confidence": confidence, "compare_module_display": display})


# --------------------------------------------------------------------------- #
# Recipes that need the image or the model
# --------------------------------------------------------------------------- #


def verify_water(entity_map: MasterPlanEntityMap, entity_ids: set[str], ctx: FixContext) -> tuple[MasterPlanEntityMap, str]:
    # Only water the extractor itself would treat as unsupported is checked:
    # a legend row, a declared amenity or a legend marker outranks the
    # reviewer's eyes, and a marker-sized box holds little blue by nature.
    unsupported = {entity.entity_id for entity in unsupported_water_entities(entity_map, ctx.project)}
    suspects = [entity for entity in entity_map.entities if entity.entity_id in entity_ids and entity.entity_id in unsupported]
    if not suspects or ctx.image is None:
        return entity_map, "nothing to verify: the flagged water is supported by the legend, records or a marker"
    verdicts: list[dict[str, Any] | None] = []
    for entity in suspects:
        if water_ink_share(ctx.image, entity.box) < WATER_MIN_BLUE_SHARE:
            verdicts.append({"feature": "no_blue_ink", "is_water": False})
            continue
        if ctx.call is None:
            verdicts.append(None)
            continue
        try:
            verdicts.append(ctx.call(build_water_check_prompt(), _crop_part(ctx.image, entity.box, pad=1.0), GeminiWaterCheck, 0.0, 256))
        except Exception:  # noqa: BLE001
            verdicts.append(None)
    before = len(entity_map.entities)
    result = apply_water_verdicts(entity_map, suspects, verdicts)
    return result, f"{before - len(result.entities)} of {len(suspects)} water features dropped after ink and crop checks"


def verify_blocks(entity_map: MasterPlanEntityMap, entity_ids: set[str], ctx: FixContext) -> tuple[MasterPlanEntityMap, str]:
    # The "building outline" crop check is calibrated on line drawings; on a
    # rendered plan it would reject real wings, so it never runs there.
    if entity_map.site.drawing_style != "block_plan":
        return entity_map, "not applied: block crop checks run on block plans only"
    suspects = [entity for entity in entity_map.entities if entity.entity_id in entity_ids and entity.entity_type == "residential_block"]
    if not suspects or ctx.image is None or ctx.call is None:
        return entity_map, "nothing to verify"
    doomed: set[str] = set()
    for entity in suspects:
        try:
            verdict = ctx.call(build_footprint_check_prompt(), _crop_part(ctx.image, entity.box, pad=0.5), GeminiFootprintCheck, 0.0, 128)
        except Exception:  # noqa: BLE001 - unverifiable keeps the block
            continue
        if not bool(verdict.get("is_building")):
            doomed.add(entity.entity_id)
    result, dropped = drop_entities(entity_map, doomed, "qa_false_positive_blocks_dropped")
    return result, f"{dropped} of {len(suspects)} flagged blocks failed the crop check and were dropped"


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #


def apply_fixes(
    entity_map: MasterPlanEntityMap,
    area_estimate: AreaEstimateResult | None,
    findings: list[Finding],
    ctx: FixContext,
    playbook: Playbook,
) -> tuple[MasterPlanEntityMap, AreaEstimateResult | None, list[FixAction]]:
    actions: list[FixAction] = []
    recipes = {recipe.trigger: recipe for recipe in playbook.fix_recipes}

    def record(code: str, applied: bool, detail: str) -> None:
        recipe = recipes.get(code)
        actions.append(FixAction(finding_code=code, recipe=recipe.id if recipe else "none", applied=applied, detail=detail))

    for finding in findings:
        code = finding.code
        ids = set(finding.entity_ids)
        if code == "duplicate_block_labels":
            entity_map, renamed = dedupe_block_labels(entity_map)
            record(code, renamed > 0, f"{renamed} duplicate labels renamed")
        elif code == "missed_blocks":
            if entity_map.site.drawing_style == "block_plan" and ctx.image is not None and ctx.image_part is not None and ctx.call is not None:
                before = sum(1 for entity in entity_map.entities if entity.entity_type == "residential_block")
                entity_map = recover_footprints(entity_map, ctx.image, ctx.image_part, ctx.call)
                after = sum(1 for entity in entity_map.entities if entity.entity_type == "residential_block")
                record(code, after > before, f"footprint recovery added {after - before} blocks ({before} -> {after})")
            else:
                record(code, False, "no automatic recipe for rendered plans; recorded for the teacher")
        elif code == "false_positive_water":
            entity_map, detail = verify_water(entity_map, ids, ctx)
            record(code, "dropped" in detail and not detail.startswith("0 of"), detail)
        elif code == "false_positive_block":
            entity_map, detail = verify_blocks(entity_map, ids, ctx)
            record(code, "dropped" in detail and not detail.startswith("0 of"), detail)
        elif code == "oversized_entity":
            doomed = {
                entity.entity_id for entity in entity_map.entities
                if entity.entity_id in ids and entity.entity_type not in OVERSIZE_EXEMPT_TYPES and entity.relative_area > OVERSIZED_RELATIVE_AREA
            }
            entity_map, dropped = drop_entities(entity_map, doomed, "qa_oversized_boxes_dropped")
            record(code, dropped > 0, f"{dropped} oversized boxes dropped")
        elif code == "estimate_inconsistent" and area_estimate is not None:
            fixed = clamp_estimate(area_estimate)
            record(code, fixed is not area_estimate, "green range clamped to the open range" if fixed is not area_estimate else "already consistent")
            area_estimate = fixed
        elif code == "estimate_overconfident" and area_estimate is not None:
            area_estimate = downgrade_estimate(area_estimate, "QA fixer: a line drawing's pixel classes carry little land-use signal.")
            record(code, True, "confidence set to Low")
        else:
            record(code, False, "no recipe; recorded for the teacher")
    return entity_map, area_estimate, actions
