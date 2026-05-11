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

        # Backward-compatible fields should also stay frontend-safe.
        row.winner_reason = category_copy.frontend_winner_reason
        row.tradeoff = category_copy.frontend_tradeoff

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

    _validate_no_banned_frontend_terms(comparison)

    return comparison


def _clean_optional_copy(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = _clean_frontend_copy(value)
    return cleaned or None


def _clean_frontend_copy(value: str) -> str:
    cleaned = str(value or "").strip()

    for term in BANNED_FRONTEND_TERMS:
        cleaned = cleaned.replace(term, "")

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
