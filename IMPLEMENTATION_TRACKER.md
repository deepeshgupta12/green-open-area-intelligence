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
