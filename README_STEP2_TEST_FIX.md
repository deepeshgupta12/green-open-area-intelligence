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
