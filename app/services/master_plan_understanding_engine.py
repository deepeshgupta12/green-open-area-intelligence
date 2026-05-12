from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path

from google import genai

from app.config import get_settings
from app.schemas.image_schema import ImageMetadata
from app.schemas.master_plan_understanding_schema import (
    ManualCorrectionState,
    MasterPlanCategoryEvidence,
    MasterPlanLegendItem,
    MasterPlanPreprocessingArtifact,
    MasterPlanUnderstandingResult,
    MasterPlanZone,
)
from app.schemas.project_schema import ParsedProjectMetadata
from app.schemas.vision_schema import VisionAnalysisResult
from app.services.master_plan_preprocessor import create_master_plan_preprocessing_artifacts
from app.utils.llm_utils import extract_json_from_text, load_image_part_for_gemini


CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "green_landscape": [
        "green", "garden", "lawn", "landscape", "tree", "orchard", "woodland",
        "park", "plant", "butterfly", "herb", "nursery", "central green",
    ],
    "open_space": [
        "open", "plaza", "deck", "podium", "pathway", "walk", "court", "pool",
        "play", "amenity open", "aos", "recreation", "seating",
    ],
    "built_density": ["tower", "building", "clubhouse", "retail", "entry lobby", "lobby"],
    "amenity_richness": ["gym", "pool", "court", "clubhouse", "spa", "library", "hall", "cafe"],
    "sports_active_lifestyle": [
        "football", "running", "track", "tennis", "basketball", "badminton", "squash",
        "cricket", "volleyball", "skating", "jogging", "yoga", "gym", "sports",
    ],
    "family_community": [
        "kids", "child", "senior", "pet", "day care", "party", "community", "clubhouse",
        "amphitheater", "play", "family",
    ],
    "water_leisure": ["pool", "water", "spa", "leisure", "deck", "clubhouse"],
    "access_circulation": [
        "road", "internal road", "road network", "driveway", "internal driveway", "drop", "drop-off", "drop off",
        "entry", "entrance", "exit", "gate", "vehicular", "pedestrian", "access", "frontage",
        "pathway", "walkway", "bus", "school bus bay", "parking", "ramp", "movement", "circulation",
        "approach", "pickup", "pickups", "drop-offs",
    ],
    "environment_sustainability": [
        "rain", "harvesting", "stp", "sewage", "treated water", "solar", "eco", "green",
        "sustainability", "waste",
    ],
}

ZONE_CATEGORY_LABELS = {
    "green_landscape": "green",
    "open_space": "open",
    "built_density": "built",
    "amenity_richness": "amenity",
    "sports_active_lifestyle": "sports",
    "family_community": "family",
    "water_leisure": "water_leisure",
    "access_circulation": "circulation",
    "environment_sustainability": "sustainability",
}


def extract_master_plan_understanding(
    project: ParsedProjectMetadata,
    image_metadata: ImageMetadata,
    vision: VisionAnalysisResult | None = None,
    output_dir: Path | None = None,
    use_gemini: bool = True,
) -> MasterPlanUnderstandingResult:
    artifacts = create_master_plan_preprocessing_artifacts(
        image_metadata=image_metadata,
        project_id=project.project_id,
        output_dir=output_dir,
    )

    deterministic = _build_deterministic_understanding(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        artifacts=artifacts,
    )

    settings = get_settings()
    if not use_gemini or not settings.gemini_api_key:
        deterministic.internal_processing_notes.append(
            "Gemini structure extraction skipped; deterministic Datacenter/vision fallback used."
        )
        return deterministic

    try:
        gemini_result = _extract_with_gemini(
            project=project,
            deterministic=deterministic,
            artifacts=artifacts,
        )
        return _merge_understanding(deterministic, gemini_result)
    except Exception as exc:
        deterministic.technical_warnings.append(
            f"Gemini structure extraction failed; deterministic fallback used: {exc}"
        )
        return deterministic


def _build_deterministic_understanding(
    project: ParsedProjectMetadata,
    image_metadata: ImageMetadata,
    vision: VisionAnalysisResult | None,
    artifacts: list[MasterPlanPreprocessingArtifact],
) -> MasterPlanUnderstandingResult:
    candidate_texts = _collect_candidate_texts(project)
    legend_items = _extract_legend_like_items(candidate_texts)
    zones = _build_zones(project=project, vision=vision, legend_items=legend_items)
    category_evidence = _build_category_evidence(project=project, zones=zones, legend_items=legend_items)

    correction_recommended = False
    correction_reason = None
    if image_metadata.quality.label in {"Low", "Very Low"}:
        correction_recommended = True
        correction_reason = "Master plan image quality is low; manual boundary/zone review is recommended."
    if vision and vision.boundary.manual_correction_recommended:
        correction_recommended = True
        correction_reason = vision.boundary.boundary_reason

    confidence = "High" if len(legend_items) >= 8 and not correction_recommended else "Medium"
    if image_metadata.quality.label in {"Low", "Very Low"}:
        confidence = "Low"

    return MasterPlanUnderstandingResult(
        project_id=project.project_id,
        project_name=project.project_name,
        extraction_confidence_label=confidence,
        manual_correction=ManualCorrectionState(
            boundary_correction_available=True,
            zone_tagging_available=True,
            correction_recommended=correction_recommended,
            correction_reason=correction_reason,
        ),
        preprocessing_artifacts=artifacts,
        legend_items=legend_items,
        zones=zones,
        category_evidence=category_evidence,
        internal_processing_notes=[
            "Legend-like entities were extracted from Datacenter master-plan description, amenities and vision components.",
            "Zone classification is category-based and directional; exact geometry requires manual correction or labelled training data.",
        ],
        technical_warnings=[] if confidence != "Low" else ["Low image quality may reduce extraction accuracy."],
    )


def _extract_with_gemini(
    project: ParsedProjectMetadata,
    deterministic: MasterPlanUnderstandingResult,
    artifacts: list[MasterPlanPreprocessingArtifact],
) -> MasterPlanUnderstandingResult:
    settings = get_settings()

    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is missing. Cannot run Gemini structure extraction.")

    client = genai.Client(api_key=settings.gemini_api_key)

    plan_crop = next((item.path for item in artifacts if item.artifact_type == "plan_region_crop"), None)
    legend_crop = next((item.path for item in artifacts if item.artifact_type == "legend_region_crop"), None)

    contents = [
        (
            "You extract structured master-plan entities from real-estate layout images. "
            "Return only JSON. Never invent exact measurements.\n\n"
            + _build_structure_prompt(project, deterministic)
        )
    ]
    if plan_crop:
        contents.append(load_image_part_for_gemini(plan_crop))
    if legend_crop:
        contents.append(load_image_part_for_gemini(legend_crop))

    response = client.models.generate_content(
        model=settings.gemini_vision_model,
        contents=contents,
        config={
            "temperature": 0.1,
            "response_mime_type": "application/json",
        },
    )

    response_text = response.text or "{}"
    payload = extract_json_from_text(response_text)
    return _parse_gemini_understanding_payload(project, deterministic.preprocessing_artifacts, payload)

def _build_structure_prompt(project: ParsedProjectMetadata, deterministic: MasterPlanUnderstandingResult) -> str:
    seed = {
        "project_id": project.project_id,
        "project_name": project.project_name,
        "datacenter_amenities": [item.name for item in project.amenities],
        "known_legend_items": [item.model_dump(mode="json") for item in deterministic.legend_items[:60]],
        "known_zones": [item.model_dump(mode="json") for item in deterministic.zones[:60]],
    }
    return f"""
Extract master-plan structure from the provided plan crop and legend crop.

Rules:
- Extract visible or declared entities only.
- Do not estimate exact area percentages.
- Classify each zone/entity into one of: green_landscape, open_space, built_density, amenity_richness, sports_active_lifestyle, family_community, water_leisure, access_circulation, environment_sustainability.
- Keep names specific, e.g. 'central landscaped garden', 'football court', 'driveway', 'kids pool'.
- Return concise JSON only.

Seed facts from Datacenter JSON:
{json.dumps(seed, ensure_ascii=False)}

Return JSON schema:
{{
  "extraction_confidence_label": "High|Medium|Low",
  "manual_correction_recommended": true,
  "manual_correction_reason": "reason or null",
  "legend_items": [{{"code":"GR-01", "raw_label":"Four a Side Football Court", "normalized_label":"football court", "inferred_category":"sports_active_lifestyle", "level":"Residential Ground Level", "confidence_label":"High"}}],
  "zones": [{{"zone_id":"z1", "label":"central landscaped garden", "zone_category":"green_landscape", "source":"vision", "confidence_label":"High", "level":null, "buyer_relevance":"supports outdoor living"}}],
  "category_evidence": [{{"category_key":"green_landscape", "declared_entities":["Large Green Area"], "visible_entities":["central landscaped garden"], "legend_entities":["butterfly garden"], "spatial_notes":["green zones appear distributed around amenity areas"], "evidence_strength":"Strong"}}],
  "technical_warnings": []
}}
"""


def _parse_gemini_understanding_payload(
    project: ParsedProjectMetadata,
    artifacts: list[MasterPlanPreprocessingArtifact],
    payload: dict,
) -> MasterPlanUnderstandingResult:
    legend_items = [
        MasterPlanLegendItem(
            code=item.get("code"),
            raw_label=str(item.get("raw_label") or item.get("label") or "").strip(),
            normalized_label=str(item.get("normalized_label") or item.get("raw_label") or "").strip(),
            inferred_category=_normalize_category(item.get("inferred_category")),
            level=item.get("level"),
            confidence_label=item.get("confidence_label") or "Medium",
        )
        for item in payload.get("legend_items", [])
        if str(item.get("raw_label") or item.get("label") or "").strip()
    ]
    zones = [
        MasterPlanZone(
            zone_id=str(item.get("zone_id") or f"ai_zone_{idx+1}"),
            label=str(item.get("label") or "").strip(),
            zone_category=_normalize_category(item.get("zone_category")),
            source=str(item.get("source") or "vision_model"),
            confidence_label=item.get("confidence_label") or "Medium",
            level=item.get("level"),
            buyer_relevance=item.get("buyer_relevance"),
        )
        for idx, item in enumerate(payload.get("zones", []))
        if str(item.get("label") or "").strip()
    ]
    evidence = [
        MasterPlanCategoryEvidence(
            category_key=_normalize_category(item.get("category_key")),
            declared_entities=_clean_list(item.get("declared_entities", [])),
            visible_entities=_clean_list(item.get("visible_entities", [])),
            legend_entities=_clean_list(item.get("legend_entities", [])),
            spatial_notes=_clean_list(item.get("spatial_notes", [])),
            evidence_strength=item.get("evidence_strength") or "Moderate",
        )
        for item in payload.get("category_evidence", [])
    ]
    return MasterPlanUnderstandingResult(
        project_id=project.project_id,
        project_name=project.project_name,
        extraction_confidence_label=payload.get("extraction_confidence_label") or "Medium",
        manual_correction=ManualCorrectionState(
            boundary_correction_available=True,
            zone_tagging_available=True,
            correction_recommended=bool(payload.get("manual_correction_recommended", False)),
            correction_reason=payload.get("manual_correction_reason"),
        ),
        preprocessing_artifacts=artifacts,
        legend_items=legend_items,
        zones=zones,
        category_evidence=evidence,
        internal_processing_notes=["Gemini master-plan structure extraction completed."],
        technical_warnings=_clean_list(payload.get("technical_warnings", [])),
    )


def _merge_understanding(
    fallback: MasterPlanUnderstandingResult,
    ai: MasterPlanUnderstandingResult,
) -> MasterPlanUnderstandingResult:
    if ai.legend_items:
        fallback.legend_items = _merge_legend_items(fallback.legend_items, ai.legend_items)
    if ai.zones:
        fallback.zones = _merge_zones(fallback.zones, ai.zones)
    if ai.category_evidence:
        fallback.category_evidence = _merge_category_evidence(fallback.category_evidence, ai.category_evidence)
    fallback.extraction_confidence_label = ai.extraction_confidence_label or fallback.extraction_confidence_label
    fallback.manual_correction = ai.manual_correction
    fallback.internal_processing_notes.extend(ai.internal_processing_notes)
    fallback.technical_warnings.extend(ai.technical_warnings)
    return fallback


def _collect_candidate_texts(project: ParsedProjectMetadata) -> list[str]:
    texts: list[str] = []
    if project.master_plan:
        texts.append(_strip_html(project.master_plan.description_html or ""))
        texts.append(project.master_plan.name or "")
        texts.append(project.master_plan.alt_tag or "")
    texts.extend([item.name for item in project.amenities])
    texts.extend(project.green_amenity_signals)
    texts.extend(project.open_space_signals)
    texts.extend([item.text for item in project.wow_factors])
    return [text for text in texts if text]


def _extract_legend_like_items(texts: list[str]) -> list[MasterPlanLegendItem]:
    items: list[MasterPlanLegendItem] = []
    for text in texts:
        clean = _strip_html(text)
        code_matches = re.findall(r"\b([A-Z]{1,3}-?\d{1,3})\s*[:.-]?\s*([^,;\n\r<]{3,80})", clean)
        for code, label in code_matches:
            normalized = _normalize_label(label)
            category = _infer_category(normalized)
            items.append(
                MasterPlanLegendItem(
                    code=code,
                    raw_label=label.strip(),
                    normalized_label=normalized,
                    inferred_category=category,
                    confidence_label="Medium",
                )
            )

        # Also split long amenity/description phrases into entity candidates.
        for candidate in re.split(r"[,;•\n\r]+", clean):
            normalized = _normalize_label(candidate)
            if len(normalized) < 3 or len(normalized) > 70:
                continue
            category = _infer_category(normalized)
            if category == "unknown":
                continue
            items.append(
                MasterPlanLegendItem(
                    raw_label=candidate.strip(),
                    normalized_label=normalized,
                    inferred_category=category,
                    confidence_label="Medium",
                )
            )

    return _merge_legend_items([], items)[:80]


def _build_zones(
    project: ParsedProjectMetadata,
    vision: VisionAnalysisResult | None,
    legend_items: list[MasterPlanLegendItem],
) -> list[MasterPlanZone]:
    zones: list[MasterPlanZone] = []
    for idx, item in enumerate(legend_items):
        zones.append(
            MasterPlanZone(
                zone_id=f"legend_{idx+1}",
                label=item.normalized_label,
                zone_category=item.inferred_category,
                source="legend_or_datacenter",
                confidence_label=item.confidence_label,
                level=item.level,
                buyer_relevance=_buyer_relevance(item.inferred_category),
            )
        )
    if vision:
        for idx, component in enumerate(vision.detected_components):
            category = _normalize_component_type(component.component_type)
            zones.append(
                MasterPlanZone(
                    zone_id=f"vision_{idx+1}",
                    label=component.label,
                    zone_category=category,
                    source="vision_model_component",
                    confidence_label=component.confidence,
                    buyer_relevance=_buyer_relevance(category),
                )
            )
    return _merge_zones([], zones)[:100]


def _build_category_evidence(
    project: ParsedProjectMetadata,
    zones: list[MasterPlanZone],
    legend_items: list[MasterPlanLegendItem],
) -> list[MasterPlanCategoryEvidence]:
    evidence: list[MasterPlanCategoryEvidence] = []
    for category_key in CATEGORY_KEYWORDS:
        declared = []
        declared.extend(_matching_names([item.name for item in project.amenities], category_key))
        declared.extend(_matching_names(project.green_amenity_signals + project.open_space_signals, category_key))
        declared.extend(_matching_names([item.text for item in project.wow_factors], category_key))
        if category_key == "access_circulation":
            declared.extend(_extract_access_entities_from_project(project))

        visible = [zone.label for zone in zones if zone.zone_category == category_key and "vision" in zone.source.lower()]
        legend = [item.normalized_label for item in legend_items if item.inferred_category == category_key]
        total_count = len(set(declared + visible + legend))
        if total_count >= 6:
            strength = "Strong"
        elif total_count >= 3:
            strength = "Moderate"
        elif total_count >= 1:
            strength = "Weak"
        else:
            strength = "Insufficient"
        evidence.append(
            MasterPlanCategoryEvidence(
                category_key=category_key,
                declared_entities=_dedupe(declared)[:10],
                visible_entities=_dedupe(visible)[:10],
                legend_entities=_dedupe(legend)[:10],
                spatial_notes=_spatial_notes(category_key, visible, legend),
                evidence_strength=strength,
            )
        )
    return evidence


def _extract_access_entities_from_project(project: ParsedProjectMetadata) -> list[str]:
    texts = []

    if project.master_plan:
        texts.append(_strip_html(project.master_plan.description_html or ""))
        texts.append(project.master_plan.name or "")
        texts.append(project.master_plan.alt_tag or "")

    texts.extend(project.open_space_signals)
    texts.extend([item.text for item in project.wow_factors])

    combined = " ".join(texts).lower()
    entities: list[str] = []

    phrase_map = {
        "direct frontage": "Direct frontage",
        "frontage": "Frontage",
        "direct access": "Direct access",
        "access road": "Access road",
        "approach road": "Approach road",
        "internal road": "Internal road network",
        "road network": "Internal road network",
        "road networks": "Internal road network",
        "main driveway": "Main driveway",
        "internal driveway": "Internal driveway",
        "driveway": "Driveway",
        "driveway and podium parking": "Driveway and Podium Parking",
        "podium parking": "Podium Parking",
        "parking access": "Parking access",
        "parking": "Parking access",
        "drop-off": "Drop-off zone",
        "drop off": "Drop-off zone",
        "entry / exit": "Entry / Exit",
        "entry/exit": "Entry / Exit",
        "entry point": "Entry point",
        "entry points": "Entry points",
        "entry": "Entry",
        "entrance": "Entrance",
        "exit": "Exit",
        "security gate": "Security Gate",
        "gate": "Gate",
        "vehicular": "Vehicular access",
        "pedestrian": "Pedestrian access",
        "school bus bay": "School bus bay",
        "ramp": "Ramp",
        "movement": "Internal movement",
        "circulation": "Internal circulation",
        "pickup": "Pickup/drop-off access",
        "pickups": "Pickup/drop-off access",
        "drop-offs": "Drop-off zone",
    }

    for needle, label in phrase_map.items():
        if needle in combined:
            entities.append(label)

    return _dedupe(entities)


def _matching_names(names: list[str], category_key: str) -> list[str]:
    keywords = CATEGORY_KEYWORDS.get(category_key, [])
    result = []
    for name in names:
        lowered = str(name).lower()
        if any(keyword in lowered for keyword in keywords):
            result.append(str(name).strip())
    return result


def _spatial_notes(category_key: str, visible: list[str], legend: list[str]) -> list[str]:
    notes = []
    if visible:
        notes.append("Visible master-plan components support this category.")
    if legend:
        notes.append("Legend/Datacenter entities support this category.")
    if category_key in {"green_landscape", "open_space"} and len(visible + legend) >= 4:
        notes.append("Multiple entities suggest this category is distributed across the plan rather than represented by a single isolated feature.")
    return notes


def _strip_html(value: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", value or "")
    clean = unescape(clean)
    return " ".join(clean.split())


def _normalize_label(value: str) -> str:
    value = _strip_html(value)
    value = re.sub(r"^[A-Z]{1,3}-?\d{1,3}\s*[:.-]?\s*", "", value).strip()
    return " ".join(value.split())


def _infer_category(label: str) -> str:
    lowered = label.lower()
    matches = []
    for category_key, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            matches.append(category_key)
    if not matches:
        return "unknown"
    # Prefer more specific lifestyle categories before broad open/amenity labels.
    priority = [
        "sports_active_lifestyle", "family_community", "water_leisure", "access_circulation",
        "environment_sustainability", "green_landscape", "built_density", "amenity_richness", "open_space",
    ]
    for item in priority:
        if item in matches:
            return item
    return matches[0]


def _normalize_category(value: str | None) -> str:
    if not value:
        return "unknown"
    value = str(value).strip().lower().replace(" ", "_")
    aliases = {
        "green": "green_landscape",
        "landscape": "green_landscape",
        "open": "open_space",
        "built": "built_density",
        "sports": "sports_active_lifestyle",
        "family": "family_community",
        "water": "water_leisure",
        "circulation": "access_circulation",
        "access": "access_circulation",
        "sustainability": "environment_sustainability",
    }
    return aliases.get(value, value if value in CATEGORY_KEYWORDS else _infer_category(value))


def _normalize_component_type(component_type: str) -> str:
    lowered = str(component_type).lower()
    if "green" in lowered or "landscape" in lowered:
        return "green_landscape"
    if "road" in lowered or "driveway" in lowered or "path" in lowered:
        return "access_circulation"
    if "sport" in lowered or "court" in lowered or "play" in lowered:
        return "sports_active_lifestyle"
    if "pool" in lowered or "water" in lowered:
        return "water_leisure"
    if "built" in lowered or "clubhouse" in lowered or "retail" in lowered:
        return "built_density"
    if "paved" in lowered or "open" in lowered:
        return "open_space"
    return "unknown"


def _buyer_relevance(category_key: str) -> str | None:
    return {
        "green_landscape": "supports outdoor living and visual relief",
        "open_space": "supports breathing room and common-area usability",
        "built_density": "helps judge crowding and built-footprint pressure",
        "amenity_richness": "supports lifestyle depth",
        "sports_active_lifestyle": "supports fitness and active use cases",
        "family_community": "supports kids, seniors, pets and social use cases",
        "water_leisure": "supports pool-side and clubhouse-led leisure",
        "access_circulation": "supports entry, drop-off and internal movement",
        "environment_sustainability": "supports sustainability feature screening",
    }.get(category_key)


def _merge_legend_items(existing: list[MasterPlanLegendItem], incoming: list[MasterPlanLegendItem]) -> list[MasterPlanLegendItem]:
    by_key = {item.normalized_label.lower(): item for item in existing if item.normalized_label}
    for item in incoming:
        key = item.normalized_label.lower()
        if key and key not in by_key and item.inferred_category != "unknown":
            by_key[key] = item
    return list(by_key.values())


def _merge_zones(existing: list[MasterPlanZone], incoming: list[MasterPlanZone]) -> list[MasterPlanZone]:
    by_key = {item.label.lower(): item for item in existing if item.label}
    for item in incoming:
        key = item.label.lower()
        if key and key not in by_key and item.zone_category != "unknown":
            by_key[key] = item
    return list(by_key.values())


def _merge_category_evidence(existing: list[MasterPlanCategoryEvidence], incoming: list[MasterPlanCategoryEvidence]) -> list[MasterPlanCategoryEvidence]:
    by_key = {item.category_key: item for item in existing}
    for item in incoming:
        current = by_key.get(item.category_key)
        if not current:
            by_key[item.category_key] = item
            continue
        current.declared_entities = _dedupe(current.declared_entities + item.declared_entities)
        current.visible_entities = _dedupe(current.visible_entities + item.visible_entities)
        current.legend_entities = _dedupe(current.legend_entities + item.legend_entities)
        current.spatial_notes = _dedupe(current.spatial_notes + item.spatial_notes)
        current.evidence_strength = _stronger_evidence(current.evidence_strength, item.evidence_strength)
    return list(by_key.values())


def _stronger_evidence(a: str, b: str) -> str:
    order = {"Insufficient": 0, "Weak": 1, "Moderate": 2, "Strong": 3, "High": 3}
    return a if order.get(a, 0) >= order.get(b, 0) else b


def _clean_list(values) -> list[str]:
    if not isinstance(values, list):
        return []
    return _dedupe([str(item).strip() for item in values if str(item).strip()])


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
