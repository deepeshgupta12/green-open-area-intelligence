from __future__ import annotations

import re

from app.schemas.master_plan_compare_schema import MasterPlanComparisonResult


BANNED_FRONTEND_TERMS = [
    "opencv",
    "unknown/unclassified",
    "unknown area",
    "segmentation",
    "pixel",
    "image quality",
    "area estimate confidence",
]

THREE_PROJECT_PHRASES = [
    (re.compile(r"\bboth projects\b", flags=re.IGNORECASE), "the alternatives"),
    (re.compile(r"\bboth alternatives\b", flags=re.IGNORECASE), "the alternatives"),
]

WATER_LEISURE_BLOCKED_CHIPS = [
    "treated water",
    "treated water supply",
    "24*7 water supply",
    "24 x 7 water supply",
    "24/7 water supply",
    "water supply",
    "sewage",
    "sewage treatment",
    "stp",
    "rainwater",
    "rain water",
    "solar",
    "eco",
]

CLEAR_WINNER_NARROW_PATTERNS = [
    "gap is narrow",
    "difference is narrow",
    "gap is small",
    "difference is small",
    "close call",
    "close comparison",
    "slight edge",
    "slightly ahead",
]


STATUS_CLEAR = "Clear Winner"
STATUS_CLOSE = "Close Call"
STATUS_WEAK = "Weak Differentiator"
STATUS_INSUFFICIENT = "Insufficient Evidence"


ACCESS_FRONTEND_ALLOWED_TOKENS = [
    "driveway",
    "entry",
    "drop",
    "drop-off",
    "drop off",
    "internal road",
    "vehicular",
    "pedestrian",
    "access",
    "frontage",
    "gate",
    "ramp",
    "circulation",
    "parking",
    "movement",
    "podium parking",
]

ACCESS_FRONTEND_BLOCKED_TOKENS = [
    "lobby",
    "lobbies",
    "entrance lobby",
    "entrance lobbies",
    "double height",
    "double-height",
]


def finalize_frontend_comparison_contract(
    comparison: MasterPlanComparisonResult,
) -> MasterPlanComparisonResult:
    """Final frontend contract hardening before API response/report writing.

    This function intentionally mutates and returns the same comparison object.
    It is the last guardrail after deterministic scoring and optional OpenAI copy.
    """

    for row in comparison.category_comparison_matrix:
        _normalize_status_display(row)
        _clean_row_evidence(row)
        _sanitize_row_copy(row)
        _sync_legacy_copy_fields(row)

    _sanitize_overall_copy(comparison)
    _validate_frontend_contract(comparison)
    return comparison


def _normalize_status_display(row) -> None:
    if row.show_as_insufficient or row.category_status == STATUS_INSUFFICIENT:
        row.category_status = STATUS_INSUFFICIENT
        row.show_as_decisive = False
        row.show_as_close_call = False
        row.show_as_weak = False
        row.show_as_insufficient = True
        row.show_winner_badge = False
        row.winner_badge_label = "No Clear Winner"
        return

    if row.show_as_weak or row.category_status == STATUS_WEAK:
        row.category_status = STATUS_WEAK
        row.show_as_decisive = False
        row.show_as_close_call = False
        row.show_as_weak = True
        row.show_as_insufficient = False
        row.show_winner_badge = True
        row.winner_badge_label = "Relative Edge"
        return

    if row.show_as_close_call or row.category_status == STATUS_CLOSE:
        row.category_status = STATUS_CLOSE
        row.show_as_decisive = False
        row.show_as_close_call = True
        row.show_as_weak = False
        row.show_as_insufficient = False
        if row.internal_scoring.score_gap <= 0:
            row.show_winner_badge = False
            row.winner_badge_label = "No Clear Winner"
        else:
            row.show_winner_badge = True
            row.winner_badge_label = "Winner"
        return

    row.category_status = STATUS_CLEAR
    row.show_as_decisive = True
    row.show_as_close_call = False
    row.show_as_weak = False
    row.show_as_insufficient = False
    row.show_winner_badge = True
    row.winner_badge_label = "Winner"


def _clean_row_evidence(row) -> None:
    row.declared_evidence = _clean_evidence_list(row.category_key, row.declared_evidence)
    row.visible_evidence = _clean_evidence_list(row.category_key, row.visible_evidence)
    row.spatial_evidence = _clean_evidence_list(row.category_key, row.spatial_evidence)

    for score in row.project_scores:
        score.best_details = _clean_evidence_list(row.category_key, score.best_details)

    _sanitize_access_circulation_evidence(row)


def _clean_evidence_list(category_key: str, values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue

        lowered = cleaned.lower()
        if category_key == "water_leisure" and any(term in lowered for term in WATER_LEISURE_BLOCKED_CHIPS):
            continue

        key = lowered
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)

    return result



def _sanitize_access_circulation_evidence(row) -> None:
    if getattr(row, "category_key", None) != "access_circulation":
        return

    def is_allowed(value: str) -> bool:
        lowered = str(value or "").lower()

        if any(token in lowered for token in ACCESS_FRONTEND_BLOCKED_TOKENS):
            return False

        return any(token in lowered for token in ACCESS_FRONTEND_ALLOWED_TOKENS)

    row.visible_evidence = [
        item for item in getattr(row, "visible_evidence", [])
        if is_allowed(item)
    ]
    row.declared_evidence = [
        item for item in getattr(row, "declared_evidence", [])
        if is_allowed(item)
    ]
    row.spatial_evidence = [
        item for item in getattr(row, "spatial_evidence", [])
        if is_allowed(item)
    ]

    for score in getattr(row, "project_scores", []):
        score.best_details = [
            item for item in getattr(score, "best_details", [])
            if is_allowed(item)
        ]

def _sanitize_row_copy(row) -> None:
    row.frontend_winner_reason = _sanitize_text(row.frontend_winner_reason)
    row.frontend_tradeoff = _sanitize_text(row.frontend_tradeoff)
    row.frontend_category_summary = _sanitize_text(row.frontend_category_summary)

    project_name = row.winner_project_name or f"Project {row.winner_project_slot}"
    category_label = row.category_label.lower()
    evidence = _join_for_copy((row.visible_evidence + row.declared_evidence + row.spatial_evidence)[:2])

    if row.show_as_insufficient:
        row.frontend_winner_reason = (
            f"No clear winner can be established for {category_label}; the available plan details are not strong enough to rank the projects confidently."
        )
        row.frontend_tradeoff = (
            "Use this category as informational only until clearer layout or official project evidence is available."
        )
        row.frontend_category_summary = (
            f"{row.category_label} should not be treated as a decisive comparison factor in this run."
        )
        return

    if row.show_as_weak:
        row.frontend_winner_reason = (
            f"{project_name} has a directional edge for {category_label}"
            + (f" through {evidence}" if evidence else "")
            + ", but it is not strong enough to be a major buying differentiator."
        )
        row.frontend_tradeoff = (
            "Use this as a supporting signal, not as a primary reason to prefer one project over another."
        )
        row.frontend_category_summary = (
            f"{row.category_label} provides some differentiation, but the evidence is moderate."
        )
        return

    if row.show_as_close_call:
        if row.internal_scoring.score_gap <= 0:
            row.frontend_winner_reason = (
                f"This is a close call: no clear winner can be established for {category_label} because the compared projects are effectively tied on the available cleaned evidence."
            )
            row.frontend_tradeoff = (
                "Use this category as shared context rather than a reason to prefer one project over another."
            )
            row.frontend_category_summary = (
                f"{row.category_label} is useful context, but it does not create a meaningful ranking difference in this run."
            )
            return
        row.frontend_winner_reason = (
            f"{project_name} is marginally ahead for {category_label}"
            + (f", mainly due to {evidence}" if evidence else "")
            + "; the nearest alternative should still be treated as comparable."
        )
        row.frontend_tradeoff = (
            "The difference is small, so show this as a close call rather than a decisive win."
        )
        row.frontend_category_summary = (
            f"{row.category_label} is useful context, but buyers should not over-index on this category alone."
        )
        return

    # Clear winner copy guardrail.
    if row.show_as_decisive and row.internal_scoring.score_gap >= 8:
        lowered_tradeoff = row.frontend_tradeoff.lower()
        if any(pattern in lowered_tradeoff for pattern in CLEAR_WINNER_NARROW_PATTERNS):
            row.frontend_tradeoff = (
                f"{project_name} has a clear directional lead in this category, but the result should still be verified against official project documents."
            )


def _sync_legacy_copy_fields(row) -> None:
    row.winner_reason = row.frontend_winner_reason
    row.tradeoff = row.frontend_tradeoff


def _sanitize_overall_copy(comparison: MasterPlanComparisonResult) -> None:
    comparison.overall_recommendation.one_liner = _sanitize_text(comparison.overall_recommendation.one_liner)
    comparison.overall_recommendation.detailed_reason = _sanitize_text(comparison.overall_recommendation.detailed_reason)
    comparison.overall_recommendation.frontend_headline = _sanitize_text(comparison.overall_recommendation.frontend_headline)
    comparison.overall_recommendation.frontend_summary = _sanitize_text(comparison.overall_recommendation.frontend_summary)

    comparison.user_friendly_summary.headline = _sanitize_text(comparison.user_friendly_summary.headline)
    comparison.user_friendly_summary.short_summary = _sanitize_text(comparison.user_friendly_summary.short_summary)
    comparison.user_friendly_summary.caution_note = _sanitize_text(comparison.user_friendly_summary.caution_note or "")

    for attr in [
        "best_for_green_living",
        "best_for_amenities",
        "best_for_family_living",
        "best_for_access",
    ]:
        value = getattr(comparison.user_friendly_summary, attr)
        if value:
            setattr(comparison.user_friendly_summary, attr, _sanitize_text(value))

    comparison.overall_recommendation.tradeoffs = [
        _sanitize_text(value) for value in comparison.overall_recommendation.tradeoffs
    ]
    comparison.overall_recommendation.key_advantages = [
        _sanitize_text(value) for value in comparison.overall_recommendation.key_advantages
    ]


def _sanitize_text(value: str) -> str:
    text = str(value or "").strip()
    for pattern, replacement in THREE_PROJECT_PHRASES:
        text = pattern.sub(replacement, text)
    text = " ".join(text.split())
    return text


def _validate_frontend_contract(comparison: MasterPlanComparisonResult) -> None:
    frontend_texts: list[str] = []

    for row in comparison.category_comparison_matrix:
        frontend_texts.extend([
            row.frontend_winner_reason,
            row.frontend_tradeoff,
            row.frontend_category_summary,
            row.winner_reason,
            row.tradeoff,
        ])
        for item in row.project_scores:
            frontend_texts.append(item.user_facing_one_liner)

        if row.category_key == "water_leisure":
            water_chips = row.declared_evidence + row.visible_evidence + row.spatial_evidence
            water_chips += [chip for score in row.project_scores for chip in score.best_details]
            for chip in water_chips:
                lowered = chip.lower()
                if any(term in lowered for term in WATER_LEISURE_BLOCKED_CHIPS):
                    raise ValueError(f"Water & Leisure contains invalid frontend evidence chip: {chip}")

        if row.show_as_insufficient and row.show_winner_badge:
            raise ValueError(f"Insufficient Evidence row still has a winner badge: {row.category_key}")

        if row.show_as_weak and row.winner_badge_label != "Relative Edge":
            raise ValueError(f"Weak Differentiator row must use Relative Edge label: {row.category_key}")

        if row.show_as_decisive and row.internal_scoring.score_gap >= 8:
            lowered_tradeoff = row.frontend_tradeoff.lower()
            if any(pattern in lowered_tradeoff for pattern in CLEAR_WINNER_NARROW_PATTERNS):
                raise ValueError(f"Clear Winner row has narrow-gap tradeoff: {row.category_key}")

    frontend_texts.extend([
        comparison.overall_recommendation.one_liner,
        comparison.overall_recommendation.detailed_reason,
        comparison.overall_recommendation.frontend_headline,
        comparison.overall_recommendation.frontend_summary,
        comparison.user_friendly_summary.headline,
        comparison.user_friendly_summary.short_summary,
        comparison.user_friendly_summary.caution_note or "",
    ])

    combined = "\n".join(frontend_texts).lower()
    for banned in BANNED_FRONTEND_TERMS:
        if banned in combined:
            raise ValueError(f"Frontend copy contains banned technical term: {banned}")

    if "both projects" in combined:
        raise ValueError("Frontend copy contains 'both projects' in a three-project comparison.")


def _join_for_copy(values: list[str]) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])} and {cleaned[-1]}"
