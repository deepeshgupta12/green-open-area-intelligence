# Model Logic

## 1. Model Type

The Master Plan Intelligence is a hybrid AI estimation engine.

It combines:

1. Datacenter JSON parsing
2. OpenAI Vision reasoning
3. OpenCV-based image segmentation
4. Rule-based validation
5. Confidence scoring
6. Guardrail enforcement

## 2. Why Hybrid

OpenAI Vision can reason about master plan components, but it should not be the only source for pixel-level measurement.

OpenCV can estimate color/region distribution, but it does not understand semantic context by itself.

The product combines both.

## 3. Visual Classes

The engine uses the following classes:

1. project_boundary
2. building_footprint
3. green_landscape
4. road_driveway
5. paved_open_area
6. sports_court_play_area
7. water_pool
8. clubhouse_retail_structure
9. unknown_unclear_area

## 4. Green Area Calculation

Green Area includes:

- green_landscape
- landscaped gardens
- lawns
- tree-covered areas
- planted recreational zones
- visible green podium landscape

Formula:

```text
Green Area % = Green Landscape Pixels / Project Boundary Pixels × 100
```

When the exact pixel result is available, the engine converts it into a range.

Example:

```text
Raw estimate: 32%
Display range: ~28–35%
```

## 5. Open Area Calculation

Open Area includes all non-building footprint area inside the project boundary.

Formula:

```text
Open Area % = 100 - Building Footprint % - Clubhouse/Retail Structure Footprint %
```

Open area includes:

- green area
- roads
- pathways
- paved zones
- sports courts
- pools
- play areas
- decks
- open recreational zones

## 6. User Boundary Correction

If manual boundary points are provided, they override AI-inferred project boundary.

Priority order:

1. Manual boundary
2. AI-detected boundary
3. Full master plan content area
4. Fallback with low confidence

## 7. Range Conversion

The engine should not expose raw exact values directly.

Suggested range logic:

```text
High confidence: ±3%
Medium confidence: ±5%
Low confidence: ±8–10%
```

Example:

```text
Raw Green Area = 32%
Medium Confidence Range = ~27–37%
```

Final display should be rounded into user-friendly bands.

## 8. Datacenter JSON Signals

The JSON parser extracts:

- project area
- total units
- amenities
- green signals
- open space signals
- wow factors
- RERA data
- master plan description
- project category
- project status

These signals do not directly calculate area unless a value is explicitly declared. They validate the image-based estimate.

## 9. Direct Value Extraction

If JSON or text contains direct values such as:

- 70% open space
- 2.53 acres podium landscape
- 3 acres central green
- 80% open area

The engine captures them as declared signals.

Direct values increase confidence but must still be source-tagged.

## 10. Guardrails

Mandatory guardrails:

1. Green Area <= Open Area
2. Open Area cannot be below 0 or above 100
3. Green Area cannot be below 0 or above 100
4. Low image quality reduces confidence
5. Missing project boundary reduces confidence
6. Manual boundary improves confidence
7. Direct declared source improves confidence
8. Conflicting JSON/image evidence reduces confidence
9. Unknown area above threshold reduces confidence
10. Low-confidence results should display broader ranges or qualitative labels

## 11. Confidence Impact

Confidence increases when:

- project area exists
- master plan image is clear
- boundary is detected
- manual boundary is provided
- green amenity signals exist
- OpenAI and OpenCV outputs align
- direct values exist in source data

Confidence decreases when:

- master plan is stylized
- boundary is unclear
- JSON is missing
- OpenAI and OpenCV disagree
- unknown area is high
- project area is missing
- image resolution is poor

## 12. Output Statuses

The engine may return:

1. numeric_estimate_available
2. range_estimate_available
3. qualitative_only
4. insufficient_data
5. failed_processing
