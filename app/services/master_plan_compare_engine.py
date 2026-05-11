from __future__ import annotations

from collections import Counter
from uuid import uuid4

from app.schemas.area_schema import AreaEstimateResult
from app.schemas.category_insight_schema import CategoryComparisonResult, CategoryInsight
from app.schemas.master_plan_compare_schema import (
    CategoryComparisonMatrixRow,
    CategoryWinner,
    ComparedProjectSummary,
    MasterPlanComparisonResult,
    OverallMasterPlanRecommendation,
    ProjectCategoryComparison,
    UserFriendlyComparisonSummary,
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
    "evidence_reliability",
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
    summary = _build_user_friendly_summary(projects, winners, overall, matrix)

    return MasterPlanComparisonResult(
        comparison_run_id=run_id,
        projects=projects,
        category_comparison_matrix=matrix,
        category_winners=winners,
        overall_recommendation=overall,
        user_friendly_summary=summary,
        notes=[
            "This comparison is based on estimated planning signals, not official measurements.",
            "Category winners use score, confidence, extracted details and risk signals.",
            "If two projects are close, the winner reason should be treated as directional rather than absolute.",
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

    rows = []

    for category_key in CATEGORY_PRIORITY_ORDER:
        comparisons = []

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
                    user_facing_one_liner=_make_project_category_one_liner(project, category),
                    best_details=category.extracted_master_plan_details[:6],
                    risk_signals=category.risk_signals[:4],
                )
            )

        if not comparisons:
            continue

        winner = _pick_category_winner(comparisons)
        winner_category = category_maps[winner.project_slot][category_key]

        rows.append(
            CategoryComparisonMatrixRow(
                category_key=category_key,
                category_label=winner_category.category_label,
                project_scores=comparisons,
                winner_project_slot=winner.project_slot,
                winner_project_id=winner.project_id,
                winner_project_name=winner.project_name,
                winner_reason=_build_winner_reason(winner, winner_category),
                tradeoff=_build_tradeoff(winner_category),
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
    winners = []

    for row in matrix:
        winner_score = 0
        for item in row.project_scores:
            if item.project_slot == row.winner_project_slot:
                winner_score = item.score
                break

        winners.append(
            CategoryWinner(
                category_key=row.category_key,
                category_label=row.category_label,
                winner_project_slot=row.winner_project_slot or "",
                winner_project_id=row.winner_project_id or "",
                winner_project_name=row.winner_project_name,
                winner_score=winner_score,
                winner_reason=row.winner_reason,
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
        f"Leads on {item.category_label.lower()}."
        for item in project_winners[:5]
    ]

    tradeoffs = []
    for row in matrix:
        if row.winner_project_slot == winning_project.project_slot and row.tradeoff:
            tradeoffs.append(row.tradeoff)
    tradeoffs = _dedupe(tradeoffs)[:4]

    return OverallMasterPlanRecommendation(
        winner_project_slot=winning_project.project_slot,
        winner_project_id=winning_project.project_id,
        winner_project_name=winning_project.project_name,
        score=winning_project.overall_category_score or 0,
        rating=winning_project.overall_category_rating or "Moderate",
        one_liner=(
            f"{winning_project.project_name or 'This project'} is the strongest overall master-plan pick because it leads across "
            f"{len(project_winners)} planning categories."
        ),
        detailed_reason=(
            f"{winning_project.project_name or 'The winning project'} performs best across the most category dimensions, "
            "combining planning breadth, category depth and available evidence quality. Treat this as a directional comparison because the model still depends on estimated master-plan interpretation."
        ),
        key_advantages=key_advantages,
        tradeoffs=tradeoffs,
    )


def _build_user_friendly_summary(
    projects: list[ComparedProjectSummary],
    winners: list[CategoryWinner],
    overall: OverallMasterPlanRecommendation,
    matrix: list[CategoryComparisonMatrixRow],
) -> UserFriendlyComparisonSummary:
    winner_by_category = {item.category_key: item for item in winners}

    return UserFriendlyComparisonSummary(
        headline=(
            f"{overall.winner_project_name or 'Project ' + overall.winner_project_slot} comes out strongest overall on master-plan quality."
        ),
        short_summary=(
            "The comparison looks at greenery, open space, built density, amenities, sports, family spaces, water/leisure, access and evidence reliability. "
            "The winner is based on category-level strengths, not just one aggregate score."
        ),
        best_for_green_living=_winner_phrase(winner_by_category.get("green_landscape"), "green living"),
        best_for_amenities=_winner_phrase(winner_by_category.get("amenity_richness"), "amenity depth"),
        best_for_family_living=_winner_phrase(winner_by_category.get("family_community"), "family living"),
        best_for_access=_winner_phrase(winner_by_category.get("access_circulation"), "access and internal movement"),
        caution_note=(
            "Use this as a planning-quality comparison, not an official area or RERA measurement."
        ),
    )


def _winner_phrase(winner: CategoryWinner | None, label: str) -> str | None:
    if not winner:
        return None

    return f"{winner.winner_project_name or 'Project ' + winner.winner_project_slot} looks best for {label}."


def _make_project_category_one_liner(
    project: ParsedProjectMetadata,
    category: CategoryInsight,
) -> str:
    details = category.extracted_master_plan_details[:4]
    detail_text = ", ".join(details)

    if detail_text:
        return (
            f"{project.project_name or 'This project'} is rated {category.rating.lower()} for "
            f"{category.category_label.lower()} because of {detail_text}."
        )

    return (
        f"{project.project_name or 'This project'} is rated {category.rating.lower()} for "
        f"{category.category_label.lower()} based on available master-plan and Datacenter evidence."
    )


def _build_winner_reason(
    winner: ProjectCategoryComparison,
    category: CategoryInsight,
) -> str:
    details = ", ".join(winner.best_details[:4])

    if details:
        return (
            f"{winner.project_name or 'Project ' + winner.project_slot} leads this category with a score of "
            f"{winner.score}, supported by {details}."
        )

    return (
        f"{winner.project_name or 'Project ' + winner.project_slot} leads this category with a score of "
        f"{winner.score} and stronger available evidence than the other compared projects."
    )


def _build_tradeoff(category: CategoryInsight) -> str:
    if category.risk_signals:
        return category.risk_signals[0]

    if category.confidence_label != "High":
        return f"Confidence is {category.confidence_label.lower()}, so the result should be treated as directional."

    return "No major category-specific tradeoff detected from available evidence."


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
