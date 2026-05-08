from app.services.vision_analyzer import parse_vision_analysis_payload


def test_parse_vision_analysis_payload():
    payload = {
        "project_id": "342956",
        "project_name": "Birla Taranya",
        "boundary": {
            "boundary_visible": True,
            "boundary_confidence": "Medium",
            "boundary_reason": "The boundary appears visible but partially inferred.",
            "manual_correction_recommended": True,
        },
        "detected_components": [
            {
                "component_type": "green_landscape",
                "label": "Central landscaped zone",
                "visual_description": "Large visible landscaped area near the amenities.",
                "confidence": "Medium",
                "likely_counts_toward_green_area": True,
                "likely_counts_toward_open_area": True,
                "likely_counts_as_building_footprint": False,
            },
            {
                "component_type": "building_footprint",
                "label": "Residential tower blocks",
                "visual_description": "Multiple tower footprints are visible.",
                "confidence": "High",
                "likely_counts_toward_green_area": False,
                "likely_counts_toward_open_area": False,
                "likely_counts_as_building_footprint": True,
            },
        ],
        "green_area_visual_estimate": {
            "qualitative_estimate": "Moderate",
            "reasoning": "Several green zones are visible but the image is not enough for exact measurement.",
        },
        "open_area_visual_estimate": {
            "qualitative_estimate": "High",
            "reasoning": "There are visible roads, courts, decks, and landscaped spaces.",
        },
        "building_footprint_visual_estimate": {
            "qualitative_estimate": "Moderate",
            "reasoning": "Multiple tower footprints are visible.",
        },
        "visible_green_area_indicators": ["landscaped zone", "green amenity area"],
        "visible_open_area_indicators": ["internal road", "sports court"],
        "visible_built_area_indicators": ["tower footprints"],
        "warnings": ["Boundary should be manually reviewed."],
        "model_notes": ["Qualitative analysis only."],
    }

    parsed = parse_vision_analysis_payload(payload)

    assert parsed.project_id == "342956"
    assert parsed.boundary.boundary_visible is True
    assert parsed.boundary.boundary_confidence == "Medium"
    assert parsed.boundary.manual_correction_recommended is True
    assert len(parsed.detected_components) == 2
    assert parsed.green_area_visual_estimate.qualitative_estimate == "Moderate"
    assert parsed.open_area_visual_estimate.qualitative_estimate == "High"
    assert parsed.building_footprint_visual_estimate.qualitative_estimate == "Moderate"
    assert len(parsed.warnings) == 1
