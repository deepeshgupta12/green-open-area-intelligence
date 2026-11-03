"""Backend QA agents from the command line.

  python scripts/qa_agents.py playbook              # show the current playbook
  python scripts/qa_agents.py review <run_dir>      # re-review a stored run (and fix, re-review, teach)

A run directory is data/output/analysis_runs/<id> or data/output/entity_runs/<id>;
the matching data/input/.../<id> folder supplies the image.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from app.agents.orchestrator import run_qa_loop  # noqa: E402
from app.agents.playbook import default_playbook_path, load_playbook  # noqa: E402
from app.schemas.area_schema import AreaEstimateResult  # noqa: E402
from app.schemas.master_plan_entity_schema import MasterPlanEntityMap  # noqa: E402

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def show_playbook() -> None:
    playbook = load_playbook()
    print(f"playbook v{playbook.version} ({default_playbook_path()}), updated {playbook.updated_at}\n")
    print("Acceptance rules")
    for rule in playbook.acceptance_rules:
        print(f"  {rule.id} [{rule.severity}, {rule.scope}, {rule.source}] {rule.text}")
    print("\nRejection cases")
    for case in playbook.rejection_cases:
        print(f"  {case.id} [{case.scope}, {case.source}] {case.symptom}\n       check: {case.check}\n       fix:   {case.resolution}")
    print("\nFix recipes")
    for recipe in playbook.fix_recipes:
        print(f"  {recipe.id} {recipe.trigger} -> {recipe.action}")
    print("\nLessons")
    for lesson in playbook.lessons:
        print(f"  - {lesson}")


def review_run(run_dir: Path, teach: bool, max_rounds: int) -> int:
    entity_map_path = run_dir / "master_plan_entity_map.json"
    if not entity_map_path.is_file():
        print(f"no master_plan_entity_map.json in {run_dir}")
        return 1
    entity_map = MasterPlanEntityMap.model_validate(json.loads(entity_map_path.read_text(encoding="utf-8")))
    estimate = None
    estimate_path = run_dir / "area_estimate.json"
    if estimate_path.is_file():
        estimate = AreaEstimateResult.model_validate(json.loads(estimate_path.read_text(encoding="utf-8")))

    input_dir = Path(str(run_dir).replace("/data/output/", "/data/input/"))
    images = [path for path in input_dir.glob("*") if path.suffix.lower() in IMAGE_SUFFIXES] if input_dir.is_dir() else []
    if not images:
        print(f"no image found under {input_dir}")
        return 1

    fixed_map, fixed_estimate, trail = run_qa_loop(
        entity_map, estimate, image_path=images[0], project=None, run_id=run_dir.name, output_dir=run_dir,
        max_rounds=max_rounds, teach_enabled=teach,
    )
    print(f"run {run_dir.name}: {trail.final_verdict} (score {trail.final_score}, adopted round {trail.adopted_round}, lessons {trail.lessons_recorded})")
    for item in trail.rounds:
        print(f"  round {item.round}: {item.review.verdict} {item.review.score} observed={item.review.observed}")
        for finding in item.review.findings:
            print(f"    - {finding.code} [{finding.severity}, {finding.source}] {finding.detail}")
        for action in item.actions:
            print(f"    > {action.finding_code} -> {action.recipe} {'applied' if action.applied else 'skipped'}: {action.detail}")
    before = sum(1 for entity in entity_map.entities if entity.entity_type == "residential_block")
    after = sum(1 for entity in fixed_map.entities if entity.entity_type == "residential_block")
    print(f"residential blocks: {before} -> {after}; trail written to {run_dir / 'qa_trail.json'}")
    if fixed_estimate is not None and estimate is not None and fixed_estimate != estimate:
        print(f"estimate: {estimate.confidence.label} -> {fixed_estimate.confidence.label}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Backend QA agents")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("playbook", help="print the playbook")
    review = sub.add_parser("review", help="review (and fix) a stored run")
    review.add_argument("run_dir")
    review.add_argument("--no-teach", action="store_true", help="do not let the teacher update the playbook")
    review.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()
    if args.command == "playbook":
        show_playbook()
        return 0
    return review_run(Path(args.run_dir).resolve(), teach=not args.no_teach, max_rounds=args.rounds)


if __name__ == "__main__":
    raise SystemExit(main())
