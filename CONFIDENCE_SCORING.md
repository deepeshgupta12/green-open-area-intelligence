# Confidence Scoring

## 1. Confidence Philosophy

Confidence is mandatory for every output.

The engine must never return Green Area or Open Area without explaining how confident it is and why.

## 2. Score Range

```text
0.00 to 1.00
```

## 3. Labels

```text
High: 0.80 to 1.00
Medium: 0.55 to 0.79
Low: 0.30 to 0.54
Insufficient: below 0.30
```

## 4. Suggested Base Score

Start with:

```text
0.50
```

Then add or subtract based on evidence.

## 5. Positive Signals

### Project JSON available

```text
+0.08
```

### Project area available

```text
+0.08
```

### Master plan image available

```text
+0.12
```

### AI boundary detected

```text
+0.08
```

### Manual boundary provided

```text
+0.15
```

### Green amenity signals available

```text
+0.06
```

### Master plan description available

```text
+0.05
```

### Direct open/green value declared in source

```text
+0.15
```

### OpenAI and OpenCV estimates aligned

```text
+0.10
```

## 6. Negative Signals

### Boundary unclear

```text
-0.12
```

### Low image quality

```text
-0.10
```

### Unknown area above 20%

```text
-0.10
```

### JSON/image conflict

```text
-0.10
```

### Green Area adjusted due to guardrail

```text
-0.07
```

### Missing project area

```text
-0.08
```

### No green/open-space signals in JSON

```text
-0.05
```

## 7. Final Score Clamp

The final score must always be clamped between:

```text
0.00 and 1.00
```

## 8. Range Width by Confidence

### High

```text
±3%
```

### Medium

```text
±5%
```

### Low

```text
±8–10%
```

### Insufficient

Do not show numeric range.

Show:

```text
Data not sufficient for reliable estimate.
```

## 9. Confidence Reason Format

Each confidence output must contain reasons.

Example:

```json
{
  "score": 0.74,
  "label": "Medium",
  "reasons": [
    "Project JSON was available.",
    "Project area was available.",
    "Master plan image was available.",
    "AI detected a project boundary.",
    "Manual boundary was not provided.",
    "Green amenity signals were found in project data."
  ]
}
```

## 10. Compare Module Display

### High

```text
High Confidence Estimate
```

### Medium

```text
Medium Confidence Estimate
```

### Low

```text
Low Confidence Indicative Estimate
```

### Insufficient

```text
Not enough data
```
