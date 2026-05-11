from __future__ import annotations

import json

from openai import OpenAI

from app.config import get_settings
from app.schemas.master_plan_compare_schema import MasterPlanComparisonResult
from app.schemas.master_plan_narrative_schema import (
    CategoryNarrativeCopy,
    MasterPlanNarrativeResult,
    OverallNarrativeCopy,
)
from app.utils.openai_utils import extract_json_from_text


BANNED_FRONTEND_TERMS = [
    "OpenCV",
    "opencv",
    "unknown/unclassified",
    "unknown area",
    "segmentation",
    "pixel",
    "image quality",
    "model confidence",
    "confidence score",
    "area estimate confidence",
    "technical",
]


def enhance_master_plan_comparison_with_openai(
    comparison: MasterPlanComparisonResult,
) -> MasterPlanComparisonResult:
    settings = get_settings()

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is missing. Cannot generate frontend narrative copy.")

    client = OpenAI(api_key=settings.openai_api_key)

    prompt = build_master_plan_narrative_prompt(comparison)

    response = client.chat.completions.create(
        model=settings.openai_text_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a senior real-estate product copywriter. "
                    "You write buyer-friendly, concise, evidence-backed frontend copy for property comparison modules."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.25,
    )

    response_text = response.choices[0].message.content or ""
    payload = extract_json_from_text(response_text)
    narrative = parse_master_plan_narrative_payload(payload)

    return apply_narrative_to_comparison(comparison=comparison, narrative=narrative)


def build_master_plan_narrative_prompt(
    comparison: MasterPlanComparisonResult,
) -> str:
    narrative_input = {
        "projects": [project.model_dump(mode="json") for project in comparison.projects],
        "category_rows": [
            {
                "category_key": row.category_key,
                "category_label": row.category_label,
                "winner_project_slot": row.winner_project_slot,
                "winner_project_name": row.winner_project_name,
                "project_scores": [
                    {
                        "project_slot": item.project_slot,
                        "project_name": item.project_name,
                        "score": item.score,
                        "rating": item.rating,
                        "confidence_label": item.confidence_label,
                        "best_details": item.best_details,
                    }
                    for item in row.project_scores
                ],
                "category_status": row.category_status,
                "evidence_strength": row.evidence_strength,
                "confidence_badge": row.confidence_badge,
                "show_as_insufficient": row.show_as_insufficient,
                "show_as_close_call": row.show_as_close_call,
                "show_as_weak": row.show_as_weak,
                "show_as_decisive": row.show_as_decisive,
                "declared_evidence": row.declared_evidence,
                "visible_evidence": row.visible_evidence,
                "spatial_evidence": row.spatial_evidence,
                "internal_scoring": row.internal_scoring.model_dump(mode="json"),
            }
            for row in comparison.category_comparison_matrix
        ],
        "overall_recommendation": comparison.overall_recommendation.model_dump(mode="json"),
        "user_friendly_summary": comparison.user_friendly_summary.model_dump(mode="json"),
    }

    return f"""
You will receive deterministic master-plan comparison facts for three real-estate projects.

Your job:
- Do NOT change winners.
- Do NOT change scores.
- Do NOT mention model internals.
- Do NOT mention OpenCV, segmentation, unknown area, pixels, image quality, confidence score, or internal evidence.
- Write frontend-ready buyer-facing copy only.
- Use specific project details where available.
- Keep every sentence useful for a property buyer comparing projects.
- Avoid generic phrases like "strong planning", "multiple signals", "available evidence", "model read", "category dimensions".
- Mention that values are directional only in the tradeoff/caution, not in every reason.
- Keep the tone professional and clear.
- Follow category_status strictly:
  * Clear Winner: you may use "leads", "best", or "stronger" only when evidence supports it.
  * Close Call: never use "superior", "excels", "clear", "strongest", or "best". Use "marginally ahead", "slightly ahead", or "close alternative".
  * Weak Differentiator: say it is a directional edge, not a major buying differentiator.
  * Insufficient Evidence: do not declare a winner. Say "No clear winner can be established" and explain that the category should be treated as informational.
- Do not use exact numeric scores in frontend copy.
- Do not use the phrase "both projects" because this is a three-project comparison. Use "the alternatives" or name the relevant projects.
- If category_status = Clear Winner and internal_scoring.score_gap >= 8, never say the gap/difference is narrow, small, close, or slight.
- If category_status = Clear Winner and internal_scoring.score_gap < 8, you may mention that the lead is directional, but do not call it narrow unless category_status is Close Call.
- Do not invent parks, zones, facilities, or sustainability features that are not present in the input facts.
- For Sustainability Signals, describe only feature availability. Do not claim verified impact, lower living costs, energy savings, or environmental performance.
- For Water & Leisure, do not mention water-supply utilities such as 24*7 Water Supply, Treated Water Supply, STP, rainwater harvesting, or sewage treatment.

For each category, write:
1. frontend_winner_reason: Why the winner is better in buyer-friendly terms.
2. frontend_tradeoff: A safe, buyer-friendly caveat or tradeoff.
3. frontend_category_summary: How a buyer should interpret this category.

For the overall copy, write:
1. frontend_headline
2. frontend_summary
3. best_for_green_living
4. best_for_amenities
5. best_for_family_living
6. best_for_access
7. caution_note

Input facts:
{json.dumps(narrative_input, ensure_ascii=False, indent=2)}

Return ONLY valid JSON.

Required JSON schema:
{{
  "category_copies": [
    {{
      "category_key": "green_landscape",
      "frontend_winner_reason": "Buyer-friendly reason. No technical terms.",
      "frontend_tradeoff": "Buyer-friendly tradeoff. No technical terms.",
      "frontend_category_summary": "Buyer-friendly category guidance. No technical terms."
    }}
  ],
  "overall_copy": {{
    "frontend_headline": "Short headline.",
    "frontend_summary": "2-3 sentence summary.",
    "best_for_green_living": "Project X is best for ...",
    "best_for_amenities": "Project X is best for ...",
    "best_for_family_living": "Project X is best for ...",
    "best_for_access": "Project X is best for ...",
    "caution_note": "Directional comparison caveat without technical terms."
  }}
}}
"""


def parse_master_plan_narrative_payload(payload: dict) -> MasterPlanNarrativeResult:
    category_copies = [
        CategoryNarrativeCopy(
            category_key=str(item.get("category_key", "")).strip(),
            frontend_winner_reason=_clean_frontend_copy(item.get("frontend_winner_reason", "")),
            frontend_tradeoff=_clean_frontend_copy(item.get("frontend_tradeoff", "")),
            frontend_category_summary=_clean_frontend_copy(item.get("frontend_category_summary", "")),
        )
        for item in payload.get("category_copies", [])
    ]

    overall_payload = payload.get("overall_copy", {})

    overall_copy = OverallNarrativeCopy(
        frontend_headline=_clean_frontend_copy(overall_payload.get("frontend_headline", "")),
        frontend_summary=_clean_frontend_copy(overall_payload.get("frontend_summary", "")),
        best_for_green_living=_clean_optional_copy(overall_payload.get("best_for_green_living")),
        best_for_amenities=_clean_optional_copy(overall_payload.get("best_for_amenities")),
        best_for_family_living=_clean_optional_copy(overall_payload.get("best_for_family_living")),
        best_for_access=_clean_optional_copy(overall_payload.get("best_for_access")),
        caution_note=_clean_frontend_copy(overall_payload.get("caution_note", "")),
    )

    return MasterPlanNarrativeResult(
        category_copies=category_copies,
        overall_copy=overall_copy,
    )


def apply_narrative_to_comparison(
    comparison: MasterPlanComparisonResult,
    narrative: MasterPlanNarrativeResult,
) -> MasterPlanComparisonResult:
    copy_by_category = {
        item.category_key: item for item in narrative.category_copies
    }

    for row in comparison.category_comparison_matrix:
        category_copy = copy_by_category.get(row.category_key)
        if category_copy is None:
            continue

        row.frontend_winner_reason = category_copy.frontend_winner_reason
        row.frontend_tradeoff = category_copy.frontend_tradeoff
        row.frontend_category_summary = category_copy.frontend_category_summary

        _apply_status_copy_guardrails(row)

        # Backward-compatible fields should also stay frontend-safe.
        row.winner_reason = row.frontend_winner_reason
        row.tradeoff = row.frontend_tradeoff

    comparison.overall_recommendation.frontend_headline = narrative.overall_copy.frontend_headline
    comparison.overall_recommendation.frontend_summary = narrative.overall_copy.frontend_summary
    comparison.overall_recommendation.one_liner = narrative.overall_copy.frontend_headline
    comparison.overall_recommendation.detailed_reason = narrative.overall_copy.frontend_summary

    comparison.user_friendly_summary.headline = narrative.overall_copy.frontend_headline
    comparison.user_friendly_summary.short_summary = narrative.overall_copy.frontend_summary
    comparison.user_friendly_summary.best_for_green_living = narrative.overall_copy.best_for_green_living
    comparison.user_friendly_summary.best_for_amenities = narrative.overall_copy.best_for_amenities
    comparison.user_friendly_summary.best_for_family_living = narrative.overall_copy.best_for_family_living
    comparison.user_friendly_summary.best_for_access = narrative.overall_copy.best_for_access
    comparison.user_friendly_summary.caution_note = narrative.overall_copy.caution_note

    for winner in comparison.category_winners:
        row = next(
            (
                item
                for item in comparison.category_comparison_matrix
                if item.category_key == winner.category_key
            ),
            None,
        )
        if row:
            winner.winner_reason = row.frontend_winner_reason

    _enforce_summary_guardrails(comparison)
    _validate_no_banned_frontend_terms(comparison)

    return comparison



def _apply_status_copy_guardrails(row) -> None:
    label = row.category_label.lower()
    project_name = row.winner_project_name or "the leading project"
    evidence = _join_for_copy((row.visible_evidence + row.declared_evidence)[:3])

    if row.category_status == "Insufficient Evidence":
        row.frontend_winner_reason = (
            f"No clear winner can be established for {label}; the available plan details are not strong enough to rank the projects confidently."
        )
        row.frontend_tradeoff = (
            "Use this category as informational only until clearer layout or official project evidence is available."
        )
        row.frontend_category_summary = (
            f"{row.category_label} should not be treated as a decisive comparison factor in this run."
        )
        row.show_winner_badge = False
        row.winner_badge_label = "No Clear Winner"
        return

    if row.category_status == "Close Call":
        row.frontend_winner_reason = (
            f"{project_name} is marginally ahead for {label}"
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

    if row.category_status == "Weak Differentiator":
        row.frontend_winner_reason = (
            f"{project_name} has a directional edge for {label}"
            + (f" through {evidence}" if evidence else "")
            + ", but it is not strong enough to be a major buying differentiator."
        )
        row.frontend_tradeoff = (
            "Use this as a supporting signal, not as a primary reason to prefer one project over another."
        )
        row.frontend_category_summary = (
            f"{row.category_label} provides some differentiation, but the evidence is moderate."
        )


def _enforce_summary_guardrails(comparison: MasterPlanComparisonResult) -> None:
    rows_by_key = {row.category_key: row for row in comparison.category_comparison_matrix}

    def safe_best_for(category_key: str, fallback: str | None) -> str | None:
        row = rows_by_key.get(category_key)
        if not row or row.show_as_insufficient:
            return None
        project_name = row.winner_project_name or f"Project {row.winner_project_slot}"
        if row.show_as_close_call:
            return f"{project_name} is marginally ahead for {row.category_label.lower()}."
        if row.show_as_weak:
            return f"{project_name} has a directional edge for {row.category_label.lower()}."
        return fallback

    comparison.user_friendly_summary.best_for_green_living = safe_best_for(
        "green_landscape", comparison.user_friendly_summary.best_for_green_living
    )
    comparison.user_friendly_summary.best_for_amenities = safe_best_for(
        "amenity_richness", comparison.user_friendly_summary.best_for_amenities
    )
    comparison.user_friendly_summary.best_for_family_living = safe_best_for(
        "family_community", comparison.user_friendly_summary.best_for_family_living
    )
    comparison.user_friendly_summary.best_for_access = safe_best_for(
        "access_circulation", comparison.user_friendly_summary.best_for_access
    )


def _join_for_copy(values: list[str]) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])} and {cleaned[-1]}"

def _clean_optional_copy(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = _clean_frontend_copy(value)
    return cleaned or None


def _clean_frontend_copy(value: str) -> str:
    cleaned = str(value or "").strip()

    for term in BANNED_FRONTEND_TERMS:
        cleaned = cleaned.replace(term, "")

    cleaned = cleaned.replace("both projects", "the alternatives")
    cleaned = cleaned.replace("Both projects", "The alternatives")
    cleaned = cleaned.replace("both alternatives", "the alternatives")
    cleaned = cleaned.replace("Both alternatives", "The alternatives")

    cleaned = " ".join(cleaned.split())
    return cleaned


def _validate_no_banned_frontend_terms(comparison: MasterPlanComparisonResult) -> None:
    frontend_texts: list[str] = []

    for row in comparison.category_comparison_matrix:
        frontend_texts.extend(
            [
                row.frontend_winner_reason,
                row.frontend_tradeoff,
                row.frontend_category_summary,
                row.winner_reason,
                row.tradeoff,
            ]
        )

        for item in row.project_scores:
            frontend_texts.append(item.user_facing_one_liner)

    frontend_texts.extend(
        [
            comparison.overall_recommendation.one_liner,
            comparison.overall_recommendation.detailed_reason,
            comparison.overall_recommendation.frontend_headline,
            comparison.overall_recommendation.frontend_summary,
            comparison.user_friendly_summary.headline,
            comparison.user_friendly_summary.short_summary,
            comparison.user_friendly_summary.caution_note or "",
        ]
    )

    combined = "\n".join(frontend_texts).lower()

    blocked = [
        term
        for term in BANNED_FRONTEND_TERMS
        if term.lower() in combined
    ]

    if blocked:
        raise ValueError(
            f"OpenAI narrative output contains banned frontend technical terms: {blocked}"
        )

    if "both projects" in combined:
        raise ValueError("OpenAI narrative output contains 'both projects' in a three-project comparison.")
