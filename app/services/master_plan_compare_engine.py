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
from app.schemas.project_schema import ParsedProjectMetadata


# Frontend-facing categories only.
# Evidence Reliability is intentionally excluded and moved to internal_evidence_quality.
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
    "opencv",
    "unknown/unclassified",
    "unknown area",
    "segmentation",
    "pixel",
    "image quality:",
    "area estimate confidence",
    "confidence score",
    "score of",
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
) -> MasterPlanComparisonResult:
    run_id = comparison_run_id or str(uuid4())

    bundles = [
        ("A", project_a, area_a, category_a),
        ("B", project_b, area_b, category_b),
        ("C", project_c, area_c, category_c),
    ]

    projects = [
        _project_summary(slot, project, area, category)
        for slot, project, area, category in bundles
    ]

    matrix = _build_category_matrix(bundles)
    winners = _build_category_winners(matrix)
    overall = _build_overall_recommendation(projects, winners, matrix)
    summary = _build_user_friendly_summary(projects, winners, overall)
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
        ],
    )


def _project_summary(
    slot: str,
    project: ParsedProjectMetadata,
    area: AreaEstimateResult,
    category: CategoryComparisonResult,
) -> ComparedProjectSummary:
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
    bundles: list[tuple[str, ParsedProjectMetadata, AreaEstimateResult, CategoryComparisonResult]],
) -> list[CategoryComparisonMatrixRow]:
    category_maps = {
        slot: {item.category_key: item for item in category.category_scores}
        for slot, _, _, category in bundles
    }

    rows: list[CategoryComparisonMatrixRow] = []

    for category_key in CATEGORY_PRIORITY_ORDER:
        comparisons: list[ProjectCategoryComparison] = []

        for slot, project, _, _ in bundles:
            category = category_maps[slot].get(category_key)
            if category is None:
                continue

            comparisons.append(
                ProjectCategoryComparison(
                    project_slot=slot,
                    project_id=project.project_id,
                    project_name=project.project_name,
                    score=category.score,
                    rating=category.rating,
                    confidence_label=category.confidence_label,
                    user_facing_one_liner=_make_project_category_one_liner(
                        project=project,
                        category=category,
                    ),
                    best_details=_filter_frontend_details(category.extracted_master_plan_details)[:6],
                    risk_signals=_frontend_safe_risks(category.risk_signals)[:4],
                )
            )

        if not comparisons:
            continue

        winner = _pick_category_winner(comparisons)
        winner_category = category_maps[winner.project_slot][category_key]
        score_gap = _score_gap(winner, comparisons)
        winner_reason = _build_deterministic_winner_reason(
            winner=winner,
            category=winner_category,
            all_projects=comparisons,
        )
        tradeoff = _build_frontend_tradeoff(
            winner=winner,
            category=winner_category,
            all_projects=comparisons,
        )
        category_summary = _build_deterministic_category_summary(
            winner=winner,
            category=winner_category,
            score_gap=score_gap,
        )

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
                internal_scoring=CategoryInternalScoring(
                    winner_score=winner.score,
                    score_gap=score_gap,
                    confidence_label=winner.confidence_label,
                    category_key=category_key,
                ),
            )
        )

    return rows


def _pick_category_winner(
    comparisons: list[ProjectCategoryComparison],
) -> ProjectCategoryComparison:
    confidence_bonus = {
        "High": 3,
        "Medium": 1,
        "Low": -2,
        "Insufficient": -5,
    }

    def ranking_key(item: ProjectCategoryComparison) -> tuple[int, int, int]:
        return (
            item.score + confidence_bonus.get(item.confidence_label, 0),
            len(item.best_details),
            -len(item.risk_signals),
        )

    return sorted(comparisons, key=ranking_key, reverse=True)[0]


def _build_category_winners(matrix: list[CategoryComparisonMatrixRow]) -> list[CategoryWinner]:
    winners: list[CategoryWinner] = []

    for row in matrix:
        winner_score = row.internal_scoring.winner_score

        winners.append(
            CategoryWinner(
                category_key=row.category_key,
                category_label=row.category_label,
                winner_project_slot=row.winner_project_slot or "",
                winner_project_id=row.winner_project_id or "",
                winner_project_name=row.winner_project_name,
                winner_score=winner_score,
                winner_reason=row.frontend_winner_reason,
            )
        )

    return winners


def _build_overall_recommendation(
    projects: list[ComparedProjectSummary],
    winners: list[CategoryWinner],
    matrix: list[CategoryComparisonMatrixRow],
) -> OverallMasterPlanRecommendation:
    winner_counts = Counter(item.winner_project_slot for item in winners)

    score_by_slot = {
        project.project_slot: project.overall_category_score or 0
        for project in projects
    }

    def overall_key(project: ComparedProjectSummary) -> tuple[int, int]:
        return (
            winner_counts.get(project.project_slot, 0),
            score_by_slot.get(project.project_slot, 0),
        )

    winning_project = sorted(projects, key=overall_key, reverse=True)[0]

    project_winners = [
        item for item in winners if item.winner_project_slot == winning_project.project_slot
    ]

    key_advantages = [
        _overall_advantage_copy(item.category_key, item.category_label)
        for item in project_winners[:5]
    ]

    tradeoffs = _dedupe(
        [
            row.frontend_tradeoff
            for row in matrix
            if row.winner_project_slot == winning_project.project_slot and row.frontend_tradeoff
        ]
    )[:4]

    winner_name = winning_project.project_name or f"Project {winning_project.project_slot}"

    headline = (
        f"{winner_name} has the strongest overall master-plan profile among the three."
    )
    summary = (
        f"{winner_name} leads in {len(project_winners)} buyer-relevant categories and performs strongly across the overall planning mix. "
        "Use this as a directional comparison, while exact open/green area values should be checked against official layout or RERA documents."
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


def _build_user_friendly_summary(
    projects: list[ComparedProjectSummary],
    winners: list[CategoryWinner],
    overall: OverallMasterPlanRecommendation,
) -> UserFriendlyComparisonSummary:
    winner_by_category = {item.category_key: item for item in winners}

    return UserFriendlyComparisonSummary(
        headline=overall.frontend_headline,
        short_summary=overall.frontend_summary,
        best_for_green_living=_winner_phrase(winner_by_category.get("green_landscape"), "green-led outdoor living"),
        best_for_amenities=_winner_phrase(winner_by_category.get("amenity_richness"), "overall amenity depth"),
        best_for_family_living=_winner_phrase(winner_by_category.get("family_community"), "family and community use"),
        best_for_access=_winner_phrase(winner_by_category.get("access_circulation"), "access and internal movement"),
        caution_note=(
            "Master plan images are often stylized; use this comparison as a planning-quality guide and verify exact open/green area from official documents."
        ),
    )


def _build_internal_evidence_quality(
    bundles: list[tuple[str, ParsedProjectMetadata, AreaEstimateResult, CategoryComparisonResult]],
) -> InternalEvidenceQuality:
    project_evidence: list[InternalProjectEvidenceQuality] = []

    for slot, project, area, category in bundles:
        evidence_category = next(
            (
                item
                for item in category.category_scores
                if item.category_key == "evidence_reliability"
            ),
            None,
        )

        technical_details = []
        technical_warnings = []

        if evidence_category:
            technical_details.extend(evidence_category.extracted_master_plan_details)
            technical_warnings.extend(evidence_category.risk_signals)

        technical_details.extend(area.confidence.reasons)
        technical_warnings.extend(area.warnings)

        project_evidence.append(
            InternalProjectEvidenceQuality(
                project_slot=slot,
                project_id=project.project_id,
                project_name=project.project_name,
                confidence_label=area.confidence.label,
                technical_details=_dedupe(technical_details),
                technical_warnings=_dedupe(technical_warnings),
            )
        )

    return InternalEvidenceQuality(
        opencv_used_for_frontend_copy=False,
        frontend_excludes_technical_metrics=True,
        technical_metrics_are_internal_only=True,
        project_evidence=project_evidence,
        global_notes=[
            "OpenCV output is retained only for internal diagnostics.",
            "OpenCV unknown/unclassified area must not appear in frontend winner reasons.",
            "Frontend reasons are generated from deterministic category winners and extracted buyer-relevant entities.",
        ],
    )


def _winner_phrase(winner: CategoryWinner | None, label: str) -> str | None:
    if not winner:
        return None

    project_name = winner.winner_project_name or f"Project {winner.winner_project_slot}"
    return f"{project_name} looks best for {label}."


def _make_project_category_one_liner(
    project: ParsedProjectMetadata,
    category: CategoryInsight,
) -> str:
    project_name = project.project_name or "This project"
    details = _filter_frontend_details(category.extracted_master_plan_details)[:4]
    detail_text = _join_details(details)

    if category.category_key == "green_landscape":
        if detail_text:
            return (
                f"{project_name} is better suited for garden-led outdoor living, with {detail_text} supporting the green-space story."
            )
        return f"{project_name} has limited visible green-planning evidence in the available master-plan inputs."

    if category.category_key == "open_space":
        if detail_text:
            return (
                f"{project_name} feels stronger on openness, with {detail_text} indicating more usable outdoor and circulation space."
            )
        return f"{project_name} has limited specific open-space details available for comparison."

    if category.category_key == "built_density":
        if detail_text:
            return (
                f"{project_name} shows a more comfortable density signal, with {detail_text} helping explain the built-footprint reading."
            )
        return f"{project_name} has limited density-specific evidence beyond estimated built-footprint interpretation."

    if category.category_key == "amenity_richness":
        if detail_text:
            return (
                f"{project_name} offers stronger lifestyle depth, with amenities such as {detail_text}."
            )
        return f"{project_name} has limited amenity evidence in the parsed data."

    if category.category_key == "sports_active_lifestyle":
        if detail_text:
            return (
                f"{project_name} works better for active households, with {detail_text} supporting sports and movement-led living."
            )
        return f"{project_name} has limited sports-specific planning evidence."

    if category.category_key == "family_community":
        if detail_text:
            return (
                f"{project_name} is more family-oriented, with {detail_text} supporting kids, seniors, pets and social use cases."
            )
        return f"{project_name} has limited family/community-specific evidence."

    if category.category_key == "water_leisure":
        if detail_text:
            return (
                f"{project_name} has stronger leisure appeal, with {detail_text} supporting pool-side or clubhouse-led recreation."
            )
        return f"{project_name} has limited water/leisure evidence."

    if category.category_key == "access_circulation":
        if detail_text:
            return (
                f"{project_name} gives clearer movement planning, with {detail_text} supporting day-to-day entry, drop-off and internal circulation."
            )
        return f"{project_name} has limited access/circulation evidence in the available master-plan data."

    if category.category_key == "environment_sustainability":
        if detail_text:
            return (
                f"{project_name} shows better sustainability feature coverage, with {detail_text} present in the project data."
            )
        return f"{project_name} has limited sustainability-specific evidence."

    if detail_text:
        return f"{project_name} is rated {category.rating.lower()} for {category.category_label.lower()}, supported by {detail_text}."

    return f"{project_name} has available evidence for {category.category_label.lower()}, but the comparison should be treated as directional."


def _build_deterministic_winner_reason(
    winner: ProjectCategoryComparison,
    category: CategoryInsight,
    all_projects: list[ProjectCategoryComparison],
) -> str:
    project_name = winner.project_name or f"Project {winner.project_slot}"
    details = _filter_frontend_details(winner.best_details)[:4]
    detail_text = _join_details(details)
    margin = _score_gap(winner, all_projects)

    if category.category_key == "built_density":
        if detail_text:
            return (
                f"{project_name} is the safer density-comfort pick because {detail_text} points to a less pressured layout profile than the alternatives."
            )
        return (
            f"{project_name} has the best density-comfort signal among the three, but the evidence should be checked against official layout drawings."
        )

    if category.category_key == "access_circulation" and winner.score < 60:
        return (
            f"{project_name} is only a relative pick for access and circulation; all three projects have limited explicit movement-planning details."
        )

    if detail_text:
        if margin <= 3:
            return (
                f"{project_name} is marginally ahead because it has slightly clearer evidence around {detail_text}; show this as a close comparison."
            )

        return (
            f"{project_name} leads because it has clearer buyer-relevant evidence around {detail_text}."
        )

    return (
        f"{project_name} leads directionally, but the available category evidence is thin."
    )


def _build_frontend_tradeoff(
    winner: ProjectCategoryComparison,
    category: CategoryInsight,
    all_projects: list[ProjectCategoryComparison],
) -> str:
    project_name = winner.project_name or f"Project {winner.project_slot}"

    if category.category_key == "access_circulation" and winner.score < 60:
        return (
            "Access and circulation details are limited across all three projects, so avoid showing this as a strong differentiator."
        )

    if category.category_key == "environment_sustainability":
        return (
            "These are feature-availability signals only; environmental certification or actual performance is not verified here."
        )

    if winner.confidence_label != "High":
        return (
            f"{project_name} leads this category directionally, but exact area or layout interpretation should be checked with official documents."
        )

    if _is_close_category(winner, all_projects):
        return (
            "The gap between projects is small, so show this as a close call rather than a decisive win."
        )

    return (
        "Treat this as a planning-quality signal, not an official measurement of area or amenity delivery."
    )


def _build_deterministic_category_summary(
    winner: ProjectCategoryComparison,
    category: CategoryInsight,
    score_gap: int,
) -> str:
    project_name = winner.project_name or f"Project {winner.project_slot}"

    if score_gap <= 3:
        return (
            f"{project_name} is slightly ahead in this category, but the difference is narrow."
        )

    return (
        f"{project_name} is the directional category leader based on the available master-plan and project-data details."
    )


def _overall_advantage_copy(category_key: str, category_label: str) -> str:
    if category_key == "green_landscape":
        return "Stronger garden-led outdoor living story."
    if category_key == "open_space":
        return "Better openness and breathing-room signal."
    if category_key == "built_density":
        return "More comfortable density profile."
    if category_key == "amenity_richness":
        return "Broader lifestyle amenity coverage."
    if category_key == "sports_active_lifestyle":
        return "Better active-lifestyle and sports coverage."
    if category_key == "family_community":
        return "Stronger family and community-use planning."
    if category_key == "water_leisure":
        return "Better pool and leisure-led recreation story."
    if category_key == "access_circulation":
        return "Clearer access and internal movement planning."
    if category_key == "environment_sustainability":
        return "More sustainability-related feature signals."

    return f"Leads on {category_label.lower()}."


def _score_gap(
    winner: ProjectCategoryComparison,
    all_projects: list[ProjectCategoryComparison],
) -> int:
    other_scores = [item.score for item in all_projects if item.project_slot != winner.project_slot]
    if not other_scores:
        return 0

    return int(winner.score - max(other_scores))


def _is_close_category(
    winner: ProjectCategoryComparison,
    all_projects: list[ProjectCategoryComparison],
) -> bool:
    return _score_gap(winner, all_projects) <= 3


def _filter_frontend_details(details: list[str]) -> list[str]:
    cleaned_details: list[str] = []

    for detail in details:
        cleaned = str(detail).strip()
        if not cleaned:
            continue

        lowered = cleaned.lower()

        if any(term in lowered for term in TECHNICAL_TERMS_TO_HIDE):
            continue

        if lowered in {"open", "green", "landscape", "tree", "pool"}:
            continue

        cleaned_details.append(cleaned)

    return _dedupe(cleaned_details)


def _frontend_safe_risks(risks: list[str]) -> list[str]:
    safe: list[str] = []

    for risk in risks:
        lowered = risk.lower()

        if "opencv" in lowered or "unknown/unclassified" in lowered:
            safe.append(
                "Exact area estimates should be treated as directional because the master plan is not an official measurement drawing."
            )
            continue

        if "stylized" in lowered or "not to scale" in lowered:
            safe.append(
                "Master plan visuals may be stylized and should be verified with official layout or RERA documents."
            )
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
