from PIL import Image, ImageDraw

from app.services.master_plan_entity_extractor import (
    GeminiMarkerExtraction,
    GeminiSiteExtraction,
    build_tile_specs,
    count_credible_wings,
    map_markers_to_full_image,
    marker_has_ink,
    merge_structure_and_wings,
    missing_wing_keys,
    normalize_entity_type,
    parse_master_plan_entity_payload,
    parse_model_json,
    reconcile_wing_labels,
    wing_key,
    wings_to_entities,
)
from app.services.master_plan_entity_extractor import _format_wing_label_like


def build_sample_payload() -> dict:
    return {
        "extraction_confidence_label": "High",
        "site": {
            "shape_class": "irregular",
            "north_arrow_present": True,
            "external_roads": [{"label": "12 m wide road", "width_text": "12 m", "side": "left"}],
            "entry_exit_count": 1,
        },
        "legend_items": [
            {"code": "01.", "label": "Entry/Exit"},
            {"code": "10.", "label": "Parking"},
            {"code": "12.", "label": "Water Cascading"},
            {"code": "24.", "label": "Tennis Court"},
            {"code": "36.", "label": "Butterfly Garden"},
        ],
        "entities": [
            {
                "entity_id": "e1",
                "entity_type": "residential_block",
                "label": "Wing - A",
                "box_2d": [100, 100, 300, 250],
                "confidence": "High",
                "attributes": [{"key": "wing", "value": "A"}],
            },
            {
                "entity_id": "e2",
                "entity_type": "residential_block",
                "label": "Wing - B",
                "box_2d": [600, 700, 850, 900],
                "confidence": "High",
            },
            {
                "entity_id": "e3",
                "entity_type": "sports_court",
                "label": "Tennis court",
                "legend_code": "24",
                "box_2d": [320, 120, 420, 220],
                "confidence": "Medium",
                "adjacent_to": ["Wing - A"],
            },
            # Marker for code 24 sits inside the court box: should merge, not duplicate.
            {
                "entity_id": "e4",
                "entity_type": "legend_marker",
                "legend_code": "24.",
                "label": "",
                "box_2d": [330, 130, 345, 140],
            },
            # Marker for code 36 has no layout box: becomes a located lawn_garden.
            {
                "entity_id": "e8",
                "entity_type": "legend_marker",
                "legend_code": "36",
                "label": "",
                "box_2d": [800, 200, 815, 212],
            },
            {
                "entity_id": "e5",
                "entity_type": "parking",
                "label": "Surface parking",
                "legend_code": "10",
                "box_2d": [650, 660, 720, 700],
            },
            {
                "entity_id": "e6",
                "entity_type": "Entry Gate",
                "label": "Entry/Exit",
                "legend_code": "1",
                "box_2d": [0, 0, 40, 40],
            },
            {
                "entity_id": "e7",
                "entity_type": "sports_court",
                "label": "Duplicate tennis court",
                "box_2d": [322, 122, 420, 220],
            },
            {
                "entity_id": "bad-box",
                "entity_type": "lawn_garden",
                "label": "Broken",
                "box_2d": [500, 500],
            },
            {
                "entity_id": "unknown-type",
                "entity_type": "spaceship_pad",
                "label": "Nope",
                "box_2d": [10, 10, 50, 50],
            },
        ],
        "diagnostics": [{"code": "marker_tile_failed", "count": 1, "items": ["timeout"]}],
    }


def test_parse_payload_builds_entities_and_derived_metadata():
    result = parse_master_plan_entity_payload(
        build_sample_payload(),
        image_width=1800,
        image_height=1200,
        project_id="p1",
        project_name="Sample",
    )

    assert result.project_id == "p1"
    assert result.coordinate_system == "fraction_of_image"

    # Duplicate court, bad box and unknown type are dropped; marker 24 merged
    # into the court; marker 36 became a feature of its own.
    labels = [entity.label for entity in result.entities]
    assert "Duplicate tennis court" not in labels
    assert "Broken" not in labels
    assert "Nope" not in labels
    assert not any(entity.entity_type == "legend_marker" for entity in result.entities)
    assert len(result.entities) == 6

    court = next(entity for entity in result.entities if entity.label == "Tennis court")
    assert court.entity_group == "amenity"
    assert court.legend_code == "24"
    assert court.legend_label == "Tennis Court"
    assert court.located_by == "both"
    assert court.category_key == "sports_active_lifestyle"
    assert court.nearest_residential_block == "Wing - A"
    assert court.box.x_min == 0.12 and court.box.y_min == 0.32

    garden = next(entity for entity in result.entities if entity.label == "Butterfly Garden")
    assert garden.entity_type == "lawn_garden"
    assert garden.located_by == "legend_marker"
    assert garden.legend_code == "36"
    # Marker boxes are expanded to a usable hover target.
    assert garden.box.x_max - garden.box.x_min >= 0.02
    assert garden.box.y_max - garden.box.y_min >= 0.02

    wing_a = next(entity for entity in result.entities if entity.label == "Wing - A")
    assert wing_a.attributes == {"wing": "A"}
    assert wing_a.located_by == "layout_model"
    assert wing_a.nearest_residential_block is None

    gate = next(entity for entity in result.entities if entity.entity_type == "entry_exit_gate")
    assert gate.legend_code == "01"

    by_code = {item.code: item for item in result.legend}
    assert set(by_code) == {"01", "10", "12", "24", "36"}
    assert by_code["24"].located_on_plan is True
    assert by_code["24"].marker_count == 1
    assert by_code["36"].located_on_plan is True
    assert by_code["12"].located_on_plan is False

    assert result.site.entry_exit_count == 1
    assert result.site.shape_class == "irregular"
    assert result.site.residential_block_labels == ["Wing - A", "Wing - B"]
    assert result.site.external_roads[0].width_text == "12 m"
    assert result.site.parking_cluster_count == 1

    proximity = {item.block_label: item for item in result.block_proximity}
    assert "Tennis court" in proximity["Wing - A"].nearby_amenities
    assert proximity["Wing - B"].near_parking is True
    assert proximity["Wing - A"].nearest_amenity_distance is not None
    assert proximity["Wing - A"].nearest_amenity_distance < 0.15

    assert result.entity_counts["residential_block"] == 2
    assert result.group_counts["structure"] == 3
    assert result.group_counts["landscape"] == 1

    # Diagnostics are machine-readable codes, never prose.
    codes = {item.code: item for item in result.diagnostics}
    assert codes["marker_tile_failed"].items == ["timeout"]
    assert codes["invalid_entities_dropped"].count == 2  # bad box + unknown type; the duplicate is deduped
    assert codes["legend_items_not_located"].items == ["12"]
    assert all(" " not in item.code for item in result.diagnostics)
    assert result.extraction_confidence_label == "High"


def test_collapsed_boxes_keep_only_the_first_entity():
    payload = {
        "legend_items": [],
        "entities": [
            {"entity_type": "residential_block", "label": "Tower 1", "box_2d": [100, 100, 300, 300]},
            {"entity_type": "swimming_pool", "label": "Pool", "box_2d": [600, 430, 620, 500]},
            {"entity_type": "sports_court", "label": "Court", "box_2d": [600, 430, 620, 500]},
            {"entity_type": "lawn_garden", "label": "Lawn", "box_2d": [600, 430, 620, 500]},
        ],
    }
    result = parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000)

    assert [entity.label for entity in result.entities] == ["Tower 1", "Pool"]
    assert {item.code: item.count for item in result.diagnostics}["collapsed_boxes_discarded"] == 2


def test_evenly_spaced_runs_and_oversized_boxes_are_discarded():
    payload = {
        "legend_items": [],
        "entities": [
            {"entity_type": "residential_block", "label": "Tower 1", "box_2d": [100, 100, 300, 300]},
            # Four identical parking boxes stepping 0.10 across one row: a pattern.
            {"entity_type": "parking", "label": "Parking", "box_2d": [300, 150, 340, 200]},
            {"entity_type": "parking", "label": "Parking", "box_2d": [300, 250, 340, 300]},
            {"entity_type": "parking", "label": "Parking", "box_2d": [300, 350, 340, 400]},
            {"entity_type": "parking", "label": "Parking", "box_2d": [300, 450, 340, 500]},
            # A genuine, irregular parking cluster survives.
            {"entity_type": "parking", "label": "Visitor parking", "box_2d": [700, 600, 760, 690]},
            # A road box covering most of the drawing is noise; the boundary is allowed to.
            {"entity_type": "internal_road", "label": "Road network", "box_2d": [100, 100, 950, 950]},
            {"entity_type": "site_boundary", "label": "Site boundary", "box_2d": [0, 0, 1000, 1000]},
        ],
    }
    result = parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000)

    labels = [entity.label for entity in result.entities]
    assert labels == ["Tower 1", "Visitor parking", "Site boundary"]
    codes = {item.code: item.count for item in result.diagnostics}
    assert codes["patterned_boxes_discarded"] == 4
    assert codes["oversized_boxes_discarded"] == 1


def test_drawing_box_far_from_its_legend_marker_is_discarded():
    payload = {
        "legend_items": [{"code": "24", "label": "Tennis Court"}, {"code": "13", "label": "Swimming Pool"}],
        "entities": [
            {"entity_type": "residential_block", "label": "Wing - A", "box_2d": [100, 100, 300, 300]},
            # Drawn far from marker 24: contradicted, dropped.
            {"entity_type": "sports_court", "label": "TENNIS COURT", "box_2d": [400, 650, 460, 710]},
            # Drawn around marker 13: agrees, merged.
            {"entity_type": "swimming_pool", "label": "Swimming pool", "box_2d": [250, 680, 290, 720]},
            {"entity_type": "legend_marker", "legend_code": "24", "label": "", "box_2d": [0.54, 0.40, 0.56, 0.42]},
            {"entity_type": "legend_marker", "legend_code": "13", "label": "", "box_2d": [0.26, 0.69, 0.28, 0.71]},
        ],
    }
    result = parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000)

    by_label = {entity.label: entity for entity in result.entities}
    assert "TENNIS COURT" not in by_label
    assert by_label["Tennis Court"].located_by == "legend_marker"
    assert by_label["Tennis Court"].entity_type == "sports_court"
    assert by_label["Swimming pool"].located_by == "both"
    assert by_label["Swimming pool"].legend_code == "13"
    assert len(result.entities) == 3
    assert {item.code: item.count for item in result.diagnostics}["marker_contradicted_boxes_discarded"] == 1


def test_normalize_entity_type_aliases():
    assert normalize_entity_type("residential_block") == "residential_block"
    assert normalize_entity_type("Tower") == "residential_block"
    assert normalize_entity_type("DG Yard / Transformer") == "utility_yard"
    assert normalize_entity_type("Kids play zone") == "kids_play_area"
    assert normalize_entity_type("12m wide external road") == "external_road"
    assert normalize_entity_type("Entry Plaza") == "plaza"
    assert normalize_entity_type("Snakes & Ladders") == "outdoor_game"
    assert normalize_entity_type("Nine Square") == "outdoor_game"
    assert normalize_entity_type("Water Cascading") == "water_feature"
    assert normalize_entity_type("Working Pods") == "working_pods"
    assert normalize_entity_type("Competition Pool") == "swimming_pool"
    # Word-start matching: "pet" must not fire inside "competition".
    assert normalize_entity_type("Competition") is None
    assert normalize_entity_type("") is None
    assert normalize_entity_type("spaceship_pad") is None


def test_boxes_accept_fraction_and_thousand_scale():
    payload = {
        "legend_items": [],
        "entities": [
            {"entity_id": "a", "entity_type": "lawn_garden", "label": "Lawn", "box_2d": [0.1, 0.2, 0.3, 0.4]},
            {"entity_id": "b", "entity_type": "lawn_garden", "label": "Lawn 2", "box_2d": [900, 800, 700, 600]},
        ],
    }
    result = parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000)

    lawn = result.entities[0]
    assert (lawn.box.x_min, lawn.box.y_min, lawn.box.x_max, lawn.box.y_max) == (0.2, 0.1, 0.4, 0.3)

    flipped = result.entities[1]
    assert (flipped.box.x_min, flipped.box.y_min, flipped.box.x_max, flipped.box.y_max) == (0.6, 0.7, 0.8, 0.9)

    assert result.extraction_confidence_label == "Low"


def test_tiles_cover_image_and_markers_map_back():
    tiles = build_tile_specs(2, 2, 0.1)
    assert len(tiles) == 4
    assert tiles[0] == (0.0, 0.0, 0.6, 0.6)
    assert tiles[3] == (0.4, 0.4, 1.0, 1.0)

    mapped = map_markers_to_full_image(
        [{"legend_code": "24", "box_2d": [500, 500, 600, 600]}],
        tiles[3],
    )
    assert len(mapped) == 1
    ymin, xmin, ymax, xmax = mapped[0]["box_2d"]
    assert (round(xmin, 3), round(ymin, 3), round(xmax, 3), round(ymax, 3)) == (0.7, 0.7, 0.76, 0.76)
    assert mapped[0]["entity_type"] == "legend_marker"


def test_same_marker_seen_in_two_tiles_yields_one_feature():
    payload = {
        "legend_items": [{"code": "35", "label": "Musical Garden"}, {"code": "10", "label": "Parking"}],
        "entities": [
            {"entity_type": "residential_block", "label": "Wing - A", "box_2d": [100, 100, 300, 300]},
            # Same circle, two overlapping tiles, boxes a few pixels apart and not overlapping.
            {"entity_type": "legend_marker", "legend_code": "35", "label": "", "box_2d": [0.550, 0.040, 0.562, 0.052]},
            {"entity_type": "legend_marker", "legend_code": "35.", "label": "", "box_2d": [0.556, 0.053, 0.568, 0.065]},
            # Two genuinely different parking markers far apart stay separate.
            {"entity_type": "legend_marker", "legend_code": "10", "label": "", "box_2d": [0.300, 0.300, 0.312, 0.312]},
            {"entity_type": "legend_marker", "legend_code": "10", "label": "", "box_2d": [0.700, 0.700, 0.712, 0.712]},
        ],
    }
    result = parse_master_plan_entity_payload(payload, image_width=1800, image_height=1200)

    gardens = [entity for entity in result.entities if entity.label == "Musical Garden"]
    parkings = [entity for entity in result.entities if entity.entity_type == "parking"]
    assert len(gardens) == 1
    assert len(parkings) == 2
    assert {item.code: item.marker_count for item in result.legend} == {"35": 1, "10": 2}


def test_dedicated_wing_pass_replaces_structure_wings_and_detects_fabrication():
    structure = [
        {"entity_type": "residential_block", "label": "Wing - A", "box_2d": [100, 100, 200, 200]},
        {"entity_type": "clubhouse", "label": "Clubhouse", "box_2d": [300, 300, 400, 400]},
    ]
    credible_wings = wings_to_entities(
        [
            {"label": "Wing - G", "wing": "G", "box_2d": [420, 100, 570, 190]},
            {"label": "Wing - H", "wing": "H", "box_2d": [580, 100, 720, 250]},
            {"label": "Wing - F", "wing": "F", "box_2d": [490, 290, 620, 440]},
        ]
    )
    assert credible_wings[0]["entity_type"] == "residential_block"
    assert credible_wings[0]["attributes"] == [{"key": "wing", "value": "G"}]
    assert count_credible_wings(credible_wings) == 3

    merged = merge_structure_and_wings(structure, credible_wings)
    assert sorted(item["label"] for item in merged) == ["Clubhouse", "Wing - A", "Wing - F", "Wing - G", "Wing - H"]

    # No wing pass result: the structures call's wing is kept as a fallback.
    assert sorted(item["label"] for item in merge_structure_and_wings(structure, [])) == ["Clubhouse", "Wing - A"]

    # Same-size boxes at a regular step are the model fabricating a pattern.
    fabricated = wings_to_entities(
        [
            {"label": "Wing - A", "box_2d": [400, 100, 540, 250]},
            {"label": "Wing - B", "box_2d": [400, 300, 540, 450]},
            {"label": "Wing - C", "box_2d": [400, 500, 540, 650]},
            {"label": "Wing - D", "box_2d": [400, 700, 540, 850]},
        ]
    )
    assert count_credible_wings(fabricated) == 0

    # Boxes the height of a text line are the printed label, not the footprint.
    label_sized = wings_to_entities([{"label": "Wing - G", "box_2d": [410, 100, 430, 160]}])
    assert count_credible_wings(label_sized) == 0

    # When both passes name the same wing, the footprint-sized box wins.
    footprint = {"entity_type": "residential_block", "label": "WING - G", "box_2d": [420, 100, 570, 190]}
    chosen = merge_structure_and_wings([footprint], label_sized)
    assert len(chosen) == 1
    assert chosen[0]["box_2d"] == [420, 100, 570, 190]


def test_cross_type_column_of_identical_boxes_is_discarded():
    payload = {
        "legend_items": [],
        "entities": [
            {"entity_type": "residential_block", "label": "Wing - A", "box_2d": [100, 100, 300, 300]},
            # Different features, one exact size, one shared left edge, uneven step: a placeholder column.
            {"entity_type": "driveway", "label": "Driveway", "box_2d": [390, 600, 410, 620]},
            {"entity_type": "commercial_block", "label": "Commercial", "box_2d": [410, 600, 430, 620]},
            {"entity_type": "water_feature", "label": "Water Feature", "box_2d": [450, 600, 470, 620]},
            {"entity_type": "swimming_pool", "label": "Swimming Pool", "box_2d": [490, 600, 510, 620]},
            # A genuine pool elsewhere survives.
            {"entity_type": "swimming_pool", "label": "Lap pool", "box_2d": [700, 200, 760, 300]},
        ],
    }
    result = parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000)

    assert sorted(entity.label for entity in result.entities) == ["Lap pool", "Wing - A"]
    assert {item.code: item.count for item in result.diagnostics}["patterned_boxes_discarded"] == 4


def test_overlapping_wing_choice_is_resolved_with_the_other_pass():
    # Structures pass put Wing E on top of Wing D; the dedicated pass has E elsewhere.
    structure = [
        {"entity_type": "residential_block", "label": "WING - D", "box_2d": [370, 390, 470, 440]},
        {"entity_type": "residential_block", "label": "WING - E", "box_2d": [400, 390, 500, 440]},
    ]
    dedicated = wings_to_entities(
        [
            {"label": "Wing - D", "box_2d": [370, 390, 470, 440]},
            {"label": "Wing - E", "box_2d": [430, 310, 490, 380]},
        ]
    )
    merged = {item["label"].lower(): item["box_2d"] for item in merge_structure_and_wings(structure, dedicated)}
    assert merged["wing - e"] == [430, 310, 490, 380]
    assert merged["wing - d"] == [370, 390, 470, 440]


def test_tiny_cross_type_pairs_and_road_label_boxes_are_discarded():
    payload = {
        "legend_items": [],
        "entities": [
            {"entity_type": "residential_block", "label": "Wing - A", "box_2d": [100, 100, 300, 300]},
            # Placeholder pair: tiny, same size, same left edge, different types.
            {"entity_type": "entry_exit_gate", "label": "Entry Gate", "box_2d": [370, 620, 390, 640]},
            {"entity_type": "security_cabin", "label": "Security Cabin", "box_2d": [390, 620, 410, 640]},
            # Two real courts drawn alike and side by side must survive.
            {"entity_type": "sports_court", "label": "Tennis Court", "box_2d": [600, 400, 680, 460]},
            {"entity_type": "swimming_pool", "label": "Lap Pool", "box_2d": [600, 470, 680, 530]},
            # The road's printed label boxed as an internal road.
            {"entity_type": "internal_road", "label": "12M Wide Road", "box_2d": [350, 60, 370, 100]},
        ],
    }
    result = parse_master_plan_entity_payload(payload, image_width=1800, image_height=1270)

    assert sorted(entity.label for entity in result.entities) == ["Lap Pool", "Tennis Court", "Wing - A"]
    codes = {item.code: item.count for item in result.diagnostics}
    assert codes["patterned_boxes_discarded"] == 2
    assert codes["road_label_boxes_discarded"] == 1


def test_wing_labels_are_corrected_from_the_printed_name():
    assert wing_key("WING - B") == "b"
    assert wing_key("Tower 12") == "12"
    assert wing_key("B") == "b"
    assert wing_key("Clubhouse") is None

    wings = wings_to_entities(
        [
            {"label": "Wing - A", "wing": "A", "box_2d": [400, 600, 500, 680]},
            {"label": "Wing - B", "wing": "B", "box_2d": [510, 360, 610, 430]},  # actually Wing F
            {"label": "Wing - F", "wing": "F", "box_2d": [420, 310, 490, 380]},  # actually Wing E
            {"label": "Wing - E", "wing": "E", "box_2d": [420, 270, 490, 340]},  # unreadable crop
        ]
    )
    printed = ["WING - A", "WING - F", "WING - E", None]
    fixed, diagnostic = reconcile_wing_labels(wings, printed)

    by_label = {raw["label"].lower(): raw for raw in fixed}
    assert "wing - a" in by_label
    assert by_label["wing - f"]["box_2d"] == [510, 360, 610, 430]
    assert by_label["wing - f"]["attributes"] == [{"key": "wing", "value": "F"}]
    # The verified E (relabelled from F's box) beats the unverified claim of E.
    assert by_label["wing - e"]["box_2d"] == [420, 310, 490, 380]
    assert "wing - b" not in by_label
    assert diagnostic == {"code": "wing_labels_reconciled", "count": 3, "items": ["relabelled:2", "dropped:1"]}

    untouched, none = reconcile_wing_labels(wings[:1], ["Wing - A"])
    assert untouched == wings[:1]
    assert none is None


def test_missing_wing_keys_finds_gaps_in_sequential_runs():
    assert missing_wing_keys(["a", "b", "c", "d", "e", "g", "h"]) == ["f"]
    assert missing_wing_keys(["1", "2", "4"]) == ["3"]
    assert missing_wing_keys(["a", "b", "c"]) == []
    assert missing_wing_keys(["a"]) == []
    assert missing_wing_keys(["a", "2"]) == []
    assert missing_wing_keys([None, "b", "d"]) == ["c"]
    assert _format_wing_label_like("WING - A", "f") == "WING - F"
    assert _format_wing_label_like("Tower 3", "7") == "Tower 7"
    assert _format_wing_label_like("Something odd", "b") == "Wing - B"


def test_per_type_area_caps_drop_plan_sized_tree_belts():
    payload = {
        "legend_items": [],
        "entities": [
            {"entity_type": "tree_canopy_buffer", "label": "Tree belt", "box_2d": [280, 20, 700, 590]},
            {"entity_type": "tree_canopy_buffer", "label": "Edge trees", "box_2d": [100, 590, 230, 900]},
            {"entity_type": "internal_road", "label": "Loop road", "box_2d": [280, 100, 750, 950]},
        ],
    }
    result = parse_master_plan_entity_payload(payload, image_width=1800, image_height=1270)
    assert [entity.label for entity in result.entities] == ["Edge trees"]
    assert {item.code: item.count for item in result.diagnostics}["oversized_boxes_discarded"] == 2


def test_parse_model_json_wraps_a_bare_list():
    wrapped = parse_model_json('[{"legend_code": "24", "box_2d": [1, 2, 3, 4]}]', GeminiMarkerExtraction)
    assert wrapped == {"markers": [{"legend_code": "24", "box_2d": [1, 2, 3, 4]}]}
    assert parse_model_json('{"markers": []}', GeminiMarkerExtraction) == {"markers": []}


def test_parse_model_json_salvages_a_looping_legend_response():
    looping = (
        '{"extraction_confidence_label": "High", "site": {"shape_class": "l_shaped"}, "legend_items": ['
        '{"code": "01", "label": "Entry/Exit"}, {"code": "02", "label": "Entry Gate"}, '
        '{"code": "03", "label": "Driveway"}, {"code": "01", "label": "Entry/Exit"}, '
        '{"code": "02", "label": "Entry Gate"}, {"code": "03", "label": "Driveway"}, {"code": "01", "label": "Entry/Ex'
    )
    salvaged = parse_model_json(looping, GeminiSiteExtraction)
    assert salvaged["legend_items"] == [
        {"code": "01", "label": "Entry/Exit"},
        {"code": "02", "label": "Entry Gate"},
        {"code": "03", "label": "Driveway"},
    ]
    assert salvaged["entities"] == []


def test_parse_model_json_salvages_truncated_marker_list():
    truncated = (
        '{"markers": [\n'
        '  {"legend_code": "10", "box_2d": [100, 200, 120, 220]},\n'
        '  {"box_2d": [300, 400, 320, 420], "legend_code": "24"},\n'
        '  {"legend_code": "11", "box_2d": [500, 6'
    )
    salvaged = parse_model_json(truncated, GeminiMarkerExtraction)
    assert salvaged == {
        "markers": [
            {"legend_code": "10", "box_2d": [100, 200, 120, 220]},
            {"legend_code": "24", "box_2d": [300, 400, 320, 420]},
        ]
    }


def test_marker_has_ink_rejects_blank_paper():
    image = Image.new("RGB", (400, 400), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((100, 100, 130, 130), fill=(230, 120, 20))

    on_marker = [100 / 400, 100 / 400, 130 / 400, 130 / 400]
    on_blank = [300 / 400, 300 / 400, 330 / 400, 330 / 400]

    assert marker_has_ink(image, on_marker) is True
    assert marker_has_ink(image, on_blank) is False
