# Green Open Area Intelligence Engine

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com)
[![Gemini 3.5 Flash](https://img.shields.io/badge/Gemini-3.5%20Flash-4285F4)](https://ai.google.dev)
[![OpenCV](https://img.shields.io/badge/OpenCV-4.10-5C3EE8)](https://opencv.org)
[![Tests](https://img.shields.io/badge/tests-62%20passing-brightgreen)](tests/)
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
7. [Master plan entity map and hover viewer](#master-plan-entity-map-and-hover-viewer)
8. [Architecture](#architecture)
9. [Repository structure](#repository-structure)
10. [Getting started](#getting-started)
11. [API reference](#api-reference)
12. [CLI](#cli)
13. [Output example](#output-example)
14. [Environment variables](#environment-variables)
15. [Testing](#testing)
16. [Status and roadmap](#status-and-roadmap)
17. [Disclaimer](#disclaimer)
18. [License](#license)

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
| 3. Vision reasoning | `app/services/vision_analyzer.py` | Sends the normalised image plus project context to **Gemini 3.5 Flash** and gets back structured JSON: boundary confidence, visible green / open / built zones, a qualitative estimate, and warnings such as "stylised, not to scale". |
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

The comparison is served by the API (`POST /compare-master-plans`) and covered by tests; the React frontend is now dedicated to single-plan analysis (next section).

## Master plan entity map and hover viewer

`POST /master-plan/entities` turns one master plan image into a **spatial entity map**: every wing, commercial block, clubhouse, gate, road, parking cluster, court, pool, garden, play area, game and utility yard with a bounding box, plus the legend as printed and a few site-level facts. The React app (`frontend/`, Vite + React + TypeScript) takes the plan either as a **public image URL** (fetched server-side, so CDN CORS and hotlink rules never block it; the stored copy is served back from `GET /master-plan/runs/{run_id}/image`) or as an **upload**, with the project's Datacenter JSON optional. From the plan alone it builds an executive dashboard: a **composition card** (features by type, residential blocks, entry points, parking, plan thumbnail), a **land use** card (drawing area by use, summed from the located boxes; on architectural block plans also the printed plot area, sanctioned BUA and derived FSI, and a chart of the reservations printed on the sheet), an **amenities and lifestyle** section (amenity mix by lifestyle category, legend coverage meter, legend promise vs plan evidence per category, walk to the nearest amenity per block) and a **spatial and access** section (where amenities and green sit on a 3x3 grid of the drawing, block exposure counts, and a block-by-block access matrix of amenities and green nearby plus entry gate, external road, parking and utility-yard proximity). On architectural block plans the amenity section gives way to a **block plan analysis** section: reservations by type (green and open space, civic, setbacks, future development), phase towers and drawn ground coverage, and road frontages by side and width. Expanding the plan opens the **hover viewer**: the boxes are drawn over the image, hovering a region shows the feature's full metadata, clicking pins it, filters and search scope the overlay, and a collapsed inventory table is the chart's accessible twin. With the Datacenter JSON the land-use card becomes the **green and open area estimate** (low to high ranges, OpenCV pixel evidence, confidence reasons), a **home mix** card is added (carpet area by configuration, green per home, declared vs located amenities), and the zoning, density and land allocation dashboards follow.

How the extraction works (`app/services/master_plan_entity_extractor.py`):

- **Focused Gemini calls run in parallel**, each with a strict `response_schema` and thinking at its minimum (`thinking_budget=0` on Gemini 2.x, `thinking_level=minimal` on 3.x): a *wings* call for residential building footprints (re-asked once if the boxes look fabricated), a *structures* call for the other large features, a *site* call for the legend text, plot shape, external roads and drawing annotations, and a *marker* call per image tile (2x2 with overlap) for the small numbered circles that key features to the legend.
- **Numbered legend markers are treated as ground truth.** A marker whose code matches a legend row becomes that feature at that spot. A drawn box that agrees with a marker is merged with it (`located_by: both`); a drawn box far from the marker for the same feature is discarded.
- **Water features need evidence**: a pool or water body that no legend row, declared amenity or legend marker vouches for must be painted in saturated blue or cyan (tower plates and lobbies drawn in pale grey-blue are a known confusion); the ones with blue ink get a second look on their own crop, and only a clear "not water" answer removes them. Plans whose legend or records list water are left untouched.
- **Blocks named from printed key notes**: when letter keys that are not legend codes are drawn beside the buildings (for example lobby markers C and D with a note "C Lobby- Wing A&B | D Lobby- Wing C&D"), one extra focused call transcribes the notes and the blocks are named from the markers they contain ("Tower 1 (Wing A & B)"); an umbrella box around several buildings is dropped. Plans with numbered markers never trigger this call.
- **Architectural block plans** (CAD line drawings that print no legend, e.g. a municipal block plan) get two more focused calls, and only they do: one transcribes the printed site figures (title, plot area, sanctioned BUA, scale; FSI is derived) and every labelled parcel with its printed area (setbacks, R.G. area, amenity open space, school, cultural centre, garden/park), and one boxes the tower footprint outlines on the full sheet (two temperatures) and on 2x2 tiles, merged by overlap, because small outlines at the plot edges only show up on the tiles. New footprints are kept only when they do not overlap a known block, are sized like the other towers on the sheet, and pass a per-crop "building outline" check; they are named from the printed text when the crop reads a name that is not already in use, otherwise "Footprint N". Which towers belong to this phase is measured from the fill colour of each box (hatched or solid saturated fill), not taken from the model. The site summary carries `drawing_style: "block_plan"` and `printed_records`, and the green/open estimate is marked Low confidence because a line drawing carries little pixel signal.
- **Known model failure modes are filtered**: identical boxes reused across features, evenly spaced same-size runs, boxes covering most of the drawing, and circles detected on blank paper (a pixel check).
- **Derived metadata**: category key for the nine comparison categories, nearest residential block and distance, per-block proximity notes ("Wing E sits closest to Entry Plaza, Outdoor Gym and Obstacle Park; ..."), legend coverage, entity and group counts.

All coordinates are **fractions of the image** (0 to 1), so the frontend overlays them on the original upload without any server-side image serving. The same map can be produced for all three projects during a compare run with `use_ai_entity_extraction=true`; the explorer then shows the maps without a second call.

The entity map carries **no model-written prose**: the plot shape is an enum (`shape_class`), per-block proximity is a set of lists and flags, and processing notes are machine-readable `diagnostics` (`code`, `count`, `items`) that the frontend turns into sentences.

### Site metrics dashboards

`POST /master-plan/analysis` adds **key-value site metrics** (`app/services/site_metrics_engine.py`) on top of the entity map and renders three dashboards in the explorer:

- **Master Plan & Site Zoning**: parcel area, open realm and building footprint, homes per acre against micro-market and city medians, sanctioned FSI, land and open realm per home, with the plan thumbnail opening the hover viewer.
- **Density & Spaciousness Profile**: density curves (kernel density of homes per acre) for the micro-market and the city with the project marked, privacy stat tiles, a land-area-versus-unit-count scatter with a least-squares trendline, and a density-parity callout.
- **Land & Open Space Allocation**: a flow diagram from site parcel to open realm and building plinth and on to land per home, outdoor amenities and built-up envelope; hovering a flow shows how the figure is derived.

Every figure is a `MetricValue` with `value`, `unit`, `source` (`project_records`, `master_plan_estimate`, `master_plan_entities`, `derived`, `benchmark_dataset`, `unavailable`), an optional `confidence_label` and a `basis` formula key. Figures that only exist in sanction records (FSI, UDS, clubhouse area) stay `unavailable` unless supplied via `site_records_json`. Benchmarks come from a JSON dataset at `DENSITY_BENCHMARKS_PATH`; the repository ships a **synthetic sample** (`data/benchmarks/density_benchmarks.sample.json`, `is_sample: true`) that the UI badges as sample data. Every chart has a table view, hover tooltips with hit targets larger than the marks, and a colour set validated for colour-vision safety.

Entity vocabulary: `residential_block`, `commercial_block`, `clubhouse`, `security_cabin`, `utility_yard`, `entry_exit_gate`, `external_road`, `internal_road`, `driveway`, `walkway_pathway`, `parking`, `swimming_pool`, `water_feature`, `sports_court`, `kids_play_area`, `outdoor_game`, `outdoor_gym`, `plaza`, `pet_park`, `working_pods`, `other_feature`, `lawn_garden`, `tree_canopy_buffer`, `legend_marker`, `legend_block`, `title_block`, `north_arrow`, `site_boundary`. Boxes are model estimates on a stylised, not-to-scale drawing: use them to locate features, never to measure them.

## Architecture

```text
Datacenter JSON ──► json_parser ─────────────────────────────┐
                                                             │
Master plan image ─► image_preprocessor ──┬─► vision_analyzer (Gemini 3.5 Flash) ──┐
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
│   ├── main.py                   # FastAPI app: /health, /estimate, /compare-master-plans, /master-plan/entities, /master-plan/analysis
│   ├── rules/                    # class definitions, green/open rules, guardrails, confidence rules
│   ├── schemas/                  # Pydantic models for every stage's input and output
│   ├── services/                 # pipeline stages (see table above)
│   ├── storage/                  # SQLAlchemy scaffolding (persistence not yet wired)
│   └── utils/                    # file, image and Gemini client helpers
├── frontend/                     # Vite + React + TypeScript master plan analysis app (URL or upload)
├── scripts/run_single_project.py # CLI runner for a single project
├── tests/                        # pytest suite (62 tests)
├── data/
│   ├── benchmarks/               # density benchmark dataset (synthetic sample shipped)
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
- Gemini access: a Google Cloud service account with Vertex AI enabled (preferred) or an AI Studio API key

### Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: either point GOOGLE_APPLICATION_CREDENTIALS at a Vertex AI
# service-account JSON (kept outside the repo) or set GEMINI_API_KEY

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

Three-project comparison. `multipart/form-data` with `project_{a,b,c}_json_file` and `project_{a,b,c}_master_plan_image_file`, plus `use_ai_narrative` and `use_ai_structure_extraction` (both default `true`) and `use_ai_entity_extraction` (default `false`; adds a spatial entity map per project at the cost of extra Gemini calls). All pipeline stages run for each project.

Response: `comparison_run_id`, `projects`, `category_comparison_matrix`, `category_winners`, `overall_recommendation`, `user_friendly_summary`, `internal_evidence_quality`, `project_entity_maps` (`{"A": map | null, "B": ..., "C": ...}`), `run_artifacts`, `notes`.

### `POST /master-plan/analysis`

Entity map plus key-value site metrics for the dashboards (see [above](#site-metrics-dashboards)). `multipart/form-data`.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `master_plan_image_file` | file | one of file / URL | PNG / JPG / JPEG / WEBP |
| `master_plan_image_url` | string | one of file / URL | Public http(s) image URL, fetched server-side (size-capped, public hosts only) |
| `project_json_file` | file | optional | Datacenter JSON; without it the entity map and an image-only green / open estimate are returned, but no site metrics |
| `run_area_estimate` | bool | `true` | Runs Gemini vision + OpenCV segmentation to estimate open and green area (with or without project records; records raise the confidence) |
| `site_records_json` | string | optional | JSON with any of `sanctioned_fsi`, `built_up_area_sq_m`, `clubhouse_area_sq_m`, `undivided_land_share_sq_m`, `open_area_percent`, `building_footprint_sq_m`, `homes_per_floor_min`, `homes_per_floor_max` |

Response: `run_id`, `image_url` (backend path serving the stored plan), `source_image_url`, `entity_map`, `site_metrics` (or `null`), `area_estimate` (or `null`), `image_metadata`, `diagnostics`, `run_artifacts`. Typical latency is 40 to 70 seconds with the area estimate, 20 to 40 without.

### `POST /master-plan/entities`

Spatial entity map for one master plan (see [above](#master-plan-entity-map-and-hover-viewer)). `multipart/form-data`.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `master_plan_image_file` | file | one of file / URL | PNG / JPG / JPEG / WEBP |
| `master_plan_image_url` | string | one of file / URL | Public http(s) image URL, fetched server-side |
| `project_json_file` | file | optional | Datacenter JSON; seeds the model with declared amenities and tags the result with the project id |

### `GET /master-plan/runs/{run_id}/image`

Serves the master plan stored for an analysis or entities run, so the UI can display a URL-sourced plan without hotlinking the original.

Response: `run_id`, `entity_map`, `image_metadata`, `run_artifacts`. The `entity_map` carries `image_width`, `image_height`, `coordinate_system: "fraction_of_image"`, `extraction_confidence_label`, `site`, `legend`, `entities`, `entity_counts`, `group_counts`, `block_proximity`, `warnings` and `notes`. Each entity has `entity_type`, `entity_group`, `label`, `legend_code`, `legend_label`, `category_key`, `box {x_min, y_min, x_max, y_max}`, `center_x`, `center_y`, `relative_area`, `confidence_label`, `located_by`, `attributes`, `adjacent_to`, `nearest_residential_block` and `nearest_residential_distance`. Typical latency is 20 to 30 seconds for a 1800 px plan.

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
| `GOOGLE_APPLICATION_CREDENTIALS` | none | Path to a Vertex AI service-account JSON. When set, Gemini runs through Vertex AI |
| `GOOGLE_CLOUD_PROJECT` | from key file | GCP project for Vertex AI; defaults to the key file's `project_id` |
| `GOOGLE_CLOUD_LOCATION` | `global` | Vertex AI location. Gemini 3.x models are served from the `global` endpoint (and `asia-south1`); `us-central1` returns 404 for them |
| `GEMINI_API_KEY` | none | Gemini Developer API key; used only when no service-account path is set |
| `GEMINI_VISION_MODEL` | `gemini-3.5-flash` | Vision reasoning model |
| `GEMINI_TEXT_MODEL` | `gemini-3.5-flash` | Narrative model |
| `DENSITY_BENCHMARKS_PATH` | `data/benchmarks/density_benchmarks.sample.json` | Project parcel/unit dataset for density benchmarks; the default is a labelled synthetic sample |
| `APP_ENV` | `local` | Environment label |
| `APP_NAME` | `Green Open Area Intelligence Engine` | Reported by `/health` |
| `DATABASE_URL` | `sqlite:///./goa_engine.sqlite3` | Reserved for the storage layer |
| `MAX_IMAGE_SIZE_MB` | `30` | Upload size gate |
| `DEFAULT_CONFIDENCE_THRESHOLD` | `0.65` | Threshold used by compare-module display logic |

## Testing

```bash
pytest -q
```

The suite covers the JSON parser, image preprocessor, vision analyzer, segmentation engine, area calculator, confidence engine, validation engine, report writer, category insight engine, master plan compare engine, the master plan entity extractor (payload parsing, marker reconciliation, pattern filters, tiling, truncated-response salvage), the site metrics engine (unit conversions, provenance, allocation flow, density benchmarks) and all API endpoints. No test needs network access; Gemini calls are stubbed.

Frontend type-check and build:

```bash
cd frontend && npm run build
```

## Status and roadmap

**Implemented**: full single-project pipeline (parse, preprocess, Gemini vision, OpenCV segmentation, range estimate, guardrails, confidence, explanation, report), category insight engine, three-project master plan comparison API with deterministic statuses and AI narrative, frontend contract validator, master plan spatial entity map with legend-marker reconciliation, key-value site metrics with density benchmarks, FastAPI endpoints, and a React master plan analysis app (plan by URL or upload) with composition, amenity-mix, legend-coverage and block-access dashboards from the plan alone, a hover-to-inspect entity viewer, and zoning / density / allocation dashboards when project records are supplied.

**Planned**: reviewer UI with manual polygon correction, batch processing, a trained segmentation model to shrink the unknown share, a human-reviewed evaluation dataset, and wiring the SQLAlchemy storage layer (`scripts/init_db.py` and `scripts/generate_sample_report.py` are placeholders today).

## Disclaimer

Outputs are **estimates derived from a master plan image and available project data**. They are not official measurements, not RERA disclosures, and must not be presented as certified green or open area figures.

## License

MIT © 2026 Deepesh Kumar Gupta. See [LICENSE](LICENSE).
