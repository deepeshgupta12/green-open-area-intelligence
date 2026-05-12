from __future__ import annotations

import json
from typing import Any

from google import genai

from app.config import get_settings
from app.schemas.image_schema import ImageMetadata
from app.schemas.project_schema import ParsedProjectMetadata
from app.schemas.vision_schema import VisionAnalysisResult
from app.utils.llm_utils import extract_json_from_text, load_image_part_for_gemini


def analyze_master_plan_with_gemini(
    project: ParsedProjectMetadata,
    image_metadata: ImageMetadata,
) -> VisionAnalysisResult:
    settings = get_settings()

    if not settings.gemini_api_key:
        raise ValueError(
            "GEMINI_API_KEY is missing. Add it to .env before running --run-vision."
        )

    if not image_metadata.normalized_image_path:
        raise ValueError("Normalized image path is missing. Run image preprocessing first.")

    client = genai.Client(api_key=settings.gemini_api_key)

    prompt = build_vision_prompt(project=project, image_metadata=image_metadata)

    response = client.models.generate_content(
        model=settings.gemini_vision_model,
        contents=[
            prompt,
            load_image_part_for_gemini(image_metadata.normalized_image_path),
        ],
        config={
            "temperature": 0.1,
            "response_mime_type": "application/json",
        },
    )

    response_text = response.text or ""
    parsed_json = extract_json_from_text(response_text)
    parsed_json["raw_model_response"] = {"output_text": response_text}

    return parse_vision_analysis_payload(parsed_json)


def build_vision_prompt(
    project: ParsedProjectMetadata,
    image_metadata: ImageMetadata,
) -> str:
    project_context = {
        "project_id": project.project_id,
        "project_name": project.project_name,
        "city": project.city,
        "locality": project.locality,
        "project_area_acres": project.project_area_acres,
        "total_units": project.total_units,
        "project_category": project.project_category,
        "status": project.status,
        "developer_name": project.developer_name,
        "green_amenity_signals": project.green_amenity_signals,
        "open_space_signals": project.open_space_signals,
        "wow_factors": [item.text for item in project.wow_factors],
        "master_plan_description": (
            project.master_plan.description_html if project.master_plan else None
        ),
    }

    image_context = {
        "file_name": image_metadata.file_name,
        "width": image_metadata.dimensions.width,
        "height": image_metadata.dimensions.height,
        "quality_score": image_metadata.quality.score,
        "quality_label": image_metadata.quality.label,
        "quality_reasons": image_metadata.quality.reasons,
    }

    return f"""
You are an expert real-estate master plan analyst helping estimate Green Area and Open Area for a project comparison module.

You will receive:
1. A normalized project master plan image.
2. Project Datacenter JSON signals.

Your job in this step is NOT to calculate final exact percentages.
Your job is to produce a structured visual interpretation that will later be combined with OpenCV diagnostics and guardrails.

Locked definitions:

Green Area = Landscaped / planted / garden / lawn / tree-covered / green recreational area visible or declared in project data.

Open Area = Total non-building footprint area inside the project boundary, including green area, roads, pathways, paved open areas, sports courts, pools, decks, setbacks, and open recreational zones.

Mandatory guardrail:
Green Area must be less than or equal to Open Area.

Classify visible components into:
- project_boundary
- building_footprint
- green_landscape
- road_driveway
- paved_open_area
- sports_court_play_area
- water_pool
- clubhouse_retail_structure
- unknown_unclear_area

Project context:
{json.dumps(project_context, ensure_ascii=False, indent=2)}

Image context:
{json.dumps(image_context, ensure_ascii=False, indent=2)}

Return ONLY valid JSON. Do not include markdown. Do not include prose outside JSON.

Required JSON schema:
{{
  "project_id": "{project.project_id}",
  "project_name": "{project.project_name}",
  "boundary": {{
    "boundary_visible": true,
    "boundary_confidence": "High | Medium | Low | Insufficient",
    "boundary_reason": "Explain whether the image shows a clear project boundary.",
    "manual_correction_recommended": true
  }},
  "detected_components": [
    {{
      "component_type": "green_landscape",
      "label": "Central landscaped garden",
      "visual_description": "Short visual description.",
      "confidence": "High | Medium | Low",
      "likely_counts_toward_green_area": true,
      "likely_counts_toward_open_area": true,
      "likely_counts_as_building_footprint": false
    }}
  ],
  "green_area_visual_estimate": {{
    "qualitative_estimate": "Very Low | Low | Moderate | High | Very High | Unclear",
    "reasoning": "Explain visual green-area strength."
  }},
  "open_area_visual_estimate": {{
    "qualitative_estimate": "Very Low | Low | Moderate | High | Very High | Unclear",
    "reasoning": "Explain visual open-area strength."
  }},
  "building_footprint_visual_estimate": {{
    "qualitative_estimate": "Very Low | Low | Moderate | High | Very High | Unclear",
    "reasoning": "Explain visible built-footprint intensity."
  }},
  "visible_green_area_indicators": [],
  "visible_open_area_indicators": [],
  "visible_built_area_indicators": [],
  "warnings": [],
  "model_notes": []
}}

Important output rules:
1. Do not call anything official unless directly visible or declared.
2. Mention if the image appears stylized or not to scale.
3. Mention if the boundary is inferred.
4. Mention if manual correction is recommended.
5. Do not return exact percentages.
6. Use qualitative estimates only in this step.
"""


def parse_vision_analysis_payload(payload: dict[str, Any]) -> VisionAnalysisResult:
    return VisionAnalysisResult.model_validate(payload)
