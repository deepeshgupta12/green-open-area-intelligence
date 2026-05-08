# Product Bible: Green Open Area Intelligence Engine

## 1. Product Vision

The Green Open Area Intelligence Engine estimates how much green area and open area may exist within a real-estate project using only the project Datacenter JSON and the project master plan image.

The engine is designed for Square Yards-style compare modules where users need a quick, understandable signal about project openness, green cover, density, and family-friendly livability.

## 2. Problem Statement

Project comparison modules often lack structured values for green area and open area. Developers may not consistently disclose these values, and project master plans are often available only as images.

The product solves this by combining:

1. Datacenter JSON extraction
2. OpenAI Vision reasoning
3. OpenCV image segmentation
4. Rule-based guardrails
5. Confidence scoring
6. Human-correctable boundary support

## 3. Input Sources

### 3.1 Datacenter JSON

Expected signals:

- project_id
- project_name
- city
- locality
- micromarket
- project_area
- total_units
- amenities
- wow_factors
- master_plan_description
- RERA data
- image metadata
- brochure URL
- project category
- project status

### 3.2 Master Plan Image

Expected signals:

- project boundary
- building footprint
- green/landscaped zones
- roads and driveways
- paved areas
- pools/water bodies
- sports courts
- play areas
- clubhouse/retail structures
- unknown or unclear areas

## 4. Locked Definitions

### 4.1 Green Area

Green Area means landscaped / planted / garden / lawn / tree-covered / green recreational area visible or declared in project data.

Includes:

- Landscaped garden
- Lawn
- Central park
- Tree cover
- Green buffer
- Garden court
- Woodland
- Orchard
- Planted recreational space
- Green play area
- Podium landscape, if visibly green

Excludes:

- Roads
- Driveways
- Parking
- Swimming pools
- Concrete decks
- Bare paved areas
- Clubhouse
- Retail structures
- Sports courts without grass or landscape

### 4.2 Open Area

Open Area means total non-building footprint area inside the project boundary.

Includes:

- Green area
- Roads
- Pathways
- Driveways
- Paved open areas
- Sports courts
- Pools
- Decks
- Setbacks
- Open recreational zones
- Play areas

Excludes:

- Tower footprint
- Clubhouse footprint
- Retail/commercial structure footprint
- Utility structure footprint
- Other permanent built structures

## 5. Mandatory Product Guardrails

1. Green Area % must be less than or equal to Open Area %.
2. Output must be range-based unless direct official values are available.
3. Low-confidence image analysis must not show numeric precision.
4. Official language must not be used unless the value comes directly from RERA, brochure, or structured project data.
5. If boundary detection is weak, confidence must drop.
6. If image quality is poor, confidence must drop.
7. If JSON signals conflict with visual signals, confidence must drop.
8. If user provides corrected boundary, corrected boundary must override AI boundary.
9. If green area estimate exceeds open area estimate, guardrail must adjust green area downward and create a warning.
10. All outputs must include reasons and warnings.

## 6. Output Philosophy

The engine should produce helpful estimates, not legally official measurements.

Allowed:

- Estimated from master plan
- Approximate range
- Confidence: High / Medium / Low
- Based on visible layout and available project data

Not allowed unless directly sourced:

- Official green area
- Official open area
- Exact area certified by RERA

## 7. Compare Module Usage

Suggested user-facing labels:

- Estimated Green Space
- Estimated Open Area
- Confidence: Medium
- Based on master plan and project data

Suggested tooltip:

“Estimated using the project master plan and available project data. Actual values may vary from official layout or RERA disclosures.”

## 8. Product Roadmap

### Current Combined MVP

- Backend-only
- Datacenter JSON parser
- OpenAI Vision analyzer
- OpenCV segmentation
- Area calculator
- Guardrails
- Confidence score
- Markdown and JSON report

### Later Enhancements

- Reviewer UI
- Manual polygon correction
- Batch processing
- Custom segmentation model
- Project comparison API
- Human-reviewed training dataset
