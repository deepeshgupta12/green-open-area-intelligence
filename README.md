# Green Open Area Intelligence Engine

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com)
[![Gemini 2.5 Flash](https://img.shields.io/badge/Gemini-2.5%20Flash-4285F4)](https://ai.google.dev)
[![OpenCV](https://img.shields.io/badge/OpenCV-4.10-5C3EE8)](https://opencv.org)
[![Tests](https://img.shields.io/badge/tests-13%20passing-brightgreen)](tests/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A hybrid AI estimation engine that answers a question property portals usually cannot: **how green and how open is this project, really?**

Given only two inputs, a project's **Datacenter JSON** and its **master plan image**, the engine produces range-based estimates of **Green Area %** and **Open Area %**, a **confidence score with reasons**, **guardrail warnings**, and a compare-module-ready contract. A second layer compares **three projects side by side** on buyer-facing master plan categories and serves the result to a React frontend.

The engine is deliberately honest: it returns ranges, never fake precision; it never uses "official" language unless the value is in RERA, brochure or structured project data; and every output carries the reasons behind its confidence.

---

## Table of Contents

1. [Why this exists](#why-this-exists)
2. [What it does](#what-it-does)
3. [Locked definitions](#locked-definitions)
4. [Guardrails](#guardrails)
5. [Confidence scoring](#confidence-scoring)
6. [Three-project master plan comparison](#three-project-master-plan-comparison)
7. [Architecture](#architecture)
8. [Repository structure](#repository-structure)
9. [Getting started](#getting-started)
10. [API reference](#api-reference)
11. [CLI](#cli)
12. [Output example](#output-example)
13. [Environment variables](#environment-variables)
14. [Testing](#testing)
15. [Status and roadmap](#status-and-roadmap)
16. [Disclaimer](#disclaimer)
17. [License](#license)

---

## Why this exists

Project comparison modules on real-estate portals rarely have structured values for green cover and open space. Developers do not disclose them consistently, and the one artefact that shows the layout, the master plan, is almost always just an image.

Buyers still want a quick, understandable signal about openness, density and family-friendly livability. This engine produces that signal from what is actually available, and tells you how much to trust it.

## What it does

The pipeline runs in stages. Each stage writes a typed JSON artefact so every result is auditable.

| Stage | Module | What happens |
|-------|--------|--------------|
| 1. Parse | `app/services/json_parser.py` | Normalises Datacenter JSON into project metadata: area, units, amenities, RERA records, wow factors, unit mix, master plan description, and any **direct green/open claims** found in text ("70% open space", "3 acres central green"). |
| 2. Preprocess | `app/services/image_preprocessor.py` | Validates the master plan image, writes a normalised PNG, and scores image quality from sharpness, brightness and colourfulness. |
| 3. Vision reasoning | `app/services/vision_analyzer.py` | Sends the normalised image plus project context to **Gemini 2.5 Flash** and gets back structured JSON: boundary confidence, visible green / open / built zones, a qualitative estimate, and warnings such as "stylised, not to scale". |
| 4. Segmentation | `app/services/segmentation_engine.py` | **OpenCV** HSV masks for green landscape, water / pool, built structures and paved hardscape; class-wise pixel percentages, an **unknown / unclassified share**, and overlay images. |
| 5. Estimate | `app/services/area_calculator.py` | Combines segmentation lower bounds, the vision estimate, JSON signals and image quality into **range-based** Green and Open Area estimates. Applies guardrails and confidence caps. |
| 6. Explain | `validation_engine.py`, `confidence_engine.py`, `explanation_engine.py` | Validates ranges, computes the confidence score and label, and produces human-readable reasons and warnings. |
| 7. Category insights | `app/services/category_insight_engine.py` | Scores the project on buyer-facing categories (green planning, openness, built density, amenities, sports, family living, circulation, sustainability) with positives, risks, evidence and tooltips. |
| 8. Report | `app/services/report_writer.py` | Writes a Markdown report and a **compare-module JSON contract** ready for a product surface. |

## Locked definitions

**Green Area** is landscaped, planted, garden, lawn, tree-covered or green recreational area that is visible or declared in project data. Roads, driveways, parking, pools, concrete decks, bare paving, clubhouses, retail and non-grass sports courts are excluded.

**Open Area** is the total non-building footprint inside the project boundary. It includes green area, roads, pathways, paved open areas, sports courts, pools, decks, setbacks and open recreational zones. Tower, clubhouse, retail and utility footprints are excluded.

Full definitions, inclusions and exclusions live in [PRODUCT_BIBLE.md](PRODUCT_BIBLE.md).

## Guardrails

These rules are mandatory and enforced in code, not left to the model.

- **Green Area % must be ≤ Open Area %.** If an estimate violates this, green is adjusted downward and a warning is attached.
- **Ranges, not points.** Raw values are converted to bands whose width depends on confidence. Low-confidence results never show numeric precision.
- **No "official" language** unless the value comes directly from RERA, a brochure or structured project data.
- **Confidence drops** for a weak or missing boundary, poor image quality, JSON / image conflict, missing project area, or a high unknown segmentation share.
- **Confidence caps**: unknown area above 70% caps the score at 0.74; combined with a stylised / not-to-scale warning it caps at 0.69; a final range wider than 20 points caps at 0.72.
- **Manual boundary wins.** If a user-corrected boundary polygon is supplied, it overrides the AI-detected boundary (schema supported, see [DATA_CONTRACTS.md](DATA_CONTRACTS.md)).
- **All outputs include reasons and warnings.**

Comparison outputs have their own copy guardrails (see below): tied projects never show a "Clear Winner", sustainability is always described as *declared features* rather than environmental performance, and evidence chips are normalised and length-capped before they reach the frontend.

## Confidence scoring

Every output carries a score between 0 and 1, a label, and the reasons that produced it.

| Label | Score | Range width shown |
|-------|-------|-------------------|
| High | 0.80 to 1.00 | ±3% |
| Medium | 0.55 to 0.79 | ±5% |
| Low | 0.30 to 0.54 | ±8 to 10% |
| Insufficient | below 0.30 | No numeric range. "Data not sufficient for reliable estimate." |

Scoring starts at a base of 0.50 and adds or subtracts evidence signals: project JSON and project area available, master plan present, boundary detected, manual boundary supplied, green amenity signals, direct declared values, and agreement between the vision and segmentation estimates all add; unclear boundary, low image quality, high unknown area, JSON / image conflict and guardrail adjustments subtract. The exact weights are in [CONFIDENCE_SCORING.md](CONFIDENCE_SCORING.md).

## Three-project master plan comparison

`POST /compare-master-plans` takes JSON + master plan for three projects and returns a category comparison matrix built for a buyer-facing compare page.

- **Categories** include green landscape planning, open space and breathing room, built density and tower footprint, amenity richness, sports and active lifestyle, kids / family / community living, access and internal circulation, pool and water leisure, environment and sustainability, plus an evidence-reliability signal.
- **Status per category**: `Clear Winner`, `Close Call`, `Weak` or `Insufficient`, decided deterministically from score gaps, rating bands and cleaned evidence counts. Ties and near-ties are never shown as decisive.
- **Evidence chips**: master plan components and Datacenter entities that support each category, de-duplicated, normalised and capped in length.
- **Master plan understanding** (`master_plan_understanding_engine.py`): optional Gemini structure extraction of legends, towers, amenities and zones.
- **AI narrative** (`master_plan_narrative_engine.py`): optional Gemini-written buyer summary, generated *after* the deterministic matrix and constrained by it.
- **Frontend contract validator** (`frontend_contract_validator.py`): the last gate before the response. Rewrites over-claiming copy, enforces the tie rules, strips unsupported winner badges and keeps sustainability language to declared features.

The **frontend** (`frontend/`, Vite + React + TypeScript) uploads the six files, calls the endpoint and renders the headline, per-project cards and category insight cards.

## Architecture

```text
Datacenter JSON ──► json_parser ─────────────────────────────┐
                                                             │
Master plan image ─► image_preprocessor ──┬─► vision_analyzer (Gemini 2.5 Flash) ──┐
                                          └─► segmentation_engine (OpenCV) ────────┤
                                                                                   ▼
                                     area_calculator ─► validation ─► confidence ─► explanation
                                                                                   │
                                    ┌──────────────────────────────────────────────┤
                                    ▼                                              ▼
                       category_insight_engine                             report_writer
                                    │                                 (Markdown + compare contract)
            ×3 projects             ▼
      master_plan_compare_engine ─► master_plan_narrative_engine (Gemini) ─► frontend_contract_validator
                                    │
                                    ▼
                 master_plan_comparison_report_writer ─► React frontend
```

Vision and segmentation are deliberately separate sources of evidence. The vision model reasons about *what* is in the plan; OpenCV measures *how much*; neither is trusted alone, and disagreement lowers confidence.

## Repository structure

```text
green-open-area-intelligence/
├── app/
│   ├── config.py                 # pydantic-settings; reads .env
│   ├── main.py                   # FastAPI app: /health, /estimate, /compare-master-plans
│   ├── rules/                    # class definitions, green/open rules, guardrails, confidence rules
│   ├── schemas/                  # Pydantic models for every stage's input and output
│   ├── services/                 # pipeline stages (see table above)
│   ├── storage/                  # SQLAlchemy scaffolding (persistence not yet wired)
│   └── utils/                    # file and image helpers
├── frontend/                     # Vite + React + TypeScript comparison UI
├── scripts/run_single_project.py # CLI runner for a single project
├── tests/                        # pytest suite (13 tests)
├── data/
│   ├── input/                    # your project JSON + master plan images (git-ignored)
│   └── output/                   # json/, overlays/, reports/, api_runs/, compare_runs/ (git-ignored)
├── PRODUCT_BIBLE.md              # vision, definitions, guardrails, roadmap
├── MODEL_LOGIC.md                # hybrid model logic, classes, formulas, boundary priority
├── CONFIDENCE_SCORING.md         # score weights, labels, range widths
├── DATA_CONTRACTS.md             # input/output JSON contracts
├── CODE_DEPENDENCY_MAP.md        # module responsibilities and dependencies
└── IMPLEMENTATION_TRACKER.md     # step-by-step build log
```

## Getting started

### Prerequisites

- Python 3.10+
- Node.js 18+ (frontend only)
- A Google Gemini API key

### Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set GEMINI_API_KEY

uvicorn app.main:app --reload --port 2345
# Swagger UI: http://127.0.0.1:2345/docs
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# http://localhost:5173  (expects the API at http://127.0.0.1:2345; override with VITE_API_BASE_URL)
```

## API reference

### `GET /health`

Returns app name, environment and the default port.

### `POST /estimate`

Single-project estimate. `multipart/form-data`.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `project_json_file` | file | required | Datacenter JSON |
| `master_plan_image_file` | file | required | PNG / JPG / JPEG / WEBP |
| `run_vision` | bool | `false` | Gemini vision analysis |
| `run_segmentation` | bool | `true` | OpenCV segmentation |
| `run_area_estimate` | bool | `false` | Requires vision and segmentation |
| `run_category_comparison` | bool | `false` | Requires area estimate |
| `write_report` | bool | `false` | Requires area estimate |

Response: `run_id`, `run_artifacts` (paths to every JSON / overlay / report written under `data/output/api_runs/<run_id>/`), `project_metadata`, `image_metadata`, `vision_analysis`, `segmentation_result`, `area_estimate`, `category_comparison`, `final_outputs`.

### `POST /compare-master-plans`

Three-project comparison. `multipart/form-data` with `project_{a,b,c}_json_file` and `project_{a,b,c}_master_plan_image_file`, plus `use_ai_narrative` and `use_ai_structure_extraction` (both default `true`). All pipeline stages run for each project.

Response: `comparison_run_id`, `projects`, `category_comparison_matrix`, `category_winners`, `overall_recommendation`, `user_friendly_summary`, `internal_evidence_quality`, `run_artifacts`, `notes`.

## CLI

```bash
python scripts/run_single_project.py \
  --json data/input/342956.json \
  --image data/input/master_plan.jpg \
  --run-vision \
  --run-segmentation \
  --run-area-estimate \
  --run-category-comparison \
  --write-report
```

Flags are cumulative; omit later ones to stop at an earlier stage. Outputs land in `data/output/json/`, `data/output/overlays/` and `data/output/reports/`.

## Output example

```json
{
  "green_area_percentage": { "min": 28, "max": 35, "display": "~28–35%" },
  "open_area_percentage":  { "min": 62, "max": 70, "display": "~62–70%" },
  "confidence": {
    "score": 0.74,
    "label": "Medium",
    "reasons": [
      "Project area is available in Datacenter JSON.",
      "Master plan image is available.",
      "Green amenity signals are present.",
      "Boundary was detected by AI but not manually verified."
    ]
  },
  "guardrails": { "passed": true, "warnings": [], "adjustments": [] },
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

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `GEMINI_API_KEY` | none | Required for vision, structure extraction and narrative |
| `GEMINI_VISION_MODEL` | `gemini-2.5-flash` | Vision reasoning model |
| `GEMINI_TEXT_MODEL` | `gemini-2.5-flash` | Narrative model |
| `APP_ENV` | `local` | Environment label |
| `APP_NAME` | `Green Open Area Intelligence Engine` | Reported by `/health` |
| `DATABASE_URL` | `sqlite:///./goa_engine.sqlite3` | Reserved for the storage layer |
| `MAX_IMAGE_SIZE_MB` | `30` | Upload size gate |
| `DEFAULT_CONFIDENCE_THRESHOLD` | `0.65` | Threshold used by compare-module display logic |

## Testing

```bash
pytest -q
```

The suite covers the JSON parser, image preprocessor, vision analyzer, segmentation engine, area calculator, confidence engine, validation engine, report writer, category insight engine, master plan compare engine, the two API endpoints and the compare endpoint contract. Vision tests run without network access.

## Status and roadmap

**Implemented**: full single-project pipeline (parse, preprocess, Gemini vision, OpenCV segmentation, range estimate, guardrails, confidence, explanation, report), category insight engine, three-project master plan comparison with deterministic statuses and AI narrative, frontend contract validator, FastAPI endpoints, React comparison UI.

**Planned**: reviewer UI with manual polygon correction, batch processing, a trained segmentation model to shrink the unknown share, a human-reviewed evaluation dataset, and wiring the SQLAlchemy storage layer (`scripts/init_db.py` and `scripts/generate_sample_report.py` are placeholders today).

## Disclaimer

Outputs are **estimates derived from a master plan image and available project data**. They are not official measurements, not RERA disclosures, and must not be presented as certified green or open area figures.

## License

MIT © 2026 Deepesh Kumar Gupta. See [LICENSE](LICENSE).
