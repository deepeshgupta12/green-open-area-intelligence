from __future__ import annotations

import re
from typing import Any

from app.schemas.project_schema import (
    AmenityRecord,
    MasterPlanMetadata,
    ParsedProjectMetadata,
    ReraRecord,
    UnitVariant,
    WowFactorRecord,
)
from app.utils.file_utils import read_json_file, safe_get_nested, strip_html_tags


GREEN_SIGNAL_KEYWORDS = {
    "green",
    "garden",
    "landscape",
    "landscaped",
    "lawn",
    "orchard",
    "woodland",
    "tree",
    "trees",
    "plant",
    "planted",
    "park",
    "forest",
    "eco",
    "podium top",
    "podium landscape",
    "party lawn",
    "herb garden",
    "butterfly garden",
    "large green area",
    "nursery",
}

OPEN_SPACE_SIGNAL_KEYWORDS = {
    "open",
    "open area",
    "open space",
    "podium",
    "deck",
    "driveway",
    "pathway",
    "walk",
    "jogging",
    "cycle track",
    "sports",
    "court",
    "pool",
    "play",
    "play area",
    "senior citizen area",
    "amphitheater",
    "amphitheatre",
    "setback",
    "road",
    "drop-off",
    "drop off",
}


def parse_datacenter_json_file(json_path: str) -> ParsedProjectMetadata:
    payload = read_json_file(json_path)
    return parse_datacenter_payload(payload)


def parse_datacenter_payload(payload: dict[str, Any]) -> ParsedProjectMetadata:
    project_data = safe_get_nested(payload, ["data", "projectData"], default={}) or {}

    project_id = _to_string(
        safe_get_nested(payload, ["data", "projectId"])
        or project_data.get("projectId")
        or project_data.get("id")
    )

    if not project_id:
        raise ValueError("Unable to parse project_id from Datacenter JSON.")

    amenities = _parse_amenities(project_data)
    wow_factors = _parse_wow_factors(project_data)
    rera_records = _parse_rera_records(project_data)
    unit_mix = _parse_unit_mix(project_data)
    master_plan = _parse_master_plan(project_data)

    searchable_texts = _collect_searchable_text(project_data, amenities, wow_factors, master_plan)
    green_signals = _extract_keyword_signals(searchable_texts, GREEN_SIGNAL_KEYWORDS)
    open_space_signals = _extract_keyword_signals(searchable_texts, OPEN_SPACE_SIGNAL_KEYWORDS)

    parsed = ParsedProjectMetadata(
        project_id=project_id,
        project_name=_to_string(project_data.get("projectName")),
        city=_to_string(project_data.get("city")),
        locality=_to_string(project_data.get("subLocation")),
        micromarket=_to_string(project_data.get("location")),
        location=_to_string(project_data.get("location")),
        latitude=_to_float(project_data.get("latitude")),
        longitude=_to_float(project_data.get("longitude")),
        project_area_acres=_to_float(project_data.get("projectArea")),
        total_units=_to_int(project_data.get("totalUnits")),
        project_category=_to_string(project_data.get("projectCategory")),
        category_type=_to_string(project_data.get("categorytype")),
        status=_to_string(project_data.get("status")),
        developer_name=_to_string(safe_get_nested(project_data, ["developer", "name"])),
        developer_id=_to_string(project_data.get("developerId")),
        developer_grade=_to_string(project_data.get("DeveloperGrade")),
        developer_grade_category=_to_string(project_data.get("DeveloperGradeCat")),
        price_text=_to_string(project_data.get("priceText")),
        low_cost_text=_to_string(project_data.get("lowCostText")),
        high_cost_text=_to_string(project_data.get("highCostText")),
        sizes=_to_string(project_data.get("sizes")),
        brochure_url=_to_string(project_data.get("brochure")),
        project_url=_to_string(project_data.get("projectUrl")),
        last_update_date=_to_string(project_data.get("lastUpdateDate")),
        rera_records=rera_records,
        amenities=amenities,
        green_amenity_signals=green_signals,
        open_space_signals=open_space_signals,
        wow_factors=wow_factors,
        unit_mix=unit_mix,
        master_plan=master_plan,
        source_flags={
            "has_project_json": True,
            "has_project_area": project_data.get("projectArea") is not None,
            "has_total_units": project_data.get("totalUnits") is not None,
            "has_amenities": len(amenities) > 0,
            "has_green_signals": len(green_signals) > 0,
            "has_open_space_signals": len(open_space_signals) > 0,
            "has_rera_records": len(rera_records) > 0,
            "has_master_plan_metadata": master_plan is not None,
            "has_brochure_url": bool(project_data.get("brochure")),
        },
        raw_signal_summary={
            "amenity_count": len(amenities),
            "wow_factor_count": len(wow_factors),
            "rera_record_count": len(rera_records),
            "unit_variant_count": len(unit_mix),
            "green_signal_count": len(green_signals),
            "open_space_signal_count": len(open_space_signals),
            "direct_area_claims": _extract_direct_area_claims(searchable_texts),
        },
    )

    return parsed


def _parse_amenities(project_data: dict[str, Any]) -> list[AmenityRecord]:
    parsed: list[AmenityRecord] = []

    amenities_groups = project_data.get("amenities") or []

    if not isinstance(amenities_groups, list):
        return parsed

    for group in amenities_groups:
        if not isinstance(group, dict):
            continue

        category = _to_string(group.get("category"))
        amenity_items = group.get("amenity") or []

        if not isinstance(amenity_items, list):
            continue

        for amenity in amenity_items:
            if not isinstance(amenity, dict):
                continue

            name = _to_string(amenity.get("name"))
            if not name:
                continue

            parsed.append(
                AmenityRecord(
                    name=name,
                    category=category,
                    amenity_id=_to_string(amenity.get("id")),
                )
            )

    return parsed


def _parse_wow_factors(project_data: dict[str, Any]) -> list[WowFactorRecord]:
    parsed: list[WowFactorRecord] = []

    wow_factors = project_data.get("wowFactors") or []

    if not isinstance(wow_factors, list):
        return parsed

    for item in wow_factors:
        if not isinstance(item, dict):
            continue

        text = _to_string(item.get("data"))
        if text:
            parsed.append(WowFactorRecord(text=text))

    return parsed


def _parse_rera_records(project_data: dict[str, Any]) -> list[ReraRecord]:
    parsed: list[ReraRecord] = []

    rera_items = project_data.get("projectReraData") or []

    if not isinstance(rera_items, list):
        return parsed

    for item in rera_items:
        if not isinstance(item, dict):
            continue

        parsed.append(
            ReraRecord(
                rera_project_name=_to_string(item.get("ReraProjectName")),
                rera_project_number=_to_string(item.get("ReraProjectNumber")),
                qr_link=_to_string(item.get("Qrlink")),
                launch_date=_to_string(item.get("LaunchDate")),
                completion_date=_to_string(item.get("CompletionDate")),
            )
        )

    return parsed


def _parse_unit_mix(project_data: dict[str, Any]) -> list[UnitVariant]:
    parsed: list[UnitVariant] = []

    unit_groups = project_data.get("units") or []

    if not isinstance(unit_groups, list):
        return parsed

    for group in unit_groups:
        if not isinstance(group, dict):
            continue

        category = _to_string(group.get("category"))
        units = group.get("unit") or []

        if not isinstance(units, list):
            continue

        for unit in units:
            if not isinstance(unit, dict):
                continue

            parsed.append(
                UnitVariant(
                    category=category,
                    unit_name=_to_string(unit.get("unitName")),
                    bedroom_count=_to_string(unit.get("bedroomCount")),
                    unit_cat_name=_to_string(unit.get("unitCatName")),
                    unit_cat_type=_to_string(unit.get("unitCatType")),
                    unit_size=_to_string(unit.get("unitSize")),
                    carpet_area=_to_string(unit.get("carpetArea")),
                    price_text=_to_string(unit.get("priceText")),
                )
            )

    return parsed


def _parse_master_plan(project_data: dict[str, Any]) -> MasterPlanMetadata | None:
    images = project_data.get("images") or []

    if not isinstance(images, list):
        return None

    for image in images:
        if not isinstance(image, dict):
            continue

        image_type = _to_string(image.get("type"))
        name = _to_string(image.get("name"))

        combined = f"{image_type} {name}".lower()

        if "master plan" not in combined:
            continue

        return MasterPlanMetadata(
            image_id=_to_string(image.get("id")),
            name=name,
            image_type=image_type,
            path=_to_string(image.get("path")),
            url=_to_string(image.get("url")),
            alt_tag=_to_string(image.get("altTag")),
            description_html=_to_string(image.get("description")),
        )

    return None


def _collect_searchable_text(
    project_data: dict[str, Any],
    amenities: list[AmenityRecord],
    wow_factors: list[WowFactorRecord],
    master_plan: MasterPlanMetadata | None,
) -> list[str]:
    texts: list[str] = []

    text_fields = [
        project_data.get("description"),
        project_data.get("SEOUSP"),
        project_data.get("KeyAmenities"),
        project_data.get("Snapshot"),
        project_data.get("ProjectLocAndAdv"),
        safe_get_nested(project_data, ["moderation", "usp"]),
        safe_get_nested(project_data, ["moderation", "description", "manualDesc"]),
    ]

    for field in text_fields:
        text = strip_html_tags(_to_string(field))
        if text:
            texts.append(text)

    for amenity in amenities:
        texts.append(amenity.name)

    for wow_factor in wow_factors:
        texts.append(wow_factor.text)

    if master_plan:
        if master_plan.description_html:
            texts.append(strip_html_tags(master_plan.description_html))
        if master_plan.name:
            texts.append(master_plan.name)
        if master_plan.alt_tag:
            texts.append(master_plan.alt_tag)

    return texts


def _extract_keyword_signals(texts: list[str], keywords: set[str]) -> list[str]:
    found: set[str] = set()

    lowered_blob = " ".join(texts).lower()

    for keyword in keywords:
        if keyword.lower() in lowered_blob:
            found.add(keyword)

    return sorted(found)


def _extract_direct_area_claims(texts: list[str]) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    blob = " ".join(texts)
    clean_blob = re.sub(r"\s+", " ", blob)

    patterns = [
        r"(?P<value>\d+(?:\.\d+)?)\s*%\s*(?P<label>open\s*(?:space|area)|green\s*(?:space|area|cover)|landscape(?:d)?\s*(?:area)?)",
        r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>acre|acres)\s*(?:of)?\s*(?P<label>podium\s*top\s*landscape|landscape(?:d)?\s*amenities|green\s*(?:space|area|cover)|open\s*(?:space|area))",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, clean_blob, flags=re.IGNORECASE):
            claims.append({k: v for k, v in match.groupdict().items() if v is not None})

    return claims


def _to_string(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None

    return str(value).strip()


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None

    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
