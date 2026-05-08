# Data Contracts

## 1. Input Contract

The engine accepts:

1. Project Datacenter JSON file
2. Project master plan image

## 2. Project JSON Input

Minimum expected fields:

```json
{
  "data": {
    "projectId": 342956,
    "projectData": {
      "projectName": "Birla Taranya",
      "city": "Thane",
      "subLocation": "Kalwa",
      "projectArea": 13.74,
      "totalUnits": 1339,
      "amenities": [],
      "wowFactors": [],
      "images": []
    }
  }
}
```

## 3. Parsed Project Metadata Contract

The parser should normalize the input into:

```json
{
  "project_id": "342956",
  "project_name": "Birla Taranya",
  "city": "Thane",
  "locality": "Kalwa",
  "project_area_acres": 13.74,
  "total_units": 1339,
  "project_category": "residential",
  "status": "New Launch",
  "amenities": [],
  "green_amenity_signals": [],
  "open_space_signals": [],
  "wow_factors": [],
  "rera_numbers": [],
  "master_plan_description": "",
  "brochure_url": ""
}
```

## 4. Image Input Contract

Supported formats:

- PNG
- JPG
- JPEG
- WEBP

Maximum default size:

```text
15 MB
```

The image should ideally contain:

- Project boundary
- Buildings/towers
- Roads/internal circulation
- Amenities
- Landscaped zones

## 5. User Boundary Override Contract

The engine must support optional user-corrected boundary points.

Format:

```json
{
  "manual_boundary": {
    "enabled": true,
    "points": [
      {"x": 120, "y": 80},
      {"x": 920, "y": 100},
      {"x": 980, "y": 540},
      {"x": 100, "y": 560}
    ]
  }
}
```

If `manual_boundary.enabled` is true, it overrides AI boundary detection.

## 6. Area Breakup Output Contract

```json
{
  "estimated_area_breakup": {
    "building_footprint_percentage": 28,
    "green_landscape_percentage": 32,
    "road_driveway_percentage": 18,
    "paved_open_percentage": 9,
    "sports_play_area_percentage": 5,
    "water_pool_percentage": 3,
    "clubhouse_retail_structure_percentage": 4,
    "unknown_percentage": 1
  }
}
```

## 7. Final Estimate Contract

```json
{
  "final_estimates": {
    "green_area_percentage": {
      "min": 28,
      "max": 35,
      "display": "~28–35%",
      "basis": "master_plan_plus_datacenter_json"
    },
    "open_area_percentage": {
      "min": 62,
      "max": 70,
      "display": "~62–70%",
      "basis": "master_plan_plus_datacenter_json"
    }
  }
}
```

## 8. Confidence Contract

```json
{
  "confidence": {
    "score": 0.74,
    "label": "Medium",
    "reasons": [
      "Project area is available in Datacenter JSON.",
      "Master plan image is available.",
      "Green amenity signals are present.",
      "Boundary was detected by AI but not manually verified."
    ]
  }
}
```

## 9. Guardrail Contract

```json
{
  "guardrails": {
    "passed": false,
    "warnings": [
      "Estimated green area exceeded open area and was adjusted downward."
    ],
    "adjustments": [
      {
        "field": "green_area_percentage",
        "old_range": "~72–78%",
        "new_range": "~55–60%",
        "reason": "Green Area cannot exceed Open Area."
      }
    ]
  }
}
```

## 10. Compare Module Contract

```json
{
  "compare_module_display": {
    "green_space_label": "Estimated Green Space",
    "green_space_value": "~28–35%",
    "open_area_label": "Estimated Open Area",
    "open_area_value": "~62–70%",
    "confidence_label": "Medium Confidence",
    "tooltip": "Estimated using the project master plan and available project data. Actual values may vary from official layout or RERA disclosures."
  }
}
```
