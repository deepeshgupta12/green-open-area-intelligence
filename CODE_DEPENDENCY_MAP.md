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

### app/schemas/project_schema.py

Defines normalized project metadata schema.

Used by:

- json_parser.py
- validation_engine.py
- confidence_engine.py
- report_writer.py

### app/schemas/image_schema.py

Defines image metadata, boundary, and segmentation schemas.

Used by:

- image_preprocessor.py
- vision_analyzer.py
- segmentation_engine.py
- area_calculator.py

### app/schemas/output_schema.py

Defines final result schema.

Used by:

- area_calculator.py
- validation_engine.py
- confidence_engine.py
- report_writer.py
- FastAPI endpoint

### app/services/json_parser.py

Parses Datacenter JSON into normalized metadata.

Depends on:

- project_schema.py
- file_utils.py

### app/services/image_preprocessor.py

Loads, validates, and prepares master plan image.

Depends on:

- image_schema.py
- image_utils.py

### app/services/vision_analyzer.py

Calls OpenAI Vision for semantic master plan understanding.

Depends on:

- config.py
- project_schema.py
- image_schema.py

### app/services/segmentation_engine.py

Uses OpenCV for image segmentation.

Depends on:

- image_schema.py
- class_definitions.py
- image_utils.py

### app/services/area_calculator.py

Calculates green and open area estimates.

Depends on:

- green_area_rules.py
- open_area_rules.py
- guardrails.py
- output_schema.py

### app/services/validation_engine.py

Validates outputs against product rules and project metadata.

Depends on:

- guardrails.py
- project_schema.py
- output_schema.py

### app/services/confidence_engine.py

Computes confidence score, label, and reasons.

Depends on:

- confidence_rules.py
- output_schema.py

### app/services/explanation_engine.py

Generates compare-module explanation using OpenAI text model.

Depends on:

- config.py
- output_schema.py

### app/services/report_writer.py

Writes output JSON, Markdown report, and overlay image path.

Depends on:

- output_schema.py
- file_utils.py

## 4. Rule Files

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

## 5. Storage Files

### app/storage/database.py

SQLite connection setup.

### app/storage/models.py

Tables for project runs and outputs.

Storage will be implemented after the first working CLI flow.

## 6. Scripts

### scripts/run_single_project.py

CLI runner for one project.

Expected input:

```bash
python scripts/run_single_project.py \
  --json data/input/342956.json \
  --image data/input/master_plan.png
```

### scripts/init_db.py

Initializes SQLite database.

### scripts/generate_sample_report.py

Generates a sample report from a saved output.

## 7. Testing Strategy

Initial tests:

- JSON parser test
- Area calculation test
- Confidence engine test
- Guardrail validation test

## 8. Dependency Rule

Before modifying an existing file, check this map to understand dependent files.
