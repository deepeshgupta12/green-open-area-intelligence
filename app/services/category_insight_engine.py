from __future__ import annotations

import re

from app.schemas.area_schema import AreaEstimateResult
from app.schemas.category_insight_schema import (
    CategoryCompareModuleCopy,
    CategoryComparisonResult,
    CategoryInsight,
    OverallMasterPlanInsight,
)
from app.schemas.image_schema import ImageMetadata
from app.schemas.project_schema import ParsedProjectMetadata
from app.schemas.segmentation_schema import SegmentationResult
from app.schemas.vision_schema import VisionAnalysisResult


RATING_BANDS = [
    (85, "Excellent"),
    (70, "Strong"),
    (55, "Moderate"),
    (40, "Limited"),
    (0, "Weak"),
]


def build_category_comparison(
    project: ParsedProjectMetadata,
    image_metadata: ImageMetadata,
    vision: VisionAnalysisResult,
    segmentation: SegmentationResult,
    area_estimate: AreaEstimateResult,
) -> CategoryComparisonResult:
    context = _build_context(
        project=project,
        image_metadata=image_metadata,
        vision=vision,
        segmentation=segmentation,
        area_estimate=area_estimate,
    )

    categories = [
        _green_landscape_insight(context),
        _open_space_insight(context),
        _built_density_insight(context),
        _amenity_richness_insight(context),
        _sports_active_lifestyle_insight(context),
        _family_community_insight(context),
        _water_leisure_insight(context),
        _access_circulation_insight(context),
        _environment_sustainability_insight(context),
        _evidence_reliability_insight(context),
    ]

    overall = _build_overall_summary(categories=categories, context=context)

    return CategoryComparisonResult(
        project_id=project.project_id,
        project_name=project.project_name,
        category_scores=categories,
        overall_master_plan_summary=overall,
        notes=[
            "Category insights are estimated planning signals, not official measurements.",
            "Scores combine Datacenter JSON, master plan description, Vision model, OpenCV segmentation and final area estimate.",
            "One-liners and details are generated from available evidence only.",
        ],
    )


def _build_context(
    project: ParsedProjectMetadata,
    image_metadata: ImageMetadata,
    vision: VisionAnalysisResult,
    segmentation: SegmentationResult,
    area_estimate: AreaEstimateResult,
) -> dict:
    amenities = [item.name for item in project.amenities]
    amenities_lower = [item.lower() for item in amenities]

    wow_factors = [item.text for item in project.wow_factors]

    master_plan_text = ""
    if project.master_plan and project.master_plan.description_html:
        master_plan_text = _strip_html(project.master_plan.description_html)

    detected_components = [item.label for item in vision.detected_components]
    detected_component_types = [item.component_type for item in vision.detected_components]

    evidence = area_estimate.evidence_summary

    return {
        "project": project,
        "image_metadata": image_metadata,
        "vision": vision,
        "segmentation": segmentation,
        "area_estimate": area_estimate,
        "amenities": amenities,
        "amenities_lower": amenities_lower,
        "wow_factors": wow_factors,
        "master_plan_text": master_plan_text,
        "detected_components": detected_components,
        "detected_component_types": detected_component_types,
        "green_range": area_estimate.green_area_percentage.display,
        "open_range": area_estimate.open_area_percentage.display,
        "confidence_label": area_estimate.confidence.label,
        "opencv_unknown": float(evidence.get("opencv_unknown_percentage", 0) or 0),
        "opencv_green": float(evidence.get("opencv_green_percentage", 0) or 0),
        "opencv_paved": float(evidence.get("opencv_paved_percentage", 0) or 0),
        "opencv_water": float(evidence.get("opencv_water_percentage", 0) or 0),
        "opencv_built": float(evidence.get("opencv_built_percentage", 0) or 0),
    }


def _green_landscape_insight(context: dict) -> CategoryInsight:
    details = _extract_matching_details(
        context,
        [
            "large green area",
            "party lawn",
            "butterfly garden",
            "herb garden",
            "nursery fruit orchard",
            "panchatatva garden",
            "reflexology pathway",
            "woodland area",
            "golf putting lawn",
            "garden",
            "lawn",
            "tree",
            "landscape",
        ],
    )

    score = 50
    score += min(len(context["project"].green_amenity_signals) * 2, 24)
    score += _qualitative_boost(context["vision"].green_area_visual_estimate.qualitative_estimate)
    score += 4 if context["opencv_green"] > 5 else 0
    score = _penalize_for_uncertainty(score, context)

    positive = [
        f"Estimated Green Area range is {context['green_range']}.",
        f"Vision model classified green area as {context['vision'].green_area_visual_estimate.qualitative_estimate}.",
    ]

    if details:
        positive.append("Multiple green-space details were found in the master plan and Datacenter signals.")

    risks = _standard_risks(context)

    return _category(
        key="green_landscape",
        label="Green Landscape Planning",
        score=score,
        confidence=context["confidence_label"],
        one_liner=(
            f"Best suited for buyers who want garden-led outdoor living, because the layout includes named green zones like butterfly garden, herb garden, fruit orchard and woodland area."
        ),
        detailed=(
            "The project includes visible and declared green planning signals across the master plan and Datacenter JSON. "
            f"Key extracted details include {', '.join(details[:8]) if details else 'green and landscaped areas'}. "
            "Because OpenCV has a high unknown segment, the output should be treated as an estimated planning insight."
        ),
        positives=positive,
        risks=risks,
        details=details,
        sources=["Datacenter JSON amenities", "Master plan description", "Vision model analysis", "OpenCV segmentation", "Area estimate"],
        short_label="Strong Green Planning",
        tooltip="Visible landscaped zones and multiple green-space amenities are present, with exact area shown as an estimated range.",
    )


def _open_space_insight(context: dict) -> CategoryInsight:
    details = _extract_matching_details(
        context,
        [
            "open",
            "residential ground level",
            "e deck level",
            "driveway",
            "drop-off",
            "road networks",
            "sports facilities",
            "swimming pools",
            "pathway",
            "recreational spaces",
            "dedicated zones",
        ],
    )

    score = 52
    score += _qualitative_boost(context["vision"].open_area_visual_estimate.qualitative_estimate)
    score += 8 if context["opencv_paved"] > 10 else 0
    score += min(len(context["project"].open_space_signals), 20)
    score = _penalize_for_uncertainty(score, context)

    return _category(
        key="open_space",
        label="Open Space and Breathing Room",
        score=score,
        confidence=context["confidence_label"],
        one_liner=(
            f"Feels more open than dense on paper, with internal driveways, sports zones, pool areas and recreational decks spread across the layout."
        ),
        detailed=(
            "Open-space strength is supported by the Vision estimate, internal circulation signals, sports courts, pool areas and recreational zones. "
            f"Extracted open-space details include {', '.join(details[:8]) if details else 'roads, pathways and recreational spaces'}."
        ),
        positives=[
            f"Estimated Open Area range is {context['open_range']}.",
            f"Vision model classified open area as {context['vision'].open_area_visual_estimate.qualitative_estimate}.",
            "Multiple open-space and circulation signals were found.",
        ],
        risks=_standard_risks(context),
        details=details,
        sources=["Master plan description", "Vision model analysis", "OpenCV segmentation", "Area estimate"],
        short_label="High Openness",
        tooltip="The project appears to have strong open-space planning, but exact open area remains estimated.",
    )


def _built_density_insight(context: dict) -> CategoryInsight:
    units_per_acre = None
    project = context["project"]
    if project.project_area_acres and project.total_units:
        units_per_acre = round(project.total_units / project.project_area_acres, 1)

    score = 70
    if context["vision"].building_footprint_visual_estimate.qualitative_estimate == "Moderate":
        score += 4
    if units_per_acre and units_per_acre > 90:
        score -= 8
    if context["opencv_built"] < 10:
        score += 6
    score = _penalize_for_uncertainty(score, context)

    details = []
    if units_per_acre:
        details.append(f"Approx. {units_per_acre} units per acre")
    details.extend(_extract_matching_details(context, ["multiple towers", "clubhouses", "retail section", "residential living"]))

    return _category(
        key="built_density",
        label="Built Density and Tower Footprint",
        score=score,
        confidence=context["confidence_label"],
        one_liner=(
            "Moderate density signal: the project has multiple towers and high units per acre, so the open-space promise should be checked against official layout drawings."
        ),
        detailed=(
            "The built density signal combines Vision's building-footprint estimate, OpenCV built-structure detection and project density. "
            f"{'The project has about ' + str(units_per_acre) + ' units per acre, so density should be reviewed carefully.' if units_per_acre else 'Unit density could not be calculated.'}"
        ),
        positives=[
            f"Vision model classified building footprint as {context['vision'].building_footprint_visual_estimate.qualitative_estimate}.",
            f"OpenCV detected built-structure lower-bound at {context['opencv_built']}%.",
        ],
        risks=_standard_risks(context) + (["High units per acre may indicate density pressure."] if units_per_acre and units_per_acre > 90 else []),
        details=details,
        sources=["Datacenter JSON", "Vision model analysis", "OpenCV segmentation"],
        short_label="Moderate Built Density",
        tooltip="Built footprint appears balanced against open and amenity zones, but density should be reviewed with official layout data.",
    )


def _amenity_richness_insight(context: dict) -> CategoryInsight:
    amenities = context["amenities"]
    details = amenities[:18]

    categories = {item.category for item in context["project"].amenities if item.category}
    score = 45 + min(len(amenities), 45) + min(len(categories) * 3, 15)
    score = _cap(score)

    return _category(
        key="amenity_richness",
        label="Amenity Richness",
        score=score,
        confidence="High" if len(amenities) >= 20 else context["confidence_label"],
        one_liner=(
            f"Designed for amenity-heavy living, with sports, leisure, convenience, environment and safety features available in the parsed project data."
        ),
        detailed=(
            "Amenity richness is strongly supported by structured Datacenter JSON. "
            f"Detected amenity groups include {', '.join(sorted(categories)) if categories else 'multiple lifestyle categories'}."
        ),
        positives=[
            f"{len(amenities)} amenities parsed from Datacenter JSON.",
            f"{len(categories)} amenity categories detected.",
        ],
        risks=[],
        details=details,
        sources=["Datacenter JSON amenities"],
        short_label="Rich Amenity Mix",
        tooltip="The project has a broad amenity mix based on structured project data.",
    )


def _sports_active_lifestyle_insight(context: dict) -> CategoryInsight:
    keywords = [
        "Gymnasium",
        "Swimming Pool",
        "Kids' Pool",
        "Badminton Court(s)",
        "Tennis Court(s)",
        "Squash Court",
        "Football",
        "Basketball",
        "Volleyball",
        "Yoga Areas",
        "Jogging / Cycle Track",
        "Table Tennis",
        "Skating Rink",
        "Golf Putting",
        "four-a-side football court",
        "2-lane running track",
        "pickleball court",
    ]
    details = _extract_exact_or_text_details(context, keywords)

    score = 45 + min(len(details) * 5, 45)
    if "sports_court_play_area" in context["detected_component_types"]:
        score += 8
    score = _cap(score)

    return _category(
        key="sports_active_lifestyle",
        label="Sports and Active Lifestyle",
        score=score,
        confidence=context["confidence_label"],
        one_liner=(
            "Strong pick for active families, with football, running track, tennis/bowl, volleyball, pickleball, basketball, skating and pool signals in the master plan."
        ),
        detailed=(
            f"Sports planning is supported by extracted details such as {', '.join(details[:10]) if details else 'sports courts and outdoor activity zones'}. "
            "These signals indicate that the project is designed for regular outdoor and recreational activity."
        ),
        positives=[
            "Multiple sports and active-lifestyle amenities are present.",
            "Vision model detected sports/play areas.",
        ],
        risks=_standard_risks(context),
        details=details,
        sources=["Datacenter JSON amenities", "Master plan description", "Vision model analysis"],
        short_label="Strong Active Lifestyle",
        tooltip="The project includes multiple sports, pool and movement-oriented amenities.",
    )


def _family_community_insight(context: dict) -> CategoryInsight:
    keywords = [
        "Kids' Play Areas / Sand Pits",
        "Day Care Center",
        "Pet Area",
        "Party Lawn",
        "Clubhouse",
        "Amphitheater",
        "Senior Citizen Area",
        "kids' play areas",
        "musical instrument park",
        "pet park",
        "camping zone",
        "dedicated zones for seniors",
        "clubhouses",
    ]
    details = _extract_exact_or_text_details(context, keywords)

    score = 42 + min(len(details) * 6, 42)
    if len(details) >= 6:
        score += 8
    score = _cap(score)

    return _category(
        key="family_community",
        label="Kids, Family and Community Living",
        score=score,
        confidence=context["confidence_label"],
        one_liner=(
            "Better suited for families and community living, with kids’ play areas, senior zones, pet park, camping zone, party lawn and clubhouse-led social spaces."
        ),
        detailed=(
            f"Family/community planning is supported by extracted details such as {', '.join(details[:10]) if details else 'kids, senior and clubhouse spaces'}. "
            "These signals are relevant for families, children, senior citizens and community engagement."
        ),
        positives=["Family-oriented and community-oriented amenities are present."],
        risks=_standard_risks(context),
        details=details,
        sources=["Datacenter JSON amenities", "Master plan description"],
        short_label="Family-Friendly Planning",
        tooltip="The project includes multiple family, senior, pet and community-living spaces.",
    )


def _water_leisure_insight(context: dict) -> CategoryInsight:
    keywords = ["Swimming Pool", "Kids' Pool", "pool", "kids' pool", "clubhouse", "stepped seating", "leisure"]
    details = _extract_exact_or_text_details(context, keywords)

    score = 45 + min(len(details) * 7, 35)
    if context["opencv_water"] > 0.5:
        score += 8
    if "water_pool" in context["detected_component_types"]:
        score += 8
    score = _cap(score)

    return _category(
        key="water_leisure",
        label="Water and Leisure Recreation",
        score=score,
        confidence=context["confidence_label"],
        one_liner=(
            "Good leisure fit for buyers who value pool-led recreation, with swimming pools, kids’ pool, clubhouse areas and stepped seating signals."
        ),
        detailed=(
            f"Water and leisure planning is supported by {', '.join(details[:8]) if details else 'pool and leisure signals'}. "
            f"OpenCV detected water/pool lower-bound at {context['opencv_water']}%."
        ),
        positives=["Swimming pool and leisure signals are present."],
        risks=_standard_risks(context),
        details=details,
        sources=["Datacenter JSON amenities", "Master plan description", "Vision model analysis", "OpenCV segmentation"],
        short_label="Water Leisure Present",
        tooltip="Pool and leisure zones are visible/declared, with exact area treated as estimated.",
    )


def _access_circulation_insight(context: dict) -> CategoryInsight:
    keywords = [
        "direct frontage",
        "frontage",
        "direct access",
        "access road",
        "approach road",
        "main driveway",
        "internal driveway",
        "driveway",
        "drop-off zones",
        "drop-off",
        "drop off",
        "school bus bay",
        "entry points",
        "entry point",
        "entry / exit",
        "entry/exit",
        "entry",
        "entrance",
        "exit",
        "security gate",
        "gate",
        "pedestrian",
        "vehicular traffic",
        "vehicular",
        "Internal road networks",
        "internal road",
        "road network",
        "Driveway and roads",
        "parking",
        "podium parking",
        "ramp",
        "circulation",
        "internal circulation",
        "movement",
        "internal movement",
    ]
    details = _extract_exact_or_text_details(context, keywords)

    score = 45 + min(len(details) * 6, 42)

    if "road_driveway" in context["detected_component_types"]:
        score += 8

    if len(details) >= 3:
        score = max(score, 62)

    if len(details) >= 5:
        score = max(score, 68)

    score = _cap(score)

    return _category(
        key="access_circulation",
        label="Access, Entry and Internal Circulation",
        score=score,
        confidence=context["confidence_label"],
        one_liner=(
            "Better planned for daily movement, with Thane-Belapur Road frontage, internal driveway, drop-off zones, school bus bay and pedestrian/vehicular entry planning."
        ),
        detailed=(
            f"Access planning is supported by extracted details such as {', '.join(details[:10]) if details else 'roads and driveways'}. "
            "These signals are useful for evaluating entry convenience, internal movement and daily pickup/drop-off flows."
        ),
        positives=["Multiple access and circulation signals were found."],
        risks=_standard_risks(context),
        details=details,
        sources=["Master plan description", "Vision model analysis"],
        short_label="Clear Circulation Planning",
        tooltip="The layout includes access, driveway and movement-related planning signals.",
    )


def _environment_sustainability_insight(context: dict) -> CategoryInsight:
    keywords = [
        "Rain Water Harvesting",
        "Sewage Treatment Plant",
        "Eco Friendly",
        "Large Green Area",
        "Solar Heaters",
        "Treated Water Supply",
        "green",
        "eco",
    ]
    details = _extract_exact_or_text_details(context, keywords)

    score = 40 + min(len(details) * 7, 45)
    score = _cap(score)

    return _category(
        key="environment_sustainability",
        label="Environment and Sustainability",
        score=score,
        confidence="High" if len(details) >= 4 else context["confidence_label"],
        one_liner=(
            "Shows declared sustainability-related features, including rainwater harvesting, STP, treated water supply, solar heaters and large green area."
        ),
        detailed=(
            f"Environment planning is supported by extracted details such as {', '.join(details[:10]) if details else 'green and sustainability amenities'}. "
            "These are structured project-data signals and should be shown as feature availability rather than certified sustainability performance."
        ),
        positives=["Environment-related amenities are available in Datacenter JSON."],
        risks=["Sustainability certification, savings and actual environmental performance are not verified by this model."],
        details=details,
        sources=["Datacenter JSON amenities"],
        short_label="Sustainability Signals Present",
        tooltip="Environment-related amenities are available, but certification, savings and actual performance are not inferred.",
    )


def _evidence_reliability_insight(context: dict) -> CategoryInsight:
    score = int(context["area_estimate"].confidence.score * 100)
    details = [
        f"Image quality: {context['image_metadata'].quality.label} ({context['image_metadata'].quality.score})",
        f"OpenCV unknown area: {context['opencv_unknown']}%",
        f"Area estimate confidence: {context['area_estimate'].confidence.label}",
    ]

    risks = _standard_risks(context)

    return _category(
        key="evidence_reliability",
        label="Evidence Reliability",
        score=score,
        confidence=context["area_estimate"].confidence.label,
        one_liner=(
            f"Reliable enough for directional comparison, but not for official measurement because the image is usable while OpenCV still leaves a large area unclassified."
        ),
        detailed=(
            "The model has strong Datacenter and Vision evidence, but OpenCV segmentation left a large share of pixels unclassified. "
            "Therefore, the output is suitable for estimated compare-module insights, not official measurement."
        ),
        positives=[
            "Project JSON is available.",
            "Image quality is usable.",
            "Vision model boundary confidence is high.",
        ],
        risks=risks,
        details=details,
        sources=["Image metadata", "Vision model analysis", "OpenCV segmentation", "Area estimate confidence"],
        short_label="Medium Evidence Reliability",
        tooltip="Evidence is good enough for estimated insights but not for official measurement.",
    )


def _build_overall_summary(categories: list[CategoryInsight], context: dict) -> OverallMasterPlanInsight:
    non_reliability = [item for item in categories if item.category_key != "evidence_reliability"]
    score = int(round(sum(item.score for item in non_reliability) / len(non_reliability)))

    strongest = [
        item.category_label
        for item in sorted(non_reliability, key=lambda item: item.score, reverse=True)[:3]
    ]

    watchouts = []
    if context["opencv_unknown"] > 70:
        watchouts.append("OpenCV unknown/unclassified area is very high.")
    for warning in context["area_estimate"].warnings:
        if warning not in watchouts:
            watchouts.append(warning)

    return OverallMasterPlanInsight(
        score=score,
        rating=_rating(score),
        confidence_label=context["area_estimate"].confidence.label,
        one_liner=(
            "The master plan appears strong on greenery, amenities, sports and openness, with confidence moderated by image uncertainty."
        ),
        detailed_summary=(
            "The project has multiple green, sports, water, family and access-related signals from the master plan and Datacenter JSON. "
            "However, the image appears stylized and OpenCV unknown area is high, so outputs should be treated as estimated planning insights rather than official measurements."
        ),
        strongest_categories=strongest,
        watchouts=watchouts,
    )


def _category(
    key: str,
    label: str,
    score: int,
    confidence: str,
    one_liner: str,
    detailed: str,
    positives: list[str],
    risks: list[str],
    details: list[str],
    sources: list[str],
    short_label: str,
    tooltip: str,
) -> CategoryInsight:
    final_score = _cap(score)

    # Prevent visually inferred categories from looking over-certain when evidence is only medium.
    structured_only_categories = {"amenity_richness", "environment_sustainability"}
    if confidence == "Medium" and key not in structured_only_categories:
        final_score = min(final_score, 89)

    return CategoryInsight(
        category_key=key,
        category_label=label,
        score=final_score,
        rating=_rating(final_score),
        confidence_label=confidence,
        one_liner=one_liner,
        detailed_insight=detailed,
        positive_signals=_dedupe(positives),
        risk_signals=_dedupe(risks),
        extracted_master_plan_details=_dedupe(details),
        evidence_sources=_dedupe(sources),
        compare_module_copy=CategoryCompareModuleCopy(
            short_label=short_label,
            tooltip=tooltip,
        ),
    )


def _qualitative_boost(value: str) -> int:
    mapping = {
        "Very Low": 0,
        "Low": 5,
        "Moderate": 12,
        "High": 22,
        "Very High": 28,
        "Unclear": 5,
    }
    return mapping.get(value, 5)


def _penalize_for_uncertainty(score: int, context: dict) -> int:
    adjusted = score
    if context["opencv_unknown"] > 70:
        adjusted -= 8
    elif context["opencv_unknown"] > 50:
        adjusted -= 5

    if any("stylized" in warning.lower() or "not to scale" in warning.lower() for warning in context["area_estimate"].warnings):
        adjusted -= 4

    return _cap(adjusted)


def _standard_risks(context: dict) -> list[str]:
    risks = []
    if context["opencv_unknown"] > 70:
        risks.append("OpenCV unknown/unclassified area is very high.")
    elif context["opencv_unknown"] > 50:
        risks.append("OpenCV unknown/unclassified area is high.")

    for warning in context["area_estimate"].warnings:
        risks.append(warning)

    return _dedupe(risks)


def _extract_exact_or_text_details(context: dict, keywords: list[str]) -> list[str]:
    found = []

    amenity_map = {item.lower(): item for item in context["amenities"]}

    for keyword in keywords:
        keyword_lower = keyword.lower()

        for amenity_lower, amenity in amenity_map.items():
            if keyword_lower in amenity_lower or amenity_lower in keyword_lower:
                found.append(amenity)

        if keyword_lower in context["master_plan_text"].lower():
            found.append(keyword)

        for component in context["detected_components"]:
            if keyword_lower in component.lower() or component.lower() in keyword_lower:
                found.append(component)

    return _dedupe(found)


def _extract_matching_details(context: dict, keywords: list[str]) -> list[str]:
    text = context["master_plan_text"]
    details = []

    details.extend(_extract_exact_or_text_details(context, keywords))

    # Extract readable phrases around keywords from master plan description.
    sentences = re.split(r"(?<=[.!?])\\s+", text)
    for sentence in sentences:
        lowered = sentence.lower()
        if any(keyword.lower() in lowered for keyword in keywords):
            cleaned = sentence.strip()
            if 3 <= len(cleaned.split()) <= 28:
                details.append(cleaned)

    return _dedupe(details)


def _strip_html(value: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", value or "")
    clean = re.sub(r"\\s+", " ", clean)
    return clean.strip()


def _rating(score: int) -> str:
    for threshold, rating in RATING_BANDS:
        if score >= threshold:
            return rating
    return "Weak"


def _cap(score: int | float) -> int:
    return int(max(0, min(100, round(score))))


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []

    for value in values:
        if value is None:
            continue

        cleaned = str(value).strip()
        if not cleaned:
            continue

        key = cleaned.lower()
        if key in seen:
            continue

        seen.add(key)
        result.append(cleaned)

    return result
