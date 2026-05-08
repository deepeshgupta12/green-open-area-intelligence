# Implementation Tracker

## Product

Green Open Area Intelligence Engine

## Current Status

Step 2 Datacenter JSON Parser implemented. CLI parser run completed successfully. Pytest import path issue identified and fixed by adding pytest.ini with pythonpath = . before re-running tests.

## Locked Direction

- Backend-only
- OpenAI Vision + OpenCV from Day 1
- Confidence score mandatory
- Confidence reasons mandatory
- Range-based output
- AI boundary detection
- Manual boundary correction supported in schema
- Guardrails mandatory
- Green Area must be <= Open Area

## Step Log

### Step 0: Product Scope Lock

Status: Completed

Completed items:

- Locked product name
- Locked input sources
- Locked Green Area definition
- Locked Open Area definition
- Locked estimation policy
- Locked confidence requirement
- Locked guardrails
- Locked backend-only MVP direction

Pending:

- None

### Step 1: Repository and Documentation Setup

Status: Completed

Files created:

- README.md
- PRODUCT_BIBLE.md
- IMPLEMENTATION_TRACKER.md
- CODE_DEPENDENCY_MAP.md
- DATA_CONTRACTS.md
- MODEL_LOGIC.md
- CONFIDENCE_SCORING.md
- .env.example
- .gitignore
- requirements.txt

### Step 2: Datacenter JSON Parser

Status: Implemented; test fix required before final confirmation

Files implemented:

- app/config.py
- app/schemas/project_schema.py
- app/utils/file_utils.py
- app/services/json_parser.py
- scripts/run_single_project.py
- tests/test_json_parser.py

Files added during fix:

- pytest.ini

Implemented capabilities:

- Parses project ID
- Parses project name
- Parses city
- Parses locality
- Parses latitude and longitude
- Parses project area in acres
- Parses total units
- Parses project category
- Parses project status
- Parses developer details
- Parses price text
- Parses brochure URL
- Parses project URL
- Parses RERA records
- Parses amenities
- Extracts green amenity signals
- Extracts open-space signals
- Parses wow factors
- Parses unit mix
- Parses master plan metadata
- Extracts direct green/open area claims from available text
- Writes normalized parsed metadata to data/output/json

Manual parser command:

```bash
python scripts/run_single_project.py \
  --json data/input/342956.json \
  --image data/input/master_plan.png
```

Observed result:

- Parser executed successfully
- Parsed Project ID: 342956
- Parsed Project Name: Birla Taranya
- Parsed City: Thane
- Parsed Locality: Kalwa
- Parsed Project Area Acres: 13.74
- Parsed Total Units: 1339
- Parsed Amenities Count: 45
- Parsed RERA Records: 2
- Parsed Unit Variants: 6
- Master Plan Found: Yes
- Output created at data/output/json/342956_parsed_project_metadata.json

Test command:

```bash
pytest tests/test_json_parser.py -q
```

Observed issue:

```text
ModuleNotFoundError: No module named 'app'
```

Root cause:

Pytest did not automatically add the repository root to Python import path during test collection.

Fix:

Add pytest.ini at repo root:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

Re-run:

```bash
pytest tests/test_json_parser.py -q
```

Expected result:

```text
1 passed
```

Current Git Commit Target:

```text
fix: configure pytest import path
```

Next Step After Test Passes:

Step 3: Master plan image preprocessing.

Step 3 expected output:

- Validate master plan image exists
- Check image format
- Check image size
- Read image dimensions
- Generate normalized image copy
- Generate basic image quality score
- Prepare image metadata for OpenAI Vision and OpenCV

## Step 3: Master Plan Image Preprocessing

Status: Implementation added, test blocked by invalid local image input.

## What was implemented

Files implemented:

- app/schemas/image_schema.py
- app/utils/image_utils.py
- app/services/image_preprocessor.py
- tests/test_image_preprocessor.py

Files updated:

- scripts/run_single_project.py

Implemented capabilities:

- Validates master plan image path
- Validates supported image extension
- Checks image file size
- Loads image using Pillow
- Loads image using OpenCV
- Creates normalized PNG copy
- Reads normalized image dimensions
- Computes total pixels
- Calculates image sharpness metric
- Calculates brightness metric
- Calculates colorfulness metric
- Generates image quality score
- Generates image quality label
- Generates image quality reasons
- Writes image metadata JSON output
- Prints image metadata table in CLI

## Current Blocker

The file at `data/input/master_plan.png` exists but is not a valid readable image file.

Observed error:

```text
PIL.UnidentifiedImageError: cannot identify image file 'data/input/master_plan.png'
```

## Diagnosis Commands

```bash
ls -lh data/input/master_plan.png
file data/input/master_plan.png
python - <<'PY'
from pathlib import Path
p = Path('data/input/master_plan.png')
print('Size bytes:', p.stat().st_size)
print('First 80 bytes:', p.read_bytes()[:80])
PY
```

## Required Fix

Replace `data/input/master_plan.png` with the original readable master plan image file.

If the source file is JPG/JPEG, keep the correct extension and run the script with that path.

## Test Command

```bash
pytest tests/test_json_parser.py tests/test_image_preprocessor.py -q
```

Expected result after valid image replacement:

```text
2 passed
```

## Next Step After Confirmation

Step 4: OpenAI Vision Analyzer.

Expected Step 4 output:

- Send normalized master plan image to OpenAI Vision
- Send parsed project metadata context
- Ask model to detect project boundary confidence
- Ask model to identify visible green/open/built zones
- Ask model to return structured JSON
- Store OpenAI vision analysis output locally

### Step 3 Test Fix: Master Plan Image Extension Handling

Status: Pending local confirmation

Issue:

- CLI worked with `data/input/master_plan.jpg`.
- Test failed because `tests/test_image_preprocessor.py` was hardcoded to `data/input/master_plan.png`.

Fix:

- Update image preprocessor test to locate the first available supported master plan file among `.jpg`, `.jpeg`, `.png`, and `.webp`.

Validation command:

```bash
pytest tests/test_json_parser.py tests/test_image_preprocessor.py -q
```

Expected result:

```text
2 passed
```

Next step after confirmation:

Step 4: OpenAI Vision Analyzer.

### Step 4 Fix: OpenAI SDK Compatibility

Status: Pending local confirmation

Issue:

- Unit tests passed.
- Manual OpenAI Vision command failed because local OpenAI SDK did not expose `client.responses`.

Fix:

- Replace `client.responses.create(...)` with `client.chat.completions.create(...)`.
- Keep the same structured JSON prompt and typed Pydantic parsing.

Validation command:

```bash
pytest tests/test_json_parser.py tests/test_image_preprocessor.py tests/test_vision_analyzer.py -q
```

Manual command:

```bash
python scripts/run_single_project.py \
  --json data/input/342956.json \
  --image data/input/master_plan.jpg \
  --run-vision
```

Expected output:

- data/output/json/342956_vision_analysis.json

Next step after confirmation:

Step 5: OpenCV Segmentation Engine.

### Step 5: OpenCV Segmentation Engine

Status: Pending local test confirmation

Files implemented:

- app/schemas/segmentation_schema.py
- app/services/segmentation_engine.py
- tests/test_segmentation_engine.py

Files updated:

- app/rules/class_definitions.py
- scripts/run_single_project.py

Implemented capabilities:

- Reads normalized master plan image
- Creates HSV-based green landscape mask
- Creates HSV-based water/pool mask
- Creates heuristic built-structure mask
- Creates heuristic paved/open hardscape mask
- Calculates pixel count and percentage for each class
- Calculates unknown/unclassified percentage
- Saves class masks as PNG files
- Saves segmentation overlay image
- Saves segmentation result JSON
- Adds CLI flag `--run-segmentation`

Test command:

```bash
pytest tests/test_json_parser.py tests/test_image_preprocessor.py tests/test_vision_analyzer.py tests/test_segmentation_engine.py -q
```

Expected result:

```text
4 passed
```

Manual command:

```bash
python scripts/run_single_project.py \
  --json data/input/342956.json \
  --image data/input/master_plan.jpg \
  --run-segmentation
```

Expected output:

- data/output/json/342956_segmentation_result.json
- data/output/overlays/master_plan_segmentation_overlay.png
- data/output/overlays/master_plan_green_mask.png
- data/output/overlays/master_plan_water_mask.png
- data/output/overlays/master_plan_built_mask.png
- data/output/overlays/master_plan_paved_mask.png

Next step:

Step 6: Area Calculator and Range Builder.

### Step 6: Area Calculator and Range Builder

Status: Pending local test confirmation

Files implemented:

- app/schemas/area_schema.py
- app/services/area_calculator.py
- tests/test_area_calculator.py

Files updated:

- scripts/run_single_project.py

Implemented capabilities:

- Reads project metadata
- Reads image metadata
- Reads OpenAI Vision analysis
- Reads OpenCV segmentation result
- Builds range-based Green Area estimate
- Builds range-based Open Area estimate
- Applies guardrail: Green Area <= Open Area
- Uses qualitative OpenAI Vision estimate to adjust range
- Uses OpenCV pixel segmentation as lower-bound evidence
- Uses unknown/unclassified percentage to widen range
- Produces confidence score, label, and reasons
- Produces compare-module-ready display object
- Writes final area estimate JSON output
- Adds CLI flag `--run-area-estimate`

Test command:

```bash
pytest tests/test_json_parser.py tests/test_image_preprocessor.py tests/test_vision_analyzer.py tests/test_segmentation_engine.py tests/test_area_calculator.py -q
```

Expected result:

```text
5 passed
```

Manual command:

```bash
python scripts/run_single_project.py \
  --json data/input/342956.json \
  --image data/input/master_plan.jpg \
  --run-vision \
  --run-segmentation \
  --run-area-estimate
```

Expected output:

- data/output/json/342956_area_estimate.json

Next step:

Step 7: Final Report Writer and Compare Module Contract.
