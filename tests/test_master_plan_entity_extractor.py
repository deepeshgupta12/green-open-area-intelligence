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


def _water_payload() -> dict:
    payload = build_sample_payload()
    payload["legend_items"] = [{"code": "1", "label": "Pet Park"}, {"code": "2", "label": "Party Lawn"}]
    payload["entities"] = [
        {"entity_id": "w1", "entity_type": "swimming_pool", "label": "Swimming Pool 1", "box_2d": [100, 100, 180, 200], "confidence": "High"},
        {"entity_id": "w2", "entity_type": "swimming_pool", "label": "Swimming Pool 2", "box_2d": [400, 400, 470, 520]},
        {"entity_id": "w3", "entity_type": "water_feature", "label": "Water Feature", "box_2d": [700, 100, 760, 190]},
        {"entity_id": "w4", "entity_type": "swimming_pool", "label": "Marked pool", "box_2d": [500, 700, 590, 800], "located_by": "legend_marker"},
        {"entity_id": "b1", "entity_type": "residential_block", "label": "Wing - A", "box_2d": [600, 100, 900, 300]},
    ]
    return payload


def test_unsupported_water_entities_need_no_legend_or_records_support():
    from app.schemas.project_schema import AmenityRecord, ParsedProjectMetadata
    from app.services.master_plan_entity_extractor import unsupported_water_entities

    payload = _water_payload()
    entity_map = parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000)
    # Only the drawn pools are suspects; the marker-located one is trusted.
    assert [entity.entity_id for entity in unsupported_water_entities(entity_map, None)] == ["w1", "w2", "w3"]

    # A legend row that mentions water vouches for every drawn pool.
    payload["legend_items"].append({"code": "3", "label": "Swimming Pool"})
    vouched = parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000)
    assert unsupported_water_entities(vouched, None) == []

    # So does a declared amenity in the project records.
    project = ParsedProjectMetadata.model_construct(amenities=[AmenityRecord(name="Kids Splash Pool")])
    assert unsupported_water_entities(entity_map, project) == []


def test_water_verdicts_drop_only_rejected_crops_and_recount():
    from app.services.master_plan_entity_extractor import apply_water_verdicts, unsupported_water_entities

    entity_map = parse_master_plan_entity_payload(_water_payload(), image_width=1000, image_height=1000)
    suspects = unsupported_water_entities(entity_map, None)
    assert entity_map.group_counts["water"] == 4

    verdicts = [
        {"feature": "building_or_roof", "is_water": False, "reason": "tower footprint"},
        None,  # the crop could not be checked: keep it
        {"feature": "swimming_pool", "is_water": True},
    ]
    checked = apply_water_verdicts(entity_map, suspects, verdicts)

    assert [entity.entity_id for entity in checked.entities if entity.entity_group == "water"] == ["w2", "w3", "w4"]
    assert checked.group_counts["water"] == 3
    assert checked.entity_counts["swimming_pool"] == 2
    codes = {diagnostic.code: diagnostic for diagnostic in checked.diagnostics}
    assert codes["unsupported_water_discarded"].count == 1
    assert codes["unsupported_water_discarded"].items == ["Swimming Pool 1: building or roof"]
    assert codes["water_verification_failed"].count == 1
    assert checked.block_proximity[0].block_label == "Wing - A"

    # Nothing rejected: the map is unchanged apart from the diagnostics.
    untouched = apply_water_verdicts(entity_map, suspects, [{"is_water": True}] * 3)
    assert len(untouched.entities) == len(entity_map.entities)
    assert "unsupported_water_discarded" not in {diagnostic.code for diagnostic in untouched.diagnostics}


def test_water_ink_share_separates_blue_water_from_pale_plates():
    from app.schemas.master_plan_entity_schema import EntityBox
    from app.services.master_plan_entity_extractor import WATER_MIN_BLUE_SHARE, water_ink_share

    image = Image.new("RGB", (200, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 90, 90), fill=(70, 190, 230))  # saturated cyan pool
    draw.rectangle((110, 10, 190, 90), fill=(205, 220, 230))  # pale grey-blue tower plate

    pool = water_ink_share(image, EntityBox(x_min=0.05, y_min=0.1, x_max=0.45, y_max=0.9))
    plate = water_ink_share(image, EntityBox(x_min=0.55, y_min=0.1, x_max=0.95, y_max=0.9))
    assert pool >= 0.9 > WATER_MIN_BLUE_SHARE
    assert plate < WATER_MIN_BLUE_SHARE


def _key_note_payload() -> dict:
    """A plan like Kalpataru Vian: lobby letters on the buildings, wing names only in a printed note."""
    payload = build_sample_payload()
    payload["legend_items"] = [{"code": "1", "label": "Pet Park"}, {"code": "2", "label": "Party Lawn"}]
    payload["entities"] = [
        # Umbrella box around both buildings, named after a drop-off note.
        {"entity_id": "u", "entity_type": "residential_block", "label": "Tower 1", "box_2d": [356, 91, 526, 909]},
        # Right building holds lobby marker C and drop-off marker A just below it.
        {"entity_id": "r", "entity_type": "residential_block", "label": "Wing - C", "box_2d": [359, 543, 526, 910]},
        # Left building holds lobby marker D and drop-off marker B just below it.
        {"entity_id": "l", "entity_type": "residential_block", "label": "Wing - D", "box_2d": [359, 90, 526, 473]},
        {"entity_id": "mC", "entity_type": "legend_marker", "legend_code": "C", "label": "", "box_2d": [430, 720, 447, 735]},
        {"entity_id": "mA", "entity_type": "legend_marker", "legend_code": "A", "label": "", "box_2d": [530, 720, 546, 735]},
        {"entity_id": "mD", "entity_type": "legend_marker", "legend_code": "D", "label": "", "box_2d": [431, 265, 447, 280]},
        {"entity_id": "mB", "entity_type": "legend_marker", "legend_code": "B", "label": "", "box_2d": [532, 266, 547, 281]},
        {"entity_id": "m1", "entity_type": "legend_marker", "legend_code": "1", "label": "", "box_2d": [600, 100, 615, 115]},
        {"entity_id": "p", "entity_type": "parking", "label": "Parking", "box_2d": [560, 400, 620, 600]},
    ]
    return payload


def test_key_notes_are_parsed_into_wings_and_towers():
    from app.services.master_plan_entity_extractor import parse_key_notes

    notes = parse_key_notes(["A Tower 1 Drop Off | B Tower 2 Drop Off", "C Lobby- Wing A&B", "D Lobby- Wing C & D", "Legend"])
    assert set(notes) == {"a", "b", "c", "d"}
    assert notes["a"].tower == "Tower 1" and notes["a"].wings == []
    assert notes["b"].tower == "Tower 2"
    assert notes["c"].wings == ["A", "B"] and notes["c"].tower is None
    assert notes["d"].wings == ["C", "D"]


def test_key_notes_only_trigger_for_letter_keys_outside_the_legend():
    from app.services.master_plan_entity_extractor import needs_key_notes

    assert needs_key_notes(parse_master_plan_entity_payload(_key_note_payload(), image_width=1000, image_height=1000))
    # Numbered markers that match legend rows (the common case) never trigger the extra call.
    assert not needs_key_notes(parse_master_plan_entity_payload(build_sample_payload(), image_width=1000, image_height=1000))


def test_blocks_are_named_from_key_notes_and_the_umbrella_box_is_dropped():
    from app.services.master_plan_entity_extractor import apply_key_notes, parse_key_notes

    entity_map = parse_master_plan_entity_payload(_key_note_payload(), image_width=1000, image_height=1000)
    assert entity_map.site.residential_block_labels == ["Tower 1", "Wing - C", "Wing - D"]

    notes = parse_key_notes(["A Tower 1 Drop Off", "B Tower 2 Drop Off", "C Lobby- Wing A&B", "D Lobby- Wing C&D"])
    named = apply_key_notes(entity_map, notes)

    blocks = {entity.entity_id: entity for entity in named.entities if entity.entity_type == "residential_block"}
    assert set(blocks) == {"r", "l"}
    assert blocks["r"].label == "Tower 1 (Wing A & B)" and blocks["r"].attributes["wing"] == "A & B"
    assert blocks["l"].label == "Tower 2 (Wing C & D)" and blocks["l"].attributes["tower"] == "Tower 2"
    assert named.site.residential_block_labels == ["Tower 1 (Wing A & B)", "Tower 2 (Wing C & D)"]
    assert named.entity_counts["residential_block"] == 2
    assert {block.block_label for block in named.block_proximity} == {"Tower 1 (Wing A & B)", "Tower 2 (Wing C & D)"}
    parking = next(entity for entity in named.entities if entity.entity_type == "parking")
    assert parking.nearest_residential_block in {"Tower 1 (Wing A & B)", "Tower 2 (Wing C & D)"}
    codes = {diagnostic.code: diagnostic for diagnostic in named.diagnostics}
    assert codes["blocks_named_from_key_notes"].items[:2] == ["relabelled:2", "umbrella_dropped:1"]

    # Notes without any wing mapping leave the map untouched.
    assert apply_key_notes(entity_map, parse_key_notes(["A Tower 1 Drop Off"])) is entity_map


def test_block_plan_mode_only_for_plans_without_a_legend():
    from app.services.master_plan_entity_extractor import is_block_plan

    assert not is_block_plan(parse_master_plan_entity_payload(build_sample_payload(), image_width=1000, image_height=1000))
    payload = build_sample_payload()
    payload["legend_items"] = []
    assert is_block_plan(parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000))


def test_printed_records_are_typed_and_fsi_is_derived():
    from app.services.master_plan_entity_extractor import printed_records_from_payload

    records = printed_records_from_payload(
        {
            "title": "Mahindra Rainforest Phase-2",
            "plot_area_text": "2,835.56 sq.m.",
            "plot_area_sq_m": 2835.56,
            "sanctioned_bua_text": "51,683.45 sq.m.",
            "sanctioned_bua_sq_m": "51683.45",
            "scale_text": "1 : 1000",
            "parcels": [
                {"label": "RE. 1.1 MUNICIPAL SCHOOL AREA", "area_text": "REQ. 2668.10 Sq.Mt.", "area_sq_m": 2668.1, "box_2d": [408, 763, 556, 843]},
                {"label": "R. ZONE A.O.S.", "area_text": "629.10 / 366.73", "area_sq_m": None, "box_2d": [189, 661, 257, 691]},
                {"label": "", "area_sq_m": 5},
                "junk",
            ],
        }
    )
    assert records is not None
    assert records.plot_area_sq_m == 2835.56 and records.sanctioned_bua_sq_m == 51683.45
    assert records.derived_fsi == 18.23
    assert [parcel.label for parcel in records.parcels] == ["RE. 1.1 MUNICIPAL SCHOOL AREA", "R. ZONE A.O.S."]
    assert records.parcels[0].box is not None
    # A missing number falls back to the first figure printed in the area text.
    assert records.parcels[1].area_sq_m == 629.1
    assert printed_records_from_payload({"parcels": [], "plot_area_sq_m": -3}) is None


def test_footprints_skip_known_blocks_and_odd_sizes_and_keep_reading_order():
    from app.services.master_plan_entity_extractor import apply_block_plan_results, select_footprints

    payload = build_sample_payload()
    payload["legend_items"] = []
    entity_map = parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000)
    known = [entity for entity in entity_map.entities if entity.entity_type == "residential_block"]
    assert [entity.label for entity in known] == ["Wing - A", "Wing - B"]

    raws = [
        {"label": "BLDG. 3", "highlighted": False, "box_2d": [775, 510, 857, 590]},  # bottom row, middle
        {"label": "BLDG. 7", "highlighted": False, "box_2d": [775, 97, 857, 180]},  # bottom row, left
        {"label": "Wing - A", "highlighted": False, "box_2d": [100, 100, 300, 250]},  # already boxed by the wing pass
        {"label": "BLDG. 1", "highlighted": False, "box_2d": [209, 510, 354, 740]},  # plot outline, far too wide
        {"label": "BLDG. 2", "highlighted": False, "box_2d": [272, 467, 300, 540]},  # thin strip
        {"label": "TOWER 1", "highlighted": True, "box_2d": [560, 589, 640, 670]},  # middle row, highlighted
        {"label": "BLDG. 8", "highlighted": False, "box_2d": [555, 174, 640, 260]},  # middle row, left
    ]
    chosen = select_footprints(raws, known)
    assert [raw["label"] for raw in chosen] == ["BLDG. 8", "TOWER 1", "BLDG. 7", "BLDG. 3"]

    printed = [None, "WING-E", None, "garbage text"]
    result = apply_block_plan_results(entity_map, None, chosen, printed)
    blocks = [entity for entity in result.entities if entity.entity_type == "residential_block"]
    assert [entity.label for entity in blocks] == ["Wing - A", "Wing - B", "Footprint 1", "WING-E", "Footprint 2", "Footprint 3"]
    highlighted = next(entity for entity in blocks if entity.label == "WING-E")
    assert highlighted.attributes == {"wing": "E", "highlighted": "yes"}
    assert result.site.drawing_style == "block_plan" and result.site.printed_records is None
    assert result.site.residential_block_labels == ["Footprint 1", "Footprint 2", "Footprint 3", "WING-E", "Wing - A", "Wing - B"]
    assert result.entity_counts["residential_block"] == 6
    assert {diagnostic.code for diagnostic in result.diagnostics} >= {"block_plan_mode"}


def test_footprint_passes_merge_by_overlap_and_duplicate_names_become_footprints():
    from app.services.master_plan_entity_extractor import apply_block_plan_results, merge_footprint_candidates

    first = [{"label": None, "box_2d": [775, 510, 857, 590]}, {"label": None, "box_2d": [560, 589, 640, 670]}, "junk"]
    second = [
        {"label": None, "box_2d": [778, 512, 860, 592]},  # same building as the first pass, slightly shifted
        {"label": None, "box_2d": [775, 97, 857, 180]},  # new
        {"label": None, "box_2d": [10, 10]},  # unusable box
    ]
    merged = merge_footprint_candidates(first, second)
    assert [raw["box_2d"] for raw in merged] == [[775, 510, 857, 590], [560, 589, 640, 670], [775, 97, 857, 180]]

    payload = build_sample_payload()
    payload["legend_items"] = []
    entity_map = parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000)
    # "Wing - A" is already a block: a footprint whose crop also reads "WING-A" is not a second Wing A.
    result = apply_block_plan_results(entity_map, None, merged, ["WING-A", "WING - F", "Wing F"])
    blocks = [entity.label for entity in result.entities if entity.entity_type == "residential_block"]
    assert blocks == ["Wing - A", "Wing - B", "Footprint 1", "WING - F", "Footprint 2"]


def test_footprint_crop_verdicts_drop_only_rejected_candidates():
    from app.services.master_plan_entity_extractor import keep_verified_footprints

    raws = [{"box_2d": [1, 1, 2, 2]}, {"box_2d": [3, 3, 4, 4]}, {"box_2d": [5, 5, 6, 6]}]
    kept, rejected = keep_verified_footprints(raws, [{"is_building": True}, {"is_building": False, "what": "parcel"}, None])
    assert kept == [raws[0], raws[2]] and rejected == 1


def test_phase_highlight_is_decided_from_measured_fill():
    from app.schemas.master_plan_entity_schema import EntityBox
    from app.services.master_plan_entity_extractor import HIGHLIGHT_MIN_SHARE, fill_saturation_share, mark_highlighted_blocks

    image = Image.new("RGB", (200, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 90, 90), fill=(235, 150, 200))  # magenta-hatched phase tower
    draw.rectangle((110, 10, 190, 90), outline=(40, 40, 40), width=2)  # bare outline
    pink = fill_saturation_share(image, EntityBox(x_min=0.05, y_min=0.1, x_max=0.45, y_max=0.9))
    outline = fill_saturation_share(image, EntityBox(x_min=0.55, y_min=0.1, x_max=0.95, y_max=0.9))
    assert pink > HIGHLIGHT_MIN_SHARE > outline

    payload = build_sample_payload()
    payload["entities"][0]["attributes"] = [{"key": "wing", "value": "A"}, {"key": "highlighted", "value": "yes"}]  # model guess
    entity_map = parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000)
    wing_a = next(e for e in entity_map.entities if e.label == "Wing - A")
    wing_b = next(e for e in entity_map.entities if e.label == "Wing - B")
    marked = mark_highlighted_blocks(entity_map, {wing_a.entity_id: 0.02, wing_b.entity_id: 0.6})
    by_label = {e.label: e.attributes for e in marked.entities if e.entity_type == "residential_block"}
    assert by_label["Wing - A"] == {"wing": "A"}  # the guess is cleared by the measurement
    assert by_label["Wing - B"] == {"highlighted": "yes"}
    assert mark_highlighted_blocks(marked, {}) is marked


def test_bare_number_markers_resolve_prefixed_legend_codes():
    from app.services.master_plan_entity_extractor import bare_number_aliases, build_targeted_marker_prompt

    assert bare_number_aliases(["GR-1", "GR-12", "PT-33", "A"]) == {"1": "gr-1", "12": "gr-12", "33": "pt-33"}
    # A number shared by two prefixes is ambiguous and gets no alias.
    assert bare_number_aliases(["GR-1", "PT-1", "RE-2"]) == {"2": "re-2"}
    assert "GR-13 (the circle may print just 13)" in build_targeted_marker_prompt(["GR-13", "A"])

    payload = build_sample_payload()
    payload["legend_items"] = [
        {"code": "GR-1", "label": "Four a Side Football Court"},
        {"code": "GR-12", "label": "Siddha walk"},
        {"code": "PT-33", "label": "Skating rink"},
        {"code": "PT-44", "label": "Swimming pool"},
    ]
    payload["entities"] = [
        {"entity_id": "e1", "entity_type": "residential_block", "label": "Wing - A", "box_2d": [100, 100, 300, 250]},
        # Circles on the plan print the bare numbers.
        {"entity_id": "m1", "entity_type": "legend_marker", "legend_code": "12", "label": "", "box_2d": [500, 500, 515, 515]},
        {"entity_id": "m2", "entity_type": "legend_marker", "legend_code": "33", "label": "", "box_2d": [600, 600, 615, 615]},
        {"entity_id": "m3", "entity_type": "legend_marker", "legend_code": "GR-1", "label": "", "box_2d": [700, 700, 715, 715]},
    ]
    entity_map = parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000)
    located = {item.code: item.located_on_plan for item in entity_map.legend}
    assert located == {"GR-1": True, "GR-12": True, "PT-33": True, "PT-44": False}
    placed = {entity.label: entity.legend_code for entity in entity_map.entities if entity.located_by == "legend_marker"}
    assert placed == {"Four a Side Football Court": "GR-1", "Siddha walk": "GR-12", "Skating rink": "PT-33"}


def test_marker_only_area_features_get_the_drawn_area_box_when_credible():
    from app.schemas.master_plan_entity_schema import EntityBox
    from app.services.master_plan_entity_extractor import (
        apply_region_boxes,
        expansion_tile,
        marker_only_area_features,
        region_box_from_payload,
    )

    payload = build_sample_payload()
    payload["legend_items"] = [{"code": "4", "label": "Futsal Court"}, {"code": "9", "label": "Pet Park"}, {"code": "2", "label": "Club House"}]
    payload["entities"] = [
        {"entity_id": "e1", "entity_type": "residential_block", "label": "Wing - A", "box_2d": [100, 100, 300, 250]},
        {"entity_id": "m4", "entity_type": "legend_marker", "legend_code": "4", "label": "", "box_2d": [300, 400, 315, 415]},
        {"entity_id": "m9", "entity_type": "legend_marker", "legend_code": "9", "label": "", "box_2d": [700, 100, 715, 115]},
    ]
    entity_map = parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000)
    targets = {entity.label: entity for entity in marker_only_area_features(entity_map)}
    assert set(targets) == {"Futsal Court", "Pet Park"}  # both are area types placed by a marker only

    court = targets["Futsal Court"]
    tile = expansion_tile(court, aspect=1.0)
    assert tile[0] < court.center_x < tile[2] and tile[1] < court.center_y < tile[3]

    # A credible answer: a box in crop coordinates that contains the marker and is feature-sized.
    span = tile[2] - tile[0]
    local = lambda value, origin: int((value - origin) / span * 1000)  # noqa: E731
    good = {"found": True, "box_2d": [local(0.26, tile[1]), local(0.36, tile[0]), local(0.36, tile[1]), local(0.46, tile[0])]}
    box = region_box_from_payload(good, tile, court)
    assert box is not None and abs(box.x_min - 0.36) < 0.01 and abs(box.y_max - 0.36) < 0.01
    # Not credible: not found, a box that misses the marker, or one covering most of the sheet.
    assert region_box_from_payload({"found": False}, tile, court) is None
    assert region_box_from_payload({"found": True, "box_2d": [0, 0, 100, 100]}, tile, court) is None
    assert region_box_from_payload({"found": True, "box_2d": [0, 0, 1000, 1000]}, tile, court) is None

    boxed = apply_region_boxes(entity_map, {court.entity_id: box})
    after = next(entity for entity in boxed.entities if entity.entity_id == court.entity_id)
    assert after.located_by == "both" and after.relative_area > court.relative_area * 5
    assert {entity.label for entity in marker_only_area_features(boxed)} == {"Pet Park"}
    assert boxed.diagnostics[-1].code == "marker_features_boxed" and boxed.diagnostics[-1].count == 1
    assert apply_region_boxes(entity_map, {}) is entity_map


def test_entry_ornaments_building_doors_and_pool_decks_are_not_gates_or_water():
    assert normalize_entity_type("Entry feature element") == "other_feature"
    assert normalize_entity_type("Tower entry") == "other_feature"
    assert normalize_entity_type("Clubhouse 1 Entry") == "other_feature"
    assert normalize_entity_type("Club House Entry") == "other_feature"
    assert normalize_entity_type("Poolside deck") == "plaza"
    assert normalize_entity_type("Entry Plaza") == "plaza"
    # Real gates and real water are unchanged.
    assert normalize_entity_type("Pedestrian Entry") == "entry_exit_gate"
    assert normalize_entity_type("Entry (Pedestrian + Vehicular)") == "entry_exit_gate"
    assert normalize_entity_type("Entry/Exit") == "entry_exit_gate"
    assert normalize_entity_type("Swimming pool") == "swimming_pool"
    assert normalize_entity_type("Kids pool") == "swimming_pool"
