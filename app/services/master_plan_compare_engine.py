from __future__ import annotations

import re
from collections import Counter
from uuid import uuid4

from app.schemas.area_schema import AreaEstimateResult
from app.schemas.category_insight_schema import CategoryComparisonResult, CategoryInsight
from app.schemas.master_plan_compare_schema import (
    CategoryComparisonMatrixRow,
    CategoryInternalScoring,
    CategoryWinner,
    ComparedProjectSummary,
    InternalEvidenceQuality,
    InternalProjectEvidenceQuality,
    MasterPlanComparisonResult,
    OverallMasterPlanRecommendation,
    ProjectCategoryComparison,
    UserFriendlyComparisonSummary,
)
from app.schemas.master_plan_understanding_schema import (
    MasterPlanCategoryEvidence,
    MasterPlanUnderstandingResult,
)
from app.schemas.project_schema import ParsedProjectMetadata


CATEGORY_PRIORITY_ORDER = [
    "green_landscape",
    "open_space",
    "built_density",
    "amenity_richness",
    "sports_active_lifestyle",
    "family_community",
    "water_leisure",
    "access_circulation",
    "environment_sustainability",
]

FRONTEND_CATEGORY_LABELS = {
    "green_landscape": "Green Living",
    "open_space": "Open Space",
    "built_density": "Density Comfort",
    "amenity_richness": "Amenity Depth",
    "sports_active_lifestyle": "Active Lifestyle",
    "family_community": "Family & Community",
    "water_leisure": "Water & Leisure",
    "access_circulation": "Access & Movement",
    "environment_sustainability": "Sustainability Signals",
}

TECHNICAL_TERMS_TO_HIDE = {
    "opencv",
    "unknown/unclassified",
    "unknown area",
    "segmentation",
    "pixel",
    "image quality:",
    "area estimate confidence",
    "confidence score",
    "score of",
}

GENERIC_EVIDENCE_TOKENS = {
    "open",
    "green",
    "landscape",
    "tree",
    "trees",
    "pool",
    "road",
    "roads",
    "pathway",
    "pathways",
    "leisure",
    "sports facilities",
    "sports",
    "amenity",
    "amenities",
    "recreation",
    "recreational",
    "water",
    "paved zones",
    "visible landscaped zones",
}

CATEGORY_ALLOWLIST = {
    "green_landscape": {
        "large green area", "central landscaped garden", "landscaped garden", "garden", "butterfly garden",
        "herb garden", "orchard", "fruit orchard", "woodland", "lawn", "party lawn", "park",
        "green area", "central green", "private garden", "gardens", "plantation", "planting", "tree-lined",
    },
    "open_space": {
        "open space", "amenity open space", "aos", "podium", "plaza", "central plaza", "court",
        "deck", "terrace", "driveway", "internal driveway", "drop-off", "drop off", "pathway",
        "walkway", "walking", "running track", "jogging", "cycle track", "play area", "recreation",
        "swimming pool", "sports court", "kids' play", "kids play", "school bus bay",
    },
    "built_density": {
        "units per acre", "tower", "towers", "clubhouse", "retail", "future development", "building",
        "built", "footprint", "block", "wing", "podium parking", "residential tower",
    },
    "amenity_richness": {
        "gymnasium", "swimming pool", "kids' pool", "kids pool", "badminton", "tennis", "squash",
        "football", "cricket", "basketball", "volleyball", "clubhouse", "cafe", "library", "spa",
        "party hall", "party lawn", "indoor games", "amphitheater", "amphitheatre", "senior citizen",
        "pet area", "day care", "bowling", "pool/billiards", "snooker", "observatory", "retail",
    },
    "sports_active_lifestyle": {
        "gymnasium", "fitness", "football", "cricket", "basketball", "volleyball", "badminton",
        "tennis", "squash", "running track", "jogging", "cycle track", "skating", "yoga",
        "sports court", "multipurpose sports", "swimming pool", "kids' pool", "kids pool", "golf",
        "pickleball", "pool/billiards", "snooker", "court",
    },
    "family_community": {
        "kids", "kids' play", "kids play", "day care", "senior citizen", "pet area", "pet park",
        "party lawn", "clubhouse", "amphitheater", "amphitheatre", "community", "camping",
        "play area", "family", "school bus bay", "lawn", "library", "party hall",
    },
    "water_leisure": {
        "swimming pool", "kids' pool", "kids pool", "adults pool", "pool deck", "water", "spa",
        "jacuzzi", "clubhouse", "leisure", "snooker", "billiards", "pool/billiards", "stepped seating",
    },
    "access_circulation": {
        "driveway", "internal driveway", "internal road", "entry", "entrance", "gate", "drop-off", "drop off",
        "vehicular", "pedestrian", "access", "frontage", "school bus bay", "ramp", "movement", "circulation",
        "approach", "exit",
    },
    "environment_sustainability": {
        "rain water harvesting", "rainwater harvesting", "sewage treatment plant", "stp", "treated water",
        "treated water supply", "solar", "solar heaters", "eco", "eco friendly", "large green area",
        "green area", "central green", "waste", "recycling", "water conservation", "sustainability",
    },
}

CATEGORY_BLOCKLIST = {
    "water_leisure": {
        "treated water", "treated water supply", "sewage", "sewage treatment", "stp",
        "rainwater", "rain water", "rain water harvesting", "solar", "eco", "eco friendly",
    },
    "green_landscape": {
        "sewage treatment", "stp", "rain water", "rainwater", "treated water", "solar", "podium parking",
        "driveway", "internal road", "road", "entry", "retail", "tower", "clubhouse",
    },
    "open_space": {"stp", "sewage", "rainwater", "rain water", "treated water", "solar"},
    "access_circulation": {
        "swimming pool", "kids pool", "kids' pool", "gymnasium", "clubhouse", "large green area",
        "garden", "lawn", "sewage", "stp", "rainwater", "treated water", "football", "cricket",
    },
    "environment_sustainability": {"gymnasium", "badminton", "tennis", "squash", "football", "cricket", "snooker"},
}


STATUS_CLEAR = "Clear Winner"
STATUS_CLOSE = "Close Call"
STATUS_WEAK = "Weak Differentiator"
STATUS_INSUFFICIENT = "Insufficient Evidence"


def build_master_plan_comparison(
    project_a: ParsedProjectMetadata,
    area_a: AreaEstimateResult,
    category_a: CategoryComparisonResult,
    project_b: ParsedProjectMetadata,
    area_b: AreaEstimateResult,
    category_b: CategoryComparisonResult,
    project_c: ParsedProjectMetadata,
    area_c: AreaEstimateResult,
    category_c: CategoryComparisonResult,
    comparison_run_id: str | None = None,
    understanding_a: MasterPlanUnderstandingResult | None = None,
    understanding_b: MasterPlanUnderstandingResult | None = None,
    understanding_c: MasterPlanUnderstandingResult | None = None,
) -> MasterPlanComparisonResult:
    run_id = comparison_run_id or str(uuid4())
    bundles = [
        ("A", project_a, area_a, category_a, understanding_a),
        ("B", project_b, area_b, category_b, understanding_b),
        ("C", project_c, area_c, category_c, understanding_c),
    ]

    projects = [_project_summary(slot, project, area, category) for slot, project, area, category, _ in bundles]
    matrix = _build_category_matrix(bundles)
    winners = _build_category_winners(matrix)
    overall = _build_overall_recommendation(projects, winners, matrix)
    summary = _build_user_friendly_summary(winners, overall, matrix)
    internal_evidence_quality = _build_internal_evidence_quality(bundles)

    return MasterPlanComparisonResult(
        comparison_run_id=run_id,
        projects=projects,
        category_comparison_matrix=matrix,
        category_winners=winners,
        overall_recommendation=overall,
        user_friendly_summary=summary,
        internal_evidence_quality=internal_evidence_quality,
        notes=[
            "This comparison is based on estimated master-plan interpretation and Datacenter signals, not official measurements.",
            "OpenAI narrative generation may be used for frontend copy, but deterministic scoring decides winners.",
            "OpenCV and technical image-quality metrics are internal only and are not used as frontend copy.",
            "Category status controls whether the frontend should show a clear winner, close call, weak differentiator or insufficient evidence.",
            "Frontend cards should show rating/band labels; exact numeric scores are retained for internal QA only.",
        ],
    )


def _project_summary(
    slot: str,
    project: ParsedProjectMetadata,
    area: AreaEstimateResult,
    category: CategoryComparisonResult,
) -> ComparedProjectSummary:
    overall_score = category.overall_master_plan_summary.score
    overall_rating = category.overall_master_plan_summary.rating
    return ComparedProjectSummary(
        project_slot=slot,
        project_id=project.project_id,
        project_name=project.project_name,
        city=project.city,
        locality=project.locality,
        green_area_display=area.green_area_percentage.display,
        open_area_display=area.open_area_percentage.display,
        confidence_label=area.confidence.label,
        overall_category_score=overall_score,
        overall_category_rating=overall_rating,
        frontend_score_label=_frontend_score_label(overall_score, overall_rating),
    )


def _build_category_matrix(
    bundles: list[tuple[str, ParsedProjectMetadata, AreaEstimateResult, CategoryComparisonResult, MasterPlanUnderstandingResult | None]],
) -> list[CategoryComparisonMatrixRow]:
    category_maps = {slot: {item.category_key: item for item in category.category_scores} for slot, _, _, category, _ in bundles}
    understanding_maps = {slot: _understanding_evidence_map(understanding) for slot, _, _, _, understanding in bundles}
    rows: list[CategoryComparisonMatrixRow] = []

    for category_key in CATEGORY_PRIORITY_ORDER:
        comparisons: list[ProjectCategoryComparison] = []
        row_evidence_by_slot: dict[str, MasterPlanCategoryEvidence | None] = {}

        for slot, project, _, _, _ in bundles:
            category = category_maps[slot].get(category_key)
            if category is None:
                continue

            evidence = understanding_maps[slot].get(category_key)
            row_evidence_by_slot[slot] = evidence
            frontend_details = _best_frontend_details(category, evidence)

            comparisons.append(
                ProjectCategoryComparison(
                    project_slot=slot,
                    project_id=project.project_id,
                    project_name=project.project_name,
                    score=category.score,
                    rating=category.rating,
                    score_band=_score_band(category.score),
                    frontend_score_label=_frontend_score_label(category.score, category.rating),
                    confidence_label=category.confidence_label,
                    user_facing_one_liner=_make_project_category_one_liner(project, category, evidence),
                    best_details=frontend_details[:6],
                    risk_signals=_frontend_safe_risks(category.risk_signals)[:4],
                )
            )

        if not comparisons:
            continue

        winner = _pick_category_winner(comparisons, row_evidence_by_slot)
        winner_category = category_maps[winner.project_slot][category_key]
        winner_evidence = row_evidence_by_slot.get(winner.project_slot)
        score_gap = _score_gap(winner, comparisons)
        category_status = _category_status(winner, comparisons, winner_evidence)
        status_flags = _status_flags(category_status)
        evidence_strength = _evidence_strength(winner_evidence, winner)
        winner_reason = _build_deterministic_winner_reason(
            winner=winner,
            category=winner_category,
            all_projects=comparisons,
            evidence=winner_evidence,
            status=category_status,
        )
        tradeoff = _build_frontend_tradeoff(
            winner=winner,
            category=winner_category,
            all_projects=comparisons,
            evidence=winner_evidence,
            status=category_status,
        )
        category_summary = _build_deterministic_category_summary(
            winner=winner,
            category=winner_category,
            score_gap=score_gap,
            status=category_status,
        )
        declared_score, visible_score, spatial_score, confidence_score = _score_breakdown(winner, winner_evidence)
        declared_evidence = _category_clean_details(
            category_key,
            winner_evidence.declared_entities if winner_evidence else [],
            allow_raw_units=category_key == "built_density",
        )[:6]
        visible_evidence = _category_clean_details(
            category_key,
            winner_evidence.visible_entities if winner_evidence else [],
            allow_raw_units=category_key == "built_density",
        )[:6]
        spatial_evidence = _category_clean_details(
            category_key,
            winner_evidence.spatial_notes if winner_evidence else [],
            allow_raw_units=True,
        )[:4]

        rows.append(
            CategoryComparisonMatrixRow(
                category_key=category_key,
                category_label=FRONTEND_CATEGORY_LABELS.get(category_key, winner_category.category_label),
                project_scores=comparisons,
                winner_project_slot=winner.project_slot,
                winner_project_id=winner.project_id,
                winner_project_name=winner.project_name,
                winner_reason=winner_reason,
                tradeoff=tradeoff,
                frontend_winner_reason=winner_reason,
                frontend_tradeoff=tradeoff,
                frontend_category_summary=category_summary,
                category_status=category_status,
                evidence_strength=evidence_strength,
                confidence_badge=winner.confidence_label,
                show_as_decisive=status_flags["decisive"],
                show_as_close_call=status_flags["close"],
                show_as_weak=status_flags["weak"],
                show_as_insufficient=status_flags["insufficient"],
                show_winner_badge=status_flags["show_winner"],
                winner_badge_label=status_flags["winner_label"],
                declared_evidence=declared_evidence,
                visible_evidence=visible_evidence,
                spatial_evidence=spatial_evidence,
                internal_scoring=CategoryInternalScoring(
                    winner_score=winner.score,
                    score_gap=score_gap,
                    confidence_label=winner.confidence_label,
                    category_key=category_key,
                    declared_score=declared_score,
                    visible_score=visible_score,
                    spatial_score=spatial_score,
                    confidence_score=confidence_score,
                ),
            )
        )
    return rows


def _pick_category_winner(
    comparisons: list[ProjectCategoryComparison],
    evidence_by_slot: dict[str, MasterPlanCategoryEvidence | None],
) -> ProjectCategoryComparison:
    confidence_bonus = {"High": 3, "Medium": 1, "Low": -2, "Insufficient": -5}
    evidence_bonus = {"Strong": 3, "Moderate": 1, "Weak": -1, "Insufficient": -4}

    def ranking_key(item: ProjectCategoryComparison) -> tuple[int, int, int]:
        evidence = evidence_by_slot.get(item.project_slot)
        return (
            item.score + confidence_bonus.get(item.confidence_label, 0) + evidence_bonus.get(_evidence_strength(evidence, item), 0),
            len(item.best_details),
            -len(item.risk_signals),
        )

    return sorted(comparisons, key=ranking_key, reverse=True)[0]


def _build_category_winners(matrix: list[CategoryComparisonMatrixRow]) -> list[CategoryWinner]:
    return [
        CategoryWinner(
            category_key=row.category_key,
            category_label=row.category_label,
            winner_project_slot=row.winner_project_slot or "",
            winner_project_id=row.winner_project_id or "",
            winner_project_name=row.winner_project_name,
            winner_score=row.internal_scoring.winner_score,
            winner_reason=row.frontend_winner_reason,
            category_status=row.category_status,
            show_winner_badge=row.show_winner_badge,
        )
        for row in matrix
    ]


def _build_overall_recommendation(
    projects: list[ComparedProjectSummary],
    winners: list[CategoryWinner],
    matrix: list[CategoryComparisonMatrixRow],
) -> OverallMasterPlanRecommendation:
    decisive_rows = [row for row in matrix if row.show_as_decisive]
    scoring_rows = decisive_rows or [row for row in matrix if not row.show_as_insufficient] or matrix
    winner_counts = Counter(row.winner_project_slot for row in scoring_rows)
    score_by_slot = {project.project_slot: project.overall_category_score or 0 for project in projects}
    winning_project = sorted(
        projects,
        key=lambda p: (winner_counts.get(p.project_slot, 0), score_by_slot.get(p.project_slot, 0)),
        reverse=True,
    )[0]
    project_rows = [row for row in matrix if row.winner_project_slot == winning_project.project_slot and not row.show_as_insufficient]
    clear_rows = [row for row in project_rows if row.show_as_decisive]
    key_advantages = [_overall_advantage_copy(row.category_key, row.category_label) for row in (clear_rows or project_rows)[:5]]
    tradeoffs = _dedupe([row.frontend_tradeoff for row in project_rows if row.frontend_tradeoff])[:4]
    winner_name = winning_project.project_name or f"Project {winning_project.project_slot}"
    headline = f"{winner_name} has the strongest overall master-plan profile among the three."
    summary = (
        f"{winner_name} leads in {len(project_rows)} buyer-relevant categories after filtering weak or insufficient differentiators. "
        "Use this as a directional planning-quality comparison, while exact open/green area values should be checked against official layout or RERA documents."
    )
    return OverallMasterPlanRecommendation(
        winner_project_slot=winning_project.project_slot,
        winner_project_id=winning_project.project_id,
        winner_project_name=winning_project.project_name,
        score=winning_project.overall_category_score or 0,
        rating=winning_project.overall_category_rating or "Moderate",
        frontend_score_label=_frontend_score_label(winning_project.overall_category_score or 0, winning_project.overall_category_rating or "Moderate"),
        one_liner=headline,
        detailed_reason=summary,
        frontend_headline=headline,
        frontend_summary=summary,
        key_advantages=key_advantages,
        tradeoffs=tradeoffs,
    )


def _build_user_friendly_summary(
    winners: list[CategoryWinner],
    overall: OverallMasterPlanRecommendation,
    matrix: list[CategoryComparisonMatrixRow],
) -> UserFriendlyComparisonSummary:
    winner_by_category = {
        row.category_key: row
        for row in matrix
        if not row.show_as_insufficient and row.show_winner_badge
    }
    return UserFriendlyComparisonSummary(
        headline=overall.frontend_headline,
        short_summary=overall.frontend_summary,
        best_for_green_living=_winner_phrase(winner_by_category.get("green_landscape"), "green-led outdoor living"),
        best_for_amenities=_winner_phrase(winner_by_category.get("amenity_richness"), "overall amenity depth"),
        best_for_family_living=_winner_phrase(winner_by_category.get("family_community"), "family and community use"),
        best_for_access=_winner_phrase(winner_by_category.get("access_circulation"), "access and internal movement"),
        caution_note="Master plan images are often stylized; use this comparison as a planning-quality guide and verify exact open/green area from official documents.",
    )


def _build_internal_evidence_quality(bundles) -> InternalEvidenceQuality:
    project_evidence: list[InternalProjectEvidenceQuality] = []
    for slot, project, area, category, understanding in bundles:
        evidence_category = next((item for item in category.category_scores if item.category_key == "evidence_reliability"), None)
        technical_details: list[str] = []
        technical_warnings: list[str] = []
        if evidence_category:
            technical_details.extend(evidence_category.extracted_master_plan_details)
            technical_warnings.extend(evidence_category.risk_signals)
        technical_details.extend(area.confidence.reasons)
        technical_warnings.extend(area.warnings)
        if understanding:
            technical_details.extend(understanding.internal_processing_notes)
            technical_warnings.extend(understanding.technical_warnings)
        project_evidence.append(
            InternalProjectEvidenceQuality(
                project_slot=slot,
                project_id=project.project_id,
                project_name=project.project_name,
                confidence_label=area.confidence.label,
                technical_details=_dedupe(technical_details),
                technical_warnings=_dedupe(technical_warnings),
                master_plan_understanding_confidence=understanding.extraction_confidence_label if understanding else None,
                manual_correction_recommended=understanding.manual_correction.correction_recommended if understanding else False,
            )
        )
    return InternalEvidenceQuality(
        opencv_used_for_frontend_copy=False,
        frontend_excludes_technical_metrics=True,
        technical_metrics_are_internal_only=True,
        project_evidence=project_evidence,
        global_notes=[
            "OpenCV output is retained only for internal diagnostics.",
            "Frontend reasons are generated from deterministic winners, cleaned evidence entities and optional OpenAI narrative.",
            "Manual correction data can be used later to create labelled training examples.",
        ],
        manual_correction_available=True,
    )


def _understanding_evidence_map(understanding: MasterPlanUnderstandingResult | None) -> dict[str, MasterPlanCategoryEvidence]:
    if not understanding:
        return {}
    return {item.category_key: item for item in understanding.category_evidence}


def _best_frontend_details(category: CategoryInsight, evidence: MasterPlanCategoryEvidence | None) -> list[str]:
    details: list[str] = []
    if evidence:
        details.extend(evidence.visible_entities)
        details.extend(evidence.legend_entities)
        details.extend(evidence.declared_entities)
    details.extend(category.extracted_master_plan_details)
    return _category_clean_details(
        category.category_key,
        details,
        allow_raw_units=category.category_key == "built_density",
    )


def _evidence_strength(evidence: MasterPlanCategoryEvidence | None, winner: ProjectCategoryComparison | None = None) -> str:
    if evidence:
        cleaned_count = len(_category_clean_details(evidence.category_key, evidence.declared_entities + evidence.visible_entities + evidence.legend_entities))
        if cleaned_count == 0:
            return "Insufficient"
        if cleaned_count >= 4 and evidence.evidence_strength in {"Strong", "Moderate"}:
            return evidence.evidence_strength
        if cleaned_count >= 2:
            return "Moderate" if evidence.evidence_strength == "Strong" else evidence.evidence_strength
        return "Weak"
    if winner and len(winner.best_details) >= 4:
        return "Moderate"
    if winner and len(winner.best_details) >= 1:
        return "Weak"
    return "Insufficient"


def _category_status(
    winner: ProjectCategoryComparison,
    all_projects: list[ProjectCategoryComparison],
    evidence: MasterPlanCategoryEvidence | None,
) -> str:
    gap = _score_gap(winner, all_projects)
    strength = _evidence_strength(evidence, winner)
    if winner.score < 60 or strength == "Insufficient" or len(winner.best_details) == 0:
        return STATUS_INSUFFICIENT
    if gap <= 3:
        return STATUS_CLOSE
    if winner.score < 70 or strength == "Weak":
        return STATUS_WEAK
    return STATUS_CLEAR


def _status_flags(status: str) -> dict[str, bool | str]:
    if status == STATUS_INSUFFICIENT:
        winner_label = "No Clear Winner"
        show_winner = False
    elif status == STATUS_WEAK:
        winner_label = "Relative Edge"
        show_winner = True
    else:
        winner_label = "Winner"
        show_winner = True

    return {
        "decisive": status == STATUS_CLEAR,
        "close": status == STATUS_CLOSE,
        "weak": status == STATUS_WEAK,
        "insufficient": status == STATUS_INSUFFICIENT,
        "show_winner": show_winner,
        "winner_label": winner_label,
    }


def _score_breakdown(winner: ProjectCategoryComparison, evidence: MasterPlanCategoryEvidence | None) -> tuple[int, int, int, int]:
    declared_count = len(_category_clean_details(evidence.category_key, evidence.declared_entities)) if evidence else 0
    visible_count = len(_category_clean_details(evidence.category_key, evidence.visible_entities + evidence.legend_entities)) if evidence else 0
    spatial_count = len(_category_clean_details(evidence.category_key, evidence.spatial_notes, allow_raw_units=True)) if evidence else 0
    declared_score = min(100, 40 + declared_count * 10)
    visible_score = min(100, 35 + visible_count * 15)
    spatial_score = min(100, 35 + spatial_count * 20)
    confidence_score = {"High": 90, "Medium": 70, "Low": 45}.get(winner.confidence_label, 55)
    return declared_score, visible_score, spatial_score, confidence_score


def _winner_phrase(row: CategoryComparisonMatrixRow | None, label: str) -> str | None:
    if not row or row.show_as_insufficient:
        return None
    project_name = row.winner_project_name or f"Project {row.winner_project_slot}"
    if row.show_as_close_call:
        return f"{project_name} is marginally ahead for {label}."
    if row.show_as_weak:
        return f"{project_name} has a directional edge for {label}."
    return f"{project_name} is best for {label}."


def _make_project_category_one_liner(
    project: ParsedProjectMetadata,
    category: CategoryInsight,
    evidence: MasterPlanCategoryEvidence | None,
) -> str:
    project_name = project.project_name or "This project"
    details = _best_frontend_details(category, evidence)[:4]
    detail_text = _join_details(details)
    label = FRONTEND_CATEGORY_LABELS.get(category.category_key, category.category_label).lower()
    if not detail_text:
        return f"{project_name} has limited specific evidence for {label}."
    templates = {
        "green_landscape": f"{project_name} has green-living evidence around {detail_text}.",
        "open_space": f"{project_name} has open-space evidence around {detail_text}.",
        "built_density": f"{project_name} has density-comfort evidence around {detail_text}.",
        "amenity_richness": f"{project_name} has amenity evidence such as {detail_text}.",
        "sports_active_lifestyle": f"{project_name} has active-lifestyle evidence around {detail_text}.",
        "family_community": f"{project_name} has family/community evidence around {detail_text}.",
        "water_leisure": f"{project_name} has water/leisure evidence around {detail_text}.",
        "access_circulation": f"{project_name} has access/movement evidence around {detail_text}.",
        "environment_sustainability": f"{project_name} has sustainability evidence around {detail_text}.",
    }
    return templates.get(category.category_key, f"{project_name} is supported by {detail_text}.")


def _build_deterministic_winner_reason(
    winner: ProjectCategoryComparison,
    category: CategoryInsight,
    all_projects: list[ProjectCategoryComparison],
    evidence: MasterPlanCategoryEvidence | None,
    status: str,
) -> str:
    project_name = winner.project_name or f"Project {winner.project_slot}"
    label = FRONTEND_CATEGORY_LABELS.get(category.category_key, category.category_label).lower()
    details = _best_frontend_details(category, evidence)[:4] or winner.best_details[:4]
    detail_text = _join_details(details)

    if status == STATUS_INSUFFICIENT:
        return f"No clear winner can be established for {label}; the available plan details are too limited to make a confident comparison."
    if status == STATUS_CLOSE:
        return f"{project_name} is marginally ahead for {label}, mainly because of {detail_text}. Treat the next-best project as a close alternative."
    if status == STATUS_WEAK:
        return f"{project_name} has a directional edge for {label}, but this is not a major differentiator because the evidence is limited."
    if category.category_key == "built_density":
        return f"{project_name} is the stronger density-comfort pick because {detail_text} points to a less pressured layout profile than the alternatives."
    if detail_text:
        return f"{project_name} leads for {label} because the extracted evidence is stronger around {detail_text}."
    return f"{project_name} leads directionally for {label}, but the available category evidence should be reviewed before making this a primary claim."


def _build_frontend_tradeoff(
    winner: ProjectCategoryComparison,
    category: CategoryInsight,
    all_projects: list[ProjectCategoryComparison],
    evidence: MasterPlanCategoryEvidence | None,
    status: str,
) -> str:
    if status == STATUS_INSUFFICIENT:
        return "Do not show this as a winner-led category; use it only as an informational note until clearer layout evidence is available."
    if status == STATUS_CLOSE:
        return "The gap is small, so show this as a close call rather than a decisive win."
    if status == STATUS_WEAK:
        return "This is a directional edge, but it should not be treated as a major buying differentiator."
    if category.category_key == "environment_sustainability":
        return "These are feature-availability signals only; environmental certification or actual performance is not verified here."
    return "Treat this as a planning-quality signal, not an official measurement of area or amenity delivery."


def _build_deterministic_category_summary(
    winner: ProjectCategoryComparison,
    category: CategoryInsight,
    score_gap: int,
    status: str,
) -> str:
    label = FRONTEND_CATEGORY_LABELS.get(category.category_key, category.category_label)
    if status == STATUS_INSUFFICIENT:
        return f"{label} does not have enough evidence for a confident three-project ranking."
    if status == STATUS_CLOSE:
        return f"{label} is a close call; buyers should treat the leading project and the nearest alternative as comparable."
    if status == STATUS_WEAK:
        return f"{label} provides some differentiation, but it is not strong enough to be a primary decision factor."
    return f"{label} has a clear directional leader based on cleaned master-plan and project-data evidence."


def _overall_advantage_copy(category_key: str, category_label: str) -> str:
    return {
        "green_landscape": "Stronger garden-led outdoor living story.",
        "open_space": "Better openness and breathing-room signal.",
        "built_density": "More comfortable density profile.",
        "amenity_richness": "Broader lifestyle amenity coverage.",
        "sports_active_lifestyle": "Better active-lifestyle and sports coverage.",
        "family_community": "Stronger family and community-use planning.",
        "water_leisure": "Better pool and leisure-led recreation story.",
        "access_circulation": "Clearer access and internal movement planning.",
        "environment_sustainability": "More sustainability-related feature signals.",
    }.get(category_key, f"Leads on {category_label.lower()}.")


def _score_gap(winner: ProjectCategoryComparison, all_projects: list[ProjectCategoryComparison]) -> int:
    other_scores = [item.score for item in all_projects if item.project_slot != winner.project_slot]
    return int(winner.score - max(other_scores)) if other_scores else 0


def _score_band(score: int) -> str:
    if score >= 85:
        return "85–100"
    if score >= 70:
        return "70–84"
    if score >= 55:
        return "55–69"
    return "Below 55"


def _frontend_rating_label(score: int) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Strong"
    if score >= 55:
        return "Moderate"
    return "Limited"


def _frontend_score_label(score: int, rating: str | None = None) -> str:
    return f"{_frontend_rating_label(score)} ({_score_band(score)})"


def _category_clean_details(category_key: str, details: list[str], allow_raw_units: bool = False) -> list[str]:
    cleaned_details: list[str] = []
    allowlist = CATEGORY_ALLOWLIST.get(category_key, set())
    blocklist = CATEGORY_BLOCKLIST.get(category_key, set())

    for detail in details:
        cleaned = _normalize_detail(detail)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if any(term in lowered for term in TECHNICAL_TERMS_TO_HIDE):
            continue
        if lowered in GENERIC_EVIDENCE_TOKENS:
            continue
        if any(blocked in lowered for blocked in blocklist):
            continue
        if not allow_raw_units and re.fullmatch(r"[a-z\s/]+", lowered) and len(lowered) <= 4:
            continue
        if allowlist and not any(allowed in lowered for allowed in allowlist):
            continue
        cleaned_details.append(cleaned)

    return _dedupe(cleaned_details)


def _filter_frontend_details(details: list[str]) -> list[str]:
    # Kept for backward compatibility. Prefer _category_clean_details for new call sites.
    cleaned_details: list[str] = []
    for detail in details:
        cleaned = _normalize_detail(detail)
        lowered = cleaned.lower()
        if not cleaned:
            continue
        if any(term in lowered for term in TECHNICAL_TERMS_TO_HIDE):
            continue
        if lowered in GENERIC_EVIDENCE_TOKENS:
            continue
        cleaned_details.append(cleaned)
    return _dedupe(cleaned_details)


def _normalize_detail(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" -•:;,.|/")
    replacements = {
        "STP": "Sewage Treatment Plant",
        "AOS": "Amenity Open Space",
    }
    return replacements.get(cleaned, cleaned)


def _frontend_safe_risks(risks: list[str]) -> list[str]:
    safe = []
    for risk in risks:
        lowered = risk.lower()
        if "opencv" in lowered or "unknown/unclassified" in lowered:
            safe.append("Exact area estimates should be treated as directional because the master plan is not an official measurement drawing.")
            continue
        if "stylized" in lowered or "not to scale" in lowered:
            safe.append("Master plan visuals may be stylized and should be verified with official layout or RERA documents.")
            continue
        safe.append(risk)
    return _dedupe(safe)


def _join_details(details: list[str]) -> str:
    if not details:
        return ""
    if len(details) == 1:
        return details[0]
    if len(details) == 2:
        return f"{details[0]} and {details[1]}"
    return f"{', '.join(details[:-1])} and {details[-1]}"


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        cleaned = str(value).strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result
