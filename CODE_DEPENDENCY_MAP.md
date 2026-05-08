# Code Dependency Map

## 1. Current Architecture

The engine is organized into schemas, services, rules, storage, utilities, scripts, and tests.

## 2. Main Flow

```text
scripts/run_single_project.py
        ↓
app/services/json_parser.py
        ↓
app/services/image_preprocessor.py
        ↓
app/services/vision_analyzer.py
        ↓
app/services/segmentation_engine.py
        ↓
app/services/area_calculator.py
        ↓
app/services/validation_engine.py
        ↓
app/services/confidence_engine.py
        ↓
app/services/explanation_engine.py
        ↓
app/services/report_writer.py
```

## 3. File Responsibilities

### app/config.py

Loads environment variables and app settings.

Depends on:

- pydantic-settings
- dotenv

Used by:

- scripts/run_single_project.py
- future FastAPI app initialization

### app/schemas/project_schema.py

Defines normalized project metadata schema.

Current models:

- ReraRecord
- AmenityRecord
- WowFactorRecord
- UnitVariant
- MasterPlanMetadata
- ParsedProjectMetadata

Used by:

- app/services/json_parser.py
- tests/test_json_parser.py
- future validation/confidence/reporting modules

### app/utils/file_utils.py

Provides:

- ensure_directory
- read_json_file
- write_json_file
- safe_get_nested
- strip_html_tags

Used by:

- app/services/json_parser.py
- scripts/run_single_project.py

### app/services/json_parser.py

Primary Datacenter JSON parser.

Depends on:

- app.schemas.project_schema
- app.utils.file_utils

Used by:

- scripts/run_single_project.py
- tests/test_json_parser.py

Current responsibilities:

- Read Datacenter JSON payload
- Normalize project-level metadata
- Parse amenities
- Parse RERA records
- Parse wow factors
- Parse unit mix
- Parse master plan metadata
- Extract green amenity signals
- Extract open-space signals
- Extract direct area claims from available text

### scripts/run_single_project.py

CLI runner for Step 2.

Current behavior:

- Reads project Datacenter JSON
- Parses normalized metadata
- Writes output JSON
- Prints parsed metadata summary
- Accepts image path but does not process image yet

Depends on:

- app.config
- app.services.json_parser
- app.utils.file_utils

### tests/test_json_parser.py

Validates Birla Taranya JSON parsing using:

```text
data/input/342956.json
```

Depends on:

- app.services.json_parser

### pytest.ini

Required for local test imports.

Purpose:

- Adds repo root to Python import path
- Ensures pytest can import app.* modules

Content:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

## 4. Step 2 Import Issue

Observed error:

```text
ModuleNotFoundError: No module named 'app'
```

Reason:

Pytest did not add the repository root to sys.path during collection.

Resolution:

Create pytest.ini in repo root with:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

Alternative temporary command:

```bash
PYTHONPATH=. pytest tests/test_json_parser.py -q
```

Preferred permanent fix:

Use pytest.ini.

## 5. Rule Files

### app/rules/class_definitions.py

Defines segmentation classes.

### app/rules/green_area_rules.py

Defines what counts as green area.

### app/rules/open_area_rules.py

Defines what counts as open area.

### app/rules/confidence_rules.py

Defines scoring weights and thresholds.

### app/rules/guardrails.py

Defines non-negotiable product guardrails.

These will be implemented in later steps.

## 6. Storage Files

### app/storage/database.py

SQLite connection setup.

### app/storage/models.py

Tables for project runs and outputs.

Storage will be implemented after the first working CLI flow.

## 7. Testing Strategy

Initial tests:

- JSON parser test
- Area calculation test
- Confidence engine test
- Guardrail validation test

## 8. Dependency Rule

Before modifying an existing file, check this map to understand dependent files.

## Step 3 Implemented Dependency Details

### app/schemas/image_schema.py

Defines:

- ImageDimensions
- ImageQualityAssessment
- ImageMetadata

Used by:

- app/services/image_preprocessor.py
- tests/test_image_preprocessor.py

### app/utils/image_utils.py

Provides:

- validate_image_path
- get_file_size_mb
- load_image_with_pillow
- load_image_with_cv2
- save_normalized_png
- calculate_laplacian_variance
- calculate_brightness_score
- calculate_colorfulness_score

Used by:

- app/services/image_preprocessor.py

### app/services/image_preprocessor.py

Primary image preprocessing service.

Depends on:

- app.config
- app.schemas.image_schema
- app.utils.image_utils

Used by:

- scripts/run_single_project.py
- tests/test_image_preprocessor.py

### scripts/run_single_project.py

Updated to support Step 3.

Current behavior:

- Parses project Datacenter JSON
- Writes parsed project metadata JSON
- Preprocesses master plan image when image path is provided
- Writes image metadata JSON
- Writes normalized PNG image
- Prints project metadata table
- Prints image metadata table

### tests/test_image_preprocessor.py

Validates master plan preprocessing using:

```text
data/input/master_plan.png
```

Important: the test requires `data/input/master_plan.png` to be a valid image file. If the local file is corrupted, HTML, JSON, or a failed download saved as `.png`, the test will correctly fail.

## Step 3 Test Fix Dependency Note

### tests/test_image_preprocessor.py

Updated responsibility:

- No longer assumes the master plan input must be `master_plan.png`.
- Finds the first available supported file from:

```text
data/input/master_plan.jpg
data/input/master_plan.jpeg
data/input/master_plan.png
data/input/master_plan.webp
```

Depends on:

- app/services/image_preprocessor.py

Reason:

- The valid local master plan input is `master_plan.jpg`.
- The previous `master_plan.png` file was invalid/corrupt or not a readable image.