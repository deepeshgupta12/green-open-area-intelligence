from __future__ import annotations

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
from app.schemas.master_plan_understanding_schema import MasterPlanCategoryEvidence, MasterPlanUnderstandingResult
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

TECHNICAL_TERMS_TO_HIDE = [
    "opencv", "unknown/unclassified", "unknown area", "segmentation", "pixel",
    "image quality:", "area estimate confidence", "confidence score", "score of",
]


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
    summary = _build_user_friendly_summary(winners, overall)
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
        ],
    )


def _project_summary(slot: str, project: ParsedProjectMetadata, area: AreaEstimateResult, category: CategoryComparisonResult) -> ComparedProjectSummary:
    return ComparedProjectSummary(
        project_slot=slot,
        project_id=project.project_id,
        project_name=project.project_name,
        city=project.city,
        locality=project.locality,
        green_area_display=area.green_area_percentage.display,
        open_area_display=area.open_area_percentage.display,
        confidence_label=area.confidence.label,
        overall_category_score=category.overall_master_plan_summary.score,
        overall_category_rating=category.overall_master_plan_summary.rating,
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
        winner_reason = _build_deterministic_winner_reason(winner, winner_category, comparisons, winner_evidence, category_status)
        tradeoff = _build_frontend_tradeoff(winner, winner_category, comparisons, winner_evidence, category_status)
        category_summary = _build_deterministic_category_summary(winner, winner_category, score_gap, category_status)
        declared_score, visible_score, spatial_score, confidence_score = _score_breakdown(winner, winner_evidence)

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
                show_as_insufficient=status_flags["insufficient"],
                declared_evidence=(winner_evidence.declared_entities if winner_evidence else [])[:6],
                visible_evidence=(winner_evidence.visible_entities if winner_evidence else [])[:6],
                spatial_evidence=(winner_evidence.spatial_notes if winner_evidence else [])[:4],
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


def _pick_category_winner(comparisons: list[ProjectCategoryComparison], evidence_by_slot: dict[str, MasterPlanCategoryEvidence | None]) -> ProjectCategoryComparison:
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
        )
        for row in matrix
    ]


def _build_overall_recommendation(projects: list[ComparedProjectSummary], winners: list[CategoryWinner], matrix: list[CategoryComparisonMatrixRow]) -> OverallMasterPlanRecommendation:
    decisive_rows = [row for row in matrix if row.show_as_decisive]
    winner_counts = Counter(row.winner_project_slot for row in decisive_rows) or Counter(item.winner_project_slot for item in winners)
    score_by_slot = {project.project_slot: project.overall_category_score or 0 for project in projects}
    winning_project = sorted(projects, key=lambda p: (winner_counts.get(p.project_slot, 0), score_by_slot.get(p.project_slot, 0)), reverse=True)[0]
    project_rows = [row for row in matrix if row.winner_project_slot == winning_project.project_slot and not row.show_as_insufficient]
    key_advantages = [_overall_advantage_copy(row.category_key, row.category_label) for row in project_rows[:5]]
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
        one_liner=headline,
        detailed_reason=summary,
        frontend_headline=headline,
        frontend_summary=summary,
        key_advantages=key_advantages,
        tradeoffs=tradeoffs,
    )


def _build_user_friendly_summary(winners: list[CategoryWinner], overall: OverallMasterPlanRecommendation) -> UserFriendlyComparisonSummary:
    winner_by_category = {item.category_key: item for item in winners}
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
        technical_details = []
        technical_warnings = []
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
            "Frontend reasons are generated from deterministic winners, extracted entities and optional OpenAI narrative.",
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
    return _filter_frontend_details(details)


def _evidence_strength(evidence: MasterPlanCategoryEvidence | None, winner: ProjectCategoryComparison | None = None) -> str:
    if evidence:
        return evidence.evidence_strength
    if winner and len(winner.best_details) >= 4:
        return "Moderate"
    if winner and len(winner.best_details) >= 1:
        return "Weak"
    return "Insufficient"


def _category_status(winner: ProjectCategoryComparison, all_projects: list[ProjectCategoryComparison], evidence: MasterPlanCategoryEvidence | None) -> str:
    gap = _score_gap(winner, all_projects)
    strength = _evidence_strength(evidence, winner)
    if winner.score < 60 or strength == "Insufficient" or len(winner.best_details) == 0:
        return "Insufficient Evidence"
    if gap <= 3:
        return "Close Call"
    if winner.score < 70 or strength == "Weak":
        return "Weak Differentiator"
    return "Clear Winner"


def _status_flags(status: str) -> dict[str, bool]:
    return {
        "decisive": status == "Clear Winner",
        "close": status == "Close Call",
        "insufficient": status == "Insufficient Evidence",
    }


def _score_breakdown(winner: ProjectCategoryComparison, evidence: MasterPlanCategoryEvidence | None) -> tuple[int, int, int, int]:
    declared_count = len(evidence.declared_entities) if evidence else 0
    visible_count = len(evidence.visible_entities) if evidence else 0
    spatial_count = len(evidence.spatial_notes) if evidence else 0
    declared_score = min(100, 40 + declared_count * 10)
    visible_score = min(100, 35 + visible_count * 15)
    spatial_score = min(100, 35 + spatial_count * 20)
    confidence_score = {"High": 90, "Medium": 70, "Low": 45}.get(winner.confidence_label, 55)
    return declared_score, visible_score, spatial_score, confidence_score


def _winner_phrase(winner: CategoryWinner | None, label: str) -> str | None:
    if not winner:
        return None
    return f"{winner.winner_project_name or 'Project ' + winner.winner_project_slot} looks best for {label}."


def _make_project_category_one_liner(project: ParsedProjectMetadata, category: CategoryInsight, evidence: MasterPlanCategoryEvidence | None) -> str:
    project_name = project.project_name or "This project"
    details = _best_frontend_details(category, evidence)[:4]
    detail_text = _join_details(details)
    if not detail_text:
        return f"{project_name} has limited specific evidence for {FRONTEND_CATEGORY_LABELS.get(category.category_key, category.category_label).lower()}."
    templates = {
        "green_landscape": f"{project_name} is better suited for garden-led outdoor living, with {detail_text} supporting the green-space story.",
        "open_space": f"{project_name} feels stronger on openness, with {detail_text} indicating usable outdoor or circulation space.",
        "built_density": f"{project_name} shows a more comfortable density signal, with {detail_text} helping explain the layout profile.",
        "amenity_richness": f"{project_name} offers stronger lifestyle depth, with amenities such as {detail_text}.",
        "sports_active_lifestyle": f"{project_name} works better for active households, with {detail_text} supporting sports and movement-led living.",
        "family_community": f"{project_name} is more family-oriented, with {detail_text} supporting kids, seniors, pets or social use cases.",
        "water_leisure": f"{project_name} has stronger leisure appeal, with {detail_text} supporting pool-side or clubhouse-led recreation.",
        "access_circulation": f"{project_name} gives clearer movement planning, with {detail_text} supporting entry, drop-off or internal circulation.",
        "environment_sustainability": f"{project_name} shows better sustainability feature coverage, with {detail_text} present in the project data.",
    }
    return templates.get(category.category_key, f"{project_name} is supported by {detail_text}.")


def _build_deterministic_winner_reason(winner: ProjectCategoryComparison, category: CategoryInsight, all_projects: list[ProjectCategoryComparison], evidence: MasterPlanCategoryEvidence | None, status: str) -> str:
    project_name = winner.project_name or f"Project {winner.project_slot}"
    details = _best_frontend_details(category, evidence)[:4] or winner.best_details[:4]
    detail_text = _join_details(details)
    if status == "Insufficient Evidence":
        return f"No strong winner is available for {FRONTEND_CATEGORY_LABELS.get(category.category_key, category.category_label).lower()}; the available plan details are too limited to make a decisive claim."
    if status == "Close Call":
        return f"{project_name} is only slightly ahead for {FRONTEND_CATEGORY_LABELS.get(category.category_key, category.category_label).lower()}, mainly because of {detail_text}."
    if category.category_key == "built_density":
        return f"{project_name} is the safer density-comfort pick because {detail_text} points to a less pressured layout profile than the alternatives."
    if detail_text:
        return f"{project_name} leads because it has clearer buyer-relevant evidence around {detail_text}."
    return f"{project_name} leads directionally, but the available category evidence should be reviewed before showing this as a decisive claim."


def _build_frontend_tradeoff(winner: ProjectCategoryComparison, category: CategoryInsight, all_projects: list[ProjectCategoryComparison], evidence: MasterPlanCategoryEvidence | None, status: str) -> str:
    if status == "Insufficient Evidence":
        return "Show this category as informational only; the master plan does not provide enough explicit detail to rank the projects confidently."
    if status == "Close Call":
        return "The gap between projects is small, so show this as a close call rather than a decisive win."
    if status == "Weak Differentiator":
        return "The winner is directional, but the evidence is not strong enough to make this a major buying differentiator."
    if category.category_key == "environment_sustainability":
        return "These are feature-availability signals only; environmental certification or actual performance is not verified here."
    return "Treat this as a planning-quality signal, not an official measurement of area or amenity delivery."


def _build_deterministic_category_summary(winner: ProjectCategoryComparison, category: CategoryInsight, score_gap: int, status: str) -> str:
    label = FRONTEND_CATEGORY_LABELS.get(category.category_key, category.category_label)
    if status == "Insufficient Evidence":
        return f"{label} should be treated as an insufficient-evidence category for this comparison."
    if status == "Close Call":
        return f"{label} is a close call; buyers should not over-index on this category alone."
    if status == "Weak Differentiator":
        return f"{label} provides some differentiation, but it is not a dominant deciding factor."
    return f"{label} has a clear directional leader based on extracted master-plan and project-data entities."


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


def _filter_frontend_details(details: list[str]) -> list[str]:
    cleaned_details = []
    for detail in details:
        cleaned = str(detail).strip()
        lowered = cleaned.lower()
        if not cleaned:
            continue
        if any(term in lowered for term in TECHNICAL_TERMS_TO_HIDE):
            continue
        if lowered in {"open", "green", "landscape", "tree", "pool", "leisure"}:
            continue
        cleaned_details.append(cleaned)
    return _dedupe(cleaned_details)


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
