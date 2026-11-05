"""Fixture-plan regression: re-run the pipeline on the known sheets and check the confirmed facts.

The engineer agent runs this inside its worktree before it opens a pull
request; a developer can run it by hand with ``scripts/qa_agents.py
regression``. Expectations live in ``docs/regression/plans.json`` and are
the facts confirmed on each sheet (12 towers on the Mahindra block plan, no
water on Kalpataru Vian, ...), expressed as inclusive ranges so ordinary
run-to-run variance passes and a real regression does not.
"""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.schemas.master_plan_entity_schema import MasterPlanEntityMap

logger = logging.getLogger(__name__)

DEFAULT_MANIFEST = Path("docs/regression/plans.json")
COUNT_METRICS = ("residential_block", "swimming_pool", "water_feature", "sports_court", "entry_exit_gate")


@dataclass
class MetricCheck:
    metric: str
    expected: Any
    actual: Any
    ok: bool


@dataclass
class PlanResult:
    name: str
    title: str
    ok: bool
    checks: list[MetricCheck] = field(default_factory=list)
    error: str | None = None
    run_id: str | None = None
    attempts: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "title": self.title, "ok": self.ok, "error": self.error, "run_id": self.run_id,
            "attempts": self.attempts, "checks": [check.__dict__ for check in self.checks],
        }


def load_manifest(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or DEFAULT_MANIFEST
    payload = json.loads(Path(target).read_text(encoding="utf-8"))
    return list(payload.get("plans", []))


def metrics_from_entity_map(entity_map: MasterPlanEntityMap) -> dict[str, Any]:
    """The handful of numbers the expectations talk about."""
    counts = entity_map.entity_counts or {}
    legend_total = len(entity_map.legend)
    placed = sum(1 for item in entity_map.legend if item.located_on_plan)
    metrics: dict[str, Any] = {metric: int(counts.get(metric, 0)) for metric in COUNT_METRICS}
    metrics.update({
        "drawing_style": entity_map.site.drawing_style or "rendered",
        "entities_total": len(entity_map.entities),
        "legend_total": legend_total,
        "legend_placed_share": round(placed / legend_total, 3) if legend_total else None,
        "diagnostics_present": sorted({item.code for item in entity_map.diagnostics}),
    })
    return metrics


def evaluate(expect: dict[str, Any], metrics: dict[str, Any]) -> list[MetricCheck]:
    """Compare the metrics with the manifest's expectations; a missing metric fails."""
    checks: list[MetricCheck] = []
    for metric, expected in expect.items():
        actual = metrics.get(metric)
        if metric == "diagnostics_present":
            present = set(actual or [])
            ok = all(code in present for code in expected)
            checks.append(MetricCheck(metric, expected, sorted(present & set(expected)), ok))
        elif isinstance(expected, list) and len(expected) == 2 and all(isinstance(v, (int, float)) for v in expected):
            ok = actual is not None and expected[0] <= actual <= expected[1]
            checks.append(MetricCheck(metric, expected, actual, bool(ok)))
        else:
            checks.append(MetricCheck(metric, expected, actual, actual == expected))
    return checks


def resolve_image(entry: dict[str, Any], repo_root: Path, download_dir: Path) -> Path:
    """The stored input image when this machine has it, else the public URL fetched once."""
    local = entry.get("local_image")
    if local:
        candidate = repo_root / local
        if candidate.is_file():
            return candidate
    url = entry.get("image_url")
    if not url:
        raise FileNotFoundError(f"{entry.get('name')}: no local image and no image_url")
    from app.config import get_settings
    from app.utils.remote_image import download_image

    download_dir.mkdir(parents=True, exist_ok=True)
    return download_image(url, download_dir, max_bytes=get_settings().max_image_size_mb * 1024 * 1024)


def run_plan_pipeline(image_path: Path, run_id: str, qa_enabled: bool = True) -> MasterPlanEntityMap:
    """Extraction plus the QA loop, the way the API runs them, without the estimate and metrics stages."""
    from app.agents.orchestrator import run_qa_loop
    from app.config import get_settings
    from app.services.image_preprocessor import preprocess_master_plan_image
    from app.services.master_plan_entity_extractor import extract_master_plan_entities

    settings = get_settings()
    image_metadata = preprocess_master_plan_image(str(image_path))
    entity_map = extract_master_plan_entities(image_metadata=image_metadata, project=None)
    output_dir = settings.data_output_dir / "regression_runs" / run_id
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "master_plan_entity_map.extracted.json").write_text(json.dumps(entity_map.model_dump(mode="json"), indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 - diagnostics only
        pass
    if qa_enabled and settings.qa_agents_enabled:
        # The trail is written beside the extracted map so a failed check can be traced to the extractor or to the fixer.
        entity_map, _, _ = run_qa_loop(
            entity_map, None, image_path=image_metadata.normalized_image_path or str(image_path),
            project=None, run_id=run_id, output_dir=output_dir, teach_enabled=False,
        )
    return entity_map


def _run_one(entry: dict[str, Any], run_id: str, root: Path, download_dir: Path, runner) -> PlanResult:
    name, title = str(entry.get("name")), str(entry.get("title") or entry.get("name"))
    try:
        image = resolve_image(entry, root, download_dir)
        entity_map = runner(image, run_id)
        checks = evaluate(entry.get("expect", {}), metrics_from_entity_map(entity_map))
        return PlanResult(name=name, title=title, ok=all(check.ok for check in checks), checks=checks, run_id=run_id)
    except Exception as exc:  # noqa: BLE001 - one plan's failure is a failed check, not a crash
        logger.warning("regression: %s failed: %s", name, exc)
        return PlanResult(name=name, title=title, ok=False, error=str(exc)[:400], run_id=run_id)


def run_regression(
    manifest_path: Path | None = None,
    only: list[str] | None = None,
    repo_root: Path | None = None,
    runner=run_plan_pipeline,
    retries: int = 1,
) -> dict[str, Any]:
    """Run every fixture plan (or the named ones) and return the report as a plain dict.

    The vision model varies run to run, so a plan that fails is run once more
    (``retries``) before it counts as a regression; a pass on the retry is
    reported as such so a reviewer can see the flakiness.
    """
    root = repo_root or Path.cwd()
    entries = [entry for entry in load_manifest(manifest_path) if not only or entry.get("name") in only]
    results: list[PlanResult] = []
    with tempfile.TemporaryDirectory(prefix="regression-images-") as tmp:
        for index, entry in enumerate(entries, start=1):
            name = str(entry.get("name"))
            result = _run_one(entry, f"regression-{name}-{index}", root, Path(tmp), runner)
            attempt = 1
            while not result.ok and attempt <= retries:
                attempt += 1
                logger.warning("regression: %s failed; running it once more to separate variance from a regression", name)
                result = _run_one(entry, f"regression-{name}-{index}-retry{attempt - 1}", root, Path(tmp), runner)
            result.attempts = attempt
            results.append(result)
    return {"ok": all(result.ok for result in results) and bool(results), "plans": [result.as_dict() for result in results]}


def report_markdown(report: dict[str, Any]) -> str:
    lines = ["| Plan | Result | Checks |", "|---|---|---|"]
    for plan in report.get("plans", []):
        if plan.get("error"):
            cell = f"error: {plan['error'][:120]}"
        else:
            parts = []
            for check in plan.get("checks", []):
                mark = "ok" if check["ok"] else "FAIL"
                parts.append(f"{check['metric']} {check['actual']} ({mark}, expected {check['expected']})")
            cell = "; ".join(parts)
        verdict = "pass" if plan["ok"] else "fail"
        if plan.get("attempts", 1) > 1:
            verdict += f" (on attempt {plan['attempts']})"
        lines.append(f"| {plan['title']} | {verdict} | {cell} |")
    return "\n".join(lines)
