# Green Open Area Intelligence Engine

A backend-only AI estimation engine for calculating estimated Green Area and Open Area for real-estate projects using Datacenter JSON and project master plan images.

## Objective

The engine estimates:

1. Green Area %
2. Open Area %
3. Confidence score
4. Confidence label
5. Confidence reasons
6. Guardrail warnings
7. Compare-module-ready output

## Input Sources

1. Project Datacenter JSON
2. Project Master Plan Image

## Locked Definitions

### Green Area

Landscaped / planted / garden / lawn / tree-covered / green recreational area visible or declared in project data.

### Open Area

Total non-building footprint area inside the project boundary, including green area, roads, pathways, paved open areas, sports courts, pools, decks, setbacks, and open recreational zones.

## Mandatory Guardrail

Green Area % must always be less than or equal to Open Area %.

## Estimation Policy

The engine returns estimated ranges and confidence scores. It does not claim official values unless they are directly available in source data.

Example:

```json
{
  "green_area_percentage": {
    "min": 28,
    "max": 35,
    "display": "~28–35%"
  },
  "open_area_percentage": {
    "min": 62,
    "max": 70,
    "display": "~62–70%"
  },
  "confidence": {
    "score": 0.74,
    "label": "Medium"
  }
}
```

## Tech Stack

- Python
- FastAPI
- OpenAI Vision
- OpenCV
- SQLite
- Pydantic
- Pytest

## Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Execution Plan

The first implementation will be CLI-first, then API-first.

1. Repo and documentation setup
2. Datacenter JSON parser
3. Image preprocessing
4. OpenAI vision analyzer
5. OpenCV segmentation engine
6. Area calculation
7. Guardrails and confidence scoring
8. Report generation
9. FastAPI endpoint
