"""Reviewer agent: does the analysis pass?

Two layers. Deterministic rule checks run first and cost nothing; they
encode the playbook's hard rules as code. Then one model pass looks at the
image with the playbook text, counts what it sees (towers, pools, gates)
and compares with what was extracted. A finding from the model is advisory
until a measurement or a focused check backs it; the fixer enforces that.
"""

from __future__ import annotations

from typing import Any, Callable

from google.genai import types
from PIL import Image
from pydantic import BaseModel, Field

from app.agents.playbook import playbook_prompt_text, scoped
from app.schemas.agent_schema import Finding, Playbook, ReviewReport
from app.schemas.area_schema import AreaEstimateResult
from app.schemas.master_plan_entity_schema import MasterPlanEntityMap
from app.schemas.project_schema import ParsedProjectMetadata
from app.services.master_plan_entity_extractor import (
    WATER_MIN_BLUE_SHARE,
    _normalize_code,
    bare_number_aliases,
    marker_only_area_features,
    plan_declares_water,
    unsupported_water_entities,
    water_ink_share,
    wing_key,
)

OVERSIZED_RELATIVE_AREA = 0.35
# The area types whose drawn extent matters to a reader (rule A9).
MAJOR_AREA_TYPES = {"sports_court", "swimming_pool", "lawn_garden", "kids_play_area", "clubhouse"}
OVERSIZE_EXEMPT_TYPES = {"external_road", "internal_road", "driveway", "site_boundary", "legend_block", "title_block"}
SEVERITY_PENALTY = {"blocker": 0.5, "major": 0.2, "minor": 0.05}
MODEL_FINDING_CODES = {"missed_blocks", "false_positive_block", "false_positive_water", "mislabelled_block", "missed_legend_item", "other"}
VERIFIABLE_MODEL_CODES = {"false_positive_block", "false_positive_water"}


def plan_scope(entity_map: MasterPlanEntityMap) -> str:
    return "block_plan" if entity_map.site.drawing_style == "block_plan" else "rendered"


# --------------------------------------------------------------------------- #
# Layer 1: rules as code
# --------------------------------------------------------------------------- #


def run_rule_checks(
    entity_map: MasterPlanEntityMap,
    area_estimate: AreaEstimateResult | None,
    project: ParsedProjectMetadata | None,
    image: Image.Image | None,
) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    applied: list[str] = []
    blocks = [entity for entity in entity_map.entities if entity.entity_type == "residential_block"]
    scope = plan_scope(entity_map)

    # A3: unique block labels
    applied.append("A3")
    seen: dict[str, list[str]] = {}
    for block in blocks:
        key = wing_key(block.label) or block.label.strip().lower()
        seen.setdefault(key, []).append(block.entity_id)
    duplicates = {key: ids for key, ids in seen.items() if len(ids) > 1}
    if duplicates:
        findings.append(Finding(
            code="duplicate_block_labels", severity="major",
            detail=f"{sum(len(ids) - 1 for ids in duplicates.values())} residential blocks repeat another block's name.",
            entity_ids=[entity_id for ids in duplicates.values() for entity_id in ids[1:]],
            suggested_fix="Relabel the later duplicates as unnamed footprints.",
        ))

    # A2: water needs support
    applied.append("A2")
    water = [entity for entity in entity_map.entities if entity.entity_group == "water"]
    if water and image is not None and not plan_declares_water(entity_map.legend, project):
        unsupported = [
            entity for entity in water
            if entity.located_by == "layout_model" and not entity.legend_code and water_ink_share(image, entity.box) < WATER_MIN_BLUE_SHARE
        ]
        if unsupported:
            findings.append(Finding(
                code="false_positive_water", severity="blocker",
                detail=f"{len(unsupported)} water features have no legend, record or marker support and no blue ink.",
                entity_ids=[entity.entity_id for entity in unsupported],
                entity_labels=[entity.label for entity in unsupported],
                suggested_fix="Drop them unless a crop check confirms water.",
            ))

    # A7: oversized boxes
    applied.append("A7")
    oversized = [
        entity for entity in entity_map.entities
        if entity.entity_type not in OVERSIZE_EXEMPT_TYPES and entity.entity_group != "annotation" and entity.relative_area > OVERSIZED_RELATIVE_AREA
    ]
    if oversized:
        findings.append(Finding(
            code="oversized_entity", severity="major",
            detail=f"{len(oversized)} feature boxes cover more than {int(OVERSIZED_RELATIVE_AREA * 100)}% of the sheet.",
            entity_ids=[entity.entity_id for entity in oversized],
            entity_labels=[entity.label for entity in oversized],
            suggested_fix="Drop them.",
        ))

    # A4: legend coverage on rendered plans
    if scope == "rendered" and len(entity_map.legend) >= 5:
        applied.append("A4")
        located = sum(1 for item in entity_map.legend if item.located_on_plan)
        if located < len(entity_map.legend) / 2:
            findings.append(Finding(
                code="low_legend_coverage", severity="major",
                detail=f"Only {located} of {len(entity_map.legend)} legend items were placed on the plan.",
                suggested_fix="Targeted marker re-scan (already attempted during extraction); record for the teacher.",
            ))

    # A5: block plans carry their printed records
    if scope == "block_plan":
        applied.append("A5")
        records = entity_map.site.printed_records
        if records is None or (records.plot_area_sq_m is None and records.sanctioned_bua_sq_m is None and not records.parcels):
            findings.append(Finding(
                code="missing_printed_records", severity="major",
                detail="No printed plot area, BUA or parcel areas were transcribed from the block plan.",
                suggested_fix="Re-run the printed records call.",
            ))
        elif records.parcels and any(parcel.area_sq_m is None for parcel in records.parcels):
            missing = [parcel.label for parcel in records.parcels if parcel.area_sq_m is None]
            findings.append(Finding(
                code="parcel_area_missing", severity="minor",
                detail=f"{len(missing)} parcels have a label but no readable area.",
                entity_labels=missing,
            ))

    # A6: estimate sanity
    if area_estimate is not None:
        applied.append("A6")
        green, open_ = area_estimate.green_area_percentage, area_estimate.open_area_percentage
        if green.max > open_.max + 1e-6 or green.min > open_.min + 1e-6:
            findings.append(Finding(
                code="estimate_inconsistent", severity="blocker",
                detail=f"Green range {green.display} exceeds open range {open_.display}.",
                suggested_fix="Clamp green to open.",
            ))
        if scope == "block_plan" and area_estimate.confidence.label != "Low":
            findings.append(Finding(
                code="estimate_overconfident", severity="major",
                detail=f"A line drawing's estimate is labelled {area_estimate.confidence.label} confidence.",
                suggested_fix="Downgrade to Low.",
            ))

    # A9: a court, pool or lawn that a marker placed must be boxed as an area.
    # Once the extractor has tried, what is left is what the drawing does not
    # give (seating spots, bays), so the finding drops to minor.
    applied.append("A9")
    marker_only = [entity for entity in marker_only_area_features(entity_map) if entity.entity_type in MAJOR_AREA_TYPES]
    if marker_only:
        attempted = any(diagnostic.code in {"marker_features_boxed", "marker_expansion_attempted"} for diagnostic in entity_map.diagnostics)
        findings.append(Finding(
            code="marker_only_area_features", severity="minor" if attempted else "major",
            detail=f"{len(marker_only)} area features (courts, pools, lawns, play areas) are placed by a marker but not boxed on the drawing"
            + (" after an expansion attempt." if attempted else "."),
            entity_ids=[entity.entity_id for entity in marker_only],
            entity_labels=[entity.label for entity in marker_only],
            suggested_fix="Box the drawn area around each marker.",
        ))

    # A10: markers whose codes are not in the legend mean the circles were misread
    applied.append("A10")
    if entity_map.legend:
        codes = [item.code for item in entity_map.legend]
        legend_keys = {_normalize_code(code) for code in codes} | set(bare_number_aliases(codes))
        unknown = [
            entity for entity in entity_map.entities
            if entity.entity_type == "legend_marker" and entity.legend_code and _normalize_code(entity.legend_code) not in legend_keys
        ]
        if len(unknown) >= 5:
            findings.append(Finding(
                code="unreadable_markers", severity="minor",
                detail=f"{len(unknown)} circle markers carry codes that are not in the legend ({', '.join(sorted({e.legend_code or '' for e in unknown})[:8])}); the circles are too small to read reliably on this sheet.",
                entity_ids=[entity.entity_id for entity in unknown],
            ))

    # A1 (deterministic part): no blocks at all is a blocker
    applied.append("A1")
    if not blocks:
        findings.append(Finding(
            code="missed_blocks", severity="blocker",
            detail="No residential block was boxed.",
            suggested_fix="Run the footprint recovery pass.",
        ))

    return findings, applied


# --------------------------------------------------------------------------- #
# Layer 2: the model looks at the image
# --------------------------------------------------------------------------- #


class GeminiReviewFinding(BaseModel):
    code: str = Field(description="One of: missed_blocks, false_positive_block, false_positive_water, mislabelled_block, missed_legend_item, other.")
    severity: str = Field(default="major", description="blocker, major or minor.")
    detail: str
    entity_labels: list[str] = Field(default_factory=list, description="Labels of the extracted features concerned, if any.")


class GeminiCount(BaseModel):
    """An independent count, made before the model sees what was extracted."""

    towers_seen: int = Field(default=0, description="Residential towers / wings drawn on the plan, one per separate building footprint.")
    pools_seen: int = Field(default=0, description="Swimming pools or water bodies drawn on the plan.")
    gates_seen: int = Field(default=0, description="Entry / exit points marked on the plan.")
    notes: str | None = Field(default=None, description="Where the towers are, in one sentence.")


class GeminiReview(BaseModel):
    findings: list[GeminiReviewFinding] = Field(default_factory=list)
    summary: str | None = None


def build_count_prompt(scope: str) -> str:
    sheet = "architectural block plan (line drawing)" if scope == "block_plan" else "real-estate master plan rendering"
    return (
        f"This is a {sheet}. Count, carefully and only what is actually drawn: residential towers or wings "
        "(one per separate building footprint, including unlabelled outlines at the plot edges and any "
        "colour-filled or hatched ones; do not count parcels, plots, roads, text blocks, or blank placeholders "
        "labelled future development), swimming pools or "
        "water bodies, and entry/exit points. Say in one sentence where the towers are. Return JSON only."
    )


def compact_summary(entity_map: MasterPlanEntityMap, area_estimate: AreaEstimateResult | None) -> str:
    blocks = [entity.label for entity in entity_map.entities if entity.entity_type == "residential_block"]
    water = [entity.label for entity in entity_map.entities if entity.entity_group == "water"]
    gates = sum(1 for entity in entity_map.entities if entity.entity_type == "entry_exit_gate")
    legend = entity_map.legend
    located = sum(1 for item in legend if item.located_on_plan)
    lines = [
        f"drawing_style: {entity_map.site.drawing_style or 'rendered'}",
        f"residential blocks ({len(blocks)}): {', '.join(blocks) or 'none'}",
        f"water features ({len(water)}): {', '.join(water) or 'none'}",
        f"entry/exit gates boxed: {gates}; site says {entity_map.site.entry_exit_count}",
        f"legend rows: {len(legend)}, placed: {located}",
        f"group counts: {entity_map.group_counts}",
    ]
    records = entity_map.site.printed_records
    if records:
        lines.append(f"printed: plot {records.plot_area_sq_m} sq.m, BUA {records.sanctioned_bua_sq_m} sq.m, parcels {len(records.parcels)}")
    if area_estimate:
        lines.append(f"estimate: green {area_estimate.green_area_percentage.display}, open {area_estimate.open_area_percentage.display}, {area_estimate.confidence.label} confidence")
    if entity_map.diagnostics:
        lines.append("deliberate steps already taken (pixel measurements, printed notes, crop checks); do not report these as errors:")
        for diagnostic in entity_map.diagnostics:
            items = f" ({', '.join(diagnostic.items[:4])})" if diagnostic.items else ""
            lines.append(f"  - {diagnostic.code}: {diagnostic.count}{items}")
    return "\n".join(lines)


def build_review_prompt(playbook: Playbook, scope: str, summary: str, observed: dict[str, Any]) -> str:
    return (
        "You are the reviewer of an automated master plan analysis. Look at the drawing and judge the extraction "
        "below against the playbook. An independent count of the drawing is given; use it. List findings only "
        "where the extraction contradicts the drawing: boxes on things that are not buildings (false_positive_block), "
        "water that is not drawn (false_positive_water), wrong block names (mislabelled_block), legend items drawn "
        "but not placed (missed_legend_item), anything else (other). Name the extracted labels concerned. Be "
        "conservative: a feature you cannot verify is not a finding, and the deliberate steps listed in the "
        "summary (water removed for lack of blue ink, blocks named from a printed key note, candidates rejected "
        "by a crop check) are correct by construction. Return JSON only.\n\n"
        f"{playbook_prompt_text(playbook, scope)}\n\nINDEPENDENT COUNT: towers {observed.get('towers_seen')}, "
        f"pools {observed.get('pools_seen')}, gates {observed.get('gates_seen')}. {observed.get('notes') or ''}\n\n"
        f"EXTRACTION SUMMARY:\n{summary}"
    )


def run_model_count(scope: str, image_part: types.Part, call: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    payload = call(build_count_prompt(scope), image_part, GeminiCount, 0.0, 512)
    return {
        "towers_seen": int(payload.get("towers_seen") or 0),
        "pools_seen": int(payload.get("pools_seen") or 0),
        "gates_seen": int(payload.get("gates_seen") or 0),
        "notes": payload.get("notes"),
    }


def run_model_review(
    entity_map: MasterPlanEntityMap,
    area_estimate: AreaEstimateResult | None,
    image_part: types.Part,
    playbook: Playbook,
    call: Callable[..., dict[str, Any]],
    project: ParsedProjectMetadata | None = None,
) -> tuple[list[Finding], dict[str, Any]]:
    scope = plan_scope(entity_map)
    # The count comes first and sees only the drawing, so it cannot anchor on
    # what was extracted; the judgement call then reads both.
    observed = run_model_count(scope, image_part, call)
    payload = call(build_review_prompt(playbook, scope, compact_summary(entity_map, area_estimate), observed), image_part, GeminiReview, 0.0, 2048)
    observed["summary"] = payload.get("summary")
    findings: list[Finding] = []
    boxed = sum(1 for entity in entity_map.entities if entity.entity_type == "residential_block")
    seen = observed["towers_seen"]

    # A1 from the model's count: the count decides the severity, not the model's
    # wording. On a block plan every gap is worth a repair round because the
    # footprint recovery is cheap and only adds verified outlines; on a
    # rendered plan, with no recipe, a single tower is within the count's noise.
    if seen > 0 and boxed < seen:
        gap = seen - boxed
        if gap >= 3 or (seen >= 5 and boxed < 0.7 * seen):
            severity = "blocker"
        elif gap == 2 or scope == "block_plan":
            severity = "major"
        else:
            severity = "minor"
        # A count the recovery pass has already been sent after twice, and
        # could not satisfy, is more likely the count's error than a missing
        # tower: it is no longer a blocker.
        attempts = sum(1 for diagnostic in entity_map.diagnostics if diagnostic.code == "footprint_recovery_attempted")
        if severity == "blocker" and attempts >= 2:
            severity = "major"
        findings.append(Finding(
            code="missed_blocks", severity=severity, source="model",
            detail=f"The reviewer sees {seen} towers; {boxed} are boxed ({gap} missing).",
            suggested_fix="Run the footprint recovery pass.",
        ))

    for raw in payload.get("findings", []) or []:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or "other").strip().lower()
        if code not in MODEL_FINDING_CODES or code == "missed_blocks":
            continue
        severity = str(raw.get("severity") or "major").strip().lower()
        if severity not in SEVERITY_PENALTY:
            severity = "major"
        # Only findings a recipe can verify keep their weight; an opinion the
        # fixer cannot test is recorded as minor so it cannot sink the score.
        if code not in VERIFIABLE_MODEL_CODES:
            severity = "minor"
        labels = [str(label) for label in (raw.get("entity_labels") or []) if str(label).strip()]
        ids = [entity.entity_id for entity in entity_map.entities if entity.label in labels]
        if code == "false_positive_water":
            # Water backed by the legend, the records or a marker outranks the
            # model's eyes; only unsupported water can be a finding.
            unsupported = {entity.entity_id for entity in unsupported_water_entities(entity_map, project)}
            ids = [entity_id for entity_id in ids if entity_id in unsupported]
            if not ids:
                continue
            severity = "major"
        findings.append(Finding(
            code=code, severity=severity, source="model",  # type: ignore[arg-type]
            detail=str(raw.get("detail") or code), entity_ids=ids, entity_labels=labels,
        ))
    return findings, observed


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #


def score_findings(findings: list[Finding]) -> float:
    penalty = sum(SEVERITY_PENALTY[finding.severity] for finding in findings)
    return round(max(0.0, 1.0 - penalty), 3)


def review_analysis(
    entity_map: MasterPlanEntityMap,
    area_estimate: AreaEstimateResult | None,
    *,
    project: ParsedProjectMetadata | None,
    image: Image.Image | None,
    image_part: types.Part | None,
    playbook: Playbook,
    call: Callable[..., dict[str, Any]] | None,
) -> ReviewReport:
    findings, applied = run_rule_checks(entity_map, area_estimate, project, image)
    observed: dict[str, Any] = {}
    model_used = False
    if call is not None and image_part is not None:
        try:
            model_findings, observed = run_model_review(entity_map, area_estimate, image_part, playbook, call, project)
            model_used = True
            known = {finding.code for finding in findings}
            findings.extend(finding for finding in model_findings if finding.code not in known)
        except Exception as exc:  # noqa: BLE001 - the rules still decide
            observed = {"model_error": str(exc)[:200]}
    score = score_findings(findings)
    verdict = "fail" if any(finding.severity == "blocker" for finding in findings) else "pass"
    rules = [rule.id for rule in scoped(playbook.acceptance_rules, plan_scope(entity_map)) if rule.id in applied]
    return ReviewReport(verdict=verdict, score=score, findings=findings, observed=observed, rules_applied=rules, model_used=model_used)
