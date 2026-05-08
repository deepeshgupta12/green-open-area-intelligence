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

# Step 2 Test Fix

## Issue

Running:

```bash
pytest tests/test_json_parser.py -q
```

failed with:

```text
ModuleNotFoundError: No module named 'app'
```

## Root Cause

Pytest could not resolve the `app` package because the repository root was not added to the Python path during test collection.

## Fix

Create `pytest.ini` in the repository root:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

## Command

```bash
cat > pytest.ini <<'EOF'
[pytest]
pythonpath = .
testpaths = tests
EOF
```

## Re-run Test

```bash
pytest tests/test_json_parser.py -q
```

Expected:

```text
1 passed
```

## Commit

```bash
git add pytest.ini IMPLEMENTATION_TRACKER.md CODE_DEPENDENCY_MAP.md
git commit -m "fix: configure pytest import path"
```

# Step 3 Image Input Fix

## Issue

Step 3 failed because `data/input/master_plan.png` exists but is not a readable image file.

The error was:

```text
PIL.UnidentifiedImageError: cannot identify image file 'data/input/master_plan.png'
```

This usually means the file is one of the following:

1. An HTML page saved with `.png` extension
2. A broken/incomplete download
3. A text file or redirect response saved as an image
4. A zero-byte or corrupted file
5. A different format with the wrong extension

## Diagnosis Commands

Run these from the repo root:

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

A valid PNG should usually start with bytes similar to:

```text
b'\x89PNG\r\n\x1a\n'
```

A valid JPEG should usually start with bytes similar to:

```text
b'\xff\xd8\xff'
```

If the first bytes show `<html`, `{`, or plain text, it is not a valid image.

## Fix

Replace `data/input/master_plan.png` with the real image file.

Example if the real image is in Downloads:

```bash
cp ~/Downloads/master_plan.png data/input/master_plan.png
```

If the file is actually JPG/JPEG, do not rename it manually. Copy it with the correct extension:

```bash
cp ~/Downloads/master_plan.jpg data/input/master_plan.jpg
```

Then run the Step 3 script using the correct file path:

```bash
python scripts/run_single_project.py \
  --json data/input/342956.json \
  --image data/input/master_plan.jpg
```

or, for PNG:

```bash
python scripts/run_single_project.py \
  --json data/input/342956.json \
  --image data/input/master_plan.png
```

## Test Command

```bash
pytest tests/test_json_parser.py tests/test_image_preprocessor.py -q
```

Expected result:

```text
2 passed
```

## Commit Note

A commit may have already been created even though the test failed:

```text
feat: add master plan image preprocessing
```

Do not create another implementation commit until the image file is corrected and the test passes.

After the image is fixed and tests pass, commit only the input/test fix if needed:

```bash
git add .
git commit -m "test: validate master plan image preprocessing with valid input"
```

# Step 3 Test Fix: Master Plan Image Extension

## Issue

The Step 3 CLI ran successfully with:

```bash
python scripts/run_single_project.py \
  --json data/input/342956.json \
  --image data/input/master_plan.jpg
```

But the test failed because `tests/test_image_preprocessor.py` was hardcoded to look for:

```text
data/input/master_plan.png
```

The valid master plan image is now:

```text
data/input/master_plan.jpg
```

## Root Cause

The original PNG file was not a valid readable image. The corrected file is a JPG, but the test still expected PNG.

## Fix

Update `tests/test_image_preprocessor.py` so it can detect either:

```text
data/input/master_plan.jpg
data/input/master_plan.jpeg
data/input/master_plan.png
data/input/master_plan.webp
```

## Validation Command

```bash
pytest tests/test_json_parser.py tests/test_image_preprocessor.py -q
```

## Expected Result

```text
2 passed
```

## Commit Message

```bash
git add tests/test_image_preprocessor.py IMPLEMENTATION_TRACKER.md CODE_DEPENDENCY_MAP.md
git commit -m "fix: support jpg master plan input in image preprocessor test"
```
# Step 4 Fix: OpenAI SDK Compatibility

## Issue

The test passed, but the manual OpenAI Vision run failed with:

```text
AttributeError: 'OpenAI' object has no attribute 'responses'
```

## Root Cause

The installed OpenAI Python SDK in the local environment does not expose `client.responses.create(...)`.

## Fix

Use the widely supported Chat Completions vision path:

```python
client.chat.completions.create(...)
```

with message content containing:

```json
[
  {"type": "text", "text": "..."},
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
]
```

## Files Impacted

- app/services/vision_analyzer.py

## Validation

Run:

```bash
pytest tests/test_json_parser.py tests/test_image_preprocessor.py tests/test_vision_analyzer.py -q
```

Expected:

```text
3 passed
```

Then run:

```bash
python scripts/run_single_project.py \
  --json data/input/342956.json \
  --image data/input/master_plan.jpg \
  --run-vision
```

Expected output:

```text
data/output/json/342956_vision_analysis.json
```

## Commit

```bash
git add app/services/vision_analyzer.py IMPLEMENTATION_TRACKER.md CODE_DEPENDENCY_MAP.md
git commit -m "fix: use chat completions for OpenAI vision analyzer"
```
# Step 5: OpenCV Segmentation Engine

## Objective

Implement the OpenCV segmentation layer for master plan images.

This step uses the normalized master plan image and creates rough pixel-based masks for:

- green landscape
- water/pool
- road/paved/open hardscape
- likely building footprint / built structures
- unknown/unclassified area

## Important Note

This is not the final area calculation step. Step 5 produces class-wise pixel percentages and overlay images. Final green/open range calculation, guardrails, confidence scoring, and compare-module output will come in later steps.

## Inputs

```text
data/output/overlays/master_plan_normalized.png
```

## Outputs

```text
data/output/json/342956_segmentation_result.json
data/output/overlays/master_plan_segmentation_overlay.png
data/output/overlays/master_plan_green_mask.png
data/output/overlays/master_plan_water_mask.png
data/output/overlays/master_plan_built_mask.png
data/output/overlays/master_plan_paved_mask.png
```

## Test Command

```bash
pytest tests/test_json_parser.py tests/test_image_preprocessor.py tests/test_vision_analyzer.py tests/test_segmentation_engine.py -q
```

## Expected Result

```text
4 passed
```

## Manual Command

```bash
python scripts/run_single_project.py \
  --json data/input/342956.json \
  --image data/input/master_plan.jpg \
  --run-segmentation
```

## Commit

```bash
git add .
git commit -m "feat: add OpenCV segmentation engine"
```

# Step 6: Area Calculator and Range Builder

## Objective

Convert the OpenAI Vision analysis and OpenCV segmentation result into range-based Green Area and Open Area estimates.

## Why Step 6 is Needed

Step 5 produced raw pixel percentages, but the unknown/unclassified area is high. Therefore, the product should not directly use OpenCV percentages as final estimates.

Step 6 combines:

- OpenCV segmentation percentages
- OpenAI Vision qualitative estimate
- Project JSON signals
- Image quality score
- Unknown/unclassified percentage
- Mandatory guardrails

## Inputs

```text
data/output/json/342956_parsed_project_metadata.json
data/output/json/master_plan_image_metadata.json
data/output/json/342956_vision_analysis.json
data/output/json/342956_segmentation_result.json
```

## Outputs

```text
data/output/json/342956_area_estimate.json
```

## Core Rules

- Output range, not exact percentage.
- Green Area % must be less than or equal to Open Area %.
- High unknown segmentation area must widen the range and reduce confidence.
- Vision output can boost or adjust the estimate, but cannot override guardrails.
- Final output must include reasons and warnings.

## Manual Command

```bash
python scripts/run_single_project.py \
  --json data/input/342956.json \
  --image data/input/master_plan.jpg \
  --run-vision \
  --run-segmentation \
  --run-area-estimate
```

## Test Command

```bash
pytest tests/test_json_parser.py tests/test_image_preprocessor.py tests/test_vision_analyzer.py tests/test_segmentation_engine.py tests/test_area_calculator.py -q
```

## Expected Result

```text
5 passed
```

## Commit

```bash
git add .
git commit -m "feat: add area calculator and range builder"

# Step 6 Fix: Confidence Calibration

## Issue

Step 6 generated a valid area estimate, but the confidence label was too optimistic.

Current result:

```text
Estimated Green Area: ~25–49%
Estimated Open Area: ~39–67%
Confidence Score: 0.82
Confidence Label: High
```

However, the same output also contains:

```text
OpenCV unknown/unclassified area: 73.97%
Image may be stylized and not to scale.
```

## Product Concern

A High confidence label is not appropriate when:

- Unknown/unclassified segmentation area is above 70%
- The image may be stylized or not to scale
- The final estimate range is very wide

## Fix

Add confidence caps:

- If OpenCV unknown/unclassified area > 70%, max confidence score should be 0.74.
- If both high unknown area and stylized/not-to-scale warning exist, max confidence score should be 0.69.
- If Green Area or Open Area range width is greater than 20 percentage points, max confidence score should be 0.72.
- Final confidence should become Medium in this scenario.

## Expected Outcome

For Birla Taranya, after calibration:

```text
Confidence Label: Medium
```

This better reflects the evidence quality.

## Validation

```bash
pytest tests/test_area_calculator.py -q
pytest tests/test_json_parser.py tests/test_image_preprocessor.py tests/test_vision_analyzer.py tests/test_segmentation_engine.py tests/test_area_calculator.py -q
```

## Commit

```bash
git add app/services/area_calculator.py tests/test_area_calculator.py IMPLEMENTATION_TRACKER.md CODE_DEPENDENCY_MAP.md
git commit -m "fix: calibrate confidence caps for high unknown segmentation"
```

```
# Step 7: Final Report Writer and Compare Module Contract

## Objective

Create final human-readable and machine-readable outputs for the Green Open Area Intelligence Engine.

## Scope

Step 7 adds:

- Final Markdown report generation
- Compare-module contract JSON generation
- Audit-friendly output summary
- Source/evidence section
- Warnings and confidence reasons section
- Output paths printed in CLI

## Inputs

```text
Parsed project metadata
Image metadata
OpenAI Vision analysis
OpenCV segmentation result
Area estimate result
```

## Outputs

```text
data/output/reports/342956_area_estimate_report.md
data/output/json/342956_compare_module_contract.json
```

## Test Command

```bash
pytest tests/test_json_parser.py tests/test_image_preprocessor.py tests/test_vision_analyzer.py tests/test_segmentation_engine.py tests/test_area_calculator.py tests/test_report_writer.py -q
```

## Expected Result

```text
6 passed
```

## Manual Command

```bash
python scripts/run_single_project.py \
  --json data/input/342956.json \
  --image data/input/master_plan.jpg \
  --run-vision \
  --run-segmentation \
  --run-area-estimate \
  --write-report
```

## Commit

```bash
git add .
git commit -m "feat: add final report writer and compare module contract"
```

